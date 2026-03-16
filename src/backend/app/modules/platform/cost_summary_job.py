"""
PA-012: Nightly token attribution and cost summary batch job.

Scheduled daily at 03:30 UTC (30 minutes after the health score job at 03:00 UTC).
For each active tenant, aggregates usage_events by (provider, model) for the
previous day and upserts the result into cost_summary_daily.

Upsert is idempotent — re-running for the same (tenant_id, date) updates the
existing row instead of inserting a duplicate.

PA-013 extension: after computing totals, calculates gross margin using
plan-tier daily revenue (from env vars) minus LLM cost and per-tenant
infrastructure cost. Margin is stored as a percentage clamped to [-100, 100].
If plan revenue is zero the margin columns are set to NULL.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

from app.core.session import async_session_factory

logger = structlog.get_logger()

# Target run time: 03:30 UTC
_SCHEDULE_HOUR_UTC = 3
_SCHEDULE_MINUTE_UTC = 30

# ---------------------------------------------------------------------------
# Plan revenue / infrastructure cost config (PA-013)
# ---------------------------------------------------------------------------

# Daily revenue per plan tier (USD).  Defaults to 0 so margin comes out None
# when the operator has not configured these, rather than producing nonsense.
_PLAN_REVENUE: dict[str, float] = {
    "starter": float(os.environ.get("PLAN_REVENUE_STARTER_DAILY_USD", "0")),
    "professional": float(os.environ.get("PLAN_REVENUE_PRO_DAILY_USD", "0")),
    "enterprise": float(os.environ.get("PLAN_REVENUE_ENTERPRISE_DAILY_USD", "0")),
}

# Estimated daily infrastructure cost shared equally across all tenants.
_INFRA_COST_PER_TENANT_DAILY: float = float(
    os.environ.get("INFRA_COST_PER_TENANT_DAILY_USD", "0")
)


# ---------------------------------------------------------------------------
# Gross margin helper (PA-013)
# ---------------------------------------------------------------------------


def _compute_gross_margin(
    plan_revenue: float,
    total_cost_usd: float,
    infra_cost: float,
) -> Optional[float]:
    """
    Calculate gross margin percentage for one tenant/day.

    Formula:
        gross_margin_pct = (plan_revenue - total_cost_usd - infra_cost)
                           / plan_revenue * 100

    Returns None when plan_revenue is zero (division-by-zero guard).
    Result is clamped to [-100.0, 100.0] to absorb edge-case data anomalies.

    Args:
        plan_revenue:   Daily revenue attributed to this tenant's plan.
        total_cost_usd: Sum of LLM usage costs for the day.
        infra_cost:     Estimated daily infrastructure cost for this tenant.

    Returns:
        Gross margin as a percentage (float) or None if plan_revenue == 0.
    """
    if plan_revenue == 0.0:
        return None
    raw = (plan_revenue - total_cost_usd - infra_cost) / plan_revenue * 100.0
    return max(-100.0, min(100.0, raw))


# ---------------------------------------------------------------------------
# Per-tenant plan lookup (PA-013)
# ---------------------------------------------------------------------------


async def _fetch_tenant_plan(tenant_id: str, db: Any) -> Optional[str]:
    """
    Fetch the plan tier string for a tenant from the tenants table.

    Returns the plan string (e.g. "starter", "professional", "enterprise") or
    None if the tenant row is not found.

    Args:
        tenant_id: UUID string of the tenant.
        db:        AsyncSession — must already have the correct RLS context set
                   by the caller (_process_tenant sets 'platform' scope).
    """
    result = await db.execute(
        text("SELECT plan FROM tenants WHERE id = :tenant_id"),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    if row is None:
        return None
    return row[0]


# ---------------------------------------------------------------------------
# Per-tenant processing
# ---------------------------------------------------------------------------


async def _process_tenant(tenant_id: str, target_date: date, db: Any) -> None:
    """
    Aggregate usage_events for one tenant on target_date and upsert into
    cost_summary_daily.

    Sets LOCAL app.current_scope = 'platform' before any queries so that
    the cost_summary_daily RLS policy allows access.

    PA-013: Also queries the tenant's plan tier and computes gross margin
    columns (plan_revenue_usd, infra_cost_estimate_usd, gross_margin_pct).

    Args:
        tenant_id:   UUID string of the tenant to process.
        target_date: The date to aggregate (typically yesterday).
        db:          AsyncSession — caller is responsible for the session scope.
    """
    # Both settings required for full RLS bypass:
    # - app.user_role = 'platform_admin'  → satisfies usage_events platform policy
    # - app.current_scope = 'platform'    → satisfies cost_summary_daily policy
    await db.execute(text("SET LOCAL app.current_scope = 'platform'"))
    await db.execute(text("SET LOCAL app.user_role = 'platform_admin'"))

    # Aggregate usage_events for the tenant on the target date.
    result = await db.execute(
        text(
            """
            SELECT
                provider,
                model,
                SUM(tokens_in)  AS tokens_in,
                SUM(tokens_out) AS tokens_out,
                SUM(cost_usd)   AS cost_usd
            FROM usage_events
            WHERE tenant_id = :tid
              AND DATE(created_at) = :target_date
            GROUP BY provider, model
            """
        ),
        {"tid": tenant_id, "target_date": target_date},
    )
    rows = result.fetchall()

    # Build model_breakdown list from aggregated rows.
    model_breakdown: list[dict] = []
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost_usd = 0.0

    for row in rows:
        provider = row[0] or ""
        model = row[1] or ""
        tokens_in = int(row[2] or 0)
        tokens_out = int(row[3] or 0)
        cost_usd = float(row[4] or 0.0)

        model_breakdown.append(
            {
                "provider": provider,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": round(cost_usd, 6),
            }
        )
        total_tokens_in += tokens_in
        total_tokens_out += tokens_out
        total_cost_usd += cost_usd

    # PA-013: Gross margin calculation.
    plan = await _fetch_tenant_plan(tenant_id, db)
    plan_revenue = _PLAN_REVENUE.get(plan or "", 0.0) if plan else 0.0
    infra_cost = _INFRA_COST_PER_TENANT_DAILY
    gross_margin = _compute_gross_margin(plan_revenue, total_cost_usd, infra_cost)

    # plan_revenue_usd / infra_cost_estimate_usd are None when plan_revenue == 0
    # (no revenue configured) to avoid storing misleading zero values.
    plan_revenue_usd: Optional[float] = plan_revenue if plan_revenue != 0.0 else None
    infra_cost_usd: Optional[float] = infra_cost if plan_revenue != 0.0 else None

    # Upsert — ON CONFLICT updates in place so re-runs are idempotent.
    await db.execute(
        text(
            """
            INSERT INTO cost_summary_daily
                (tenant_id, date, total_tokens_in, total_tokens_out,
                 total_cost_usd, model_breakdown,
                 plan_revenue_usd, infra_cost_estimate_usd, gross_margin_pct,
                 updated_at)
            VALUES
                (:tid, :date, :tokens_in, :tokens_out,
                 :cost_usd, CAST(:breakdown AS jsonb),
                 :plan_revenue_usd, :infra_cost_usd, :gross_margin_pct,
                 NOW())
            ON CONFLICT (tenant_id, date) DO UPDATE SET
                total_tokens_in       = EXCLUDED.total_tokens_in,
                total_tokens_out      = EXCLUDED.total_tokens_out,
                total_cost_usd        = EXCLUDED.total_cost_usd,
                model_breakdown       = EXCLUDED.model_breakdown,
                plan_revenue_usd      = EXCLUDED.plan_revenue_usd,
                infra_cost_estimate_usd = EXCLUDED.infra_cost_estimate_usd,
                gross_margin_pct      = EXCLUDED.gross_margin_pct,
                updated_at            = NOW()
            """
        ),
        {
            "tid": tenant_id,
            "date": target_date,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "cost_usd": round(total_cost_usd, 6),
            "breakdown": json.dumps(model_breakdown),
            "plan_revenue_usd": plan_revenue_usd,
            "infra_cost_usd": infra_cost_usd,
            "gross_margin_pct": round(gross_margin, 2)
            if gross_margin is not None
            else None,
        },
    )
    await db.commit()

    logger.info(
        "cost_summary_job_tenant_processed",
        tenant_id=tenant_id,
        target_date=str(target_date),
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        total_cost_usd=round(total_cost_usd, 6),
        model_count=len(model_breakdown),
        gross_margin_pct=round(gross_margin, 2) if gross_margin is not None else None,
    )


# ---------------------------------------------------------------------------
# Public job entrypoint
# ---------------------------------------------------------------------------


async def run_cost_summary_job() -> None:
    """
    Execute one full cost summary run across all active tenants.

    Aggregates usage_events from the previous calendar day (yesterday UTC)
    for every active tenant and upserts into cost_summary_daily.

    Per-tenant errors are isolated: an exception for one tenant never stops
    processing of others. Never raises — all top-level exceptions are logged.
    """
    job_start = time.monotonic()
    # Target the previous day so the day is fully closed.
    target_date = date.today() - timedelta(days=1)
    processed = 0
    errors = 0

    try:
        async with async_session_factory() as db:
            # RLS bypass: tenants table requires platform scope and user_role.
            await db.execute(text("SET LOCAL app.current_scope = 'platform'"))
            await db.execute(text("SET LOCAL app.user_role = 'platform_admin'"))
            result = await db.execute(
                text("SELECT id FROM tenants WHERE status = 'active'")
            )
            tenant_rows = result.fetchall()
    except Exception as exc:
        logger.error(
            "cost_summary_job_tenant_fetch_failed",
            error=str(exc),
        )
        return

    tenant_ids = [str(row[0]) for row in tenant_rows]

    if not tenant_ids:
        logger.info("cost_summary_job_no_active_tenants")
        return

    for tenant_id in tenant_ids:
        try:
            async with async_session_factory() as db:
                await _process_tenant(tenant_id, target_date, db)
            processed += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "cost_summary_job_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

    duration_ms = round((time.monotonic() - job_start) * 1000, 1)

    logger.info(
        "cost_summary_job_complete",
        target_date=str(target_date),
        total_tenants=len(tenant_ids),
        processed=processed,
        errors=errors,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Scheduler (daily at 03:30 UTC)
# ---------------------------------------------------------------------------


def _seconds_until_next_run() -> float:
    """
    Calculate seconds until the next 03:30 UTC trigger.

    Returns at least 60s (minimum jitter guard) to avoid double-fires
    if the clock is very close to 03:30 UTC at startup.
    """
    now = datetime.now(timezone.utc)
    next_run = now.replace(
        hour=_SCHEDULE_HOUR_UTC,
        minute=_SCHEDULE_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    if next_run <= now:
        next_run = now.replace(
            hour=_SCHEDULE_HOUR_UTC,
            minute=_SCHEDULE_MINUTE_UTC,
            second=0,
            microsecond=0,
        ) + timedelta(days=1)

    delta = (next_run - now).total_seconds()
    return max(delta, 60.0)


async def start_cost_summary_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_cost_summary_job() daily at 03:30 UTC.

    Designed to be launched as an asyncio background task via asyncio.create_task()
    in app/main.py lifespan. Exits gracefully on CancelledError.
    """
    logger.info(
        "cost_summary_scheduler_started",
        schedule="daily at 03:30 UTC",
    )

    while True:
        try:
            sleep_secs = _seconds_until_next_run()
            logger.debug(
                "cost_summary_next_run_in",
                seconds=round(sleep_secs, 0),
            )
            await asyncio.sleep(sleep_secs)
            await run_cost_summary_job()
        except asyncio.CancelledError:
            logger.info("cost_summary_scheduler_cancelled")
            return
        except Exception as exc:
            # Never crash the scheduler loop — log and retry on next cycle.
            logger.error(
                "cost_summary_scheduler_loop_error",
                error=str(exc),
            )
