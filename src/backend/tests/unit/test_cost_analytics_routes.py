"""
Unit tests for COST-1: /platform/analytics/cost/summary,
/platform/analytics/cost/tenants, and /platform/analytics/cost/margin-trend.

All tests use mocked dependencies — no real database or Redis required.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_USER_ID = "cccccccc-0000-0000-0000-000000000001"


def _make_platform_user():
    user = MagicMock()
    user.id = _FAKE_USER_ID
    user.scope = "platform"
    user.roles = ["platform_admin"]
    user.tenant_id = None
    return user


def _async_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test get_cost_analytics_db helper (shared by all three sub-routes)
# ---------------------------------------------------------------------------


class TestGetCostAnalyticsDb:
    """Validates the shared DB helper used by all three sub-routes."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_tenants(self):
        from app.modules.platform.routes import get_cost_analytics_db

        db = _async_db()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.return_value = mock_result

        by_tenant, llm_total, rev_total = await get_cost_analytics_db(
            days=30, filter_tenant_id=None, db=db
        )

        assert by_tenant == []
        assert llm_total == 0.0
        assert rev_total == 0.0

    @pytest.mark.asyncio
    async def test_aggregates_token_costs(self):
        from app.modules.platform.routes import get_cost_analytics_db

        db = _async_db()
        # One tenant: 1,000,000 tokens_in, 500,000 tokens_out
        # input rate 0.005/1k → 5.0; output rate 0.015/1k → 7.5; total 12.5
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, i: [
            "aaaaaaaa-0000-0000-0000-000000000001",
            "Acme Corp",
            "professional",
            1_000_000,
            500_000,
        ][i]

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]
        db.execute.return_value = mock_result

        with patch.dict(
            "os.environ",
            {"INPUT_COST_PER_1K": "0.005", "OUTPUT_COST_PER_1K": "0.015"},
        ):
            by_tenant, llm_total, rev_total = await get_cost_analytics_db(
                days=30, filter_tenant_id=None, db=db
            )

        assert len(by_tenant) == 1
        t = by_tenant[0]
        assert t["tenant_id"] == "aaaaaaaa-0000-0000-0000-000000000001"
        assert t["name"] == "Acme Corp"
        assert t["plan"] == "professional"
        # 1M * 0.005 / 1000 + 500K * 0.015 / 1000 = 5.0 + 7.5 = 12.5
        assert abs(t["llm_cost_usd"] - 12.5) < 0.01
        assert abs(llm_total - 12.5) < 0.01
        # 30 days at $299/month → 299.0 revenue
        assert abs(rev_total - 299.0) < 0.01


# ---------------------------------------------------------------------------
# Test GET /platform/analytics/cost/summary (HTTP layer)
# ---------------------------------------------------------------------------


class TestCostSummaryEndpoint:
    """Tests for GET /platform/analytics/cost/summary."""

    def _make_client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_requires_auth(self):
        """Unauthenticated request returns 401 or 403."""
        client = self._make_client()
        resp = client.get("/api/v1/platform/analytics/cost/summary")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_summary_response_shape(self):
        from app.modules.platform.routes import get_cost_summary

        db = _async_db()
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, i: [
            "bbbbbbbb-0000-0000-0000-000000000002",
            "Beta Ltd",
            "enterprise",
            500_000,
            250_000,
        ][i]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]
        db.execute.return_value = mock_result

        with patch.dict(
            "os.environ",
            {
                "INPUT_COST_PER_1K": "0.005",
                "OUTPUT_COST_PER_1K": "0.015",
                "INFRA_COST_PER_TENANT_DAILY_USD": "1.50",
            },
        ):
            result = await get_cost_summary(
                period="30d",
                current_user=_make_platform_user(),
                session=db,
            )

        assert "total_llm_cost" in result
        assert "total_infra_cost" in result
        assert "total_revenue" in result
        assert "period" in result
        assert result["period"] == "30d"
        # 1 tenant × 30 days × $1.50/day = $45
        assert abs(result["total_infra_cost"] - 45.0) < 0.01

    @pytest.mark.asyncio
    async def test_invalid_period_falls_back_to_30d(self):
        from app.modules.platform.routes import get_cost_summary

        db = _async_db()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.return_value = mock_result

        result = await get_cost_summary(
            period="INVALID",
            current_user=_make_platform_user(),
            session=db,
        )
        assert result["period"] == "30d"

    @pytest.mark.asyncio
    async def test_gross_margin_is_none_when_no_revenue(self):
        """Starter plan tenants have $0 revenue — gross_margin_pct must be None."""
        from app.modules.platform.routes import get_cost_summary

        db = _async_db()
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, i: [
            "cccccccc-0000-0000-0000-000000000003",
            "Free Co",
            "starter",
            0,
            0,
        ][i]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]
        db.execute.return_value = mock_result

        with patch.dict(
            "os.environ", {"INFRA_COST_PER_TENANT_DAILY_USD": "1.50"}
        ):
            result = await get_cost_summary(
                period="30d",
                current_user=_make_platform_user(),
                session=db,
            )

        # starter revenue = 0 → gross_margin_pct must be None (avoid div/0)
        assert result["gross_margin_pct"] is None


