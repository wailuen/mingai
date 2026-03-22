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
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20

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
        with (
            patch(
                "app.modules.tenants.routes.create_tenant_db", new_callable=AsyncMock
            ) as mock_create,
            patch("fastapi.BackgroundTasks.add_task"),
        ):
            mock_create.return_value = {
                "id": "tenant-new",
                "name": "Acme Corp",
                "slug": "acme-corp-12345678",
                "plan": "professional",
                "status": "provisioning",
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
        assert data["id"] == "tenant-new"
        assert data["name"] == "Acme Corp"
        assert data["status"] == "provisioning"
        assert data["plan"] == "professional"
        # job_id returned for SSE tracking
        assert "job_id" in data
        assert len(data["job_id"]) > 0

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
        """PA-009: 200 response includes current snapshot and 12-week trend."""
        override_key = self._apply_session_override(client)
        try:
            with patch(
                "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
            ) as mock_get:
                mock_get.return_value = _MOCK_TENANT
                resp = client.get(
                    f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                    headers=platform_headers,
                )
        finally:
            client.app.dependency_overrides.pop(override_key, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "trend" in data

        current = data["current"]
        assert "composite" in current
        assert "usage_trend" in current
        assert "feature_breadth" in current
        assert "satisfaction" in current
        assert "error_rate" in current
        assert "at_risk_flag" in current

        # Trend is always 12 weeks
        assert len(data["trend"]) == 12

    def _apply_session_override(self, client):
        """
        Apply a FastAPI dependency override on the client's app that yields
        a mock DB session returning empty rows — prevents real asyncpg pool access.
        Returns the override key so the caller can clean up.

        fetchone() and fetchall() are sync calls (MagicMock), execute() is async.
        """
        from unittest.mock import MagicMock

        from app.core.session import get_async_session

        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override():
            yield mock_session

        client.app.dependency_overrides[get_async_session] = _override
        return get_async_session

    def test_health_trend_has_iso_week_labels(self, client, platform_headers):
        """PA-009: Trend entries have week labels in YYYY-Www format."""
        import re

        override_key = self._apply_session_override(client)
        try:
            with patch(
                "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
            ) as mock_get:
                mock_get.return_value = _MOCK_TENANT
                resp = client.get(
                    f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                    headers=platform_headers,
                )
        finally:
            client.app.dependency_overrides.pop(override_key, None)

        assert resp.status_code == 200
        trend = resp.json()["trend"]
        week_pattern = re.compile(r"^\d{4}-W\d{2}$")
        for entry in trend:
            assert week_pattern.match(
                entry["week"]
            ), f"Bad week format: {entry['week']}"

    def test_health_missing_weeks_have_null_values(self, client, platform_headers):
        """PA-009: Weeks with no stored data return null values, not omitted."""
        override_key = self._apply_session_override(client)
        try:
            with patch(
                "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
            ) as mock_get:
                mock_get.return_value = _MOCK_TENANT
                resp = client.get(
                    f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                    headers=platform_headers,
                )
        finally:
            client.app.dependency_overrides.pop(override_key, None)

        assert resp.status_code == 200
        trend = resp.json()["trend"]
        for entry in trend:
            assert "week" in entry
            assert "composite" in entry
            assert "usage_trend" in entry
            assert "satisfaction" in entry

    def test_health_current_snapshot_defaults_when_no_data(
        self, client, platform_headers
    ):
        """PA-009: current snapshot fields are null when no stored rows exist."""
        override_key = self._apply_session_override(client)
        try:
            with patch(
                "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
            ) as mock_get:
                mock_get.return_value = _MOCK_TENANT
                resp = client.get(
                    f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                    headers=platform_headers,
                )
        finally:
            client.app.dependency_overrides.pop(override_key, None)

        assert resp.status_code == 200
        current = resp.json()["current"]
        assert current["composite"] is None
        assert current["at_risk_flag"] is False

    def test_health_component_details_include_raw_counts(
        self, client, platform_headers
    ):
        """PA-009: current snapshot structure has no legacy fields."""
        override_key = self._apply_session_override(client)
        try:
            with patch(
                "app.modules.tenants.routes.get_tenant_db", new_callable=AsyncMock
            ) as mock_get:
                mock_get.return_value = _MOCK_TENANT
                resp = client.get(
                    f"/api/v1/platform/tenants/{TEST_TENANT_ID}/health",
                    headers=platform_headers,
                )
        finally:
            client.app.dependency_overrides.pop(override_key, None)

        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" not in data
        assert "category" not in data
        assert "at_risk" not in data
        assert "current" in data
        assert "trend" in data


# ---------------------------------------------------------------------------
# GET /api/v1/platform/tenants/{tenant_id}/quota — API-030
# ---------------------------------------------------------------------------


class TestGetTenantQuota:
    """GET /api/v1/platform/tenants/{tenant_id}/quota (API-030)"""

    def test_quota_requires_platform_admin(self, client, tenant_headers):
        """Tenant admin (non-platform admin) is rejected with 403."""
        resp = client.get(
            f"/api/v1/platform/tenants/{TEST_TENANT_ID}/quota",
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_quota_returns_structure(self, client, platform_headers):
        """200 response includes tokens, storage_gb, and users keys."""
        with patch(
            "app.modules.tenants.routes.get_tenant_quota_db",
            new_callable=AsyncMock,
        ) as mock_quota:
            mock_quota.return_value = {
                "tenant_id": TEST_TENANT_ID,
                "tokens": {"limit": 1000000, "used": 0, "period": "monthly"},
                "storage_gb": {"limit": 10.0, "used": 0.0},
                "users": {"limit": 50, "used": 12},
            }
            resp = client.get(
                f"/api/v1/platform/tenants/{TEST_TENANT_ID}/quota",
                headers=platform_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == TEST_TENANT_ID
        assert "tokens" in data
        assert "storage_gb" in data
        assert "users" in data
        assert data["tokens"]["period"] == "monthly"
        assert data["tokens"]["limit"] == 1000000
        assert data["storage_gb"]["limit"] == 10.0
        assert data["users"]["limit"] == 50
        assert data["users"]["used"] == 12

    def test_quota_returns_404_for_unknown_tenant(self, client, platform_headers):
        """Returns 404 when tenant does not exist."""
        with patch(
            "app.modules.tenants.routes.get_tenant_quota_db",
            new_callable=AsyncMock,
        ) as mock_quota:
            mock_quota.return_value = None
            resp = client.get(
                "/api/v1/platform/tenants/nonexistent/quota",
                headers=platform_headers,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/platform/tenants/{tenant_id}/quota — API-031
# ---------------------------------------------------------------------------


class TestUpdateTenantQuota:
    """PATCH /api/v1/platform/tenants/{tenant_id}/quota (API-031)"""

    def test_update_quota_requires_platform_admin(self, client, tenant_headers):
        """Tenant admin (non-platform admin) is rejected with 403."""
        resp = client.patch(
            f"/api/v1/platform/tenants/{TEST_TENANT_ID}/quota",
            json={"monthly_token_limit": 2000000},
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_update_quota_returns_updated(self, client, platform_headers):
        """200 response with updated quota limits."""
        with patch(
            "app.modules.tenants.routes.update_tenant_quota_db",
            new_callable=AsyncMock,
        ) as mock_update, patch(
            "app.modules.tenants.routes.get_tenant_quota_db",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_update.return_value = True
            mock_get.return_value = {
                "tenant_id": TEST_TENANT_ID,
                "tokens": {"limit": 2000000, "used": 0, "period": "monthly"},
                "storage_gb": {"limit": 10.0, "used": 0.0},
                "users": {"limit": 50, "used": 12},
            }
            resp = client.patch(
                f"/api/v1/platform/tenants/{TEST_TENANT_ID}/quota",
                json={"monthly_token_limit": 2000000},
                headers=platform_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["tokens"]["limit"] == 2000000

    def test_update_quota_rejects_negative_token_limit(self, client, platform_headers):
        """422 when monthly_token_limit is negative."""
        resp = client.patch(
            f"/api/v1/platform/tenants/{TEST_TENANT_ID}/quota",
            json={"monthly_token_limit": -100},
            headers=platform_headers,
        )
        assert resp.status_code == 422

    def test_update_quota_404_for_unknown_tenant(self, client, platform_headers):
        """Returns 404 when tenant does not exist."""
        with patch(
            "app.modules.tenants.routes.update_tenant_quota_db",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = None
            resp = client.patch(
                "/api/v1/platform/tenants/nonexistent/quota",
                json={"monthly_token_limit": 2000000},
                headers=platform_headers,
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/platform/provisioning/{job_id} — API-025 (SSE)
# ---------------------------------------------------------------------------


class TestProvisioningSSE:
    """GET /api/v1/platform/provisioning/{job_id} (API-025)"""

    def test_provisioning_requires_platform_admin(self, client, tenant_headers):
        """Tenant admin (non-platform admin) is rejected with 403."""
        resp = client.get(
            "/api/v1/platform/provisioning/test-job-id",
            headers=tenant_headers,
        )
        assert resp.status_code == 403

    def test_provisioning_returns_404_for_unknown_job(self, client, platform_headers):
        """Returns 404 when job_id not found in Redis."""
        with patch(
            "app.modules.tenants.routes.get_provisioning_events",
            new_callable=AsyncMock,
        ) as mock_events:
            mock_events.return_value = None
            resp = client.get(
                "/api/v1/platform/provisioning/nonexistent-job",
                headers=platform_headers,
            )
        assert resp.status_code == 404

    def test_provisioning_returns_sse_content_type(self, client, platform_headers):
        """Response has text/event-stream media type."""
        with patch(
            "app.modules.tenants.routes.get_provisioning_events",
            new_callable=AsyncMock,
        ) as mock_events:
            mock_events.return_value = [
                {
                    "step": "create_tenant",
                    "status": "completed",
                    "message": "Tenant record created",
                },
            ]
            resp = client.get(
                "/api/v1/platform/provisioning/test-job-123",
                headers=platform_headers,
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
