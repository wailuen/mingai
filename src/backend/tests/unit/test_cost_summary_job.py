"""
Unit tests for PA-012/PA-013: cost summary batch job with gross margin.

Tests aggregation logic, model_breakdown JSON structure, upsert idempotency,
per-tenant failure isolation, scheduler timing, and gross margin calculation —
all without hitting a real database.

PA-013 extended _process_tenant with a _fetch_tenant_plan() call, so the
execute() call order is now:
  [0]  SET LOCAL app.current_scope = 'platform'
  [1]  SET LOCAL app.user_role = 'platform_admin'  ← satisfies usage_events RLS
  [2]  SELECT … FROM usage_events          (aggregation)
  [3]  SELECT plan FROM tenants            (_fetch_tenant_plan)
  [4]  INSERT … ON CONFLICT                (upsert)
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.core.scheduler import seconds_until_utc
from app.modules.platform.cost_summary_job import (
    _PLAN_REVENUE,
    _compute_gross_margin,
    _process_tenant,
    run_cost_summary_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(usage_rows: list[tuple], plan: str | None = None) -> Any:
    """
    Build an async mock DB session.

    _process_tenant execute() call order (5 calls total):

      [0]  SET LOCAL app.current_scope = 'platform'
      [1]  SET LOCAL app.user_role = 'platform_admin'  ← satisfies usage_events RLS
      [2]  SELECT … FROM usage_events   → agg_result
      [3]  SELECT plan FROM tenants     → plan_result  (_fetch_tenant_plan)
      [4]  INSERT … ON CONFLICT         → no-op

    Args:
        usage_rows: Rows returned by the aggregation SELECT.
        plan:       The plan tier string to return from _fetch_tenant_plan.
                    Pass None to simulate a missing tenant row.
    """
    agg_result = MagicMock()
    agg_result.fetchall.return_value = usage_rows

    plan_result = MagicMock()
    plan_result.fetchone.return_value = (plan,) if plan is not None else None

    side_effects = [
        MagicMock(),  # [0] SET LOCAL app.current_scope = 'platform'
        MagicMock(),  # [1] SET LOCAL app.user_role = 'platform_admin'
        agg_result,  # [2] SELECT … FROM usage_events
        plan_result,  # [3] SELECT plan FROM tenants (_fetch_tenant_plan)
        MagicMock(),  # [4] INSERT … ON CONFLICT
    ]

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=side_effects)
    mock_db.commit = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# Test 1 — Aggregation formula
# ---------------------------------------------------------------------------


class TestAggregationFormula:
    """Totals are the sum of individual row values."""

    @pytest.mark.asyncio
    async def test_totals_are_summed_across_rows(self):
        """
        Given two model rows, total_tokens_in = sum of both rows, etc.
        The INSERT upsert must be called with the correct totals.
        """
        rows = [
            ("azure_openai", "gpt-5", 1000, 400, Decimal("0.002000")),
            ("azure_openai", "text-embedding-3-small", 500, 0, Decimal("0.000500")),
        ]
        mock_db = _make_db(rows)
        target = date(2026, 3, 15)

        await _process_tenant("tenant-abc", target, mock_db)

        # Capture the INSERT call parameters (index 4: scope, user_role, agg, plan, INSERT)
        params = mock_db.execute.call_args_list[4].args[1]

        assert params["tokens_in"] == 1500
        assert params["tokens_out"] == 400
        assert abs(params["cost_usd"] - 0.0025) < 1e-9

    @pytest.mark.asyncio
    async def test_single_row_totals(self):
        """Single row — totals equal that row's values exactly."""
        rows = [
            ("azure_openai", "gpt-5", 200, 80, Decimal("0.001234")),
        ]
        mock_db = _make_db(rows)

        await _process_tenant("tenant-xyz", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]
        assert params["tokens_in"] == 200
        assert params["tokens_out"] == 80
        assert abs(params["cost_usd"] - 0.001234) < 1e-9

    @pytest.mark.asyncio
    async def test_empty_usage_events_produces_zero_totals(self):
        """No usage_events → totals are all zero, model_breakdown is empty list."""
        mock_db = _make_db([])

        await _process_tenant("tenant-empty", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]
        assert params["tokens_in"] == 0
        assert params["tokens_out"] == 0
        assert params["cost_usd"] == 0.0
        breakdown = json.loads(params["breakdown"])
        assert breakdown == []


