"""
Unit tests for TA-024: Template upgrade workflow.

Endpoints under test:
  GET  /api/v1/admin/agents/{id}/upgrade-available
  PATCH /api/v1/admin/agents/{id}/upgrade

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock/patch.

Strategy:
  - Override get_async_session with an AsyncMock session so direct session.execute
    calls (set_config, UPDATE) do not hit the real asyncpg pool.
  - Patch module-level helper functions (get_agent_by_id_db,
    _get_latest_published_template_version, insert_audit_log) so DB calls are
    fully controlled.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "c" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TEST_AGENT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEST_TEMPLATE_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

_MOD = "app.modules.agents.routes"

_UPGRADE_CHECK_URL = f"/api/v1/admin/agents/{TEST_AGENT_ID}/upgrade-available"
_UPGRADE_URL = f"/api/v1/admin/agents/{TEST_AGENT_ID}/upgrade"


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_viewer_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "viewer-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

_AGENT_WITH_TEMPLATE = {
    "id": TEST_AGENT_ID,
    "name": "My HR Bot",
    "description": "HR assistant",
    "category": "HR",
    "avatar": None,
    "source": "library",
    "system_prompt": "You are an HR assistant for Acme Corp.",
    "capabilities": [],
    "status": "active",
    "version": 1,
    "template_id": TEST_TEMPLATE_ID,
    "template_version": 1,
    "created_at": "2026-03-01T00:00:00+00:00",
    "updated_at": "2026-03-01T00:00:00+00:00",
}

_AGENT_WITHOUT_TEMPLATE = {
    **_AGENT_WITH_TEMPLATE,
    "template_id": None,
    "template_version": None,
}

_LATEST_TEMPLATE_SAME_VERSION = {
    "id": TEST_TEMPLATE_ID,
    "name": "HR Policy Assistant v1",
    "version": 1,
    "changelog": "Initial release.",
}

_LATEST_TEMPLATE_NEWER_VERSION = {
    "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    "name": "HR Policy Assistant v2",
    "version": 2,
    "changelog": "Improved holiday policy guidance.",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Build an AsyncMock session with a rowcount=1 execute result."""
    mock_execute_result = MagicMock()
    mock_execute_result.rowcount = 1
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.commit = AsyncMock()
    return mock_session


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
    from app.core.session import get_async_session
    from app.main import app

    mock_session = _make_mock_session()

    async def _override_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_async_session, None)


# ---------------------------------------------------------------------------
# Patch helpers — all patch module-level helpers so no real SQL is run
# ---------------------------------------------------------------------------


def _patch_get_agent(return_value):
    return patch(f"{_MOD}.get_agent_by_id_db", new=AsyncMock(return_value=return_value))


def _patch_get_latest(return_value):
    return patch(
        f"{_MOD}._get_latest_published_template_version",
        new=AsyncMock(return_value=return_value),
    )


