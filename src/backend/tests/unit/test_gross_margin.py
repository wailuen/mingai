"""
Unit tests for PA-013: Gross Margin Calculation.

Covers:
  1. Standard gross_margin_pct formula
  2. Zero plan revenue → gross_margin_pct is None (division-by-zero guard)
  3. Margin clamped to 100% when costs are somehow negative
  4. Margin clamped to -100% when costs exceed 2x revenue
  5. Correct plan tier revenue lookup (starter / professional / enterprise)
  6. gross_margin_pct present in GET /platform/tenants/{id}/cost-usage response
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.platform.cost_summary_job import (
    _PLAN_REVENUE,
    _compute_gross_margin,
    _fetch_tenant_plan,
    _process_tenant,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_with_margin(
    usage_rows: list[tuple],
    tenant_plan: str | None,
    plan_revenue_env: dict[str, str] | None = None,
    infra_cost_env: str = "0",
) -> Any:
    """
    Build a mock DB session for _process_tenant tests that include margin.

    Execute call order (5 calls — both SET LOCAL statements required for RLS):
      0 — SET LOCAL app.current_scope = 'platform'  (cost_summary_daily RLS)
      1 — SET LOCAL app.user_role = 'platform_admin'  (usage_events RLS)
      2 — SELECT … FROM usage_events (returns usage_rows)
      3 — SELECT plan FROM tenants (returns tenant_plan)
      4 — INSERT … ON CONFLICT (upsert, no return value needed)

    commit() is a no-op AsyncMock.
    """
    agg_result = MagicMock()
    agg_result.fetchall.return_value = usage_rows

    plan_result = MagicMock()
    # Use a plain tuple so row[0] is unambiguous — MagicMock __getitem__ lambdas
    # are unreliable when the mock machinery intercepts subscript operations.
    plan_result.fetchone.return_value = (
        (tenant_plan,) if tenant_plan is not None else None
    )

    side_effects = [
        MagicMock(),  # [0] SET LOCAL app.current_scope = 'platform'
        MagicMock(),  # [1] SET LOCAL app.user_role = 'platform_admin'
        agg_result,  # [2] SELECT usage_events
        plan_result,  # [3] SELECT plan FROM tenants
        MagicMock(),  # [4] INSERT … ON CONFLICT
    ]

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=side_effects)
    mock_db.commit = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# Test 1 — Standard formula
# ---------------------------------------------------------------------------


class TestGrossMarginFormula:
    """_compute_gross_margin must implement (rev - llm - infra) / rev * 100."""

    def test_standard_calculation(self):
        """
        Given revenue=10, llm_cost=3, infra=1:
          margin = (10 - 3 - 1) / 10 * 100 = 60.0
        """
        result = _compute_gross_margin(
            plan_revenue=10.0,
            total_cost_usd=3.0,
            infra_cost=1.0,
        )
        assert result == pytest.approx(60.0)

    def test_positive_margin_below_100(self):
        """Normal profitable scenario."""
        result = _compute_gross_margin(
            plan_revenue=100.0,
            total_cost_usd=20.0,
            infra_cost=5.0,
        )
        assert result == pytest.approx(75.0)

    def test_zero_costs_gives_100_percent(self):
        """No costs → 100% margin (before clamping)."""
        result = _compute_gross_margin(
            plan_revenue=50.0,
            total_cost_usd=0.0,
            infra_cost=0.0,
        )
        assert result == pytest.approx(100.0)

    def test_breakeven_gives_zero_percent(self):
        """Costs exactly equal revenue → 0% margin."""
        result = _compute_gross_margin(
            plan_revenue=25.0,
            total_cost_usd=20.0,
            infra_cost=5.0,
        )
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 2 — Zero revenue guard
# ---------------------------------------------------------------------------


class TestZeroRevenueGuard:
    """When plan_revenue == 0, margin must be None (not a ZeroDivisionError)."""

    def test_zero_revenue_returns_none(self):
        result = _compute_gross_margin(
            plan_revenue=0.0,
            total_cost_usd=5.0,
            infra_cost=1.0,
        )
        assert result is None

    def test_zero_revenue_zero_costs_returns_none(self):
        """Even if costs are also zero, we can't divide by zero."""
        result = _compute_gross_margin(
            plan_revenue=0.0,
            total_cost_usd=0.0,
            infra_cost=0.0,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Test 3 — Clamp to 100%
# ---------------------------------------------------------------------------


class TestClampUpperBound:
    """Margin must be clamped to 100% even if costs are somehow negative."""

    def test_negative_costs_clamped_to_100(self):
        """
        If costs are negative (credit/refund scenario), raw margin > 100%.
        Must be clamped to 100.
        """
        result = _compute_gross_margin(
            plan_revenue=10.0,
            total_cost_usd=-5.0,  # credit
            infra_cost=0.0,
        )
        assert result == pytest.approx(100.0)

    def test_both_costs_negative_clamped_to_100(self):
        result = _compute_gross_margin(
            plan_revenue=10.0,
            total_cost_usd=-100.0,
            infra_cost=-50.0,
        )
        assert result == pytest.approx(100.0)

    def test_margin_just_below_100_not_clamped(self):
        """A margin of 99.9% passes through without clamping."""
        result = _compute_gross_margin(
            plan_revenue=1000.0,
            total_cost_usd=1.0,
            infra_cost=0.0,
        )
        assert result is not None
        assert result < 100.0
        assert result > 99.0


# ---------------------------------------------------------------------------
# Test 4 — Clamp to -100%
# ---------------------------------------------------------------------------


class TestClampLowerBound:
    """Margin must be clamped to -100% when costs exceed 2x revenue."""

    def test_costs_exceed_2x_revenue_clamped(self):
        """
        revenue=10, costs=30 → raw = (10-30)/10*100 = -200%. Clamp to -100.
        """
        result = _compute_gross_margin(
            plan_revenue=10.0,
            total_cost_usd=30.0,
            infra_cost=0.0,
        )
        assert result == pytest.approx(-100.0)

    def test_costs_exactly_2x_revenue_clamped(self):
        """revenue=10, costs=20 → raw -100%, no further clamping needed."""
        result = _compute_gross_margin(
            plan_revenue=10.0,
            total_cost_usd=20.0,
            infra_cost=0.0,
        )
        assert result == pytest.approx(-100.0)

    def test_costs_slightly_above_revenue_not_clamped(self):
        """revenue=10, costs=11 → margin = -10%, above lower bound."""
        result = _compute_gross_margin(
            plan_revenue=10.0,
            total_cost_usd=11.0,
            infra_cost=0.0,
        )
        assert result == pytest.approx(-10.0)


# ---------------------------------------------------------------------------
# Test 5 — Plan tier revenue lookup
# ---------------------------------------------------------------------------


class TestPlanTierLookup:
    """Different plan tiers must use their respective revenue rates."""

    def test_starter_tier_uses_starter_revenue(self):
        """
        Patch _PLAN_REVENUE so we can assert the correct key is consulted.
        starter revenue = 5.0/day, llm_cost = 1.0, infra = 0.5
        → margin = (5 - 1 - 0.5) / 5 * 100 = 70.0
        """
        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"starter": 5.0, "professional": 20.0, "enterprise": 100.0},
            clear=False,
        ):
            margin = _compute_gross_margin(
                plan_revenue=_PLAN_REVENUE.get("starter", 0.0),
                total_cost_usd=1.0,
                infra_cost=0.5,
            )
            assert margin == pytest.approx(70.0)

    def test_professional_tier_uses_pro_revenue(self):
        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"starter": 5.0, "professional": 20.0, "enterprise": 100.0},
            clear=False,
        ):
            margin = _compute_gross_margin(
                plan_revenue=_PLAN_REVENUE.get("professional", 0.0),
                total_cost_usd=4.0,
                infra_cost=1.0,
            )
            # (20 - 4 - 1) / 20 * 100 = 75.0
            assert margin == pytest.approx(75.0)

    def test_enterprise_tier_uses_enterprise_revenue(self):
        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"starter": 5.0, "professional": 20.0, "enterprise": 100.0},
            clear=False,
        ):
            margin = _compute_gross_margin(
                plan_revenue=_PLAN_REVENUE.get("enterprise", 0.0),
                total_cost_usd=10.0,
                infra_cost=5.0,
            )
            # (100 - 10 - 5) / 100 * 100 = 85.0
            assert margin == pytest.approx(85.0)

    def test_unknown_plan_tier_falls_back_to_zero_revenue(self):
        """An unrecognised plan string maps to 0 revenue → None margin."""
        revenue = _PLAN_REVENUE.get("unknown_tier", 0.0)
        margin = _compute_gross_margin(
            plan_revenue=revenue,
            total_cost_usd=1.0,
            infra_cost=0.5,
        )
        assert margin is None


