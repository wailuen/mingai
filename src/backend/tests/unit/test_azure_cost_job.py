"""
Unit tests for PA-014: Azure Cost Management pull job.

Tests cover:
  - pull_azure_infra_costs returns {} when env vars missing
  - OAuth token fetch called with correct params
  - Cost query uses correct date range (today-2 days)
  - Attribution: total_cost / active_tenant_count per day
  - Returns {} on HTTP 429
  - Returns {} on network error
  - run_azure_cost_job updates infra_is_estimated=False when Azure data available
  - run_azure_cost_job keeps infra_is_estimated=True (no update) when Azure returns {}
  - Scheduler runs at 03:45 UTC (constants check)
  - _seconds_until_next_run returns >= 60s and <= 24h+60s

Execute() call order in run_azure_cost_job for each date:
  [0]  SET LOCAL app.current_scope = 'platform'
  [1]  SET LOCAL app.user_role = 'platform_admin'
  [2]  UPDATE cost_summary_daily … WHERE date = …

Execute() call order in pull_azure_infra_costs (tenant count session):
  [0]  SET LOCAL app.current_scope = 'platform'
  [1]  SET LOCAL app.user_role = 'platform_admin'
  [2]  SELECT COUNT(*) FROM tenants …
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from app.modules.platform.azure_cost_job import (
    _LOOKBACK_DAYS,
    _SCHEDULE_HOUR_UTC,
    _SCHEDULE_MINUTE_UTC,
    _fetch_oauth_token,
    _seconds_until_next_run,
    pull_azure_infra_costs,
    run_azure_cost_job,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token_response(token: str = "test-token") -> dict:
    return {"access_token": token, "expires_in": 3600, "token_type": "Bearer"}


def _make_cost_response(rows: list[list]) -> dict:
    """Build a minimal Azure Cost Management API response."""
    return {
        "properties": {
            "columns": [
                {"name": "PreTaxCost", "type": "Number"},
                {"name": "UsageDate", "type": "Number"},
                {"name": "Currency", "type": "String"},
            ],
            "rows": rows,
        }
    }


def _make_db_session(execute_side_effects: list | None = None) -> Any:
    """Build an async mock DB session that acts as an async context manager."""
    mock_db = MagicMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_db.commit = AsyncMock()

    if execute_side_effects is not None:
        mock_db.execute = AsyncMock(side_effect=execute_side_effects)
    else:
        mock_db.execute = AsyncMock(return_value=MagicMock())
    return mock_db


_VALID_ENV = {
    "AZURE_SUBSCRIPTION_ID": "sub-123",
    "AZURE_COST_MGMT_CLIENT_ID": "client-abc",
    "AZURE_COST_MGMT_CLIENT_SECRET": "secret-xyz",
    "AZURE_TENANT_ID": "az-tenant-456",
}


# ---------------------------------------------------------------------------
# Test 1 — Missing env vars: returns {} without crashing
# ---------------------------------------------------------------------------


class TestMissingEnvVars:
    """pull_azure_infra_costs must return {} for any combination of missing env vars."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_all_vars_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await pull_azure_infra_costs()
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_subscription_id_missing(self):
        env = {k: v for k, v in _VALID_ENV.items() if k != "AZURE_SUBSCRIPTION_ID"}
        with patch.dict("os.environ", env, clear=True):
            result = await pull_azure_infra_costs()
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_client_secret_missing(self):
        env = {
            k: v for k, v in _VALID_ENV.items() if k != "AZURE_COST_MGMT_CLIENT_SECRET"
        }
        with patch.dict("os.environ", env, clear=True):
            result = await pull_azure_infra_costs()
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_azure_tenant_id_missing(self):
        env = {k: v for k, v in _VALID_ENV.items() if k != "AZURE_TENANT_ID"}
        with patch.dict("os.environ", env, clear=True):
            result = await pull_azure_infra_costs()
        assert result == {}


# ---------------------------------------------------------------------------
# Test 2 — OAuth token fetch: correct params
# ---------------------------------------------------------------------------


