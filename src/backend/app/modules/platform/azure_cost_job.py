"""
PA-014: Nightly Azure Cost Management API pull job.

Scheduled daily at 03:45 UTC (15 minutes after the cost_summary_job at 03:30 UTC).
Queries the Azure Cost Management REST API for the previous two days (Azure has a
24-48 hour reporting delay) and updates infra_cost_estimate_usd + infra_is_estimated
in cost_summary_daily.

Attribution model: total Azure daily spend divided equally by active tenant count.
Equal-split attribution is acceptable per spec — proportional-by-usage is out of scope.

Graceful degradation: if any required env var is absent, or if Azure returns 4xx/5xx,
the job logs a warning and exits without updating any rows.  The cost_summary_job
env-constant fallback remains in place (infra_is_estimated stays TRUE).

Required env vars (all new for PA-014):
  AZURE_SUBSCRIPTION_ID        — Azure subscription containing the resources
  AZURE_COST_MGMT_CLIENT_ID    — Service principal client ID
  AZURE_COST_MGMT_CLIENT_SECRET — Service principal client secret
  AZURE_TENANT_ID              — Azure AD tenant ID (for OAuth2 token endpoint)
                                  NOTE: distinct from mingai's tenant_id UUIDs
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context, seconds_until_utc
from app.core.scheduler.timing import check_missed_job
from app.core.session import async_session_factory

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Azure API constants
# ---------------------------------------------------------------------------

_AZURE_MGMT_SCOPE = "https://management.azure.com/.default"
_AZURE_TOKEN_URL_TPL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_AZURE_COST_QUERY_URL_TPL = (
    "https://management.azure.com/subscriptions/{subscription_id}"
    "/providers/Microsoft.CostManagement/query"
    "?api-version=2023-11-01"
)

# How many days back to query (Azure has a 24-48h reporting delay).
_LOOKBACK_DAYS = 2

# HTTP timeout for Azure API calls (seconds).
_HTTP_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Azure OAuth2 token fetch
# ---------------------------------------------------------------------------


async def _fetch_oauth_token(
    client: httpx.AsyncClient,
    azure_tenant_id: str,
    client_id: str,
    client_secret: str,
) -> str | None:
    """
    Request a bearer token from the Azure AD OAuth2 v2 token endpoint.

    Returns the access_token string on success, or None on any error.
    Never raises — callers treat None as a skip signal.

    Args:
        client:          httpx.AsyncClient to use for the request.
        azure_tenant_id: Azure AD tenant ID (not a mingai tenant UUID).
        client_id:       Service principal client ID.
        client_secret:   Service principal client secret.

    Returns:
        Bearer token string or None.
    """
    url = _AZURE_TOKEN_URL_TPL.format(tenant_id=azure_tenant_id)
    try:
        response = await client.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": _AZURE_MGMT_SCOPE,
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "azure_cost_job_token_request_failed",
            error=str(exc),
        )
        return None

    if response.status_code != 200:
        logger.warning(
            "azure_cost_job_token_non_200",
            status_code=response.status_code,
        )
        return None

    try:
        return response.json()["access_token"]
    except (KeyError, ValueError) as exc:
        logger.warning(
            "azure_cost_job_token_parse_failed",
            error=str(exc),
        )
        return None


# ---------------------------------------------------------------------------
# Azure Cost Management query
# ---------------------------------------------------------------------------


async def _query_azure_costs(
    client: httpx.AsyncClient,
    token: str,
    subscription_id: str,
    from_date: date,
    to_date: date,
) -> list[dict[str, Any]] | None:
    """
    POST a cost query to Azure Cost Management for the given date range.

    Returns a list of {"date": "YYYY-MM-DD", "cost": float} dicts on success,
    or None if the API returned a non-2xx status or the response was unparseable.

    Args:
        client:          httpx.AsyncClient.
        token:           Bearer token from _fetch_oauth_token.
        subscription_id: Azure subscription ID.
        from_date:       Start of query window (inclusive).
        to_date:         End of query window (inclusive).

    Returns:
        List of daily cost dicts or None.
    """
    url = _AZURE_COST_QUERY_URL_TPL.format(subscription_id=subscription_id)
    payload = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {
            "from": from_date.isoformat() + "T00:00:00Z",
            "to": to_date.isoformat() + "T23:59:59Z",
        },
        "dataset": {
            "granularity": "Daily",
            "aggregation": {
                "totalCost": {
                    "name": "PreTaxCost",
                    "function": "Sum",
                }
            },
        },
    }

    try:
        response = await client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "azure_cost_job_query_request_failed",
            error=str(exc),
        )
        return None

    if response.status_code == 429:
        logger.warning(
            "azure_cost_job_query_rate_limited",
            status_code=429,
        )
        return None

    if response.status_code >= 400:
        logger.warning(
            "azure_cost_job_query_non_2xx",
            status_code=response.status_code,
        )
        return None

    try:
        data = response.json()
        rows = data["properties"]["rows"]
        columns = [c["name"] for c in data["properties"]["columns"]]
        cost_idx = next(
            i
            for i, c in enumerate(data["properties"]["columns"])
            if c["name"] in ("PreTaxCost", "Cost")
        )
        # Azure returns UsageDate as an integer like 20260314
        date_idx = columns.index("UsageDate")

        results: list[dict[str, Any]] = []
        for row in rows:
            raw_date = str(row[date_idx])
            parsed_date = date(
                int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8])
            )
            cost = float(row[cost_idx])
            results.append({"date": parsed_date.isoformat(), "cost": cost})
        return results
    except (KeyError, ValueError, IndexError, StopIteration) as exc:
        logger.warning(
            "azure_cost_job_query_parse_failed",
            error=str(exc),
        )
        return None


# ---------------------------------------------------------------------------
# Active tenant count
# ---------------------------------------------------------------------------


async def _fetch_active_tenant_count(db: Any) -> int:
    """
    Return the count of active tenants.

    Returns 1 (minimum denominator) if the query fails or returns zero,
    so that division never produces ZeroDivisionError or Infinity.

    Args:
        db: AsyncSession with SET LOCAL app.current_scope = 'platform' already set.

    Returns:
        Integer count >= 1.
    """
    try:
        result = await db.execute(
            text("SELECT COUNT(*) FROM tenants WHERE status = 'active'")
        )
        row = result.fetchone()
        count = int(row[0]) if row and row[0] else 0
        return max(count, 1)
    except Exception as exc:
        logger.warning(
            "azure_cost_job_tenant_count_failed",
            error=str(exc),
        )
        return 1


# ---------------------------------------------------------------------------
# Public: pull_azure_infra_costs
# ---------------------------------------------------------------------------


async def pull_azure_infra_costs() -> dict[str, float]:
    """
    Query Azure Cost Management API for the previous 2 days.

    Returns a dict mapping date strings ("YYYY-MM-DD") to per-tenant cost (USD),
    calculated as total_daily_azure_spend / active_tenant_count.

    Returns {} (empty dict) on any error, so that callers can fall back gracefully
    to the env-constant estimate without crashing.

    Required env vars (all read at call time so tests can patch os.environ):
        AZURE_SUBSCRIPTION_ID
        AZURE_COST_MGMT_CLIENT_ID
        AZURE_COST_MGMT_CLIENT_SECRET
        AZURE_TENANT_ID

    Returns:
        {date_str: cost_usd_per_tenant} or {} on error/missing config.
    """
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
    client_id = os.environ.get("AZURE_COST_MGMT_CLIENT_ID", "")
    client_secret = os.environ.get("AZURE_COST_MGMT_CLIENT_SECRET", "")
    azure_tenant_id = os.environ.get("AZURE_TENANT_ID", "")

    if not all([subscription_id, client_id, client_secret, azure_tenant_id]):
        missing = [
            name
            for name, val in [
                ("AZURE_SUBSCRIPTION_ID", subscription_id),
                ("AZURE_COST_MGMT_CLIENT_ID", client_id),
                ("AZURE_COST_MGMT_CLIENT_SECRET", client_secret),
                ("AZURE_TENANT_ID", azure_tenant_id),
            ]
            if not val
        ]
        logger.warning(
            "azure_cost_job_missing_env_vars",
            missing=missing,
        )
        return {}

    today = date.today()
    from_date = today - timedelta(days=_LOOKBACK_DAYS)
    to_date = today - timedelta(days=1)

    async with httpx.AsyncClient() as client:
        token = await _fetch_oauth_token(
            client, azure_tenant_id, client_id, client_secret
        )
        if token is None:
            return {}

        cost_rows = await _query_azure_costs(
            client, token, subscription_id, from_date, to_date
        )

    if cost_rows is None:
        return {}

    if not cost_rows:
        logger.info("azure_cost_job_no_rows_returned")
        return {}

    # Fetch active tenant count for proportional attribution.
    # Both SET LOCAL statements required: tenants RLS checks app.user_role.
    try:
        async with async_session_factory() as db:
            await db.execute(text("SET LOCAL app.current_scope = 'platform'"))
            await db.execute(text("SET LOCAL app.user_role = 'platform_admin'"))
            tenant_count = await _fetch_active_tenant_count(db)
    except Exception as exc:
        logger.warning(
            "azure_cost_job_tenant_count_session_failed",
            error=str(exc),
        )
        tenant_count = 1

    result: dict[str, float] = {}
    for row in cost_rows:
        per_tenant = round(row["cost"] / tenant_count, 6)
        result[row["date"]] = per_tenant

    logger.info(
        "azure_cost_job_pull_complete",
        days_returned=len(result),
        tenant_count=tenant_count,
    )
    return result


# ---------------------------------------------------------------------------
# Public: run_azure_cost_job
# ---------------------------------------------------------------------------


async def run_azure_cost_job() -> int:
    """
    Execute one full Azure cost pull and update cost_summary_daily.

    For each date returned by pull_azure_infra_costs():
      - Updates infra_cost_estimate_usd to the per-tenant Azure cost
      - Sets infra_is_estimated = FALSE (real API data)
      - Sets infra_last_updated_at = NOW()

    If pull_azure_infra_costs() returns {} (no data / error):
      - No rows are updated; infra_is_estimated remains TRUE for all rows.

    Uses SET LOCAL app.current_scope = 'platform' for RLS bypass.
    Per-date errors are isolated — one failed update does not block others.
    Never raises — all exceptions are logged.
    """
    azure_costs = await pull_azure_infra_costs()

    if not azure_costs:
        logger.info(
            "azure_cost_job_skipped_no_data",
        )
        return 0

    for date_str, per_tenant_cost in azure_costs.items():
        try:
            async with async_session_factory() as db:
                await db.execute(text("SET LOCAL app.current_scope = 'platform'"))
                await db.execute(text("SET LOCAL app.user_role = 'platform_admin'"))
                await db.execute(
                    text(
                        """
                        UPDATE cost_summary_daily
                        SET
                            infra_cost_estimate_usd = :infra_cost,
                            infra_is_estimated      = FALSE,
                            infra_last_updated_at   = NOW()
                        WHERE date = CAST(:target_date AS date)
                        """
                    ),
                    {
                        "infra_cost": per_tenant_cost,
                        "target_date": date_str,
                    },
                )
                await db.commit()

            logger.info(
                "azure_cost_job_date_updated",
                date=date_str,
                per_tenant_cost=per_tenant_cost,
            )
        except Exception as exc:
            logger.error(
                "azure_cost_job_date_update_failed",
                date=date_str,
                error=str(exc),
            )

    return len(azure_costs)


# ---------------------------------------------------------------------------
# Scheduler (daily at 03:45 UTC)
# ---------------------------------------------------------------------------


async def start_azure_cost_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_azure_cost_job() daily at 03:45 UTC.

    Designed to be launched via asyncio.create_task() in app/main.py lifespan.
    Exits gracefully on CancelledError.  Never propagates other exceptions —
    errors are logged and the loop continues to the next cycle.
    """
    logger.info(
        "azure_cost_scheduler_started",
        schedule="daily at 03:45 UTC",
    )

    while True:
        try:
            # SCHED-025: Missed-job recovery — runs immediately on the first
            # iteration if the 03:45 UTC slot passed today with no completed row.
            # On subsequent iterations check_missed_job returns False (row exists).
            async with async_session_factory() as _db:
                if await check_missed_job(
                    _db, "azure_cost", scheduled_hour=3, scheduled_minute=45
                ):
                    async with DistributedJobLock("azure_cost", ttl=1200) as _acquired:
                        if _acquired:
                            async with job_run_context("azure_cost") as ctx:
                                _days_processed = await run_azure_cost_job()
                                ctx.records_processed = _days_processed or 0
                    logger.info("azure_cost_missed_job_recovered")

            sleep_secs = seconds_until_utc(3, 45)
            logger.debug(
                "azure_cost_next_run_in",
                seconds=round(sleep_secs, 0),
            )
            await asyncio.sleep(sleep_secs)
            async with DistributedJobLock("azure_cost", ttl=1200) as acquired:
                if not acquired:
                    logger.debug(
                        "azure_cost_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    async with job_run_context("azure_cost") as ctx:
                        days_processed = await run_azure_cost_job()
                        ctx.records_processed = days_processed or 0
        except asyncio.CancelledError:
            logger.info("azure_cost_scheduler_cancelled")
            return
        except Exception as exc:
            logger.error(
                "azure_cost_scheduler_loop_error",
                error=str(exc),
            )
