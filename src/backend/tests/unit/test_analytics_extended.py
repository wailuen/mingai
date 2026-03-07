"""
Unit tests for extended analytics API endpoints (API-074, API-075).

Tests auth, RBAC, and response structure for:
- GET /api/v1/admin/analytics/satisfaction  (extended with period, per_agent, trend)
- GET /api/v1/admin/analytics/engagement

Tier 1: Fast, isolated, uses mocking for DB layer.
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


# ---------------------------------------------------------------------------
# Satisfaction analytics extended (API-074)
# ---------------------------------------------------------------------------


class TestSatisfactionPeriodFilter:
    """Test period parameter support on GET /admin/analytics/satisfaction."""

    def test_satisfaction_default_period_is_30d(self, client, admin_headers):
        """Default period is 30d when not specified."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_overall_db",
            new_callable=AsyncMock,
        ) as mock_overall, patch(
            "app.modules.admin.analytics.get_satisfaction_per_agent_db",
            new_callable=AsyncMock,
        ) as mock_per_agent, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_period_db",
            new_callable=AsyncMock,
        ) as mock_trend, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_trend30d, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_overall.return_value = (85.0, 60)
            mock_per_agent.return_value = []
            mock_trend.return_value = []
            mock_trend30d.return_value = []
            mock_7d.return_value = 85.0

            resp = client.get(
                "/api/v1/admin/analytics/satisfaction", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "30d"

    def test_satisfaction_7d_period(self, client, admin_headers):
        """period=7d is respected and returned in response."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_overall_db",
            new_callable=AsyncMock,
        ) as mock_overall, patch(
            "app.modules.admin.analytics.get_satisfaction_per_agent_db",
            new_callable=AsyncMock,
        ) as mock_per_agent, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_period_db",
            new_callable=AsyncMock,
        ) as mock_trend, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_trend30d, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_overall.return_value = (80.0, 30)
            mock_per_agent.return_value = []
            mock_trend.return_value = []
            mock_trend30d.return_value = []
            mock_7d.return_value = 80.0

            resp = client.get(
                "/api/v1/admin/analytics/satisfaction?period=7d", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "7d"

    def test_satisfaction_returns_full_spec_fields(self, client, admin_headers):
        """Response includes all spec fields: overall_rate, total_ratings, period, per_agent, trend, not_enough_data."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_overall_db",
            new_callable=AsyncMock,
        ) as mock_overall, patch(
            "app.modules.admin.analytics.get_satisfaction_per_agent_db",
            new_callable=AsyncMock,
        ) as mock_per_agent, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_period_db",
            new_callable=AsyncMock,
        ) as mock_trend, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_trend30d, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_overall.return_value = (87.5, 120)
            mock_per_agent.return_value = [
                {
                    "agent_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "name": "HR Agent",
                    "satisfaction_rate": 90.0,
                    "ratings_count": 80,
                }
            ]
            mock_trend.return_value = [
                {"date": "2026-03-01", "rate": 85.0},
                {"date": "2026-03-02", "rate": 90.0},
            ]
            mock_trend30d.return_value = []
            mock_7d.return_value = 88.0

            resp = client.get(
                "/api/v1/admin/analytics/satisfaction", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_rate" in data
        assert "total_ratings" in data
        assert "period" in data
        assert "per_agent" in data
        assert "daily_trend" in data
        assert "not_enough_data" in data
        assert isinstance(data["per_agent"], list)
        assert isinstance(data["daily_trend"], list)
        assert isinstance(data["not_enough_data"], bool)


class TestSatisfactionNotEnoughData:
    """Test not_enough_data flag (< 50 ratings)."""

    def test_not_enough_data_when_less_than_50_ratings(self, client, admin_headers):
        """not_enough_data is True when total_ratings < 50."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_overall_db",
            new_callable=AsyncMock,
        ) as mock_overall, patch(
            "app.modules.admin.analytics.get_satisfaction_per_agent_db",
            new_callable=AsyncMock,
        ) as mock_pa, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_period_db",
            new_callable=AsyncMock,
        ) as mock_t, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_t30, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_overall.return_value = (60.0, 10)
            mock_pa.return_value = []
            mock_t.return_value = []
            mock_t30.return_value = []
            mock_7d.return_value = 60.0

            resp = client.get(
                "/api/v1/admin/analytics/satisfaction", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["not_enough_data"] is True
        assert data["total_ratings"] == 10

    def test_not_enough_data_false_when_50_or_more_ratings(self, client, admin_headers):
        """not_enough_data is False when total_ratings >= 50."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_overall_db",
            new_callable=AsyncMock,
        ) as mock_overall, patch(
            "app.modules.admin.analytics.get_satisfaction_per_agent_db",
            new_callable=AsyncMock,
        ) as mock_pa, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_period_db",
            new_callable=AsyncMock,
        ) as mock_t, patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_t30, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_overall.return_value = (85.0, 50)
            mock_pa.return_value = []
            mock_t.return_value = []
            mock_t30.return_value = []
            mock_7d.return_value = 85.0

            resp = client.get(
                "/api/v1/admin/analytics/satisfaction", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["not_enough_data"] is False


# ---------------------------------------------------------------------------
# Engagement analytics (API-075)
# ---------------------------------------------------------------------------


class TestEngagementAuth:
    """GET /admin/analytics/engagement - auth and RBAC."""

    def test_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.get("/api/v1/admin/analytics/engagement")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        """403 when end_user tries to access."""
        resp = client.get("/api/v1/admin/analytics/engagement", headers=user_headers)
        assert resp.status_code == 403


class TestEngagementResponse:
    """GET /admin/analytics/engagement - response structure."""

    def test_engagement_returns_structure(self, client, admin_headers):
        """Returns all required fields: dau, wau, mau, period, per_agent, inactive_users, feature_adoption."""
        mock_data = {
            "dau": 42,
            "wau": 150,
            "mau": 300,
            "inactive_users": {"count": 50, "pct": 14.3},
            "feature_adoption": {
                "memory_notes": 0.25,
                "glossary_queries": 0.12,
                "feedback": 0.38,
            },
            "per_agent": [
                {
                    "agent_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "name": "HR Agent",
                    "dau": 20,
                    "wau": 75,
                }
            ],
        }
        with patch(
            "app.modules.admin.analytics.get_engagement_db",
            new_callable=AsyncMock,
        ) as mock_engagement:
            mock_engagement.return_value = mock_data

            resp = client.get(
                "/api/v1/admin/analytics/engagement", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "dau" in data
        assert "wau" in data
        assert "mau" in data
        assert "period" in data
        assert "per_agent" in data
        assert "inactive_users" in data
        assert "feature_adoption" in data

        assert isinstance(data["dau"], int)
        assert isinstance(data["wau"], int)
        assert isinstance(data["mau"], int)
        assert isinstance(data["per_agent"], list)

        inactive = data["inactive_users"]
        assert "count" in inactive
        assert "pct" in inactive

        adoption = data["feature_adoption"]
        assert "memory_notes" in adoption
        assert "glossary_queries" in adoption
        assert "feedback" in adoption

    def test_engagement_default_period_is_30d(self, client, admin_headers):
        """Default period is 30d when not specified."""
        mock_data = {
            "dau": 0,
            "wau": 0,
            "mau": 0,
            "inactive_users": {"count": 0, "pct": 0.0},
            "feature_adoption": {
                "memory_notes": 0.0,
                "glossary_queries": 0.0,
                "feedback": 0.0,
            },
            "per_agent": [],
        }
        with patch(
            "app.modules.admin.analytics.get_engagement_db",
            new_callable=AsyncMock,
        ) as mock_engagement:
            mock_engagement.return_value = mock_data

            resp = client.get(
                "/api/v1/admin/analytics/engagement", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "30d"

    def test_engagement_accepts_period_90d(self, client, admin_headers):
        """period=90d is accepted and reflected in response."""
        mock_data = {
            "dau": 5,
            "wau": 20,
            "mau": 60,
            "inactive_users": {"count": 10, "pct": 5.0},
            "feature_adoption": {
                "memory_notes": 0.1,
                "glossary_queries": 0.05,
                "feedback": 0.2,
            },
            "per_agent": [],
        }
        with patch(
            "app.modules.admin.analytics.get_engagement_db",
            new_callable=AsyncMock,
        ) as mock_engagement:
            mock_engagement.return_value = mock_data

            resp = client.get(
                "/api/v1/admin/analytics/engagement?period=90d", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "90d"
