"""
Unit tests for PA-017 platform issue action endpoints.

Tests the 7 new endpoints added to platform_issues_router:
  POST   /platform/issues/{id}/accept
  PATCH  /platform/issues/{id}/severity
  POST   /platform/issues/{id}/wont-fix
  PATCH  /platform/issues/{id}/assign
  POST   /platform/issues/{id}/request-info
  POST   /platform/issues/{id}/route
  POST   /platform/issues/{id}/close-duplicate

Coverage per endpoint: 401 unauthenticated, 403 wrong role, 404 not found,
200 happy path, validation failures.

Tier 1: Fast, isolated. Uses FastAPI dependency_overrides for the DB session
and patches the three shared DB helper functions.
"""
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "b" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_ISSUE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEST_USER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TEST_REPORTER_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"

_ISSUE_ROW = {
    "id": TEST_ISSUE_ID,
    "tenant_id": TEST_TENANT_ID,
    "reporter_id": TEST_REPORTER_ID,
    "status": "open",
}

_MOD = "app.modules.issues.routes"


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


# ---------------------------------------------------------------------------
# Helpers: mock session via app.dependency_overrides and patch helpers
# ---------------------------------------------------------------------------


def _build_mock_session(execute_side_effects: list | None = None):
    """
    Build a mock AsyncSession.

    execute_side_effects is a list of return values for successive execute() calls.
    If None, each execute() returns a result with no rows.
    """
    session = AsyncMock()
    session.commit = AsyncMock(return_value=None)

    empty_result = MagicMock()
    empty_result.fetchone = MagicMock(return_value=None)
    empty_result.fetchall = MagicMock(return_value=[])

    if execute_side_effects is None:
        session.execute = AsyncMock(return_value=empty_result)
    else:
        results = []
        for val in execute_side_effects:
            r = MagicMock()
            r.fetchone = MagicMock(return_value=val)
            r.fetchall = MagicMock(return_value=[val] if val is not None else [])
            results.append(r)
        session.execute = AsyncMock(side_effect=results + [empty_result] * 10)

    return session


@contextmanager
def _override_session(session):
    """Override get_async_session FastAPI dependency with a mock session."""
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


# ---------------------------------------------------------------------------
# POST /platform/issues/{id}/accept
# ---------------------------------------------------------------------------