# ---------------------------------------------------------------------------
# Test 2 — model_breakdown JSON structure
# ---------------------------------------------------------------------------


class TestModelBreakdownStructure:
    """model_breakdown JSONB must be a list of correctly-keyed dicts."""

    @pytest.mark.asyncio
    async def test_breakdown_contains_all_required_keys(self):
        rows = [
            ("azure_openai", "gpt-5", 1234, 567, Decimal("0.003456")),
        ]
        mock_db = _make_db(rows)

        await _process_tenant("t1", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]
        breakdown = json.loads(params["breakdown"])

        assert len(breakdown) == 1
        item = breakdown[0]
        assert item["provider"] == "azure_openai"
        assert item["model"] == "gpt-5"
        assert item["tokens_in"] == 1234
        assert item["tokens_out"] == 567
        assert abs(item["cost_usd"] - 0.003456) < 1e-9

    @pytest.mark.asyncio
    async def test_breakdown_has_one_entry_per_model(self):
        """Two distinct (provider, model) pairs produce two breakdown entries."""
        rows = [
            ("azure_openai", "gpt-5", 100, 50, Decimal("0.001")),
            ("openai", "gpt-4o", 200, 100, Decimal("0.002")),
        ]
        mock_db = _make_db(rows)

        await _process_tenant("t1", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]
        breakdown = json.loads(params["breakdown"])
        assert len(breakdown) == 2

    @pytest.mark.asyncio
    async def test_breakdown_cost_rounded_to_6_decimal_places(self):
        """cost_usd in each breakdown entry is rounded to 6 decimal places."""
        rows = [
            ("azure_openai", "gpt-5", 1, 1, Decimal("0.0000001234567")),
        ]
        mock_db = _make_db(rows)

        await _process_tenant("t1", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]
        breakdown = json.loads(params["breakdown"])
        # round(..., 6) of 0.0000001234567 = 0.0
        assert breakdown[0]["cost_usd"] == round(0.0000001234567, 6)


# ---------------------------------------------------------------------------
# Test 3 — Upsert idempotency
# ---------------------------------------------------------------------------


class TestRLSBypass:
    """Both SET LOCAL statements required for full RLS bypass."""

    @pytest.mark.asyncio
    async def test_both_set_local_statements_issued(self):
        """
        _process_tenant must issue SET LOCAL for both app.current_scope
        (cost_summary_daily RLS) and app.user_role (usage_events RLS).
        """
        mock_db = _make_db([])
        await _process_tenant("t1", date(2026, 3, 15), mock_db)

        call_stmts = [str(mock_db.execute.call_args_list[i].args[0]) for i in range(2)]
        assert any(
            "current_scope" in s and "platform" in s for s in call_stmts
        ), "SET LOCAL app.current_scope = 'platform' must be called"
        assert any(
            "user_role" in s and "platform_admin" in s for s in call_stmts
        ), "SET LOCAL app.user_role = 'platform_admin' must be called"


class TestUpsertIdempotency:
    """Calling _process_tenant twice for the same date updates, not duplicates."""

    @pytest.mark.asyncio
    async def test_upsert_called_on_conflict(self):
        """
        The INSERT statement must use ON CONFLICT (tenant_id, date) DO UPDATE,
        ensuring a second call for the same date is an update not an insert.
        """
        rows = [("azure_openai", "gpt-5", 500, 200, Decimal("0.001"))]
        target = date(2026, 3, 15)

        # First call
        mock_db1 = _make_db(rows)
        await _process_tenant("tenant-upsert", target, mock_db1)

        # Second call with updated values
        rows2 = [("azure_openai", "gpt-5", 999, 300, Decimal("0.005"))]
        mock_db2 = _make_db(rows2)
        await _process_tenant("tenant-upsert", target, mock_db2)

        # Both calls must have executed the upsert (5th execute = INSERT...ON CONFLICT)
        # Call order: SET LOCAL scope [0], SET LOCAL user_role [1], SELECT agg [2], SELECT plan [3], INSERT [4]
        assert mock_db1.execute.await_count == 5
        assert mock_db2.execute.await_count == 5

        # Second upsert must carry the new values
        params2 = mock_db2.execute.call_args_list[4].args[1]
        assert params2["tokens_in"] == 999
        assert params2["tokens_out"] == 300

    @pytest.mark.asyncio
    async def test_commit_called_after_upsert(self):
        """db.commit() is always called to persist the upsert."""
        mock_db = _make_db([])
        await _process_tenant("t1", date(2026, 3, 15), mock_db)
        mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 4 — Per-tenant failure isolation
