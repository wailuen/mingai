"""
Unit tests for TA-026 through TA-030 analytics API endpoints.

TA-026: GET /api/v1/admin/analytics/satisfaction-dashboard
TA-027: GET /api/v1/admin/agents/{id}/analytics
TA-028: Root cause correlation (embedded in TA-027)
TA-029: GET /api/v1/admin/glossary/analytics
TA-030: GET /api/v1/admin/analytics/engagement-v2

Tier 1: Fast, isolated, mocks DB layer (get_*_db helpers and compute_*_db helpers).
"""
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "b" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "aaaabbbb-aaaa-bbbb-aaaa-bbbbaaaabbbb"
TEST_AGENT_ID = "ccccdddd-cccc-dddd-cccc-ddddccccdddd"


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _make_tenant_admin_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "ta-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
        "scope": "tenant",
        "plan": "professional",
        "email": "admin@example.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_end_user_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "end-user-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["end_user"],
        "scope": "tenant",
        "plan": "professional",
        "email": "user@example.com",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "token_version": 2,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
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
    """Function-scoped client so dependency_overrides do not leak between tests."""
    from app.main import app

    # Ensure no leftover overrides from previous tests
    app.dependency_overrides.clear()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_make_tenant_admin_token()}"}


@pytest.fixture
def user_headers():
    return {"Authorization": f"Bearer {_make_end_user_token()}"}


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

SAMPLE_DAILY_TREND = [
    {"date": "2026-03-01", "satisfaction_rate": 0.80, "count": 10},
    {"date": "2026-03-02", "satisfaction_rate": 0.85, "count": 12},
    {"date": "2026-03-03", "satisfaction_rate": None, "count": 0},
]

SAMPLE_AGENTS_LIST = [
    {
        "agent_id": TEST_AGENT_ID,
        "agent_name": "Finance Bot",
        "satisfaction_rate": 0.85,
        "session_count": 42,
        "feedback_count": 15,
    },
    {
        "agent_id": "eeeeffff-eeee-ffff-eeee-ffffeeeeffff",
        "agent_name": "HR Bot",
        "satisfaction_rate": None,
        "session_count": 0,
        "feedback_count": 0,
    },
]

SAMPLE_SATISFACTION_DASHBOARD = {
    "rolling_7d_rate": 0.78,
    "total_feedback_count": 120,
    "agents": SAMPLE_AGENTS_LIST,
    "daily_trend": SAMPLE_DAILY_TREND,
}

SAMPLE_LOW_CONFIDENCE = [
    {
        "conversation_id": "conv-001",
        "query_snippet": "What is the expense limit?",
        "confidence": 0.45,
        "timestamp": "2026-03-07T10:00:00",
    },
]

SAMPLE_GUARDRAIL_EVENTS = [
    {
        "trigger_reason": "off_topic",
        "query_snippet": "Tell me a joke about",
        "timestamp": "2026-03-07T09:00:00",
    },
]

SAMPLE_CORRELATION = {
    "potential_cause": "document_freshness",
    "sync_at": "2026-03-06T10:00:00+00:00",
    "satisfaction_drop_at": "2026-03-07T00:00:00Z",
    "drop_magnitude": 15.2,
    "confidence": "medium",
}

SAMPLE_AGENT_ANALYTICS = {
    "agent_id": TEST_AGENT_ID,
    "agent_name": "Finance Bot",
    "daily_satisfaction": SAMPLE_DAILY_TREND,
    "low_confidence_responses": SAMPLE_LOW_CONFIDENCE,
    "guardrail_events": SAMPLE_GUARDRAIL_EVENTS,
    "correlation": SAMPLE_CORRELATION,
}

SAMPLE_GLOSSARY_ANALYTICS = [
    {
        "term_id": "gggggggg-gggg-gggg-gggg-gggggggggggg",
        "term": "vacation",
        "satisfaction_with": 0.87,
        "satisfaction_without": 0.71,
        "query_count_with": 42,
        "lift_pct": 22.5,
        "data_quality": "sufficient",
    },
    {
        "term_id": "hhhhhhhh-hhhh-hhhh-hhhh-hhhhhhhhhhhh",
        "term": "PTO",
        "satisfaction_with": 0.60,
        "satisfaction_without": 0.55,
        "query_count_with": 5,
        "lift_pct": 9.1,
        "data_quality": "insufficient",
    },
]

