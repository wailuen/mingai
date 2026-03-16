"""
Unit tests for PA-025: Template performance tracking batch job.

  POST /platform/batch/template-performance  — manual trigger
  run_template_performance_batch()           — aggregation logic

Tier 1: Fast, isolated. Uses AsyncMock + dependency_overrides.
"""
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient
from jose import jwt

TEST_JWT_SECRET = "e" * 64
TEST_JWT_ALGORITHM = "HS256"
TEST_TENANT_ID = "12345678-1234-5678-1234-567812345678"
TEST_TEMPLATE_A = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
TEST_TEMPLATE_B = "bbbbcccc-dddd-eeee-ffff-000011112222"

_MOD_BATCH = "app.modules.platform.performance"
_MOD_ROUTES = "app.modules.platform.routes"
_TRIGGER_URL = "/api/v1/platform/batch/template-performance"


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
# POST /platform/batch/template-performance — auth
# ---------------------------------------------------------------------------


class TestBatchTriggerAuth:
    def test_requires_auth(self, client):
        resp = client.post(_TRIGGER_URL)
        assert resp.status_code == 401

    def test_requires_platform_admin(self, client):
        resp = client.post(_TRIGGER_URL, headers=_tenant_headers())
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /platform/batch/template-performance — happy path
# ---------------------------------------------------------------------------