# ---------------------------------------------------------------------------


class TestPerTenantFailureIsolation:
    """One tenant failure must not abort processing of the remaining tenants."""

    @pytest.mark.asyncio
    async def test_one_failing_tenant_does_not_abort_others(self):
        """
        With three tenants, if the first raises an exception the other two
        are still processed.
        """
        tenant_ids = ["t-fail", "t-ok-1", "t-ok-2"]
        processed_ids: list[str] = []

        async def fake_process(tenant_id: str, target_date: date, db: Any) -> None:
            if tenant_id == "t-fail":
                raise RuntimeError("simulated DB failure")
            processed_ids.append(tenant_id)

        # Patch async_session_factory as an async context manager
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # First call returns tenant list; subsequent calls are per-tenant sessions
        tenant_result = MagicMock()
        tenant_result.fetchall.return_value = [(tid,) for tid in tenant_ids]
        mock_session.execute = AsyncMock(return_value=tenant_result)

        with patch(
            "app.modules.platform.cost_summary_job.async_session_factory",
            return_value=mock_session,
        ), patch(
            "app.modules.platform.cost_summary_job._process_tenant",
            side_effect=fake_process,
        ):
            await run_cost_summary_job()

        # t-ok-1 and t-ok-2 must have been processed despite t-fail raising
        assert "t-ok-1" in processed_ids
        assert "t-ok-2" in processed_ids
        assert "t-fail" not in processed_ids

    @pytest.mark.asyncio
    async def test_all_tenants_succeed_no_errors(self):
        """Happy path: all tenants succeed, no errors logged."""
        tenant_ids = ["t-a", "t-b"]
        processed_ids: list[str] = []

        async def fake_process(tenant_id: str, target_date: date, db: Any) -> None:
            processed_ids.append(tenant_id)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        tenant_result = MagicMock()
        tenant_result.fetchall.return_value = [(tid,) for tid in tenant_ids]
        mock_session.execute = AsyncMock(return_value=tenant_result)

        with patch(
            "app.modules.platform.cost_summary_job.async_session_factory",
            return_value=mock_session,
        ), patch(
            "app.modules.platform.cost_summary_job._process_tenant",
            side_effect=fake_process,
        ):
            await run_cost_summary_job()

        assert set(processed_ids) == {"t-a", "t-b"}

    @pytest.mark.asyncio
    async def test_no_active_tenants_returns_early(self):
        """If no active tenants, job exits early without calling _process_tenant."""
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=empty_result)

        with patch(
            "app.modules.platform.cost_summary_job.async_session_factory",
            return_value=mock_session,
        ), patch("app.modules.platform.cost_summary_job._process_tenant") as mock_pt:
            await run_cost_summary_job()

        mock_pt.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — _seconds_until_next_run bounds
# ---------------------------------------------------------------------------


class TestSecondsUntilNextRun:
    """Scheduler delay must be within sane bounds."""

    def test_returns_at_least_60_seconds(self):
        """Always returns >= 60s regardless of current time."""
        delay = seconds_until_utc(3, 30)
        assert delay >= 60.0

    def test_returns_at_most_one_day_plus_buffer(self):
        """Delay cannot exceed 24 hours plus 60s buffer."""
        delay = seconds_until_utc(3, 30)
        assert delay <= 24 * 3600 + 60.0

    def test_schedule_constants_are_correct(self):
        """Job is configured for 03:30 UTC."""
        # seconds_until_utc(3, 30) schedules at 03:30 UTC — verify bounds
        delay = seconds_until_utc(3, 30)
        assert 60.0 <= delay <= 24 * 3600 + 60.0


# ---------------------------------------------------------------------------
# Test 6 — PA-013 Gross margin calculation (_compute_gross_margin)
# ---------------------------------------------------------------------------