class TestOAuthTokenFetch:
    """_fetch_oauth_token must POST to the correct endpoint with correct form body."""

    @pytest.mark.asyncio
    async def test_token_fetch_posts_to_correct_url(self):
        """Token request POSTs to login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token."""
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        with respx.mock:
            route = respx.post(token_url).mock(
                return_value=httpx.Response(200, json=_make_token_response())
            )
            async with httpx.AsyncClient() as client:
                token = await _fetch_oauth_token(
                    client, "az-tenant-456", "cid", "csecret"
                )

        assert token == "test-token"
        assert route.called

    @pytest.mark.asyncio
    async def test_token_fetch_sends_client_credentials_grant(self):
        """grant_type=client_credentials and scope=management.azure.com/.default."""
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        captured_data: dict = {}

        def capture_request(request: httpx.Request) -> httpx.Response:
            import urllib.parse

            parsed = urllib.parse.parse_qs(request.content.decode())
            captured_data.update({k: v[0] for k, v in parsed.items()})
            return httpx.Response(200, json=_make_token_response())

        with respx.mock:
            respx.post(token_url).mock(side_effect=capture_request)
            async with httpx.AsyncClient() as client:
                await _fetch_oauth_token(client, "az-tenant-456", "cid", "csecret")

        assert captured_data["grant_type"] == "client_credentials"
        assert "management.azure.com" in captured_data["scope"]

    @pytest.mark.asyncio
    async def test_token_fetch_returns_none_on_401(self):
        """Non-200 response → None (no crash)."""
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        with respx.mock:
            respx.post(token_url).mock(
                return_value=httpx.Response(401, json={"error": "unauthorized"})
            )
            async with httpx.AsyncClient() as client:
                token = await _fetch_oauth_token(
                    client, "az-tenant-456", "cid", "csecret"
                )

        assert token is None

    @pytest.mark.asyncio
    async def test_token_fetch_returns_none_on_network_error(self):
        """Network exception → None (no crash)."""
        with respx.mock:
            respx.post(
                "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
            ).mock(side_effect=httpx.ConnectError("connection refused"))
            async with httpx.AsyncClient() as client:
                token = await _fetch_oauth_token(
                    client, "az-tenant-456", "cid", "csecret"
                )

        assert token is None


# ---------------------------------------------------------------------------
# Test 3 — Cost query uses correct date range
# ---------------------------------------------------------------------------


class TestCostQueryDateRange:
    """pull_azure_infra_costs must query the previous _LOOKBACK_DAYS days."""

    @pytest.mark.asyncio
    async def test_date_range_covers_lookback_days(self):
        """
        The cost query timePeriod.from should be (today - 2 days) and
        timePeriod.to should be (today - 1 day).
        """
        today = date.today()
        expected_from = (today - timedelta(days=_LOOKBACK_DAYS)).isoformat()
        expected_to = (today - timedelta(days=1)).isoformat()

        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        cost_url = (
            "https://management.azure.com/subscriptions/sub-123"
            "/providers/Microsoft.CostManagement/query"
        )

        captured_body: dict = {}

        def capture_cost_request(request: httpx.Request) -> httpx.Response:
            import json

            captured_body.update(json.loads(request.content))
            return httpx.Response(200, json=_make_cost_response([]))

        mock_session = _make_db_session()
        count_result = MagicMock()
        count_result.fetchone.return_value = (3,)
        mock_session.execute = AsyncMock(
            side_effect=[MagicMock(), MagicMock(), count_result]
        )

        with respx.mock, patch.dict("os.environ", _VALID_ENV), patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ):
            respx.post(token_url).mock(
                return_value=httpx.Response(200, json=_make_token_response())
            )
            respx.post(cost_url).mock(side_effect=capture_cost_request)
            await pull_azure_infra_costs()

        assert captured_body["timePeriod"]["from"].startswith(expected_from)
        assert captured_body["timePeriod"]["to"].startswith(expected_to)


# ---------------------------------------------------------------------------
# Test 4 — Attribution: total_cost / active_tenant_count per day
# ---------------------------------------------------------------------------


