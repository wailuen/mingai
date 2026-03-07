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


# ---------------------------------------------------------------------------
# GET /api/v1/platform/tenants/{tenant_id}/health — API-029
# ---------------------------------------------------------------------------

_MOCK_HEALTH_COMPONENTS = {
    "usage_trend_pct": -0.15,  # 15% decline (850 recent vs 1000 prior)
    "feature_breadth": 0.60,  # 3 of 5 features active
    "satisfaction_pct": 90.0,  # 45/50 positive feedback
    "error_rate_pct": 0.0,  # 0 open issues
    "recent_queries": 850,
    "prior_queries": 1000,
    "features_active": 3,
    "positive_feedback": 45,
    "total_feedback": 50,
    "open_issues": 0,
}

_MOCK_TENANT = {
    "id": TEST_TENANT_ID,
    "name": "Acme Corp",
    "slug": "acme-corp-12345678",
    "plan": "professional",
    "status": "active",
    "primary_contact_email": "admin@acme.com",
    "created_at": "2025-01-01T00:00:00",
}


class TestGetTenantHealthScore:
    """GET /api/v1/platform/tenants/{tenant_id}/health (API-029)"""

    def test_health_requires_auth(self, client):
        """Unauthenticated request returns 401."""
        resp = client.get(f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health")
        assert resp.status_code == 401

    def test_health_requires_platform_admin(self, client, tenant_headers):
        """Tenant admin (non-platform admin) is rejected with 403."""
        resp = client.get(
            f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_health_returns_404_for_unknown_tenant(self, client, platform_headers):
        """Returns 404 when tenant does not exist."""
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None
            resp = client.get(
                "/api/v1/platform/tenants/nonexistent/health",
                headers=platform_headers,
            )
        assert resp.status_code == 404

    def test_health_returns_all_required_fields(self, client, platform_headers):
        """200 response includes overall_score, category, at_risk, and 4 components."""
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get, patch(
            "app.modules.tenants.routes.get_tenant_health_components_db",
            new_callable=AsyncMock,
        ) as mock_components:
            mock_get.return_value = _MOCK_TENANT
            mock_components.return_value = _MOCK_HEALTH_COMPONENTS
            resp = client.get(
                f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                headers=platform_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "category" in data
        assert "at_risk" in data
        assert "tenant_id" in data
        assert data["tenant_id"] == TEST_TENANT_ID

        components = data["components"]
        assert "usage_trend" in components
        assert "feature_breadth" in components
        assert "satisfaction" in components
        assert "error_rate" in components

    def test_health_component_weights_are_correct(self, client, platform_headers):
        """Each component carries the correct weight (30/20/35/15)."""
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get, patch(
            "app.modules.tenants.routes.get_tenant_health_components_db",
            new_callable=AsyncMock,
        ) as mock_components:
            mock_get.return_value = _MOCK_TENANT
            mock_components.return_value = _MOCK_HEALTH_COMPONENTS
            resp = client.get(
                f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                headers=platform_headers,
            )

        data = resp.json()["components"]
        assert data["usage_trend"]["weight"] == 0.30
        assert data["feature_breadth"]["weight"] == 0.20
        assert data["satisfaction"]["weight"] == 0.35
        assert data["error_rate"]["weight"] == 0.15

    def test_health_at_risk_flag_set_for_low_score(self, client, platform_headers):
        """at_risk is True when overall score falls below the 61-point threshold."""
        low_components = {
            **_MOCK_HEALTH_COMPONENTS,
            "usage_trend_pct": -1.0,  # maximum decline
            "feature_breadth": 0.0,
            "satisfaction_pct": 0.0,
            "error_rate_pct": 100.0,  # maximum errors
        }
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get, patch(
            "app.modules.tenants.routes.get_tenant_health_components_db",
            new_callable=AsyncMock,
        ) as mock_components:
            mock_get.return_value = _MOCK_TENANT
            mock_components.return_value = low_components
            resp = client.get(
                f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                headers=platform_headers,
            )

        data = resp.json()
        assert data["at_risk"] is True
        assert data["overall_score"] < 61.0

    def test_health_at_risk_false_for_healthy_tenant(self, client, platform_headers):
        """at_risk is False when all health components are at maximum."""
        high_components = {
            **_MOCK_HEALTH_COMPONENTS,
            "usage_trend_pct": 0.0,  # flat growth (full score)
            "feature_breadth": 1.0,
            "satisfaction_pct": 100.0,
            "error_rate_pct": 0.0,
        }
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get, patch(
            "app.modules.tenants.routes.get_tenant_health_components_db",
            new_callable=AsyncMock,
        ) as mock_components:
            mock_get.return_value = _MOCK_TENANT
            mock_components.return_value = high_components
            resp = client.get(
                f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                headers=platform_headers,
            )

        data = resp.json()
        assert data["at_risk"] is False
        assert data["overall_score"] >= 61.0

    def test_health_component_details_include_raw_counts(
        self, client, platform_headers
    ):
        """Each component includes a details dict with raw DB count data."""
        with patch(
            "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
        ) as mock_get, patch(
            "app.modules.tenants.routes.get_tenant_health_components_db",
            new_callable=AsyncMock,
        ) as mock_components:
            mock_get.return_value = _MOCK_TENANT
            mock_components.return_value = _MOCK_HEALTH_COMPONENTS
            resp = client.get(
                f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                headers=platform_headers,
            )

        data = resp.json()["components"]
        assert "recent_queries" in data["usage_trend"]["details"]
        assert "prior_queries" in data["usage_trend"]["details"]
        assert "features_active" in data["feature_breadth"]["details"]
        assert data["feature_breadth"]["details"]["features_total"] == 5
        assert "positive_feedback" in data["satisfaction"]["details"]
        assert "total_feedback" in data["satisfaction"]["details"]
        assert "open_issues" in data["error_rate"]["details"]