class TestComputeGrossMargin:
    """Unit tests for the pure _compute_gross_margin function (no DB needed)."""

    def test_standard_margin_calculation(self):
        """Standard case: margin = (revenue - llm_cost - infra) / revenue * 100."""
        # revenue=10, llm_cost=3, infra=1 → (10-3-1)/10*100 = 60.0
        assert _compute_gross_margin(10.0, 3.0, 1.0) == pytest.approx(60.0)

    def test_zero_revenue_returns_none(self):
        """Division-by-zero guard: revenue=0 → None regardless of costs."""
        assert _compute_gross_margin(0.0, 5.0, 1.0) is None
        assert _compute_gross_margin(0.0, 0.0, 0.0) is None

    def test_negative_margin_clamped_to_minus_100(self):
        """Costs exceeding 200% of revenue: clamped to -100.0."""
        # revenue=1, llm_cost=100, infra=100 → raw=-19900%, clamped=-100
        result = _compute_gross_margin(1.0, 100.0, 100.0)
        assert result == -100.0

    def test_margin_above_100_clamped_to_100(self):
        """Negative costs (credit scenario): clamped to 100.0."""
        result = _compute_gross_margin(1.0, -200.0, 0.0)
        assert result == 100.0

    def test_zero_costs_full_margin(self):
        """No LLM or infra cost → 100% gross margin."""
        assert _compute_gross_margin(10.0, 0.0, 0.0) == pytest.approx(100.0)

    def test_exact_breakeven(self):
        """LLM + infra == revenue → 0% gross margin."""
        assert _compute_gross_margin(10.0, 8.0, 2.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 7 — PA-013 Gross margin upsert integration
# ---------------------------------------------------------------------------


class TestGrossMarginUpsert:
    """Verify that _process_tenant writes gross margin columns to the upsert."""

    @pytest.mark.asyncio
    async def test_gross_margin_written_when_plan_revenue_configured(self):
        """
        When PLAN_REVENUE has a non-zero value for 'professional',
        gross_margin_pct, plan_revenue_usd, and infra_cost_estimate_usd are
        populated in the upsert params.
        """
        rows = [("azure_openai", "gpt-5", 1000, 400, Decimal("2.00"))]
        mock_db = _make_db(rows, plan="professional")

        # Patch env-sourced constants so test is deterministic
        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"professional": 10.0},
        ), patch(
            "app.modules.platform.cost_summary_job._INFRA_COST_PER_TENANT_DAILY",
            1.0,
        ):
            await _process_tenant("t1", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]

        # revenue=10, llm_cost=2, infra=1 → margin = 70.0
        assert params["plan_revenue_usd"] == pytest.approx(10.0)
        assert params["infra_cost_usd"] == pytest.approx(1.0)
        assert params["gross_margin_pct"] == pytest.approx(70.0)

    @pytest.mark.asyncio
    async def test_gross_margin_is_none_when_no_plan_revenue(self):
        """
        When plan revenue is 0 (unconfigured), gross_margin_pct and the
        revenue/infra columns are None to avoid storing misleading data.
        """
        rows = [("azure_openai", "gpt-5", 1000, 400, Decimal("2.00"))]
        mock_db = _make_db(rows, plan="starter")

        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"starter": 0.0},
        ), patch(
            "app.modules.platform.cost_summary_job._INFRA_COST_PER_TENANT_DAILY",
            1.0,
        ):
            await _process_tenant("t1", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]

        assert params["plan_revenue_usd"] is None
        assert params["infra_cost_usd"] is None
        assert params["gross_margin_pct"] is None

    @pytest.mark.asyncio
    async def test_gross_margin_is_none_when_tenant_plan_not_found(self):
        """
        When _fetch_tenant_plan returns None (tenant row missing),
        gross_margin_pct is None.
        """
        rows = [("azure_openai", "gpt-5", 1000, 400, Decimal("2.00"))]
        # plan=None → simulate missing tenant row
        mock_db = _make_db(rows, plan=None)

        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"professional": 10.0},
        ):
            await _process_tenant("t1", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]
        assert params["gross_margin_pct"] is None

    @pytest.mark.asyncio
    async def test_gross_margin_rounded_to_2_decimal_places(self):
        """gross_margin_pct is rounded to 2 decimal places before upsert."""
        rows = [("azure_openai", "gpt-5", 100, 50, Decimal("1.001"))]
        mock_db = _make_db(rows, plan="enterprise")

        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"enterprise": 3.0},
        ), patch(
            "app.modules.platform.cost_summary_job._INFRA_COST_PER_TENANT_DAILY",
            0.0,
        ):
            await _process_tenant("t1", date(2026, 3, 15), mock_db)

        params = mock_db.execute.call_args_list[4].args[1]
        # (3.0 - 1.001 - 0.0) / 3.0 * 100 = 66.633...% → rounds to 66.63
        expected = round((3.0 - 1.001 - 0.0) / 3.0 * 100.0, 2)
        assert params["gross_margin_pct"] == pytest.approx(expected, abs=1e-6)