class TestCostAttribution:
    """Per-tenant cost = total Azure daily cost / active tenant count."""

    @pytest.mark.asyncio
    async def test_cost_split_by_tenant_count(self):
        """With 4 tenants and $40 total, per-tenant cost = $10."""
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        cost_url = (
            "https://management.azure.com/subscriptions/sub-123"
            "/providers/Microsoft.CostManagement/query"
        )
        today = date.today()
        date_str = (today - timedelta(days=1)).strftime("%Y%m%d")

        rows = [[40.0, int(date_str), "USD"]]

        mock_session = _make_db_session()
        count_result = MagicMock()
        count_result.fetchone.return_value = (4,)
        mock_session.execute = AsyncMock(
            side_effect=[MagicMock(), MagicMock(), count_result]
        )

        with respx.mock, patch.dict("os.environ", _VALID_ENV), patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ):
            respx.post(token_url).mock(
                return_value=httpx.Response(200, json=_make_token_response())
            )
            respx.post(cost_url).mock(
                return_value=httpx.Response(200, json=_make_cost_response(rows))
            )
            result = await pull_azure_infra_costs()

        target_date = (today - timedelta(days=1)).isoformat()
        assert target_date in result
        assert abs(result[target_date] - 10.0) < 1e-5

    @pytest.mark.asyncio
    async def test_single_tenant_gets_full_cost(self):
        """With 1 active tenant, per-tenant cost equals total cost."""
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        cost_url = (
            "https://management.azure.com/subscriptions/sub-123"
            "/providers/Microsoft.CostManagement/query"
        )
        today = date.today()
        date_str = (today - timedelta(days=1)).strftime("%Y%m%d")
        rows = [[25.50, int(date_str), "USD"]]

        mock_session = _make_db_session()
        count_result = MagicMock()
        count_result.fetchone.return_value = (1,)
        mock_session.execute = AsyncMock(
            side_effect=[MagicMock(), MagicMock(), count_result]
        )

        with respx.mock, patch.dict("os.environ", _VALID_ENV), patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ):
            respx.post(token_url).mock(
                return_value=httpx.Response(200, json=_make_token_response())
            )
            respx.post(cost_url).mock(
                return_value=httpx.Response(200, json=_make_cost_response(rows))
            )
            result = await pull_azure_infra_costs()

        target_date = (today - timedelta(days=1)).isoformat()
        assert abs(result[target_date] - 25.50) < 1e-5


# ---------------------------------------------------------------------------
# Test 5 — HTTP 429 returns {}
# ---------------------------------------------------------------------------


class TestHttp429GracefulDegradation:
    """Azure API 429 must result in {} with no crash."""

    @pytest.mark.asyncio
    async def test_returns_empty_on_429(self):
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        cost_url = (
            "https://management.azure.com/subscriptions/sub-123"
            "/providers/Microsoft.CostManagement/query"
        )

        with respx.mock, patch.dict("os.environ", _VALID_ENV):
            respx.post(token_url).mock(
                return_value=httpx.Response(200, json=_make_token_response())
            )
            respx.post(cost_url).mock(
                return_value=httpx.Response(429, json={"error": "TooManyRequests"})
            )
            result = await pull_azure_infra_costs()

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_on_500(self):
        """Azure 500 is also a graceful degradation path."""
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        cost_url = (
            "https://management.azure.com/subscriptions/sub-123"
            "/providers/Microsoft.CostManagement/query"
        )

        with respx.mock, patch.dict("os.environ", _VALID_ENV):
            respx.post(token_url).mock(
                return_value=httpx.Response(200, json=_make_token_response())
            )
            respx.post(cost_url).mock(
                return_value=httpx.Response(500, json={"error": "InternalError"})
            )
            result = await pull_azure_infra_costs()

        assert result == {}


# ---------------------------------------------------------------------------
# Test 6 — Network error returns {}
# ---------------------------------------------------------------------------


