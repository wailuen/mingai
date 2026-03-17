"""
Unit tests for TA-007: KB access control API.

  GET  /admin/knowledge-base/{id}/access
  PATCH /admin/knowledge-base/{id}/access

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
TEST_INDEX_ID = str(uuid.uuid4())

_BASE_URL = f"/api/v1/admin/knowledge-base/{TEST_INDEX_ID}/access"


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


def _patch_db(get_row=None, user_count=0, kb_owned=True):
    """
    Patch DB session.

    Routes call execute() in this order:
      1. verify_kb_belongs_to_tenant — UNION ALL query (contains "UNION ALL")
      2. get_kb_access_db / upsert_kb_access_db — kb_access_control SELECT/INSERT
      3. user count check — COUNT(*) query

    kb_owned: when True, the ownership check returns a truthy row (kb exists for
              this tenant). When False, it returns None (triggering 404).
    get_row:  the row returned by the kb_access_control SELECT (None = no row yet).
    user_count: scalar returned by COUNT(*) user validation query.
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    # Sentinel for ownership check — any truthy value works.
    _OWNED_SENTINEL = ("1",)

    async def _execute(*args, **kwargs):
        mock_result = MagicMock()
        sql = str(args[0]) if args else ""

        if "UNION ALL" in sql.upper():
            # verify_kb_belongs_to_tenant
            mock_result.fetchone.return_value = _OWNED_SENTINEL if kb_owned else None
        elif "kb_access_control" in sql and "COUNT" not in sql.upper():
            # get_kb_access_db SELECT (and upsert INSERT — fetchone not used there)
            mock_result.fetchone.return_value = get_row
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


class TestKBAccessGetAuth:
    def test_requires_auth(self, client):
        resp = client.get(_BASE_URL)
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client):
        resp = client.get(_BASE_URL, headers=_viewer_headers())
        assert resp.status_code == 403

    def test_invalid_uuid_returns_422(self, client):
        resp = client.get(
            "/api/v1/admin/knowledge-base/not-a-uuid/access",
            headers=_admin_headers(),
        )
        assert resp.status_code == 422


class TestKBAccessGetDefaults:
    def test_no_row_returns_workspace_wide(self, client):
        """When KB is owned but no access-control row exists, default is workspace_wide."""
        with _patch_db(get_row=None, kb_owned=True):
            resp = client.get(_BASE_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["index_id"] == TEST_INDEX_ID
        assert data["visibility_mode"] == "workspace_wide"
        assert data["allowed_roles"] == []
        assert data["allowed_user_ids"] == []

    def test_existing_row_returned(self, client):
        """When a row exists, it is returned correctly."""
        row = ("role_restricted", ["editor"], [])
        with _patch_db(get_row=row, kb_owned=True):
            resp = client.get(_BASE_URL, headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "role_restricted"
        assert data["allowed_roles"] == ["editor"]

    def test_foreign_tenant_kb_returns_404(self, client):
        """When KB does not belong to calling tenant, returns 404 (not 403)."""
        with _patch_db(kb_owned=False):
            resp = client.get(_BASE_URL, headers=_admin_headers())
        assert resp.status_code == 404


class TestKBAccessPatchAuth:
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


class TestKBAccessPatchValidation:
    def test_invalid_visibility_mode_returns_422(self, client):
        resp = client.patch(
            _BASE_URL,
            json={"visibility_mode": "agent_only_invalid"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_role_restricted_without_roles_returns_422(self, client):
        with _patch_db(kb_owned=True):
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "role_restricted", "allowed_roles": []},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_user_specific_without_users_returns_422(self, client):
        with _patch_db(kb_owned=True):
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "user_specific", "allowed_user_ids": []},
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_invalid_role_in_allowed_roles_returns_422(self, client):
        resp = client.patch(
            _BASE_URL,
            json={
                "visibility_mode": "role_restricted",
                "allowed_roles": ["super_admin"],
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_uuid_in_allowed_user_ids_returns_422(self, client):
        resp = client.patch(
            _BASE_URL,
            json={
                "visibility_mode": "user_specific",
                "allowed_user_ids": ["not-a-uuid"],
            },
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_user_not_in_tenant_returns_422(self, client):
        uid = str(uuid.uuid4())
        with _patch_db(user_count=0, kb_owned=True):
            resp = client.patch(
                _BASE_URL,
                json={
                    "visibility_mode": "user_specific",
                    "allowed_user_ids": [uid],
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 422

    def test_foreign_tenant_kb_returns_404(self, client):
        """PATCH for KB not owned by tenant returns 404 (not 403)."""
        with _patch_db(kb_owned=False):
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "workspace_wide"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 404


class TestKBAccessPatchSuccess:
    def test_workspace_wide_upsert(self, client):
        with _patch_db(kb_owned=True):
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "workspace_wide"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "workspace_wide"
        assert data["index_id"] == TEST_INDEX_ID

    def test_role_restricted_upsert(self, client):
        with _patch_db(kb_owned=True):
            resp = client.patch(
                _BASE_URL,
                json={
                    "visibility_mode": "role_restricted",
                    "allowed_roles": ["editor", "admin"],
                },
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "role_restricted"
        assert set(data["allowed_roles"]) == {"editor", "admin"}

    def test_agent_only_upsert(self, client):
        """agent_only is a valid mode for KB (not available for agents)."""
        with _patch_db(kb_owned=True):
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "agent_only"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility_mode"] == "agent_only"

    def test_user_specific_upsert(self, client):
        uid = str(uuid.uuid4())
        with _patch_db(user_count=1, kb_owned=True):
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

    def test_patch_returns_correct_structure(self, client):
        """Response always includes index_id, visibility_mode, allowed_roles, allowed_user_ids."""
        with _patch_db(kb_owned=True):
            resp = client.patch(
                _BASE_URL,
                json={"visibility_mode": "workspace_wide"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) >= {
            "index_id",
            "visibility_mode",
            "allowed_roles",
            "allowed_user_ids",
        }
