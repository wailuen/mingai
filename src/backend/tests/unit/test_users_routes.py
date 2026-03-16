"""
Unit tests for user routes (API-041 to API-050).

Tests user CRUD, profile management, and GDPR endpoints.
Tier 1: Fast, isolated, uses mocking.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "a" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_USER_ID = "user-001"


def _make_token(
    user_id: str = TEST_USER_ID,
    tenant_id: str = TEST_TENANT_ID,
    roles: list[str] | None = None,
    scope: str = "tenant",
    plan: str = "professional",
) -> str:
    if roles is None:
        roles = ["end_user"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles,
        "scope": scope,
        "plan": plan,
        "email": "user@test.com",
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
def user_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def admin_headers():
    return {
        "Authorization": f"Bearer {_make_token(roles=['tenant_admin'], scope='tenant')}"
    }


@pytest.fixture
def platform_headers():
    return {
        "Authorization": f"Bearer {_make_token(roles=['platform_admin'], scope='platform')}"
    }


class TestListUsers:
    """GET /api/v1/users - tenant admin only."""

    def test_list_users_requires_auth(self, client):
        resp = client.get("/api/v1/users")
        assert resp.status_code == 401

    def test_list_users_requires_tenant_admin(self, client, user_headers):
        resp = client.get("/api/v1/users", headers=user_headers)
        assert resp.status_code == 403

    def test_list_users_returns_paginated(self, client, admin_headers):
        with patch(
            "app.modules.users.routes.list_users_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_users_pagination_validation(self, client, admin_headers):
        resp = client.get("/api/v1/users?page=0", headers=admin_headers)
        assert resp.status_code == 422

    def test_list_users_page_size_max_100(self, client, admin_headers):
        resp = client.get("/api/v1/users?page_size=101", headers=admin_headers)
        assert resp.status_code == 422


class TestInviteUser:
    """POST /api/v1/users - invite user."""

    def test_invite_user_requires_auth(self, client):
        resp = client.post(
            "/api/v1/users", json={"email": "new@test.com", "role": "viewer"}
        )
        assert resp.status_code == 401

    def test_invite_user_requires_tenant_admin(self, client, user_headers):
        resp = client.post(
            "/api/v1/users",
            json={"email": "new@test.com", "role": "viewer"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_invite_user_returns_created(self, client, admin_headers):
        with patch(
            "app.modules.users.routes.invite_user_db", new_callable=AsyncMock
        ) as mock_invite:
            mock_invite.return_value = {
                "id": "user-new",
                "email": "new@test.com",
                "status": "invited",
            }
            resp = client.post(
                "/api/v1/users",
                json={"email": "new@test.com", "role": "viewer"},
                headers=admin_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data

    def test_invite_user_rejects_invalid_email(self, client, admin_headers):
        resp = client.post(
            "/api/v1/users",
            json={"email": "not-an-email", "role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_invite_user_rejects_missing_email(self, client, admin_headers):
        resp = client.post(
            "/api/v1/users",
            json={"role": "viewer"},
            headers=admin_headers,
        )
        assert resp.status_code == 422


class TestGetUser:
    """GET /api/v1/users/{id} - tenant admin or self."""

    def test_get_user_requires_auth(self, client):
        resp = client.get("/api/v1/users/user-001")
        assert resp.status_code == 401

    def test_get_user_admin_can_get_any_user(self, client, admin_headers):
        with patch(
            "app.modules.users.routes.get_user_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "user-001",
                "email": "user@test.com",
                "role": "viewer",
            }
            resp = client.get("/api/v1/users/user-001", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == "user-001"

    def test_get_user_returns_404_if_not_found(self, client, admin_headers):
        with patch(
            "app.modules.users.routes.get_user_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/users/nonexistent", headers=admin_headers)
        assert resp.status_code == 404


class TestUpdateUser:
    """PATCH /api/v1/users/{id} - tenant admin."""

    def test_update_user_requires_auth(self, client):
        resp = client.patch("/api/v1/users/user-001", json={"role": "tenant_admin"})
        assert resp.status_code == 401

    def test_update_user_requires_tenant_admin(self, client, user_headers):
        resp = client.patch(
            "/api/v1/users/user-001",
            json={"role": "tenant_admin"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    def test_update_user_returns_updated(self, client, admin_headers):
        with patch(
            "app.modules.users.routes.update_user_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {"id": "user-001", "role": "tenant_admin"}
            resp = client.patch(
                "/api/v1/users/user-001",
                json={"role": "tenant_admin"},
                headers=admin_headers,
            )
        assert resp.status_code == 200

    def test_update_user_returns_404_when_not_found(self, client, admin_headers):
        """PATCH on a non-existent user returns 404 (rowcount == 0)."""
        with patch(
            "app.modules.users.routes.update_user_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = None
            resp = client.patch(
                "/api/v1/users/nonexistent-user",
                json={"role": "tenant_admin"},
                headers=admin_headers,
            )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestDeactivateUser:
    """DELETE /api/v1/users/{id} - soft deactivate."""

    def test_deactivate_requires_auth(self, client):
        resp = client.delete("/api/v1/users/user-001")
        assert resp.status_code == 401

    def test_deactivate_requires_tenant_admin(self, client, user_headers):
        resp = client.delete("/api/v1/users/user-001", headers=user_headers)
        assert resp.status_code == 403

    def test_deactivate_returns_204(self, client, admin_headers):
        with patch(
            "app.modules.users.routes.deactivate_user_db", new_callable=AsyncMock
        ) as mock_deact:
            mock_deact.return_value = True
            resp = client.delete("/api/v1/users/user-001", headers=admin_headers)
        assert resp.status_code == 204


class TestCurrentUserProfile:
    """GET and PATCH /api/v1/users/me."""

    def test_get_me_requires_auth(self, client):
        resp = client.get("/api/v1/users/me")
        assert resp.status_code == 401

    def test_get_me_returns_profile(self, client, user_headers):
        with patch(
            "app.modules.users.routes.get_user_profile_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": TEST_USER_ID,
                "email": "user@test.com",
                "tenant_id": TEST_TENANT_ID,
            }
            resp = client.get("/api/v1/users/me", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data

    def test_patch_me_requires_auth(self, client):
        resp = client.patch("/api/v1/users/me", json={"display_name": "New Name"})
        assert resp.status_code == 401

    def test_patch_me_returns_updated(self, client, user_headers):
        with patch(
            "app.modules.users.routes.update_user_profile_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {"id": TEST_USER_ID, "display_name": "New Name"}
            resp = client.patch(
                "/api/v1/users/me",
                json={"display_name": "New Name"},
                headers=user_headers,
            )
        assert resp.status_code == 200


class TestGDPREndpoints:
    """POST /api/v1/users/me/gdpr/export and erase."""

    def test_gdpr_export_requires_auth(self, client):
        resp = client.post("/api/v1/users/me/gdpr/export")
        assert resp.status_code == 401

    def test_gdpr_export_returns_data(self, client, user_headers):
        with patch(
            "app.modules.users.routes.export_user_data", new_callable=AsyncMock
        ) as mock_export:
            mock_export.return_value = {"user_id": TEST_USER_ID, "data": {}}
            resp = client.post("/api/v1/users/me/gdpr/export", headers=user_headers)
        assert resp.status_code == 200
        assert "user_id" in resp.json()

    def test_gdpr_erase_requires_auth(self, client):
        resp = client.post("/api/v1/users/me/gdpr/erase")
        assert resp.status_code == 401

    def test_gdpr_erase_clears_all_stores(self, client, user_headers):
        with patch(
            "app.modules.users.routes.erase_user_data", new_callable=AsyncMock
        ) as mock_erase:
            mock_erase.return_value = {
                "erased": True,
                "stores_cleared": ["postgresql", "redis_l2", "working_memory"],
            }
            resp = client.post("/api/v1/users/me/gdpr/erase", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["erased"] is True
        assert len(data["stores_cleared"]) == 3