# ---------------------------------------------------------------------------
# Test 5b — _process_tenant writes correct margin params
# ---------------------------------------------------------------------------


class TestProcessTenantMarginParams:
    """_process_tenant must pass the correct margin columns to the upsert."""

    @pytest.mark.asyncio
    async def test_margin_columns_written_to_upsert(self):
        """
        With revenue=10, llm_cost=2, infra=1 → margin=(10-2-1)/10*100=70%.
        Plan row returns "starter". All three margin params flow to the INSERT.
        """
        rows = [("azure_openai", "gpt-5", 100, 50, Decimal("2.0"))]
        mock_db = _make_db_with_margin(rows, tenant_plan="starter")

        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"starter": 10.0, "professional": 20.0, "enterprise": 100.0},
            clear=False,
        ), patch(
            "app.modules.platform.cost_summary_job._INFRA_COST_PER_TENANT_DAILY",
            1.0,
        ):
            await _process_tenant("tenant-abc", date(2026, 3, 15), mock_db)

        # The upsert is the 4th execute call (index 3)
        upsert_call = mock_db.execute.call_args_list[4]
        params = upsert_call.args[1]

        assert params["plan_revenue_usd"] == pytest.approx(10.0)
        assert params["infra_cost_usd"] == pytest.approx(1.0)
        assert params["gross_margin_pct"] == pytest.approx(70.0)

    @pytest.mark.asyncio
    async def test_zero_plan_revenue_writes_none_margin(self):
        """
        When plan is not in _PLAN_REVENUE (defaults to 0), margin columns
        must be None in the upsert params.
        """
        rows = [("azure_openai", "gpt-5", 100, 50, Decimal("2.0"))]
        mock_db = _make_db_with_margin(rows, tenant_plan="free")

        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"starter": 10.0, "professional": 20.0, "enterprise": 100.0},
            clear=False,
        ):
            await _process_tenant("tenant-zero-rev", date(2026, 3, 15), mock_db)

        upsert_call = mock_db.execute.call_args_list[4]
        params = upsert_call.args[1]

        assert params["plan_revenue_usd"] is None
        assert params["infra_cost_usd"] is None
        assert params["gross_margin_pct"] is None

    @pytest.mark.asyncio
    async def test_tenant_not_found_writes_none_margin(self):
        """
        When _fetch_tenant_plan returns None (tenant row missing), plan_revenue
        is treated as 0 → all three margin columns are None.
        """
        rows = [("azure_openai", "gpt-5", 100, 50, Decimal("1.5"))]
        mock_db = _make_db_with_margin(rows, tenant_plan=None)

        with patch.dict(
            "app.modules.platform.cost_summary_job._PLAN_REVENUE",
            {"starter": 10.0, "professional": 20.0, "enterprise": 100.0},
            clear=False,
        ):
            await _process_tenant("tenant-missing", date(2026, 3, 15), mock_db)

        upsert_call = mock_db.execute.call_args_list[4]
        params = upsert_call.args[1]

        assert params["gross_margin_pct"] is None


