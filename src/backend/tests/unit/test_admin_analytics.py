"""
Unit tests for analytics API endpoints (FE-037).

Tests auth, RBAC, and response structure for:
- GET /api/v1/admin/analytics/satisfaction
- GET /api/v1/admin/analytics/low-confidence

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
# Sample mock data
# ---------------------------------------------------------------------------

SAMPLE_TREND = [
    {"date": "2026-03-01", "satisfaction_pct": 85.0, "total": 10},
    {"date": "2026-03-02", "satisfaction_pct": 90.0, "total": 12},
    {"date": "2026-03-03", "satisfaction_pct": 80.0, "total": 5},
]

SAMPLE_LOW_CONFIDENCE = [
    {
        "message_id": "msg-001",
        "query_text": "How do I reset my password?",
        "created_at": "2026-03-07T10:30:00",
        "retrieval_confidence": 0.35,
    },
    {
        "message_id": "msg-002",
        "query_text": "What is the refund policy for enterprise plans?",
        "created_at": "2026-03-07T11:00:00",
        "retrieval_confidence": 0.50,
    },
]


# ---------------------------------------------------------------------------
# GET /api/v1/admin/analytics/satisfaction
# ---------------------------------------------------------------------------


class TestSatisfactionAuth:
    """GET /admin/analytics/satisfaction - auth and RBAC."""

    def test_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.get("/api/v1/admin/analytics/satisfaction")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        """403 when end_user tries to access."""
        resp = client.get("/api/v1/admin/analytics/satisfaction", headers=user_headers)
        assert resp.status_code == 403


class TestSatisfactionResponse:
    """GET /admin/analytics/satisfaction - response structure."""

    def test_returns_trend_list(self, client, admin_headers):
        """Returns 'trend' as a list of date/satisfaction/total items."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_trend, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_trend.return_value = SAMPLE_TREND
            mock_7d.return_value = 85.0
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "trend" in data
        assert isinstance(data["trend"], list)
        assert len(data["trend"]) == 3
        # Verify each trend item has expected fields
        for item in data["trend"]:
            assert "date" in item
            assert "satisfaction_pct" in item
            assert "total" in item

    def test_satisfaction_7d_is_float(self, client, admin_headers):
        """satisfaction_7d is a float between 0 and 100."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_trend, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_trend.return_value = SAMPLE_TREND
            mock_7d.return_value = 85.0
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "satisfaction_7d" in data
        s7d = data["satisfaction_7d"]
        assert isinstance(s7d, (int, float))
        assert 0 <= s7d <= 100

    def test_empty_trend_returns_empty_list(self, client, admin_headers):
        """When no feedback data exists, trend is empty list."""
        with patch(
            "app.modules.admin.analytics.get_satisfaction_trend_db",
            new_callable=AsyncMock,
        ) as mock_trend, patch(
            "app.modules.admin.analytics.get_satisfaction_7d_db",
            new_callable=AsyncMock,
        ) as mock_7d:
            mock_trend.return_value = []
            mock_7d.return_value = 0.0
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["trend"] == []
        assert data["satisfaction_7d"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/v1/admin/analytics/low-confidence
# ---------------------------------------------------------------------------


class TestLowConfidenceAuth:
    """GET /admin/analytics/low-confidence - auth and RBAC."""

    def test_requires_auth(self, client):
        """401 when no Authorization header."""
        resp = client.get("/api/v1/admin/analytics/low-confidence")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        """403 when end_user tries to access."""
        resp = client.get(
            "/api/v1/admin/analytics/low-confidence", headers=user_headers
        )
        assert resp.status_code == 403


class TestLowConfidenceResponse:
    """GET /admin/analytics/low-confidence - response structure."""

    def test_returns_items_list(self, client, admin_headers):
        """Returns 'items' as a list of low-confidence entries."""
        with patch(
            "app.modules.admin.analytics.get_low_confidence_messages_db",
            new_callable=AsyncMock,
        ) as mock_lc:
            mock_lc.return_value = SAMPLE_LOW_CONFIDENCE
            resp = client.get(
                "/api/v1/admin/analytics/low-confidence", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) == 2
        for item in data["items"]:
            assert "message_id" in item
            assert "query_text" in item
            assert "created_at" in item
            assert "retrieval_confidence" in item

    def test_limit_param_default_is_20(self, client, admin_headers):
        """Default limit is 20 when not specified."""
        with patch(
            "app.modules.admin.analytics.get_low_confidence_messages_db",
            new_callable=AsyncMock,
        ) as mock_lc:
            mock_lc.return_value = []
            resp = client.get(
                "/api/v1/admin/analytics/low-confidence", headers=admin_headers
            )
        assert resp.status_code == 200
        # Verify the mock was called with limit=20
        call_kwargs = mock_lc.call_args.kwargs
        assert call_kwargs.get("limit") == 20

    def test_limit_param_max_50(self, client, admin_headers):
        """Limit above 50 returns 422 validation error."""
        resp = client.get(
            "/api/v1/admin/analytics/low-confidence?limit=100",
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_limit_param_accepted(self, client, admin_headers):
        """Custom limit within bounds is accepted."""
        with patch(
            "app.modules.admin.analytics.get_low_confidence_messages_db",
            new_callable=AsyncMock,
        ) as mock_lc:
            mock_lc.return_value = []
            resp = client.get(
                "/api/v1/admin/analytics/low-confidence?limit=10",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        call_kwargs = mock_lc.call_args.kwargs
        assert call_kwargs.get("limit") == 10

    def test_empty_returns_empty_items(self, client, admin_headers):
        """When no low-confidence messages exist, returns empty items list."""
        with patch(
            "app.modules.admin.analytics.get_low_confidence_messages_db",
            new_callable=AsyncMock,
        ) as mock_lc:
            mock_lc.return_value = []
            resp = client.get(
                "/api/v1/admin/analytics/low-confidence", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