# ---------------------------------------------------------------------------
# Test GET /platform/analytics/cost/tenants (HTTP layer)
# ---------------------------------------------------------------------------


class TestCostTenantsEndpoint:
    """Tests for GET /platform/analytics/cost/tenants."""

    def _make_client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_requires_auth(self):
        """Unauthenticated request returns 401 or 403."""
        client = self._make_client()
        resp = client.get("/api/v1/platform/analytics/cost/tenants")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_tenants_response_is_list(self):
        from app.modules.platform.routes import get_cost_tenants

        db = _async_db()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.return_value = mock_result

        result = await get_cost_tenants(
            period="30d",
            current_user=_make_platform_user(),
            session=db,
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_tenants_row_shape(self):
        from app.modules.platform.routes import get_cost_tenants

        db = _async_db()
        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, i: [
            "dddddddd-0000-0000-0000-000000000004",
            "Delta Corp",
            "professional",
            200_000,
            100_000,
        ][i]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]
        db.execute.return_value = mock_result

        with patch.dict(
            "os.environ",
            {
                "INPUT_COST_PER_1K": "0.005",
                "OUTPUT_COST_PER_1K": "0.015",
                "INFRA_COST_PER_TENANT_DAILY_USD": "1.50",
            },
        ):
            result = await get_cost_tenants(
                period="30d",
                current_user=_make_platform_user(),
                session=db,
            )

        assert len(result) == 1
        row = result[0]
        required_fields = {
            "tenant_id",
            "tenant_name",
            "plan",
            "tokens_consumed",
            "llm_cost",
            "infra_cost",
            "plan_revenue",
            "gross_margin_pct",
        }
        assert required_fields.issubset(set(row.keys()))
        # tokens_consumed = tokens_in + tokens_out
        assert row["tokens_consumed"] == 300_000
        # infra = 1.5 × 30
        assert abs(row["infra_cost"] - 45.0) < 0.01

    @pytest.mark.asyncio
    async def test_invalid_period_defaults_to_30d(self):
        from app.modules.platform.routes import get_cost_tenants

        db = _async_db()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute.return_value = mock_result

        # Must not raise — just clamp to 30d
        result = await get_cost_tenants(
            period="999d",
            current_user=_make_platform_user(),
            session=db,
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Test GET /platform/analytics/cost/margin-trend (HTTP layer)
# ---------------------------------------------------------------------------


class TestMarginTrendEndpoint:
    """Tests for GET /platform/analytics/cost/margin-trend."""

    def _make_client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_requires_auth(self):
        """Unauthenticated request returns 401 or 403."""
        client = self._make_client()
        resp = client.get("/api/v1/platform/analytics/cost/margin-trend")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_returns_list_of_margin_points(self):
        from app.modules.platform.routes import get_cost_margin_trend
        import datetime

        db = _async_db()

        # Two date rows from cost_summary_daily
        row1 = MagicMock()
        row1.__getitem__ = lambda self, i: [datetime.date(2026, 3, 20), 54.5][i]
        row2 = MagicMock()
        row2.__getitem__ = lambda self, i: [datetime.date(2026, 3, 21), 56.1][i]

        # margin-trend executes twice: once for set_config, once for SELECT
        set_cfg_result = MagicMock()
        rows_result = MagicMock()
        rows_result.fetchall.return_value = [row1, row2]
        db.execute.side_effect = [set_cfg_result, rows_result]

        result = await get_cost_margin_trend(
            period="7d",
            current_user=_make_platform_user(),
            session=db,
        )

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["date"] == "2026-03-20"
        assert abs(result[0]["margin_pct"] - 54.5) < 0.01
        assert result[1]["date"] == "2026-03-21"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_data(self):
        from app.modules.platform.routes import get_cost_margin_trend

        db = _async_db()
        set_cfg_result = MagicMock()
        rows_result = MagicMock()
        rows_result.fetchall.return_value = []
        db.execute.side_effect = [set_cfg_result, rows_result]

        result = await get_cost_margin_trend(
            period="30d",
            current_user=_make_platform_user(),
            session=db,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_period_defaults(self):
        from app.modules.platform.routes import get_cost_margin_trend

        db = _async_db()
        set_cfg_result = MagicMock()
        rows_result = MagicMock()
        rows_result.fetchall.return_value = []
        db.execute.side_effect = [set_cfg_result, rows_result]

        # Must not raise — clamp to 30d
        result = await get_cost_margin_trend(
            period="WRONG",
            current_user=_make_platform_user(),
            session=db,
        )
        assert isinstance(result, list)