class TestNetworkErrorGracefulDegradation:
    """Network errors (ConnectError, timeout) must result in {} with no crash."""

    @pytest.mark.asyncio
    async def test_returns_empty_on_cost_query_network_error(self):
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"
        cost_url = (
            "https://management.azure.com/subscriptions/sub-123"
            "/providers/Microsoft.CostManagement/query"
        )

        with respx.mock, patch.dict("os.environ", _VALID_ENV):
            respx.post(token_url).mock(
                return_value=httpx.Response(200, json=_make_token_response())
            )
            respx.post(cost_url).mock(
                side_effect=httpx.ConnectError("network unreachable")
            )
            result = await pull_azure_infra_costs()

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_on_token_network_error(self):
        """Token fetch network error also returns {}."""
        token_url = "https://login.microsoftonline.com/az-tenant-456/oauth2/v2.0/token"

        with respx.mock, patch.dict("os.environ", _VALID_ENV):
            respx.post(token_url).mock(side_effect=httpx.ConnectError("DNS failure"))
            result = await pull_azure_infra_costs()

        assert result == {}


# ---------------------------------------------------------------------------
# Test 7 — run_azure_cost_job: updates infra_is_estimated=False when data available
# ---------------------------------------------------------------------------


class TestRunAzureCostJobWithData:
    """When pull_azure_infra_costs returns data, DB rows must be updated."""

    @pytest.mark.asyncio
    async def test_updates_infra_is_estimated_to_false(self):
        """
        run_azure_cost_job must UPDATE cost_summary_daily with infra_is_estimated=FALSE
        for each date in the Azure cost data.
        """
        fake_costs = {"2026-03-14": 5.25, "2026-03-15": 6.00}

        mock_session = _make_db_session()
        # Each date: [SET LOCAL, UPDATE]
        mock_session.execute = AsyncMock(return_value=MagicMock())

        with patch(
            "app.modules.platform.azure_cost_job.pull_azure_infra_costs",
            AsyncMock(return_value=fake_costs),
        ), patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ):
            await run_azure_cost_job()

        # 2 dates → 2 session uses → 2 commits
        assert mock_session.commit.await_count == 2

    @pytest.mark.asyncio
    async def test_update_params_contain_false_flag_and_correct_date(self):
        """
        The UPDATE call must pass infra_is_estimated=FALSE implicitly
        (hardcoded in the SQL) and the correct target_date.
        """
        fake_costs = {"2026-03-15": 7.50}

        mock_session = _make_db_session()
        update_calls: list[dict] = []

        async def capture_execute(stmt, params=None):
            if params and "target_date" in (params or {}):
                update_calls.append(params)
            return MagicMock()

        mock_session.execute = AsyncMock(side_effect=capture_execute)

        with patch(
            "app.modules.platform.azure_cost_job.pull_azure_infra_costs",
            AsyncMock(return_value=fake_costs),
        ), patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ):
            await run_azure_cost_job()

        assert len(update_calls) == 1
        assert update_calls[0]["target_date"] == "2026-03-15"
        assert abs(update_calls[0]["infra_cost"] - 7.50) < 1e-5


# ---------------------------------------------------------------------------
# Test 7b — RLS bypass: both SET LOCAL statements must be issued
# ---------------------------------------------------------------------------