class TestBatchTriggerHappyPath:
    def test_returns_200_with_summary(self, client):
        mock_result = {
            "date": "2026-03-15",
            "templates_updated": 3,
            "errors": 0,
        }
        with patch(
            f"{_MOD_ROUTES}.run_template_performance_batch",
            new=AsyncMock(return_value=mock_result),
        ):
            resp = client.post(_TRIGGER_URL, headers=_platform_headers(), json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["templates_updated"] == 3
        assert data["errors"] == 0

    def test_passes_target_date_when_provided(self, client):
        mock_batch = AsyncMock(
            return_value={"date": "2026-03-10", "templates_updated": 1, "errors": 0}
        )
        with patch(f"{_MOD_ROUTES}.run_template_performance_batch", new=mock_batch):
            resp = client.post(
                _TRIGGER_URL,
                headers=_platform_headers(),
                json={"target_date": "2026-03-10"},
            )
        assert resp.status_code == 200
        call_kwargs = mock_batch.call_args
        import datetime as _dt

        assert call_kwargs.kwargs["target_date"] == _dt.date(2026, 3, 10)

    def test_invalid_date_returns_422(self, client):
        resp = client.post(
            _TRIGGER_URL,
            headers=_platform_headers(),
            json={"target_date": "not-a-date"},
        )
        assert resp.status_code == 422

    def test_future_date_returns_422(self, client):
        """Dates >= today should be rejected — no data exists yet."""
        from datetime import datetime, timezone, timedelta

        future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        resp = client.post(
            _TRIGGER_URL,
            headers=_platform_headers(),
            json={"target_date": future},
        )
        assert resp.status_code == 422

    def test_no_body_uses_yesterday(self, client):
        """Omitting body should not crash — batch defaults to yesterday."""
        mock_batch = AsyncMock(
            return_value={"date": "2026-03-15", "templates_updated": 0, "errors": 0}
        )
        with patch(f"{_MOD_ROUTES}.run_template_performance_batch", new=mock_batch):
            resp = client.post(_TRIGGER_URL, headers=_platform_headers())
        assert resp.status_code == 200
        # target_date kwarg should be None (function defaults to yesterday)
        call_kwargs = mock_batch.call_args
        assert call_kwargs.kwargs.get("target_date") is None


# ---------------------------------------------------------------------------
# run_template_performance_batch — aggregation formula unit tests
# ---------------------------------------------------------------------------


class TestAggregationFormulas:
    """Verify satisfaction_rate and guardrail_trigger_rate formulas directly."""

    @pytest.mark.asyncio
    async def test_satisfaction_rate_pure_positive(self):
        """All thumbs-up → satisfaction_rate = 1.0."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        # sat_rows: feedback stats only (no session_count — removed from query)
        # session_rows: authoritative session count from _SESSION_NO_FEEDBACK_QUERY
        sat_row = {
            "template_id": TEST_TEMPLATE_A,
            "positive_count": 5,
            "negative_count": 0,
            "total_feedback": 5,
        }
        session_row = {"template_id": TEST_TEMPLATE_A, "session_count": 5}
        _mock_mappings(mock_db, [sat_row], [session_row], [])

        result = await run_template_performance_batch(
            mock_db, target_date=date(2026, 3, 15)
        )
        assert result["templates_updated"] == 1
        # Verify the upsert was called with satisfaction_rate=1.0
        upsert_params = _find_upsert_call(mock_db)
        assert upsert_params["satisfaction_rate"] == 1.0
        assert upsert_params["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_satisfaction_rate_mixed_feedback(self):
        """3 up, 2 down → satisfaction_rate = 0.6."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        sat_row = {
            "template_id": TEST_TEMPLATE_A,
            "positive_count": 3,
            "negative_count": 2,
            "total_feedback": 5,
        }
        session_row = {"template_id": TEST_TEMPLATE_A, "session_count": 10}
        _mock_mappings(mock_db, [sat_row], [session_row], [])

        await run_template_performance_batch(mock_db, target_date=date(2026, 3, 15))
        upsert_params = _find_upsert_call(mock_db)
        assert abs(upsert_params["satisfaction_rate"] - 0.6) < 1e-9
        assert upsert_params["failure_count"] == 2

    @pytest.mark.asyncio
    async def test_no_feedback_yields_null_satisfaction(self):
        """Templates with sessions but no feedback → satisfaction_rate = None."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        # No feedback row, but session row exists
        session_row = {"template_id": TEST_TEMPLATE_A, "session_count": 3}
        _mock_mappings(mock_db, [], [session_row], [])

        await run_template_performance_batch(mock_db, target_date=date(2026, 3, 15))
        upsert_params = _find_upsert_call(mock_db)
        assert upsert_params["satisfaction_rate"] is None
        assert upsert_params["failure_count"] == 0
        assert upsert_params["session_count"] == 3

    @pytest.mark.asyncio
    async def test_guardrail_trigger_rate_calculation(self):
        """4 sessions, 2 had guardrail events → rate = 0.5."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        sat_row = {
            "template_id": TEST_TEMPLATE_A,
            "positive_count": 4,
            "negative_count": 0,
            "total_feedback": 4,
        }
        session_row = {"template_id": TEST_TEMPLATE_A, "session_count": 4}
        guardrail_row = {"template_id": TEST_TEMPLATE_A, "guardrail_sessions": 2}
        _mock_mappings(mock_db, [sat_row], [session_row], [guardrail_row])

        await run_template_performance_batch(mock_db, target_date=date(2026, 3, 15))
        upsert_params = _find_upsert_call(mock_db)
        assert abs(upsert_params["guardrail_trigger_rate"] - 0.5) < 1e-9

    @pytest.mark.asyncio
    async def test_no_sessions_yields_null_guardrail_rate(self):
        """No sessions → guardrail_trigger_rate = None (avoid division by zero)."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        # Guardrail row with 0 sessions (edge case — shouldn't happen but guard it)
        guardrail_row = {"template_id": TEST_TEMPLATE_A, "guardrail_sessions": 1}
        _mock_mappings(mock_db, [], [], [guardrail_row])

        await run_template_performance_batch(mock_db, target_date=date(2026, 3, 15))
        upsert_params = _find_upsert_call(mock_db)
        assert upsert_params["guardrail_trigger_rate"] is None

    @pytest.mark.asyncio
    async def test_multiple_templates_all_updated(self):
        """Two templates with data → both upserted."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        sat_rows = [
            {
                "template_id": TEST_TEMPLATE_A,
                "positive_count": 2,
                "negative_count": 1,
                "total_feedback": 3,
            },
            {
                "template_id": TEST_TEMPLATE_B,
                "positive_count": 8,
                "negative_count": 2,
                "total_feedback": 10,
            },
        ]
        session_rows = [
            {"template_id": TEST_TEMPLATE_A, "session_count": 5},
            {"template_id": TEST_TEMPLATE_B, "session_count": 12},
        ]
        _mock_mappings(mock_db, sat_rows, session_rows, [])

        result = await run_template_performance_batch(
            mock_db, target_date=date(2026, 3, 15)
        )
        assert result["templates_updated"] == 2
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_returns_date_in_result(self):
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        _mock_mappings(mock_db, [], [], [])

        result = await run_template_performance_batch(
            mock_db, target_date=date(2026, 3, 15)
        )
        assert result["date"] == "2026-03-15"

    @pytest.mark.asyncio
    async def test_sets_platform_scope_for_rls_bypass(self):
        """Batch sets app.scope='platform' as first execute call for guardrail_events RLS bypass."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        _mock_mappings(mock_db, [], [], [])

        await run_template_performance_batch(mock_db, target_date=date(2026, 3, 15))
        first_call = mock_db.execute.call_args_list[0]
        # First arg is the SQL text object — verify it contains set_config
        sql_str = str(first_call.args[0])
        assert "set_config" in sql_str
        assert "platform" in sql_str

    @pytest.mark.asyncio
    async def test_defaults_to_yesterday(self):
        """target_date=None → defaults to yesterday, does not raise."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()
        _mock_mappings(mock_db, [], [], [])

        result = await run_template_performance_batch(mock_db, target_date=None)
        from datetime import datetime, timezone, timedelta

        expected_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        assert result["date"] == str(expected_date)

    @pytest.mark.asyncio
    async def test_row_error_increments_error_count(self):
        """If upsert fails for one template, errors++ but other templates still processed."""
        from app.modules.platform.performance import run_template_performance_batch

        mock_db = MagicMock()

        sat_rows = [
            {
                "template_id": TEST_TEMPLATE_A,
                "positive_count": 1,
                "negative_count": 0,
                "total_feedback": 1,
            }
        ]
        # Calls: 1=set_config, 2=satisfaction, 3=sessions, 4=guardrail, 5=upsert (raises)
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # set_config
                mock_result.mappings.return_value = []
            elif call_count == 2:
                mock_result.mappings.return_value = sat_rows
            elif call_count == 3:
                mock_result.mappings.return_value = []
            elif call_count == 4:
                mock_result.mappings.return_value = []
            else:
                raise RuntimeError("DB error on upsert")
            return mock_result

        mock_db.execute = AsyncMock(side_effect=_side_effect)

        result = await run_template_performance_batch(
            mock_db, target_date=date(2026, 3, 15)
        )
        assert result["errors"] == 1
        assert result["templates_updated"] == 0