def _patch_insert_audit(mock=None):
    return patch(
        f"{_MOD}.insert_audit_log",
        new=mock if mock is not None else AsyncMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# TestCheckUpgradeAvailable
# ---------------------------------------------------------------------------


class TestCheckUpgradeAvailable:
    def test_requires_tenant_admin(self, client):
        """Non-admin (viewer) must receive 403."""
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            _LATEST_TEMPLATE_NEWER_VERSION
        ):
            resp = client.get(_UPGRADE_CHECK_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, client):
        resp = client.get(_UPGRADE_CHECK_URL)
        assert resp.status_code == 401

    def test_agent_not_found_returns_404(self, client):
        with _patch_get_agent(None), _patch_get_latest(None):
            resp = client.get(_UPGRADE_CHECK_URL, headers=_admin_headers())
        assert resp.status_code == 404

    def test_no_template_id_returns_no_upgrade(self, client):
        with _patch_get_agent(_AGENT_WITHOUT_TEMPLATE), _patch_get_latest(None):
            resp = client.get(_UPGRADE_CHECK_URL, headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["upgrade_available"] is False

    def test_returns_upgrade_available_when_newer_version(self, client):
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            _LATEST_TEMPLATE_NEWER_VERSION
        ):
            resp = client.get(_UPGRADE_CHECK_URL, headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["upgrade_available"] is True
        assert body["current_version"] == 1
        assert body["available_version"] == 2
        assert "Improved holiday policy" in body["changelog"]

    def test_returns_no_upgrade_when_on_latest(self, client):
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            _LATEST_TEMPLATE_SAME_VERSION
        ):
            resp = client.get(_UPGRADE_CHECK_URL, headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["upgrade_available"] is False

    def test_changelog_empty_string_when_null(self, client):
        """Agent on older version but template has NULL changelog → empty string."""
        template_no_changelog = {**_LATEST_TEMPLATE_NEWER_VERSION, "changelog": None}
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            template_no_changelog
        ):
            resp = client.get(_UPGRADE_CHECK_URL, headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["upgrade_available"] is True
        assert body["changelog"] == ""


# ---------------------------------------------------------------------------
# TestUpgradeAgent
# ---------------------------------------------------------------------------


class TestUpgradeAgent:
    def test_requires_tenant_admin(self, client):
        """Non-admin (viewer) must receive 403."""
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            _LATEST_TEMPLATE_NEWER_VERSION
        ), _patch_insert_audit():
            resp = client.patch(_UPGRADE_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, client):
        resp = client.patch(_UPGRADE_URL)
        assert resp.status_code == 401

    def test_agent_not_found_returns_404(self, client):
        with _patch_get_agent(None), _patch_get_latest(None), _patch_insert_audit():
            resp = client.patch(_UPGRADE_URL, headers=_admin_headers())
        assert resp.status_code == 404

    def test_returns_409_when_no_upgrade_available(self, client):
        """Agent already on latest version → 409 Conflict."""
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            _LATEST_TEMPLATE_SAME_VERSION
        ), _patch_insert_audit():
            resp = client.patch(_UPGRADE_URL, headers=_admin_headers())
        assert resp.status_code == 409

    def test_returns_409_when_no_template_id(self, client):
        """Custom agents (no template_id) cannot be upgraded."""
        with _patch_get_agent(_AGENT_WITHOUT_TEMPLATE), _patch_get_latest(
            None
        ), _patch_insert_audit():
            resp = client.patch(_UPGRADE_URL, headers=_admin_headers())
        assert resp.status_code == 409

    def test_upgrade_updates_template_version(self, client):
        """Successful upgrade returns 200 with new template_version and upgraded=true."""
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            _LATEST_TEMPLATE_NEWER_VERSION
        ), _patch_insert_audit():
            resp = client.patch(_UPGRADE_URL, headers=_admin_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == TEST_AGENT_ID
        assert body["template_version"] == 2
        assert body["upgraded"] is True

    def test_audit_log_written(self, client):
        """insert_audit_log must be called once with action='agent_template_upgraded'."""
        audit_mock = AsyncMock(return_value=None)
        with _patch_get_agent(_AGENT_WITH_TEMPLATE), _patch_get_latest(
            _LATEST_TEMPLATE_NEWER_VERSION
        ), _patch_insert_audit(audit_mock):
            resp = client.patch(_UPGRADE_URL, headers=_admin_headers())

        assert resp.status_code == 200
        audit_mock.assert_called_once()
        # insert_audit_log signature: (tenant_id, user_id, action, resource_type,
        #                               resource_id, details, db)
        call_kwargs = audit_mock.call_args
        # Support both positional and keyword invocation
        positional = call_kwargs[0] if call_kwargs[0] else ()
        keyword = call_kwargs[1] if call_kwargs[1] else {}
        action = keyword.get("action") or (
            positional[2] if len(positional) > 2 else None
        )
        assert action == "agent_template_upgraded"