class TestAcceptIssue:
    BASE = f"/api/v1/platform/issues/{TEST_ISSUE_ID}/accept"

    def test_accept_requires_auth(self, client):
        resp = client.post(self.BASE)
        assert resp.status_code == 401

    def test_accept_requires_platform_admin(self, client):
        resp = client.post(self.BASE, headers=_tenant_headers())
        assert resp.status_code == 403

    def test_accept_returns_404_when_issue_missing(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.post(self.BASE, headers=_platform_headers())
        assert resp.status_code == 404

    def test_accept_transitions_status_to_triaged(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(
            _ISSUE_ROW
        ), _patch_set_status():
            resp = client.post(self.BASE, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == TEST_ISSUE_ID
        assert data["status"] == "triaged"
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# PATCH /platform/issues/{id}/severity
# ---------------------------------------------------------------------------


class TestOverrideSeverity:
    BASE = f"/api/v1/platform/issues/{TEST_ISSUE_ID}/severity"

    def test_severity_requires_auth(self, client):
        resp = client.patch(self.BASE, json={"severity": "P1"})
        assert resp.status_code == 401

    def test_severity_requires_platform_admin(self, client):
        resp = client.patch(
            self.BASE, json={"severity": "P1"}, headers=_tenant_headers()
        )
        assert resp.status_code == 403

    def test_severity_rejects_invalid_value(self, client):
        resp = client.patch(
            self.BASE, json={"severity": "CRITICAL"}, headers=_platform_headers()
        )
        assert resp.status_code == 422

    def test_severity_rejects_missing_field(self, client):
        resp = client.patch(self.BASE, json={}, headers=_platform_headers())
        assert resp.status_code == 422

    def test_severity_returns_404_when_issue_missing(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.patch(
                self.BASE, json={"severity": "P2"}, headers=_platform_headers()
            )
        assert resp.status_code == 404

    def test_severity_happy_path(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(_ISSUE_ROW):
            resp = client.patch(
                self.BASE,
                json={"severity": "P0", "reason": "Escalating urgency"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["severity"] == "P0"

    def test_severity_all_valid_levels_accepted(self, client):
        for level in ("P0", "P1", "P2", "P3", "P4"):
            session = _build_mock_session()
            with _override_session(session), _patch_get_issue(_ISSUE_ROW):
                resp = client.patch(
                    self.BASE,
                    json={"severity": level},
                    headers=_platform_headers(),
                )
            assert resp.status_code == 200, f"Expected 200 for severity {level}"
            assert resp.json()["severity"] == level


# ---------------------------------------------------------------------------
# POST /platform/issues/{id}/wont-fix
# ---------------------------------------------------------------------------


class TestWontFix:
    BASE = f"/api/v1/platform/issues/{TEST_ISSUE_ID}/wont-fix"

    def test_wontfix_requires_auth(self, client):
        assert client.post(self.BASE).status_code == 401

    def test_wontfix_requires_platform_admin(self, client):
        assert client.post(self.BASE, headers=_tenant_headers()).status_code == 403

    def test_wontfix_404_when_missing(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.post(self.BASE, json={}, headers=_platform_headers())
        assert resp.status_code == 404

    def test_wontfix_closes_issue(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(
            _ISSUE_ROW
        ), _patch_set_status():
            resp = client.post(
                self.BASE,
                json={"reason": "Out of scope for current sprint"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"

    def test_wontfix_empty_reason_allowed(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(
            _ISSUE_ROW
        ), _patch_set_status():
            resp = client.post(self.BASE, json={}, headers=_platform_headers())
        assert resp.status_code == 200
        assert resp.json()["status"] == "closed"


# ---------------------------------------------------------------------------
# PATCH /platform/issues/{id}/assign
# ---------------------------------------------------------------------------


class TestAssignIssue:
    BASE = f"/api/v1/platform/issues/{TEST_ISSUE_ID}/assign"

    def test_assign_requires_auth(self, client):
        assert (
            client.patch(self.BASE, json={"assignee_email": "x@x.com"}).status_code
            == 401
        )

    def test_assign_requires_platform_admin(self, client):
        resp = client.patch(
            self.BASE, json={"assignee_email": "x@x.com"}, headers=_tenant_headers()
        )
        assert resp.status_code == 403

    def test_assign_rejects_missing_email(self, client):
        resp = client.patch(self.BASE, json={}, headers=_platform_headers())
        assert resp.status_code == 422

    def test_assign_returns_404_when_missing(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.patch(
                self.BASE,
                json={"assignee_email": "eng@platform.com"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 404

    def test_assign_returns_assigned_to(self, client):
        # execute calls: SELECT users, SELECT metadata, UPDATE, INSERT event
        user_row = MagicMock()
        user_row.__getitem__ = lambda self, i: [TEST_USER_ID, "Alice"][i]
        meta_row = MagicMock()
        meta_row.__getitem__ = lambda self, i: [{}][i]

        session = _build_mock_session(
            execute_side_effects=[user_row, meta_row, None, None]
        )
        with _override_session(session), _patch_get_issue(_ISSUE_ROW):
            resp = client.patch(
                self.BASE,
                json={"assignee_email": "eng@platform.com"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert "assigned_to" in resp.json()


# ---------------------------------------------------------------------------
# POST /platform/issues/{id}/request-info
# ---------------------------------------------------------------------------


class TestRequestInfo:
    BASE = f"/api/v1/platform/issues/{TEST_ISSUE_ID}/request-info"

    def test_request_info_requires_auth(self, client):
        assert client.post(self.BASE, json={"message": "Hi"}).status_code == 401

    def test_request_info_requires_platform_admin(self, client):
        resp = client.post(
            self.BASE,
            json={"message": "Please provide logs"},
            headers=_tenant_headers(),
        )
        assert resp.status_code == 403

    def test_request_info_rejects_empty_message(self, client):
        resp = client.post(self.BASE, json={"message": ""}, headers=_platform_headers())
        assert resp.status_code == 422

    def test_request_info_missing_message_field(self, client):
        resp = client.post(self.BASE, json={}, headers=_platform_headers())
        assert resp.status_code == 422

    def test_request_info_transitions_to_awaiting(self, client):
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(_ISSUE_ROW),
            _patch_set_status(),
            _patch_send_notifs(),
        ):
            resp = client.post(
                self.BASE,
                json={"message": "Please attach the error logs"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_info"

    def test_request_info_404_when_missing(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.post(
                self.BASE,
                json={"message": "Please attach the error logs"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /platform/issues/{id}/route
# ---------------------------------------------------------------------------


class TestRouteIssue:
    BASE = f"/api/v1/platform/issues/{TEST_ISSUE_ID}/route"

    def test_route_requires_auth(self, client):
        assert client.post(self.BASE, json={}).status_code == 401

    def test_route_requires_platform_admin(self, client):
        resp = client.post(self.BASE, json={}, headers=_tenant_headers())
        assert resp.status_code == 403

    def test_route_404_when_missing(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.post(
                self.BASE, json={"notify_tenant": True}, headers=_platform_headers()
            )
        assert resp.status_code == 404

    def test_route_transitions_to_routed(self, client):
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(_ISSUE_ROW),
            _patch_set_status(),
            _patch_send_notifs(),
        ):
            resp = client.post(
                self.BASE,
                json={"notify_tenant": True, "note": "Please investigate"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "routed"

    def test_route_without_notify_skips_notifications(self, client):
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(_ISSUE_ROW),
            _patch_set_status(),
            _patch_send_notifs() as mock_notifs,
        ):
            resp = client.post(
                self.BASE,
                json={"notify_tenant": False},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "routed"
        mock_notifs.assert_not_called()

    def test_route_empty_body_uses_defaults(self, client):
        """notify_tenant defaults to True, note defaults to ''."""
        session = _build_mock_session()
        with (
            _override_session(session),
            _patch_get_issue(_ISSUE_ROW),
            _patch_set_status(),
            _patch_send_notifs(),
        ):
            resp = client.post(self.BASE, json={}, headers=_platform_headers())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /platform/issues/{id}/close-duplicate
# ---------------------------------------------------------------------------


class TestCloseDuplicate:
    BASE = f"/api/v1/platform/issues/{TEST_ISSUE_ID}/close-duplicate"
    OTHER_ISSUE_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

    def test_close_dup_requires_auth(self, client):
        assert (
            client.post(
                self.BASE, json={"duplicate_of": self.OTHER_ISSUE_ID}
            ).status_code
            == 401
        )

    def test_close_dup_requires_platform_admin(self, client):
        resp = client.post(
            self.BASE,
            json={"duplicate_of": self.OTHER_ISSUE_ID},
            headers=_tenant_headers(),
        )
        assert resp.status_code == 403

    def test_close_dup_rejects_self_reference(self, client):
        resp = client.post(
            self.BASE,
            json={"duplicate_of": TEST_ISSUE_ID},
            headers=_platform_headers(),
        )
        assert resp.status_code == 422

    def test_close_dup_requires_duplicate_of_field(self, client):
        resp = client.post(self.BASE, json={}, headers=_platform_headers())
        assert resp.status_code == 422

    def test_close_dup_404_when_missing(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(None):
            resp = client.post(
                self.BASE,
                json={"duplicate_of": self.OTHER_ISSUE_ID},
                headers=_platform_headers(),
            )
        assert resp.status_code == 404

    def test_close_dup_closes_with_reference(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(
            _ISSUE_ROW
        ), _patch_set_status():
            resp = client.post(
                self.BASE,
                json={"duplicate_of": self.OTHER_ISSUE_ID},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "closed"
        assert data["duplicate_of"] == self.OTHER_ISSUE_ID

    def test_close_dup_optional_note_accepted(self, client):
        session = _build_mock_session()
        with _override_session(session), _patch_get_issue(
            _ISSUE_ROW
        ), _patch_set_status():
            resp = client.post(
                self.BASE,
                json={"duplicate_of": self.OTHER_ISSUE_ID, "note": "See #123"},
                headers=_platform_headers(),
            )
        assert resp.status_code == 200
