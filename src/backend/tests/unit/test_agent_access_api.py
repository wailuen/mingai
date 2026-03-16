"""
Unit tests for TA-009: Agent access control API.

  GET  /admin/agents/{id}/access
  PATCH /admin/agents/{id}/access

Also tests check_agent_access() enforcement logic.

Tier 1: Fast, isolated.
"""
import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = str(uuid.uuid4())
TEST_AGENT_ID = str(uuid.uuid4())

_BASE_URL = f"/api/v1/admin/agents/{TEST_AGENT_ID}/access"


def _make_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin-user-001",
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
        "sub": "viewer-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["viewer"],
        "scope": "tenant",
        "plan": "professional",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


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


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_admin_token()}"}


def _viewer_headers() -> dict:
    return {"Authorization": f"Bearer {_make_viewer_token()}"}


def _patch_db(
    agent_exists: bool = True,
    get_row=None,
    user_count: int = 0,
):
    """Patch DB session for agent access control tests.

    PATCH call order:
      1. agent_cards existence SELECT → fetchone() → row or None
      2. (if user_specific) users COUNT(*) → scalar()
      3. upsert INSERT/ON CONFLICT → no meaningful return
      4. commit

    GET call order:
      1. agent_access_control SELECT → fetchone() → row or None
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0
    agent_row = (uuid.UUID(TEST_AGENT_ID),) if agent_exists else None

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        sql = str(args[0]) if args else ""

        if "agent_access_control" in sql:
            mock_result.fetchone.return_value = get_row
        elif "agent_cards" in sql:
            mock_result.fetchone.return_value = agent_row
        elif "COUNT(*)" in sql.upper():
            mock_result.scalar.return_value = user_count
        else:
            mock_result.fetchone.return_value = None
            mock_result.scalar.return_value = None
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

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


class TestAgentAccessGetAuth:
    def test_requires_auth(self, client):
        resp = client.get(_BASE_URL)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.get(_BASE_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_invalid_uuid_returns_422(self, client):
        resp = client.get(
            "/api/v1/admin/agents/not-a-uuid/access",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422


class TestAgentAccessGetDefaults:
    def test_no_row_returns_workspace_wide(self, client):
        """When no agent_access_control row exists, default is workspace_wide."""
        with _patch_db(get_row=None):
            resp = client.get(_BASE_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == TEST_AGENT_ID
        assert data["visibility_mode"] == "workspace_wide"
        assert data["allowed_roles"] == []
        assert data["allowed_user_ids"] == []

    def test_existing_row_returned(self, client):
        """When a row exists, it is returned correctly."""
        row = ("role_restricted", ["editor"], [])
        with _patch_db(get_row=row):
            resp = client.get(_BASE_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "role_restricted"
        assert data["allowed_roles"] == ["editor"]


class TestAgentAccessPatchAuth:
    def test_patch_requires_auth(self, client):
        resp = client.patch(_BASE_URL, json={"visibility_mode": "workspace_wide"})
        assert resp.status_code == 401

    def test_patch_requires_tenant_admin(self, client):
        resp = client.patch(
            _BASE_URL,
            json={"visibility_mode": "workspace_wide"},
            headers=_viewer_headers(),
        )
        assert resp.status_code == 403


class TestAgentAccessPatchValidation:
    def test_agent_only_mode_not_valid_for_agents(self, client):
        """agent_only mode is reserved for KBs — not valid for agents."""
        resp = client.patch(
            _BASE_URL,
            json={"visibility_mode": "agent_only"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_visibility_mode_returns_422(self, client):
        resp = client.patch(
            _BASE_URL,
            json={"visibility_mode": "super_secret"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_agent_not_found_returns_404(self, client):
        with _patch_db(agent_exists=False):
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "workspace_wide"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 404

    def test_role_restricted_without_roles_returns_422(self, client):
        with _patch_db():
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "role_restricted", "allowed_roles": []},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_user_specific_without_users_returns_422(self, client):
        with _patch_db():
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "user_specific", "allowed_user_ids": []},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_invalid_role_returns_422(self, client):
        resp = client.patch(
            _BASE_URL,
            json={
                "visibility_mode": "role_restricted",
                "allowed_roles": ["god_mode"],
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_user_not_in_tenant_returns_422(self, client):
        uid = str(uuid.uuid4())
        with _patch_db(user_count=0):
            resp = client.patch(
                _BASE_URL,
                json={
                    "visibility_mode": "user_specific",
                    "allowed_user_ids": [uid],
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 422


class TestAgentAccessPatchSuccess:
    def test_workspace_wide_upsert(self, client):
        with _patch_db():
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "workspace_wide"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "workspace_wide"
        assert data["agent_id"] == TEST_AGENT_ID

    def test_role_restricted_upsert(self, client):
        with _patch_db():
            resp = client.patch(
                _BASE_URL,
                json={
                    "visibility_mode": "role_restricted",
                    "allowed_roles": ["editor"],
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "role_restricted"
        assert data["allowed_roles"] == ["editor"]

    def test_user_specific_upsert(self, client):
        uid = str(uuid.uuid4())
        with _patch_db(user_count=1):
            resp = client.patch(
                _BASE_URL,
                json={
                    "visibility_mode": "user_specific",
                    "allowed_user_ids": [uid],
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "user_specific"
        assert uid in data["allowed_user_ids"]

    def test_response_structure(self, client):
        with _patch_db():
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "workspace_wide"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) >= {
            "agent_id",
            "visibility_mode",
            "allowed_roles",
            "allowed_user_ids",
        }


class TestCheckAgentAccessLogic:
    """Unit tests for check_agent_access() enforcement helper."""

    def setup_method(self):
        from app.modules.admin.agent_access_control import check_agent_access

        self._check = check_agent_access

    def test_workspace_wide_always_allowed(self):
        assert self._check("workspace_wide", [], [], "any-user", ["viewer"]) is True

    def test_role_restricted_matching_role_allowed(self):
        assert (
            self._check("role_restricted", ["editor"], [], "u1", ["viewer", "editor"])
            is True
        )

    def test_role_restricted_no_matching_role_denied(self):
        assert self._check("role_restricted", ["admin"], [], "u1", ["viewer"]) is False

    def test_user_specific_matching_user_allowed(self):
        uid = str(uuid.uuid4())
        assert self._check("user_specific", [], [uid], uid, ["viewer"]) is True

    def test_user_specific_different_user_denied(self):
        uid1 = str(uuid.uuid4())
        uid2 = str(uuid.uuid4())
        assert self._check("user_specific", [], [uid1], uid2, ["viewer"]) is False

    def test_unknown_mode_denied(self):
        assert self._check("unknown_mode", [], [], "u1", ["admin"]) is False