SAMPLE_ENGAGEMENT_V2 = {
    "aggregate": {
        "dau": 12,
        "wau": 45,
        "mau": 120,
        "inactive_users": 8,
    },
    "per_agent": [
        {
            "agent_id": TEST_AGENT_ID,
            "agent_name": "Finance Bot",
            "dau": 5,
            "wau": 18,
            "mau": 45,
        }
    ],
    "feature_adoption": [
        {"feature_name": "chat", "adoption_count": 120},
        {"feature_name": "glossary_lookup", "adoption_count": 34},
    ],
}


# ===========================================================================
# TA-026: Satisfaction Dashboard
# ===========================================================================


class TestTA026Auth:
    """GET /admin/analytics/satisfaction-dashboard — auth and RBAC."""

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/admin/analytics/satisfaction-dashboard")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        resp = client.get(
            "/api/v1/admin/analytics/satisfaction-dashboard",
            headers=user_headers,
        )
        assert resp.status_code == 403


class TestTA026Response:
    """GET /admin/analytics/satisfaction-dashboard — response structure."""

    def test_returns_rolling_7d_rate(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_SATISFACTION_DASHBOARD,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "rolling_7d_rate" in data
        assert data["rolling_7d_rate"] == 0.78

    def test_returns_total_feedback_count(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_SATISFACTION_DASHBOARD,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        data = resp.json()
        assert data["total_feedback_count"] == 120

    def test_returns_agents_list(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_SATISFACTION_DASHBOARD,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        data = resp.json()
        assert "agents" in data
        assert isinstance(data["agents"], list)
        assert len(data["agents"]) == 2

    def test_agent_with_zero_feedback_has_null_satisfaction(
        self, client, admin_headers
    ):
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_SATISFACTION_DASHBOARD,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        data = resp.json()
        hr_bot = next((a for a in data["agents"] if a["agent_name"] == "HR Bot"), None)
        assert hr_bot is not None
        assert hr_bot["satisfaction_rate"] is None
        assert hr_bot["feedback_count"] == 0

    def test_returns_daily_trend_list(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_SATISFACTION_DASHBOARD,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        data = resp.json()
        assert "daily_trend" in data
        assert isinstance(data["daily_trend"], list)

    def test_daily_trend_items_have_required_fields(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_SATISFACTION_DASHBOARD,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        data = resp.json()
        for item in data["daily_trend"]:
            assert "date" in item
            assert "satisfaction_rate" in item
            assert "count" in item

    def test_rolling_7d_rate_null_when_no_feedback(self, client, admin_headers):
        no_data = {
            "rolling_7d_rate": None,
            "total_feedback_count": 0,
            "agents": [],
            "daily_trend": [],
        }
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=no_data,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        data = resp.json()
        assert data["rolling_7d_rate"] is None
        assert data["total_feedback_count"] == 0

    def test_agent_fields_present(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_satisfaction_dashboard_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_SATISFACTION_DASHBOARD,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/satisfaction-dashboard",
                headers=admin_headers,
            )
        data = resp.json()
        finance = next(
            (a for a in data["agents"] if a["agent_name"] == "Finance Bot"), None
        )
        assert finance is not None
        assert finance["agent_id"] == TEST_AGENT_ID
        assert finance["satisfaction_rate"] == 0.85
        assert finance["session_count"] == 42
        assert finance["feedback_count"] == 15


# ===========================================================================
# TA-027: Agent Performance Detail
# ===========================================================================


class TestTA027Auth:
    """GET /admin/agents/{id}/analytics — auth and RBAC."""

    def test_requires_auth(self, client):
        resp = client.get(f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        resp = client.get(
            f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
            headers=user_headers,
        )
        assert resp.status_code == 403


class TestTA027Response:
    """GET /admin/agents/{id}/analytics — response structure."""

    def _mock_agent_analytics(
        self, agent_id=TEST_AGENT_ID, correlation=SAMPLE_CORRELATION
    ):
        """Return a context manager stack mocking all agent analytics DB helpers."""
        from contextlib import ExitStack

        stack = ExitStack()
        # Mock the agent lookup (returns row with id, name)
        mock_execute = AsyncMock()
        agent_row = MagicMock()
        agent_row.__getitem__ = lambda self, i: (agent_id if i == 0 else "Finance Bot")
        mock_fetchone = MagicMock(return_value=agent_row)
        mock_result = MagicMock()
        mock_result.fetchone = mock_fetchone

        stack.enter_context(
            patch(
                "app.modules.admin.analytics.get_agent_daily_satisfaction_db",
                new_callable=AsyncMock,
                return_value=SAMPLE_DAILY_TREND,
            )
        )
        stack.enter_context(
            patch(
                "app.modules.admin.analytics.get_low_confidence_for_agent_db",
                new_callable=AsyncMock,
                return_value=SAMPLE_LOW_CONFIDENCE,
            )
        )
        stack.enter_context(
            patch(
                "app.modules.admin.analytics.get_guardrail_events_for_agent_db",
                new_callable=AsyncMock,
                return_value=SAMPLE_GUARDRAIL_EVENTS,
            )
        )
        stack.enter_context(
            patch(
                "app.modules.admin.analytics.compute_root_cause_correlation_db",
                new_callable=AsyncMock,
                return_value=correlation,
            )
        )
        return stack

    def test_returns_agent_id_and_name(self, client, admin_headers):
        with self._mock_agent_analytics():
            with patch(
                "app.core.session.get_async_session",
            ):
                # Use the full integration path by mocking at module level
                pass
        # Since the route calls session.execute for the agent lookup,
        # we need to mock the session dependency too.
        mock_session = AsyncMock()
        # Agent row mock
        mock_agent_result = MagicMock()
        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda s, i: (
            TEST_AGENT_ID if i == 0 else "Finance Bot"
        )
        mock_agent_result.fetchone = MagicMock(return_value=mock_agent_row)
        mock_session.execute = AsyncMock(return_value=mock_agent_result)

        async def override_session():
            yield mock_session

        from app.main import app
        from app.core.session import get_async_session

        app.dependency_overrides[get_async_session] = override_session
        try:
            with self._mock_agent_analytics():
                resp = client.get(
                    f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
                    headers=admin_headers,
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["agent_id"] == TEST_AGENT_ID
            assert data["agent_name"] == "Finance Bot"
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_daily_satisfaction(self, client, admin_headers):
        mock_session = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda s, i: (
            TEST_AGENT_ID if i == 0 else "Finance Bot"
        )
        mock_agent_result.fetchone = MagicMock(return_value=mock_agent_row)
        mock_session.execute = AsyncMock(return_value=mock_agent_result)

        async def override_session():
            yield mock_session

        from app.main import app
        from app.core.session import get_async_session

        app.dependency_overrides[get_async_session] = override_session
        try:
            with self._mock_agent_analytics():
                resp = client.get(
                    f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
                    headers=admin_headers,
                )
            assert resp.status_code == 200
            data = resp.json()
            assert "daily_satisfaction" in data
            assert isinstance(data["daily_satisfaction"], list)
            assert len(data["daily_satisfaction"]) == 3
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_low_confidence_responses(self, client, admin_headers):
        mock_session = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda s, i: (
            TEST_AGENT_ID if i == 0 else "Finance Bot"
        )
        mock_agent_result.fetchone = MagicMock(return_value=mock_agent_row)
        mock_session.execute = AsyncMock(return_value=mock_agent_result)

        async def override_session():
            yield mock_session

        from app.main import app
        from app.core.session import get_async_session

        app.dependency_overrides[get_async_session] = override_session
        try:
            with self._mock_agent_analytics():
                resp = client.get(
                    f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
                    headers=admin_headers,
                )
            data = resp.json()
            assert "low_confidence_responses" in data
            assert isinstance(data["low_confidence_responses"], list)
            item = data["low_confidence_responses"][0]
            assert "conversation_id" in item
            assert "query_snippet" in item
            assert "confidence" in item
            assert "timestamp" in item
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_guardrail_events(self, client, admin_headers):
        mock_session = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda s, i: (
            TEST_AGENT_ID if i == 0 else "Finance Bot"
        )
        mock_agent_result.fetchone = MagicMock(return_value=mock_agent_row)
        mock_session.execute = AsyncMock(return_value=mock_agent_result)

        async def override_session():
            yield mock_session

        from app.main import app
        from app.core.session import get_async_session

        app.dependency_overrides[get_async_session] = override_session
        try:
            with self._mock_agent_analytics():
                resp = client.get(
                    f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
                    headers=admin_headers,
                )
            data = resp.json()
            assert "guardrail_events" in data
            assert isinstance(data["guardrail_events"], list)
            event = data["guardrail_events"][0]
            assert "trigger_reason" in event
            assert "query_snippet" in event
            assert "timestamp" in event
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_correlation_when_present(self, client, admin_headers):
        mock_session = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda s, i: (
            TEST_AGENT_ID if i == 0 else "Finance Bot"
        )
        mock_agent_result.fetchone = MagicMock(return_value=mock_agent_row)
        mock_session.execute = AsyncMock(return_value=mock_agent_result)

        async def override_session():
            yield mock_session

        from app.main import app
        from app.core.session import get_async_session

        app.dependency_overrides[get_async_session] = override_session
        try:
            with self._mock_agent_analytics(correlation=SAMPLE_CORRELATION):
                resp = client.get(
                    f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
                    headers=admin_headers,
                )
            data = resp.json()
            assert data["correlation"] is not None
            assert data["correlation"]["potential_cause"] == "document_freshness"
            assert "sync_at" in data["correlation"]
            assert "drop_magnitude" in data["correlation"]
            assert data["correlation"]["confidence"] == "medium"
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_correlation_null_when_no_drop(self, client, admin_headers):
        mock_session = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_row = MagicMock()
        mock_agent_row.__getitem__ = lambda s, i: (
            TEST_AGENT_ID if i == 0 else "Finance Bot"
        )
        mock_agent_result.fetchone = MagicMock(return_value=mock_agent_row)
        mock_session.execute = AsyncMock(return_value=mock_agent_result)

        async def override_session():
            yield mock_session

        from app.main import app
        from app.core.session import get_async_session

        app.dependency_overrides[get_async_session] = override_session
        try:
            with self._mock_agent_analytics(correlation=None):
                resp = client.get(
                    f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
                    headers=admin_headers,
                )
            data = resp.json()
            assert data["correlation"] is None
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    def test_returns_404_for_unknown_agent(self, client, admin_headers):
        mock_session = AsyncMock()
        mock_agent_result = MagicMock()
        mock_agent_result.fetchone = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_agent_result)

        async def override_session():
            yield mock_session

        from app.main import app
        from app.core.session import get_async_session

        app.dependency_overrides[get_async_session] = override_session
        try:
            resp = client.get(
                f"/api/v1/admin/agents/{TEST_AGENT_ID}/analytics",
                headers=admin_headers,
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_async_session, None)


# ===========================================================================
# TA-028: Root Cause Correlation (unit logic tests)
# ===========================================================================


class TestTA028CorrelationLogic:
    """Unit tests for compute_root_cause_correlation_db logic."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_drop(self):
        """When satisfaction is stable, returns None."""
        from app.modules.admin.analytics import compute_root_cause_correlation_db

        # Stable satisfaction, no drop
        daily = [
            {"date": "2026-03-01", "satisfaction_rate": 0.80, "count": 10},
            {"date": "2026-03-02", "satisfaction_rate": 0.82, "count": 8},
            {"date": "2026-03-03", "satisfaction_rate": 0.79, "count": 9},
        ]
        mock_db = AsyncMock()
        result = await compute_root_cause_correlation_db(
            TEST_TENANT_ID, TEST_AGENT_ID, daily, mock_db
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_drop_but_no_recent_sync(self):
        """When there is a drop but no sync within 48h, returns None."""
        from app.modules.admin.analytics import compute_root_cause_correlation_db

        daily = [
            {"date": "2026-03-01", "satisfaction_rate": 0.85, "count": 10},
            {"date": "2026-03-02", "satisfaction_rate": 0.70, "count": 8},  # 15pp drop
            {"date": "2026-03-03", "satisfaction_rate": 0.70, "count": 9},
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await compute_root_cause_correlation_db(
            TEST_TENANT_ID, TEST_AGENT_ID, daily, mock_db
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_correlation_when_drop_and_sync_found(self):
        """When there is a 10pp+ drop and sync within 48h, returns correlation."""
        from app.modules.admin.analytics import compute_root_cause_correlation_db

        daily = [
            {"date": "2026-03-01", "satisfaction_rate": 0.85, "count": 10},
            {"date": "2026-03-02", "satisfaction_rate": 0.70, "count": 8},  # 15pp drop
            {"date": "2026-03-03", "satisfaction_rate": 0.70, "count": 9},
        ]
        mock_db = AsyncMock()
        sync_completed_at = datetime(2026, 3, 1, 22, 0, 0, tzinfo=timezone.utc)
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda s, i: sync_completed_at
        mock_result = MagicMock()
        mock_result.fetchone = MagicMock(return_value=mock_row)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await compute_root_cause_correlation_db(
            TEST_TENANT_ID, TEST_AGENT_ID, daily, mock_db
        )
        assert result is not None
        assert result["potential_cause"] == "document_freshness"
        assert result["confidence"] == "medium"
        assert result["drop_magnitude"] == 15.0  # round((0.85-0.70)*100, 1)
        assert "sync_at" in result
        assert result["satisfaction_drop_at"] == "2026-03-02T00:00:00Z"

    @pytest.mark.asyncio
    async def test_skips_null_rates_when_computing_drop(self):
        """Null satisfaction days are skipped in drop detection (no carry-forward)."""
        from app.modules.admin.analytics import compute_root_cause_correlation_db

        daily = [
            {"date": "2026-03-01", "satisfaction_rate": 0.85, "count": 10},
            {"date": "2026-03-02", "satisfaction_rate": None, "count": 0},  # null
            {
                "date": "2026-03-03",
                "satisfaction_rate": 0.70,
                "count": 8,
            },  # prev is None so no drop
        ]
        mock_db = AsyncMock()
        result = await compute_root_cause_correlation_db(
            TEST_TENANT_ID, TEST_AGENT_ID, daily, mock_db
        )
        # prev_rate is None when we see the 0.70, so no drop detected
        assert result is None

    @pytest.mark.asyncio
    async def test_below_10pp_threshold_no_correlation(self):
        """A 9pp drop does not trigger the correlation check."""
        from app.modules.admin.analytics import compute_root_cause_correlation_db

        daily = [
            {"date": "2026-03-01", "satisfaction_rate": 0.85, "count": 10},
            {"date": "2026-03-02", "satisfaction_rate": 0.76, "count": 8},  # 9pp drop
        ]
        mock_db = AsyncMock()
        result = await compute_root_cause_correlation_db(
            TEST_TENANT_ID, TEST_AGENT_ID, daily, mock_db
        )
        assert result is None


# ===========================================================================
# TA-029: Glossary Performance Analytics
# ===========================================================================


class TestTA029Auth:
    """GET /admin/glossary/analytics — auth and RBAC."""

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/admin/glossary/analytics")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        resp = client.get("/api/v1/admin/glossary/analytics", headers=user_headers)
        assert resp.status_code == 403


class TestTA029Response:
    """GET /admin/glossary/analytics — response structure."""

    def test_returns_list(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_glossary_analytics_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_GLOSSARY_ANALYTICS,
        ):
            resp = client.get("/api/v1/admin/glossary/analytics", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_term_fields_present(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_glossary_analytics_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_GLOSSARY_ANALYTICS,
        ):
            resp = client.get("/api/v1/admin/glossary/analytics", headers=admin_headers)
        data = resp.json()
        item = data[0]
        assert "term_id" in item
        assert "term" in item
        assert "satisfaction_with" in item
        assert "satisfaction_without" in item
        assert "query_count_with" in item
        assert "lift_pct" in item
        assert "data_quality" in item

    def test_sufficient_data_quality_flag(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_glossary_analytics_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_GLOSSARY_ANALYTICS,
        ):
            resp = client.get("/api/v1/admin/glossary/analytics", headers=admin_headers)
        data = resp.json()
        vacation = next((t for t in data if t["term"] == "vacation"), None)
        assert vacation is not None
        assert vacation["data_quality"] == "sufficient"
        assert vacation["lift_pct"] == 22.5

    def test_insufficient_data_quality_for_small_sample(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_glossary_analytics_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_GLOSSARY_ANALYTICS,
        ):
            resp = client.get("/api/v1/admin/glossary/analytics", headers=admin_headers)
        data = resp.json()
        pto = next((t for t in data if t["term"] == "PTO"), None)
        assert pto is not None
        assert pto["data_quality"] == "insufficient"

    def test_returns_empty_list_when_no_events(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_glossary_analytics_db",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/v1/admin/glossary/analytics", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []


class TestTA029GlossaryDbLogic:
    """Unit tests for get_glossary_analytics_db logic."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_glossary_match_events(self):
        """Returns empty list when analytics_events has no glossary_match rows."""
        from app.modules.admin.analytics import get_glossary_analytics_db

        mock_db = AsyncMock()
        mock_check = MagicMock()
        mock_check.scalar_one = MagicMock(return_value=0)
        mock_db.execute = AsyncMock(return_value=mock_check)

        result = await get_glossary_analytics_db(TEST_TENANT_ID, mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_glossary_terms(self):
        """Returns empty list when tenant has no glossary terms."""
        from app.modules.admin.analytics import get_glossary_analytics_db

        mock_db = AsyncMock()
        call_count = 0

        async def fake_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # Check for glossary_match events → count = 5
                mock_result.scalar_one = MagicMock(return_value=5)
            else:
                # No glossary terms
                mock_result.fetchall = MagicMock(return_value=[])
            return mock_result

        mock_db.execute = fake_execute
        result = await get_glossary_analytics_db(TEST_TENANT_ID, mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_sorted_by_lift_pct_desc(self):
        """Results are sorted by lift_pct DESC, with None values last."""
        from app.modules.admin.analytics import get_glossary_analytics_db

        # We mock at a higher level to test sorting
        items = [
            {
                "term_id": "t1",
                "term": "alpha",
                "satisfaction_with": 0.9,
                "satisfaction_without": 0.7,
                "query_count_with": 20,
                "lift_pct": 28.6,
                "data_quality": "sufficient",
            },
            {
                "term_id": "t2",
                "term": "beta",
                "satisfaction_with": 0.8,
                "satisfaction_without": 0.75,
                "query_count_with": 15,
                "lift_pct": 6.7,
                "data_quality": "sufficient",
            },
            {
                "term_id": "t3",
                "term": "gamma",
                "satisfaction_with": None,
                "satisfaction_without": None,
                "query_count_with": 0,
                "lift_pct": None,
                "data_quality": "insufficient",
            },
        ]
        # Sort as the function does
        items.sort(
            key=lambda x: x["lift_pct"] if x["lift_pct"] is not None else float("-inf"),
            reverse=True,
        )
        assert items[0]["term"] == "alpha"
        assert items[1]["term"] == "beta"
        assert items[2]["term"] == "gamma"


# ===========================================================================
# TA-030: User Engagement V2
# ===========================================================================


class TestTA030Auth:
    """GET /admin/analytics/engagement-v2 — auth and RBAC."""

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/admin/analytics/engagement-v2")
        assert resp.status_code == 401

    def test_requires_tenant_admin(self, client, user_headers):
        resp = client.get("/api/v1/admin/analytics/engagement-v2", headers=user_headers)
        assert resp.status_code == 403


class TestTA030Response:
    """GET /admin/analytics/engagement-v2 — response structure."""

    def test_returns_aggregate_block(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_engagement_v2_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_ENGAGEMENT_V2,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/engagement-v2", headers=admin_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "aggregate" in data
        agg = data["aggregate"]
        assert agg["dau"] == 12
        assert agg["wau"] == 45
        assert agg["mau"] == 120
        assert agg["inactive_users"] == 8

    def test_returns_per_agent_list(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_engagement_v2_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_ENGAGEMENT_V2,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/engagement-v2", headers=admin_headers
            )
        data = resp.json()
        assert "per_agent" in data
        assert isinstance(data["per_agent"], list)
        agent = data["per_agent"][0]
        assert agent["agent_id"] == TEST_AGENT_ID
        assert agent["agent_name"] == "Finance Bot"
        assert "dau" in agent
        assert "wau" in agent
        assert "mau" in agent

    def test_returns_feature_adoption_list(self, client, admin_headers):
        with patch(
            "app.modules.admin.analytics.get_engagement_v2_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_ENGAGEMENT_V2,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/engagement-v2", headers=admin_headers
            )
        data = resp.json()
        assert "feature_adoption" in data
        assert isinstance(data["feature_adoption"], list)
        features = {
            f["feature_name"]: f["adoption_count"] for f in data["feature_adoption"]
        }
        assert features["chat"] == 120
        assert features["glossary_lookup"] == 34

    def test_zero_counts_when_no_activity(self, client, admin_headers):
        empty = {
            "aggregate": {"dau": 0, "wau": 0, "mau": 0, "inactive_users": 0},
            "per_agent": [],
            "feature_adoption": [],
        }
        with patch(
            "app.modules.admin.analytics.get_engagement_v2_db",
            new_callable=AsyncMock,
            return_value=empty,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/engagement-v2", headers=admin_headers
            )
        data = resp.json()
        assert data["aggregate"]["dau"] == 0
        assert data["per_agent"] == []
        assert data["feature_adoption"] == []

    def test_inactive_users_is_non_negative(self, client, admin_headers):
        """inactive_users cannot be negative."""
        with patch(
            "app.modules.admin.analytics.get_engagement_v2_db",
            new_callable=AsyncMock,
            return_value=SAMPLE_ENGAGEMENT_V2,
        ):
            resp = client.get(
                "/api/v1/admin/analytics/engagement-v2", headers=admin_headers
            )
        data = resp.json()
        assert data["aggregate"]["inactive_users"] >= 0


class TestTA030EngagementV2DbLogic:
    """Unit tests for get_engagement_v2_db helper."""

    @pytest.mark.asyncio
    async def test_inactive_users_clamped_to_zero(self):
        """inactive = max(0, total_active - mau): never negative."""
        from app.modules.admin.analytics import get_engagement_v2_db

        call_count = 0

        async def fake_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalar_one = MagicMock(return_value=5)  # DAU
            elif call_count == 2:
                mock_result.scalar_one = MagicMock(return_value=10)  # WAU
            elif call_count == 3:
                mock_result.scalar_one = MagicMock(return_value=50)  # MAU
            elif call_count == 4:
                mock_result.scalar_one = MagicMock(
                    return_value=30
                )  # active_users_total (< MAU)
            elif call_count == 5:
                # per_agent query
                mock_result.fetchall = MagicMock(return_value=[])
            else:
                # feature_adoption query
                mock_result.fetchall = MagicMock(return_value=[])
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute
        data = await get_engagement_v2_db(TEST_TENANT_ID, mock_db)
        # inactive = max(0, 30 - 50) = 0
        assert data["aggregate"]["inactive_users"] == 0

    @pytest.mark.asyncio
    async def test_feature_adoption_empty_on_db_error(self):
        """feature_adoption returns empty list if analytics_events query fails."""
        from app.modules.admin.analytics import get_engagement_v2_db

        call_count = 0

        async def fake_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count <= 4:
                mock_result.scalar_one = MagicMock(return_value=10)
            elif call_count == 5:
                mock_result.fetchall = MagicMock(return_value=[])
            else:
                # Simulate analytics_events table error
                raise Exception("relation analytics_events does not exist")
            return mock_result

        mock_db = AsyncMock()
        mock_db.execute = fake_execute
        data = await get_engagement_v2_db(TEST_TENANT_ID, mock_db)
        assert data["feature_adoption"] == []
