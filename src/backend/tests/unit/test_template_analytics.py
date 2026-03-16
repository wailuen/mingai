"""
Unit tests for PA-026: Template analytics API.

  GET /platform/agent-templates/{id}/analytics

Tier 1: Fast, isolated. Uses dependency_overrides + AsyncMock helpers.
"""
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "f" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_TEMPLATE_ID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"

_MOD = "app.modules.platform.routes"
_ANALYTICS_URL = f"/api/v1/platform/agent-templates/{TEST_TEMPLATE_ID}/analytics"


def _make_platform_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "platform-admin-001",
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
        "sub": "tenant-admin-001",
        "tenant_id": TEST_TENANT_ID,
        "roles": ["tenant_admin"],
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


def _platform_headers() -> dict:
    return {"Authorization": f"Bearer {_make_platform_token()}"}


def _tenant_headers() -> dict:
    return {"Authorization": f"Bearer {_make_tenant_token()}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAnalyticsAuth:
    def test_requires_auth(self, client):
        resp = client.get(_ANALYTICS_URL)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.get(_ANALYTICS_URL, headers=_tenant_headers())
        assert resp.status_code == 403

    def test_invalid_uuid_returns_422(self, client):
        resp = client.get(
            "/api/v1/platform/agent-templates/not-a-uuid/analytics",
            headers=_platform_headers(),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 404 when template does not exist
# ---------------------------------------------------------------------------


class TestAnalyticsNotFound:
    def test_404_when_template_missing(self, client):
        """If the template doesn't exist in agent_templates, return 404."""
        # We need to patch the DB session to simulate template not found.
        # The route calls session.execute() multiple times; first call is set_config,
        # second is the EXISTS check. We return None from fetchone() for the second call.
        with _patch_db_template_not_found():
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        assert resp.status_code == 404


def _patch_db_template_not_found():
    """Patch get_async_session to return a session where template lookup returns None."""
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            # set_config call
            mock_result.fetchone.return_value = None
        else:
            # EXISTS check — return None to signal template not found
            mock_result.fetchone.return_value = None
        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestAnalyticsHappyPath:
    def test_returns_correct_structure(self, client):
        with _patch_db_analytics(
            daily_rows=[
                {
                    "date": date(2026, 3, 15),
                    "satisfaction_rate": 0.85,
                    "guardrail_trigger_rate": 0.05,
                    "failure_count": 2,
                    "session_count": 14,
                }
            ],
            tenant_count=3,
            failure_patterns=[
                {"issue_type": "accuracy", "issue_count": 5},
                {"issue_type": "tone", "issue_count": 3},
            ],
        ):
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "template_id" in data
        assert "daily_metrics" in data
        assert "tenant_count" in data
        assert "top_failure_patterns" in data

    def test_daily_metrics_correct_fields(self, client):
        with _patch_db_analytics(
            daily_rows=[
                {
                    "date": date(2026, 3, 15),
                    "satisfaction_rate": 0.9,
                    "guardrail_trigger_rate": 0.1,
                    "failure_count": 1,
                    "session_count": 10,
                }
            ],
            tenant_count=2,
            failure_patterns=[],
        ):
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        data = resp.json()
        assert len(data["daily_metrics"]) == 1
        metric = data["daily_metrics"][0]
        assert metric["date"] == "2026-03-15"
        assert metric["satisfaction_rate"] == 0.9
        assert metric["guardrail_trigger_rate"] == 0.1
        assert metric["failure_count"] == 1
        assert metric["session_count"] == 10

    def test_tenant_count_returned(self, client):
        with _patch_db_analytics(daily_rows=[], tenant_count=7, failure_patterns=[]):
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        assert resp.json()["tenant_count"] == 7

    def test_top_failure_patterns_top3(self, client):
        """Verify failure patterns are returned with issue_type and count."""
        patterns = [
            {"issue_type": "accuracy", "issue_count": 10},
            {"issue_type": "tone", "issue_count": 7},
            {"issue_type": "hallucination", "issue_count": 4},
        ]
        with _patch_db_analytics(
            daily_rows=[], tenant_count=1, failure_patterns=patterns
        ):
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        data = resp.json()
        assert len(data["top_failure_patterns"]) == 3
        assert data["top_failure_patterns"][0]["issue_type"] == "accuracy"
        assert data["top_failure_patterns"][0]["count"] == 10

    def test_empty_analytics_for_new_template(self, client):
        """Template with no perf data returns empty arrays, zero counts."""
        with _patch_db_analytics(daily_rows=[], tenant_count=0, failure_patterns=[]):
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        data = resp.json()
        assert data["daily_metrics"] == []
        assert data["tenant_count"] == 0
        assert data["top_failure_patterns"] == []

    def test_template_id_in_response(self, client):
        with _patch_db_analytics(daily_rows=[], tenant_count=0, failure_patterns=[]):
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        assert resp.json()["template_id"] == TEST_TEMPLATE_ID

    def test_null_rates_allowed_in_daily_metrics(self, client):
        """Days with no feedback have None satisfaction_rate."""
        with _patch_db_analytics(
            daily_rows=[
                {
                    "date": date(2026, 3, 14),
                    "satisfaction_rate": None,
                    "guardrail_trigger_rate": None,
                    "failure_count": 0,
                    "session_count": 5,
                }
            ],
            tenant_count=1,
            failure_patterns=[],
        ):
            resp = client.get(_ANALYTICS_URL, headers=_platform_headers())
        metric = resp.json()["daily_metrics"][0]
        assert metric["satisfaction_rate"] is None
        assert metric["guardrail_trigger_rate"] is None


# ---------------------------------------------------------------------------
# DB mock helper for happy-path tests
# ---------------------------------------------------------------------------


def _patch_db_analytics(daily_rows, tenant_count, failure_patterns):
    """Patch get_async_session for the analytics endpoint.

    Call order:
      1. set_config('app.scope', 'platform')
      2. set_config('app.tenant_id', '')   — clear stale tenant from pool
      3. EXISTS check on agent_templates → returns a row (template found)
      4. template_performance_daily query → daily_rows
      5. agent_cards tenant_count query → tenant_count scalar
      6. issue_reports failure patterns query → failure_patterns
    """
    from app.core.session import get_async_session
    from app.main import app

    mock_session = MagicMock()
    call_count = 0

    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()

        if call_count == 1:
            # set_config scope
            mock_result.fetchone.return_value = ("platform",)
            mock_result.mappings.return_value = []
        elif call_count == 2:
            # set_config tenant_id clear
            mock_result.fetchone.return_value = ("",)
            mock_result.mappings.return_value = []
        elif call_count == 3:
            # EXISTS check — template found
            mock_result.fetchone.return_value = (1,)
        elif call_count == 4:
            # daily metrics
            mock_result.mappings.return_value = daily_rows
        elif call_count == 5:
            # tenant count
            mock_result.scalar.return_value = tenant_count
        elif call_count == 6:
            # failure patterns
            mock_result.mappings.return_value = failure_patterns
        else:
            mock_result.mappings.return_value = []

        return mock_result

    mock_session.execute = AsyncMock(side_effect=_execute)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[get_async_session] = _override
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_async_session, None)

    return _ctx()
