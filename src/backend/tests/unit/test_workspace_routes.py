"""
Unit tests for workspace settings API (API-048/049).

Tests auth, RBAC, GET/PATCH for workspace settings.
Tier 1: Fast, isolated, uses mocking.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin-user",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@tenant.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_end_user_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "end-user",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": "user@tenant.com",
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


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


@pytest.fixture
def user_headers():
    return {"Authorization": f"Bearer {_make_end_user_token()}"}


class TestGetWorkspaceSettingsAuth:
    """GET /api/v1/admin/workspace - auth and RBAC."""

    def test_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.get("/api/v1/admin/workspace")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        """403 when end_user tries to access."""
        resp = client.get("/api/v1/admin/workspace", headers=user_headers)
        assert resp.status_code == 403


class TestGetWorkspaceSettings:
    """GET /api/v1/admin/workspace - returns settings."""

    def test_returns_settings_dict(self, client, admin_headers):
        """Returns workspace settings with expected keys."""
        with patch(
            "app.modules.admin.workspace.get_workspace_settings_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = {
                "name": "Acme Corp",
                "logo_url": None,
                "timezone": "UTC",
                "locale": "en",
                "auth_mode": "local",
                "notification_preferences": {},
                "tenant_name": "Acme Corp",
                "slug": "acme-corp",
                "plan": "professional",
            }
            resp = client.get("/api/v1/admin/workspace", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "tenant_name" in data
        assert "timezone" in data
        assert "locale" in data

    def test_returns_defaults_when_no_config(self, client, admin_headers):
        """Returns default settings when no config exists in DB."""
        with patch(
            "app.modules.admin.workspace.get_workspace_settings_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = {
                "name": "",
                "logo_url": None,
                "timezone": "UTC",
                "locale": "en",
                "auth_mode": "local",
                "notification_preferences": {},
                "tenant_name": "",
                "slug": "",
                "plan": "starter",
            }
            resp = client.get("/api/v1/admin/workspace", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["timezone"] == "UTC"
        assert data["locale"] == "en"


class TestPatchWorkspaceSettings:
    """PATCH /api/v1/admin/workspace - update settings."""

    def test_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.patch(
            "/api/v1/admin/workspace",
            json={"timezone": "Asia/Singapore"},
        )
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        """403 when end_user tries to update."""
        resp = client.patch(
            "/api/v1/admin/workspace",
            json={"timezone": "Asia/Singapore"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_returns_updated_settings(self, client, admin_headers):
        """Returns updated workspace settings."""
        with patch(
            "app.modules.admin.workspace.update_workspace_settings_db",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = {
                "name": "Acme Corp",
                "logo_url": None,
                "timezone": "Asia/Singapore",
                "locale": "en",
                "auth_mode": "local",
                "notification_preferences": {},
                "tenant_name": "Acme Corp",
                "slug": "acme-corp",
                "plan": "professional",
            }
            resp = client.patch(
                "/api/v1/admin/workspace",
                json={"timezone": "Asia/Singapore"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["timezone"] == "Asia/Singapore"

    def test_invalid_timezone_returns_422(self, client, admin_headers):
        """Invalid timezone string returns 422."""
        resp = client.patch(
            "/api/v1/admin/workspace",
            json={"timezone": "NotAReal/Timezone"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_partial_update_only_sends_provided_fields(self, client, admin_headers):
        """Only provided fields are sent to the DB update function."""
        with patch(
            "app.modules.admin.workspace.update_workspace_settings_db",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = {
                "name": "Acme Corp",
                "logo_url": None,
                "timezone": "UTC",
                "locale": "fr",
                "auth_mode": "local",
                "notification_preferences": {},
                "tenant_name": "Acme Corp",
                "slug": "acme-corp",
                "plan": "professional",
            }
            resp = client.patch(
                "/api/v1/admin/workspace",
                json={"locale": "fr"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        # Verify only locale was passed to update
        call_args = mock_update.call_args
        updates_arg = call_args.kwargs.get("updates") or call_args[1].get("updates")
        assert "locale" in updates_arg
        assert "timezone" not in updates_arg