# ---------------------------------------------------------------------------
# Test 6 — gross_margin_pct in cost-usage API response
# ---------------------------------------------------------------------------


class TestCostUsageAPIMarginField:
    """
    GET /platform/tenants/{id}/cost-usage must include gross_margin_pct
    in the totals dict, sourced from the most recent cost_summary_daily row.
    """

    def _make_async_session(
        self,
        *,
        tokens_in: int = 1000,
        tokens_out: int = 400,
        cost_usd: float = 2.5,
        gross_margin_pct: float | None = 68.5,
    ) -> Any:
        """
        Build a mock AsyncSession that satisfies the six execute() calls in
        get_tenant_cost_usage:
          0 — set_config app.user_role
          1 — set_config app.current_scope  (PA-013 addition)
          2 — SELECT totals from usage_events
          3 — SELECT by_model from usage_events
          4 — SELECT daily from usage_events
          5 — SELECT gross_margin_pct from cost_summary_daily
        """
        from decimal import Decimal

        # Use plain tuples for rows — they support [i] indexing reliably and
        # avoid the MagicMock.__getitem__ side-effect vs lambda binding ambiguity.
        totals_tuple = (tokens_in, tokens_out, Decimal(str(cost_usd)))

        totals_result = MagicMock()
        totals_result.fetchone.return_value = totals_tuple

        # by_model result (empty for simplicity)
        model_result = MagicMock()
        model_result.fetchall.return_value = []

        # daily result (empty)
        daily_result = MagicMock()
        daily_result.fetchall.return_value = []

        # margin row — plain 3-tuple (gross_margin_pct, infra_is_estimated,
        # infra_last_updated_at) or None when no row exists.
        # PA-014 extended the SELECT to 3 columns.
        if gross_margin_pct is not None:
            margin_tuple: tuple | None = (Decimal(str(gross_margin_pct)), True, None)
        else:
            margin_tuple = None

        margin_result = MagicMock()
        margin_result.fetchone.return_value = margin_tuple

        # set_config calls return no-op mocks
        side_effects = [
            MagicMock(),  # set_config app.user_role
            MagicMock(),  # set_config app.current_scope
            totals_result,  # SELECT totals
            model_result,  # SELECT by_model
            daily_result,  # SELECT daily
            margin_result,  # SELECT gross_margin_pct
        ]

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=side_effects)
        return mock_db

    @pytest.mark.asyncio
    async def test_gross_margin_pct_in_response(self):
        """gross_margin_pct from cost_summary_daily flows into totals dict."""
        from unittest.mock import AsyncMock, MagicMock, patch
        import uuid

        tenant_id = str(uuid.uuid4())
        mock_db = self._make_async_session(gross_margin_pct=68.5)

        # Import here to avoid circular import at module level in tests
        from app.modules.platform.cost_analytics import get_tenant_cost_usage

        # Build a mock CurrentUser with platform scope
        mock_user = MagicMock()
        mock_user.scope = "platform"

        result = await get_tenant_cost_usage(
            tenant_id=tenant_id,
            period="7d",
            from_date=None,
            to_date=None,
            current_user=mock_user,
            db=mock_db,
        )

        assert "totals" in result
        assert "gross_margin_pct" in result["totals"]
        assert result["totals"]["gross_margin_pct"] == pytest.approx(68.5)

    @pytest.mark.asyncio
    async def test_gross_margin_pct_none_when_no_summary_row(self):
        """
        When cost_summary_daily has no row for the tenant, gross_margin_pct
        is None rather than raising an error.
        """
        import uuid
        from app.modules.platform.cost_analytics import get_tenant_cost_usage

        tenant_id = str(uuid.uuid4())

        # Plain tuples — reliable indexing, no MagicMock __getitem__ ambiguity
        totals_result = MagicMock()
        totals_result.fetchone.return_value = (0, 0, None)

        model_result = MagicMock()
        model_result.fetchall.return_value = []
        daily_result = MagicMock()
        daily_result.fetchall.return_value = []

        margin_result = MagicMock()
        margin_result.fetchone.return_value = None  # no row in cost_summary_daily

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(),  # set_config user_role
                MagicMock(),  # set_config current_scope
                totals_result,
                model_result,
                daily_result,
                margin_result,
            ]
        )

        mock_user = MagicMock()
        mock_user.scope = "platform"

        result = await get_tenant_cost_usage(
            tenant_id=tenant_id,
            period="7d",
            from_date=None,
            to_date=None,
            current_user=mock_user,
            db=mock_db,
        )

        assert result["totals"]["gross_margin_pct"] is None

    @pytest.mark.asyncio
    async def test_gross_margin_pct_none_when_column_is_null(self):
        """
        When the cost_summary_daily row exists but gross_margin_pct IS NULL
        (plan revenue was 0 when the job ran), the API must return None.
        """
        import uuid
        from app.modules.platform.cost_analytics import get_tenant_cost_usage

        tenant_id = str(uuid.uuid4())

        totals_result = MagicMock()
        totals_result.fetchone.return_value = (500, 200, None)

        model_result = MagicMock()
        model_result.fetchall.return_value = []
        daily_result = MagicMock()
        daily_result.fetchall.return_value = []

        # Row exists but gross_margin_pct column value is SQL NULL → Python None.
        # PA-014: query now returns 3 columns (gross_margin_pct, infra_is_estimated,
        # MAX(infra_last_updated_at)).
        margin_result = MagicMock()
        margin_result.fetchone.return_value = (
            None,
            True,
            None,
        )  # tuple with None at index 0

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(),
                MagicMock(),
                totals_result,
                model_result,
                daily_result,
                margin_result,
            ]
        )

        mock_user = MagicMock()
        result = await get_tenant_cost_usage(
            tenant_id=tenant_id,
            period="7d",
            from_date=None,
            to_date=None,
            current_user=mock_user,
            db=mock_db,
        )

        assert result["totals"]["gross_margin_pct"] is None
