"""
Unit tests for PA-018 POST /platform/issues/batch-action endpoint.

Tests: auth, role, validation, partial success, all supported actions.
Tier 1: Fast, isolated. Uses FastAPI dependency_overrides + patch helpers.
"""
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "c" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_USER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TEST_ISSUE_1 = "11111111-1111-1111-1111-111111111111"
TEST_ISSUE_2 = "22222222-2222-2222-2222-222222222222"

_MOD = "app.modules.issues.routes"

_ISSUE_TEMPLATE = {
    "tenant_id": TEST_TENANT_ID,
    "reporter_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    "status": "open",
}


def _make_token(
    user_id: str = TEST_USER_ID,
    roles: list | None = None,
    scope: str = "platform",
) -> str:
    if roles is None:
        roles = ["platform_admin"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": TEST_TENANT_ID,
        "roles": roles,
        "scope": scope,
        "plan": "professional",
        "email": "admin@platform.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _platform_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token()}"}


def _tenant_headers() -> dict:
    return {
        "Authorization": f"Bearer {_make_token(roles=['tenant_admin'], scope='tenant')}"
    }


@pytest.fixture
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _build_mock_session():
    session = AsyncMock()
    session.commit = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)
    empty_result = MagicMock()
    empty_result.fetchone = MagicMock(return_value=None)
    empty_result.fetchall = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=empty_result)
    return session


@contextmanager
def _override_session(session):
    from app.core.session import get_async_session
    from app.main import app

    async def _dep():
        yield session

    app.dependency_overrides[get_async_session] = _dep
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_async_session, None)


def _patch_get_issue(return_value):
    return patch(
        f"{_MOD}._platform_get_issue_row", new=AsyncMock(return_value=return_value)
    )


def _patch_set_status():
    return patch(
        f"{_MOD}._platform_set_status_and_event", new=AsyncMock(return_value=None)
    )


def _patch_send_notifs():
    return patch(f"{_MOD}._send_issue_notifications", new=AsyncMock(return_value=None))


BASE = "/api/v1/platform/issues/batch-action"


class TestBatchActionAuth:
    def test_requires_auth(self, client):
        resp = client.post(
            BASE,
            json={"issue_ids": [TEST_ISSUE_1], "action": "close"},
        )
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.post(
            BASE,
            json={"issue_ids": [TEST_ISSUE_1], "action": "close"},
            headers=_tenant_headers(),
        )
        assert resp.status_code == 403


class TestBatchActionValidation:
    def test_rejects_empty_issue_ids(self, client):
        resp = client.post(
            BASE,
            json={"issue_ids": [], "action": "close"},
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_rejects_invalid_action(self, client):
        resp = client.post(
            BASE,
            json={"issue_ids": [TEST_ISSUE_1], "action": "delete"},
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_rejects_missing_action(self, client):
        resp = client.post(
            BASE,
            json={"issue_ids": [TEST_ISSUE_1]},
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_rejects_oversized_batch(self, client):
        resp = client.post(
            BASE,
            json={
                "issue_ids": ["11111111-1111-1111-1111-111111111111"] * 101,
                "action": "close",
            },
            headers=_platform_headers(),
        )
        assert resp.status_code == 422


class TestBatchActionClose:
    def test_close_single_issue_success(self, client):
        issue = {**_ISSUE_TEMPLATE, "id": TEST_ISSUE_1}
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(issue),
            _patch_set_status(),
        ):
            resp = client.post(
                BASE,
                json={"issue_ids": [TEST_ISSUE_1], "action": "close"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert TEST_ISSUE_1 in data["succeeded"]
        assert data["failed"] == []

    def test_close_multiple_issues_success(self, client):
        issue = {**_ISSUE_TEMPLATE, "id": TEST_ISSUE_1}
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(issue),
            _patch_set_status(),
        ):
            resp = client.post(
                BASE,
                json={"issue_ids": [TEST_ISSUE_1, TEST_ISSUE_2], "action": "close"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["succeeded"]) == 2
        assert data["failed"] == []

    def test_close_missing_issue_in_failed(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.post(
                BASE,
                json={"issue_ids": [TEST_ISSUE_1], "action": "close"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert len(data["failed"]) == 1
        assert data["failed"][0]["id"] == TEST_ISSUE_1
        assert "not found" in data["failed"][0]["error"].lower()

    def test_close_invalid_uuid_in_failed(self, client):
        session = _build_mock_session()
        with _override_session(session):
            resp = client.post(
                BASE,
                json={"issue_ids": ["not-a-uuid"], "action": "close"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert data["failed"][0]["id"] == "not-a-uuid"


class TestBatchActionRoute:
    def test_route_success(self, client):
        issue = {**_ISSUE_TEMPLATE, "id": TEST_ISSUE_1}
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(issue),
            _patch_set_status(),
            _patch_send_notifs(),
        ):
            resp = client.post(
                BASE,
                json={
                    "issue_ids": [TEST_ISSUE_1],
                    "action": "route",
                    "payload": {"notify_tenant": True},
                },
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert TEST_ISSUE_1 in resp.json()["succeeded"]

    def test_route_without_notify_skips_notifications(self, client):
        issue = {**_ISSUE_TEMPLATE, "id": TEST_ISSUE_1}
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(issue),
            _patch_set_status(),
            _patch_send_notifs() as mock_notifs,
        ):
            resp = client.post(
                BASE,
                json={
                    "issue_ids": [TEST_ISSUE_1],
                    "action": "route",
                    "payload": {"notify_tenant": False},
                },
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        mock_notifs.assert_not_called()


class TestBatchActionEscalate:
    def test_escalate_success(self, client):
        issue = {**_ISSUE_TEMPLATE, "id": TEST_ISSUE_1}
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(issue),
            _patch_set_status(),
        ):
            resp = client.post(
                BASE,
                json={"issue_ids": [TEST_ISSUE_1], "action": "escalate"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert TEST_ISSUE_1 in resp.json()["succeeded"]


class TestBatchActionPartialSuccess:
    def test_partial_success_structure(self, client):
        """First issue found, second not found — partial success returned."""
        session = _build_mock_session()
        call_count = [0]

        async def _get_issue(issue_id, db):
            call_count[0] += 1
            if call_count[0] == 1:
                return {**_ISSUE_TEMPLATE, "id": issue_id}
            return None

        with (
            _override_session(session),
            patch(f"{_MOD}._platform_get_issue_row", new=_get_issue),
            _patch_set_status(),
        ):
            resp = client.post(
                BASE,
                json={"issue_ids": [TEST_ISSUE_1, TEST_ISSUE_2], "action": "close"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["succeeded"]) == 1
        assert len(data["failed"]) == 1
        assert data["succeeded"][0] == TEST_ISSUE_1
        assert data["failed"][0]["id"] == TEST_ISSUE_2

    def test_all_valid_actions_accepted(self, client):
        for action in ("close", "route", "escalate"):
            issue = {**_ISSUE_TEMPLATE, "id": TEST_ISSUE_1}
            session = _build_mock_session()
            with (
                _override_session(session),
                _patch_get_issue(issue),
                _patch_set_status(),
                _patch_send_notifs(),
            ):
                resp = client.post(
                    BASE,
                    json={"issue_ids": [TEST_ISSUE_1], "action": action},
                    headers=_platform_headers(),
                )
            assert resp.status_code == 200, f"Expected 200 for action {action}"
            assert TEST_ISSUE_1 in resp.json()["succeeded"]
