"""
Unit tests for TA-032: Bulk user operations.

  POST /api/v1/admin/users/bulk-action

Actions: suspend, role_change, kb_assignment

Tier 1: Fast, isolated — mocks DB session.
"""
import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "t032" * 16
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())
_ADMIN_ID = str(uuid.uuid4())  # UUID so it passes user_ids UUID validator

_BULK_ACTION_URL = "/api/v1/admin/users/bulk-action"

_USER_A = str(uuid.uuid4())
_USER_B = str(uuid.uuid4())
_KB_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _make_admin_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": _ADMIN_ID,
            "tenant_id": TEST_TENANT_ID,
            "roles": ["tenant_admin"],
            "scope": "tenant",
            "plan": "professional",
            "exp": now + timedelta(hours=1),
            "iat": now,
            "token_version": 2,
        },
        TEST_JWT_SECRET,
        algorithm=TEST_JWT_ALGORITHM,
    )


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": TEST_TENANT_ID,
            "roles": ["viewer"],
            "scope": "tenant",
            "plan": "professional",
            "exp": now + timedelta(hours=1),
            "iat": now,
            "token_version": 2,
        },
        TEST_JWT_SECRET,
        algorithm=TEST_JWT_ALGORITHM,
    )


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_admin_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env_vars():
    env = {
        "JWT_SECRET_KEY": TEST_JWT_SECRET,
        "JWT_ALGORITHM": TEST_JWT_ALGORITHM,
        "REDIS_URL": "redis://localhost:6379/0",
        "FRONTEND_URL": "http://localhost:3022",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture(scope="module")
def client(env_vars):
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


def _patch_db_suspend(found_ids: list[str], update_succeeds: bool = True):
    """Patch DB for suspend action tests."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = [0]

    async def _execute(stmt, params=None, **kwargs):
        call_count[0] += 1
        mock_result = MagicMock()
        sql = str(stmt)

        if "SELECT id FROM users" in sql:
            # Return found_ids as rows
            mock_result.fetchall.return_value = [(fid,) for fid in found_ids]
        elif "UPDATE users SET status" in sql:
            mock_result.rowcount = 1 if update_succeeds else 0
        else:
            mock_result.fetchall.return_value = []
            mock_result.rowcount = 0

        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield mock_session
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


def _patch_db_role_change(found_ids: list[str]):
    """Patch DB for role_change action tests."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        sql = str(stmt)

        if "SELECT id FROM users" in sql:
            mock_result.fetchall.return_value = [(fid,) for fid in found_ids]
        elif "UPDATE users SET role" in sql:
            mock_result.rowcount = 1
        elif "INSERT INTO audit_log" in sql:
            mock_result.rowcount = 1
        else:
            mock_result.fetchall.return_value = []
            mock_result.rowcount = 0

        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield mock_session
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


def _patch_db_kb_assignment(found_ids: list[str], kb_exists: bool = True):
    """Patch DB for kb_assignment action tests."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()

    async def _execute(stmt, params=None, **kwargs):
        mock_result = MagicMock()
        sql = str(stmt)

        if "config->>'kb_id'" in sql or ("kb_access_control" in sql and "UNION" in sql):
            # KB ownership check — returns a row if kb_exists
            mock_result.fetchone.return_value = (1,) if kb_exists else None
        elif "SELECT id FROM users" in sql:
            mock_result.fetchall.return_value = [(fid,) for fid in found_ids]
        elif "INSERT INTO kb_access_control" in sql:
            mock_result.rowcount = 1
        else:
            mock_result.fetchall.return_value = []
            mock_result.rowcount = 0

        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override

    @contextlib.contextmanager
    def _ctx():
        try:
            yield mock_session
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


# ---------------------------------------------------------------------------
# Tests: Auth & Validation
# ---------------------------------------------------------------------------


class TestBulkActionAuth:
    def test_requires_auth(self, client):
        resp = client.post(
            _BULK_ACTION_URL,
            json={"user_ids": [_USER_A], "action": "suspend"},
        )
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.post(
            _BULK_ACTION_URL,
            json={"user_ids": [_USER_A], "action": "suspend"},
            headers=_viewer_headers(),
        )
        assert resp.status_code == 403


class TestBulkActionValidation:
    def test_too_many_user_ids_returns_422(self, client):
        ids = [str(uuid.uuid4()) for _ in range(101)]
        resp = client.post(
            _BULK_ACTION_URL,
            json={"user_ids": ids, "action": "suspend"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_empty_user_ids_returns_422(self, client):
        resp = client.post(
            _BULK_ACTION_URL,
            json={"user_ids": [], "action": "suspend"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_action_returns_422(self, client):
        resp = client.post(
            _BULK_ACTION_URL,
            json={"user_ids": [_USER_A], "action": "delete"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_uuid_in_user_ids_returns_422(self, client):
        resp = client.post(
            _BULK_ACTION_URL,
            json={"user_ids": ["not-a-uuid"], "action": "suspend"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_role_change_without_role_returns_422(self, client):
        with _patch_db_role_change([]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={"user_ids": [_USER_A], "action": "role_change", "payload": {}},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_kb_assignment_without_kb_id_returns_422(self, client):
        with _patch_db_kb_assignment([]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={"user_ids": [_USER_A], "action": "kb_assignment", "payload": {}},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_invalid_role_returns_422(self, client):
        resp = client.post(
            _BULK_ACTION_URL,
            json={
                "user_ids": [_USER_A],
                "action": "role_change",
                "payload": {"role": "superuser"},
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: suspend action
# ---------------------------------------------------------------------------


class TestBulkSuspend:
    def test_all_found_all_succeed(self, client):
        with _patch_db_suspend(found_ids=[_USER_A, _USER_B]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={"user_ids": [_USER_A, _USER_B], "action": "suspend"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["succeeded"]) == {_USER_A, _USER_B}
        assert data["failed"] == []

    def test_not_found_goes_to_failed(self, client):
        """User not in tenant goes to failed with reason 'user not found'."""
        with _patch_db_suspend(found_ids=[_USER_A]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={"user_ids": [_USER_A, _USER_B], "action": "suspend"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert _USER_A in data["succeeded"]
        failed_ids = [f["user_id"] for f in data["failed"]]
        assert _USER_B in failed_ids

    def test_response_shape(self, client):
        with _patch_db_suspend(found_ids=[_USER_A]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={"user_ids": [_USER_A], "action": "suspend"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "succeeded" in data
        assert "failed" in data
        assert isinstance(data["succeeded"], list)
        assert isinstance(data["failed"], list)


# ---------------------------------------------------------------------------
# Tests: role_change action
# ---------------------------------------------------------------------------


class TestBulkRoleChange:
    def test_role_change_all_succeed(self, client):
        with _patch_db_role_change(found_ids=[_USER_A, _USER_B]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={
                    "user_ids": [_USER_A, _USER_B],
                    "action": "role_change",
                    "payload": {"role": "viewer"},
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["succeeded"]) == {_USER_A, _USER_B}
        assert data["failed"] == []

    def test_role_change_not_found_fails(self, client):
        with _patch_db_role_change(found_ids=[]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={
                    "user_ids": [_USER_A],
                    "action": "role_change",
                    "payload": {"role": "tenant_admin"},
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert len(data["failed"]) == 1
        assert data["failed"][0]["reason"] == "user not found"


# ---------------------------------------------------------------------------
# Tests: kb_assignment action
# ---------------------------------------------------------------------------


class TestBulkKBAssignment:
    def test_kb_assignment_all_succeed(self, client):
        with _patch_db_kb_assignment(found_ids=[_USER_A, _USER_B]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={
                    "user_ids": [_USER_A, _USER_B],
                    "action": "kb_assignment",
                    "payload": {"kb_id": _KB_ID, "scope": "user_specific"},
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["succeeded"]) == {_USER_A, _USER_B}

    def test_kb_assignment_invalid_kb_id_all_fail(self, client):
        with _patch_db_kb_assignment(found_ids=[_USER_A]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={
                    "user_ids": [_USER_A],
                    "action": "kb_assignment",
                    "payload": {"kb_id": "not-a-valid-uuid"},
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert len(data["failed"]) == 1
        assert "invalid kb_id" in data["failed"][0]["reason"]

    def test_kb_assignment_kb_not_found_all_fail(self, client):
        """KB not belonging to tenant → all users fail with 'knowledge base not found'."""
        with _patch_db_kb_assignment(found_ids=[_USER_A], kb_exists=False):
            resp = client.post(
                _BULK_ACTION_URL,
                json={
                    "user_ids": [_USER_A],
                    "action": "kb_assignment",
                    "payload": {"kb_id": _KB_ID},
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert len(data["failed"]) == 1
        assert "knowledge base not found" in data["failed"][0]["reason"]


# ---------------------------------------------------------------------------
# Tests: Self-lockout prevention
# ---------------------------------------------------------------------------


class TestSelfLockout:
    def test_suspend_self_goes_to_failed(self, client):
        """Admin cannot suspend their own account."""
        with _patch_db_suspend(found_ids=[_ADMIN_ID]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={"user_ids": [_ADMIN_ID], "action": "suspend"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert len(data["failed"]) == 1
        assert "cannot suspend your own account" in data["failed"][0]["reason"]

    def test_role_change_self_goes_to_failed(self, client):
        """Admin cannot change their own role."""
        with _patch_db_role_change(found_ids=[_ADMIN_ID]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={
                    "user_ids": [_ADMIN_ID],
                    "action": "role_change",
                    "payload": {"role": "viewer"},
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == []
        assert len(data["failed"]) == 1
        assert "cannot change your own role" in data["failed"][0]["reason"]

    def test_suspend_mix_self_and_others(self, client):
        """Self goes to failed even when found in tenant; others go to succeeded."""
        with _patch_db_suspend(found_ids=[_ADMIN_ID, _USER_A]):
            resp = client.post(
                _BULK_ACTION_URL,
                json={"user_ids": [_ADMIN_ID, _USER_A], "action": "suspend"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert _USER_A in data["succeeded"]
        failed_ids = [f["user_id"] for f in data["failed"]]
        assert _ADMIN_ID in failed_ids
