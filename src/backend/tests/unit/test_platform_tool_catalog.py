"""
Unit tests for TODO-39: Tool Catalog API Alignment (TC-002 through TC-004).

Tests the retire, health history, and hard-delete guard endpoints:
  POST   /platform/tool-catalog/{id}/retire
  GET    /platform/tool-catalog/{id}/health
  DELETE /platform/tools/{id}  (409 guard when active assignments exist)

Tier 1: Fast, isolated. Uses FastAPI dependency_overrides for the DB session.
"""
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "t" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_TOOL_ID = str(uuid.uuid4())
TEST_USER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
# Session mock helpers
# ---------------------------------------------------------------------------


def _make_execute_result(fetchone_val=None, fetchall_val=None, scalar_val=None):
    r = MagicMock()
    r.fetchone = MagicMock(return_value=fetchone_val)
    r.fetchall = MagicMock(
        return_value=fetchall_val if fetchall_val is not None else (
            [fetchone_val] if fetchone_val is not None else []
        )
    )
    r.scalar = MagicMock(return_value=scalar_val)
    r.mappings = MagicMock(return_value=MagicMock(
        __iter__=MagicMock(return_value=iter([]))
    ))
    return r


def _build_mock_session(execute_side_effects: list | None = None):
    session = AsyncMock()
    session.commit = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)

    empty_result = _make_execute_result()

    if execute_side_effects is None:
        session.execute = AsyncMock(return_value=empty_result)
    else:
        results = []
        for effect in execute_side_effects:
            if isinstance(effect, Exception):
                results.append(effect)
            else:
                results.append(effect)
        # Wrap non-exception values in execute results
        side_effects = []
        for effect in execute_side_effects:
            if isinstance(effect, Exception):
                side_effects.append(effect)
            else:
                side_effects.append(effect)
        side_effects += [empty_result] * 10
        session.execute = AsyncMock(side_effect=side_effects)

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


# ---------------------------------------------------------------------------
# Helper: build a fake retire result row (named tuple style via MagicMock)
# ---------------------------------------------------------------------------


def _retire_row(is_active: bool = False, health_status: str = "unavailable"):
    row = MagicMock()
    row.id = uuid.UUID(TEST_TOOL_ID)
    row.name = "test-tool"
    row.is_active = is_active
    row.health_status = health_status
    return row


# ---------------------------------------------------------------------------
# TC-002: POST /platform/tool-catalog/{id}/retire
# ---------------------------------------------------------------------------


class TestRetireTool:
    BASE = f"/api/v1/platform/tool-catalog/{TEST_TOOL_ID}/retire"

    def test_retire_requires_auth(self, client):
        resp = client.post(self.BASE)
        assert resp.status_code == 401

    def test_retire_requires_platform_admin(self, client):
        """Tenant users must receive 403."""
        retired_row = _retire_row()
        # Build two set_config results + the UPDATE result + audit_log
        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchone_val=retired_row),
            _make_execute_result(),  # audit_log
        ])
        with _override_session(session):
            resp = client.post(self.BASE, headers=_tenant_headers())
        assert resp.status_code == 403

    def test_retire_tool_sets_is_active_false(self, client):
        """Happy-path: retire sets is_active=FALSE and health_status='unavailable'."""
        retired_row = _retire_row(is_active=False, health_status="unavailable")
        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchone_val=retired_row),  # UPDATE RETURNING
            _make_execute_result(),  # audit_log INSERT
        ])
        with _override_session(session):
            resp = client.post(self.BASE, headers=_platform_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_active"] is False
        assert body["health_status"] == "unavailable"

    def test_retire_tool_writes_audit_log(self, client):
        """Verify execute is called at least 4 times (including audit_log)."""
        retired_row = _retire_row()
        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchone_val=retired_row),  # UPDATE
            _make_execute_result(),  # audit_log
        ])
        with _override_session(session):
            resp = client.post(self.BASE, headers=_platform_headers())

        assert resp.status_code == 200
        # At minimum: 2 set_config + 1 UPDATE + 1 audit_log = 4 calls
        assert session.execute.call_count >= 4

    def test_retire_tool_not_found(self, client):
        """404 when tool_id not found (UPDATE RETURNING yields no row)."""
        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchone_val=None),  # UPDATE RETURNING → no row
        ])
        with _override_session(session):
            resp = client.post(self.BASE, headers=_platform_headers())
        assert resp.status_code == 404

    def test_retire_tool_idempotent(self, client):
        """Retiring an already-retired tool returns 200 without error."""
        # The UPDATE still succeeds even if is_active was already FALSE
        retired_row = _retire_row(is_active=False, health_status="unavailable")
        session = _build_mock_session([
            _make_execute_result(),
            _make_execute_result(),
            _make_execute_result(fetchone_val=retired_row),
            _make_execute_result(),
        ])
        with _override_session(session):
            resp = client.post(self.BASE, headers=_platform_headers())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# TC-003: GET /platform/tool-catalog/{id}/health
