"""
Unit tests for platform admin tenant routes (API-024 to API-034).

Tests tenant CRUD, suspend/activate, LLM profiles, and platform stats.
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


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["platform_admin"],
        "scope": "platform",
        "plan": "enterprise",
        "email": "platform@mingai.io",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_tenant_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "tenant-admin",
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
def platform_headers():
    return {"Authorization": f"Bearer {_make_platform_token()}"}


@pytest.fixture
def tenant_headers():
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


class TestListTenants:
    """GET /api/v1/platform/tenants - platform admin only."""

    def test_list_tenants_requires_auth(self, client):
        resp = client.get("/api/v1/platform/tenants")
        assert resp.status_code == 401

    def test_list_tenants_requires_platform_admin(self, client, tenant_headers):
        resp = client.get("/api/v1/platform/tenants", headers=tenant_headers)
        assert resp.status_code == 403

    def test_list_tenants_returns_paginated(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.list_tenants_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get("/api/v1/platform/tenants", headers=platform_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    def test_list_tenants_pagination_params(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.list_tenants_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = {
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
            }
            resp = client.get(
                "/api/v1/platform/tenants?page=1&page_size=50", headers=platform_headers
            )
        assert resp.status_code == 200


class TestCreateTenant:
    """POST /api/v1/platform/tenants."""

    def test_create_tenant_requires_platform_admin(self, client, tenant_headers):
        resp = client.post(
            "/api/v1/platform/tenants",
            json={"name": "Acme Corp", "plan": "professional"},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_create_tenant_returns_created(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.create_tenant_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "id": "tenant-new",
                "name": "Acme Corp",
                "slug": "acme-corp-12345678",
                "plan": "professional",
                "status": "active",
                "primary_contact_email": "admin@acme.com",
            }
            resp = client.post(
                "/api/v1/platform/tenants",
                json={
                    "name": "Acme Corp",
                    "plan": "professional",
                    "primary_contact_email": "admin@acme.com",
                },
                headers=platform_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data

    def test_create_tenant_rejects_empty_name(self, client, platform_headers):
        resp = client.post(
            "/api/v1/platform/tenants",
            json={
                "name": "",
                "plan": "professional",
                "primary_contact_email": "a@b.com",
            },
            headers=platform_headers,
        )
        assert resp.status_code == 422


class TestGetTenant:
    """GET /api/v1/platform/tenants/{id}."""

    def test_get_tenant_requires_platform_admin(self, client, tenant_headers):
        resp = client.get("/api/v1/platform/tenants/tenant-1", headers=tenant_headers)
        assert resp.status_code == 403

    def test_get_tenant_returns_data(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {
                "id": "tenant-1",
                "name": "Acme Corp",
                "status": "active",
            }
            resp = client.get(
                "/api/v1/platform/tenants/tenant-1", headers=platform_headers
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == "tenant-1"

    def test_get_tenant_returns_404(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get(
                "/api/v1/platform/tenants/nonexistent", headers=platform_headers
            )
        assert resp.status_code == 404


class TestUpdateTenant:
    """PATCH /api/v1/platform/tenants/{id}."""

    def test_update_tenant_requires_platform_admin(self, client, tenant_headers):
        resp = client.patch(
            "/api/v1/platform/tenants/tenant-1",
            json={"plan": "enterprise"},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_update_tenant_returns_updated(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.update_tenant_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = {"id": "tenant-1", "plan": "enterprise"}
            resp = client.patch(
                "/api/v1/platform/tenants/tenant-1",
                json={"plan": "enterprise"},
                headers=platform_headers,
            )
        assert resp.status_code == 200

    def test_update_tenant_returns_404_when_not_found(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.update_tenant_db", new_callable=AsyncMock
        ) as mock_update:
            mock_update.return_value = None
            resp = client.patch(
                "/api/v1/platform/tenants/nonexistent",
                json={"plan": "enterprise"},
                headers=platform_headers,
            )
        assert resp.status_code == 404


class TestSuspendActivateTenant:
    """POST /api/v1/platform/tenants/{id}/suspend and activate."""

    def test_suspend_requires_platform_admin(self, client, tenant_headers):
        resp = client.post(
            "/api/v1/platform/tenants/tenant-1/suspend", headers=tenant_headers
        )
        assert resp.status_code == 403

    def test_suspend_tenant_returns_200(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.suspend_tenant_db", new_callable=AsyncMock
        ) as mock_sus:
            mock_sus.return_value = {"id": "tenant-1", "status": "suspended"}
            resp = client.post(
                "/api/v1/platform/tenants/tenant-1/suspend", headers=platform_headers
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

    def test_activate_requires_platform_admin(self, client, tenant_headers):
        resp = client.post(
            "/api/v1/platform/tenants/tenant-1/activate", headers=tenant_headers
        )
        assert resp.status_code == 403

    def test_activate_tenant_returns_200(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.activate_tenant_db", new_callable=AsyncMock
        ) as mock_act:
            mock_act.return_value = {"id": "tenant-1", "status": "active"}
            resp = client.post(
                "/api/v1/platform/tenants/tenant-1/activate", headers=platform_headers
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"


class TestLLMProfiles:
    """GET and POST /api/v1/platform/llm-profiles."""

    def test_list_llm_profiles_requires_platform_admin(self, client, tenant_headers):
        resp = client.get("/api/v1/platform/llm-profiles", headers=tenant_headers)
        assert resp.status_code == 403

    def test_list_llm_profiles_returns_list(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.list_llm_profiles_db", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = []
            resp = client.get("/api/v1/platform/llm-profiles", headers=platform_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_llm_profile_requires_platform_admin(self, client, tenant_headers):
        resp = client.post(
            "/api/v1/platform/llm-profiles",
            json={
                "tenant_id": TEST_TENANT_ID,
                "name": "Primary",
                "provider": "azure",
                "primary_model": "agentic-worker",
                "intent_model": "agentic-router",
                "embedding_model": "text-embedding-3-small",
            },
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_create_llm_profile_returns_created(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.create_llm_profile_db", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {
                "id": "profile-1",
                "tenant_id": TEST_TENANT_ID,
                "name": "Primary",
                "provider": "azure",
                "primary_model": "agentic-worker",
                "intent_model": "agentic-router",
                "embedding_model": "text-embedding-3-small",
            }
            resp = client.post(
                "/api/v1/platform/llm-profiles",
                json={
                    "tenant_id": TEST_TENANT_ID,
                    "name": "Primary",
                    "provider": "azure",
                    "primary_model": "agentic-worker",
                    "intent_model": "agentic-router",
                    "embedding_model": "text-embedding-3-small",
                },
                headers=platform_headers,
            )
        assert resp.status_code == 201
        assert "id" in resp.json()


class TestPlatformStats:
    """GET /api/v1/platform/stats."""

    def test_platform_stats_requires_platform_admin(self, client, tenant_headers):
        resp = client.get("/api/v1/platform/stats", headers=tenant_headers)
        assert resp.status_code == 403

    def test_platform_stats_returns_data(self, client, platform_headers):
        with patch(
            "app.modules.tenants.routes.get_platform_stats_db", new_callable=AsyncMock
        ) as mock_stats:
            mock_stats.return_value = {
                "total_tenants": 10,
                "active_tenants": 8,
                "total_users": 500,
                "queries_today": 1200,
            }
            resp = client.get("/api/v1/platform/stats", headers=platform_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_tenants" in data