# ---------------------------------------------------------------------------
# Helpers for mock construction
# ---------------------------------------------------------------------------


def _mock_mappings(mock_db, sat_rows, session_rows, guardrail_rows):
    """Wire up mock_db.execute to return the given mappings in call order.

    Call order in run_template_performance_batch:
      1 → set_config('app.scope','platform') — no mappings needed
      2 → satisfaction query
      3 → all_sessions query
      4 → guardrail query
      5+ → upsert calls (one per template)
    """
    call_num = 0

    async def _execute(*args, **kwargs):
        nonlocal call_num
        call_num += 1
        mock_result = MagicMock()
        if call_num == 1:
            # set_config call — mappings not used
            mock_result.mappings.return_value = []
        elif call_num == 2:
            mock_result.mappings.return_value = sat_rows
        elif call_num == 3:
            mock_result.mappings.return_value = session_rows
        elif call_num == 4:
            mock_result.mappings.return_value = guardrail_rows
        else:
            mock_result.mappings.return_value = []
        return mock_result

    mock_db.execute = AsyncMock(side_effect=_execute)


def _find_upsert_call(mock_db) -> dict:
    """Extract the bind-parameter dict from the last db.execute() call (the upsert)."""
    # Last call is always the upsert
    last_call = mock_db.execute.call_args_list[-1]
    return last_call.args[1]