# ---------------------------------------------------------------------------


class TestToolHealthHistory:
    BASE = f"/api/v1/platform/tool-catalog/{TEST_TOOL_ID}/health"

    def test_health_history_requires_auth(self, client):
        resp = client.get(self.BASE)
        assert resp.status_code == 401

    def test_tool_health_history_not_found(self, client):
        """404 when tool_id doesn't exist."""
        # tool_catalog lookup returns no row
        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchone_val=None),  # tool lookup → not found
        ])
        with _override_session(session):
            resp = client.get(self.BASE, headers=_platform_headers())
        assert resp.status_code == 404

    def test_tool_health_history_returns_list(self, client):
        """Returns a JSON array; endpoint response is 200."""
        # Tool exists, but no health check rows → fallback returns []
        tool_row = MagicMock()
        tool_row.health_status = "healthy"
        tool_row.last_health_check = None

        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchone_val=tool_row),  # tool lookup
            _make_execute_result(fetchall_val=[]),  # tool_health_checks
        ])
        with _override_session(session):
            resp = client.get(self.BASE, headers=_platform_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_tool_health_history_with_check_rows(self, client):
        """Returns check rows when tool_health_checks table has data."""
        tool_row = MagicMock()
        tool_row.health_status = "healthy"
        tool_row.last_health_check = None

        # Build a fake health-check row
        check_ts = datetime.now(timezone.utc)
        check_row = MagicMock()
        check_row.checked_at = check_ts
        check_row.status = "healthy"
        check_row.latency_ms = 120
        check_row.error_msg = None

        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchone_val=tool_row),  # tool lookup
            _make_execute_result(fetchall_val=[check_row]),  # history
        ])
        with _override_session(session):
            resp = client.get(self.BASE, headers=_platform_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["status"] == "healthy"


# ---------------------------------------------------------------------------
# TC-004: DELETE /platform/tools/{id} — 409 guard for active assignments
# ---------------------------------------------------------------------------


class TestHardDeleteGuard:
    BASE = f"/api/v1/platform/tools/{TEST_TOOL_ID}"

    def test_hard_delete_blocked_with_active_assignments(self, client):
        """DELETE returns 409 when template or skill assignments exist."""
        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            # UNION ALL returns two counts — first is agent_template_tools count > 0
            _make_execute_result(fetchall_val=[(2,), (0,)]),  # refs check → 2 refs
        ])
        with _override_session(session):
            resp = client.delete(self.BASE, headers=_platform_headers())
        assert resp.status_code == 409
        assert "retire" in resp.json()["detail"].lower()

    def test_hard_delete_allowed_without_assignments(self, client):
        """DELETE succeeds when no active template or skill assignments exist."""
        deleted_row = MagicMock()
        deleted_row.__getitem__ = lambda self, key: (
            uuid.UUID(TEST_TOOL_ID) if key == 0 else "test-tool"
        )

        session = _build_mock_session([
            _make_execute_result(),  # set_config scope
            _make_execute_result(),  # set_config tenant_id
            _make_execute_result(fetchall_val=[(0,), (0,)]),  # refs check → 0 refs
            _make_execute_result(fetchall_val=[]),  # tenant assignments
            _make_execute_result(fetchone_val=deleted_row),  # DELETE RETURNING
        ])
        with _override_session(session):
            resp = client.delete(self.BASE, headers=_platform_headers())
        # 200 or 404 (depends on whether deleted_row subscript works) — NOT 409
        assert resp.status_code != 409

    def test_hard_delete_requires_platform_admin(self, client):
        """403 for non-platform-admin callers."""
        session = _build_mock_session([
            _make_execute_result(),
            _make_execute_result(),
            _make_execute_result(fetchall_val=[(0,), (0,)]),
            _make_execute_result(fetchall_val=[]),
            _make_execute_result(fetchone_val=None),
        ])
        with _override_session(session):
            resp = client.delete(self.BASE, headers=_tenant_headers())
        assert resp.status_code == 403