class TestRLSBypass:
    """Both SET LOCAL statements required for full RLS bypass in DB sessions."""

    @pytest.mark.asyncio
    async def test_update_session_sets_both_rls_locals(self):
        """
        run_azure_cost_job UPDATE session must set app.current_scope AND
        app.user_role before executing the UPDATE query.
        """
        fake_costs = {"2026-03-15": 5.00}
        issued_stmts: list[str] = []

        async def capture_execute(stmt, params=None):
            issued_stmts.append(str(stmt))
            return MagicMock()

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(side_effect=capture_execute)

        with patch(
            "app.modules.platform.azure_cost_job.pull_azure_infra_costs",
            AsyncMock(return_value=fake_costs),
        ), patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ):
            await run_azure_cost_job()

        set_local_stmts = [
            s
            for s in issued_stmts
            if "SET LOCAL" in s
            or "set_config" in s.lower()
            or "current_scope" in s
            or "user_role" in s
        ]
        assert any(
            "current_scope" in s and "platform" in s for s in set_local_stmts
        ), "SET LOCAL app.current_scope = 'platform' must be issued"
        assert any(
            "user_role" in s and "platform_admin" in s for s in set_local_stmts
        ), "SET LOCAL app.user_role = 'platform_admin' must be issued"

    @pytest.mark.asyncio
    async def test_tenant_count_session_sets_both_rls_locals(self):
        """
        pull_azure_infra_costs tenant-count session must set app.current_scope
        AND app.user_role — tenants RLS checks both.
        """
        issued_stmts: list[str] = []

        count_result = MagicMock()
        count_result.scalar.return_value = 3

        async def capture_execute(stmt, params=None):
            issued_stmts.append(str(stmt))
            return count_result

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(side_effect=capture_execute)

        with patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ), patch(
            "app.modules.platform.azure_cost_job._fetch_oauth_token",
            AsyncMock(return_value="test-token"),
        ), patch(
            "app.modules.platform.azure_cost_job._query_azure_costs",
            AsyncMock(return_value=[{"date": "2026-03-14", "cost": 9.0}]),
        ):
            import os

            with patch.dict(
                os.environ,
                {
                    "AZURE_SUBSCRIPTION_ID": "sub-123",
                    "AZURE_COST_MGMT_CLIENT_ID": "client-123",
                    "AZURE_COST_MGMT_CLIENT_SECRET": "secret-123",
                    "AZURE_TENANT_ID": "tenant-123",
                },
            ):
                from app.modules.platform.azure_cost_job import pull_azure_infra_costs

                await pull_azure_infra_costs()

        set_local_stmts = [
            s for s in issued_stmts if "current_scope" in s or "user_role" in s
        ]
        assert any(
            "current_scope" in s and "platform" in s for s in set_local_stmts
        ), "SET LOCAL app.current_scope = 'platform' must be issued for tenant count"
        assert any(
            "user_role" in s and "platform_admin" in s for s in set_local_stmts
        ), "SET LOCAL app.user_role = 'platform_admin' must be issued for tenant count"


# ---------------------------------------------------------------------------
# Test 8 — run_azure_cost_job: keeps infra_is_estimated=True when Azure returns {}
# ---------------------------------------------------------------------------


class TestRunAzureCostJobNoData:
    """When pull_azure_infra_costs returns {}, no DB rows should be touched."""

    @pytest.mark.asyncio
    async def test_no_db_calls_when_azure_returns_empty(self):
        """
        If pull_azure_infra_costs returns {}, run_azure_cost_job must make
        no database calls at all (infra_is_estimated stays TRUE).
        """
        mock_session = _make_db_session()

        with patch(
            "app.modules.platform.azure_cost_job.pull_azure_infra_costs",
            AsyncMock(return_value={}),
        ), patch(
            "app.modules.platform.azure_cost_job.async_session_factory",
            return_value=mock_session,
        ):
            await run_azure_cost_job()

        mock_session.execute.assert_not_called()
        mock_session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Test 9 — Scheduler constants at 03:45 UTC
# ---------------------------------------------------------------------------


class TestSchedulerConstants:
    """Scheduler must be configured for 03:45 UTC."""

    def test_schedule_constants_are_03_45_utc(self):
        assert _SCHEDULE_HOUR_UTC == 3
        assert _SCHEDULE_MINUTE_UTC == 45

    def test_lookback_days_is_two(self):
        """Azure has 24-48h delay — we always query back 2 days."""
        assert _LOOKBACK_DAYS == 2


# ---------------------------------------------------------------------------
# Test 10 — _seconds_until_next_run bounds
# ---------------------------------------------------------------------------


class TestSecondsUntilNextRun:
    """Scheduler delay must be within sane bounds."""

    def test_returns_at_least_60_seconds(self):
        """Always returns >= 60s regardless of current time."""
        delay = _seconds_until_next_run()
        assert delay >= 60.0

    def test_returns_at_most_one_day_plus_buffer(self):
        """Delay cannot exceed 24 hours plus 60s buffer."""
        delay = _seconds_until_next_run()
        assert delay <= 24 * 3600 + 60.0
