"""
PA-015: Nightly cost alert evaluation job.

Scheduled daily at 04:00 UTC (30 minutes after the cost summary job at 03:30 UTC).
For each active tenant:
  1. Reads yesterday's cost_summary_daily row.
  2. Resolves alert thresholds: per-tenant config or global default.
  3. If daily_spend > threshold  → creates a P2 issue + notification.
  4. If gross_margin_pct < floor → creates a P2 issue + notification.
  5. Duplicate suppression: skips if an issue with the same (tenant_id, title, date)
     already exists in issue_reports.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context, seconds_until_utc
from app.core.session import async_session_factory

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Issue titles used for duplicate suppression (exact string match)
# ---------------------------------------------------------------------------

_TITLE_SPEND = "Daily spend threshold exceeded"
_TITLE_MARGIN = "Gross margin below floor"


# ---------------------------------------------------------------------------
# Per-tenant helpers (DB queries)
# ---------------------------------------------------------------------------


async def _get_cost_summary(
    tenant_id: str, target_date: date, db: Any
) -> Optional[dict]:
    """Fetch the cost_summary_daily row for (tenant_id, target_date)."""
    result = await db.execute(
        text(
            "SELECT total_cost_usd, gross_margin_pct "
            "FROM cost_summary_daily "
            "WHERE tenant_id = :tid AND date = :date"
        ),
        {"tid": tenant_id, "date": target_date},
    )
    row = result.fetchone()
    if row is None:
        return None
    return {
        "total_cost_usd": float(row[0]) if row[0] is not None else 0.0,
        "gross_margin_pct": float(row[1]) if row[1] is not None else None,
    }


async def _get_alert_config(tenant_id: str, db: Any) -> dict:
    """
    Resolve alert thresholds for a tenant.

    Priority: per-tenant config → global default → no thresholds.
    Returns a dict with keys 'daily_spend_threshold_usd' and 'margin_floor_pct'
    (both may be None if not configured).
    """
    result = await db.execute(
        text(
            "SELECT daily_spend_threshold_usd, margin_floor_pct "
            "FROM cost_alert_configs "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    if row is not None:
        return {
            "daily_spend_threshold_usd": float(row[0]) if row[0] is not None else None,
            "margin_floor_pct": float(row[1]) if row[1] is not None else None,
        }

    # Fall back to global default (tenant_id IS NULL)
    result = await db.execute(
        text(
            "SELECT daily_spend_threshold_usd, margin_floor_pct "
            "FROM cost_alert_configs "
            "WHERE tenant_id IS NULL"
        ),
    )
    row = result.fetchone()
    if row is not None:
        return {
            "daily_spend_threshold_usd": float(row[0]) if row[0] is not None else None,
            "margin_floor_pct": float(row[1]) if row[1] is not None else None,
        }

    return {"daily_spend_threshold_usd": None, "margin_floor_pct": None}


async def _issue_already_exists(
    tenant_id: str,
    title: str,
    target_date: date,
    db: Any,
) -> bool:
    """
    Duplicate suppression check.

    Returns True if an issue_reports row with:
      - tenant_id = tenant_id
      - metadata->>'title' = title
      - DATE(created_at) = target_date

    already exists (prevents re-alerting for the same day on re-runs).
    """
    result = await db.execute(
        text(
            "SELECT 1 FROM issue_reports "
            "WHERE tenant_id = :tid "
            "  AND metadata->>'title' = :title "
            "  AND DATE(created_at) = :date "
            "LIMIT 1"
        ),
        {"tid": tenant_id, "title": title, "date": target_date},
    )
    return result.fetchone() is not None


async def _get_tenant_name(tenant_id: str, db: Any) -> str:
    """Fetch tenant name; returns fallback string on miss."""
    result = await db.execute(
        text("SELECT name FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    return row[0] if row else tenant_id


async def _create_alert_issue(
    tenant_id: str,
    title: str,
    description: str,
    db: Any,
) -> None:
    """
    Insert a P2 cost_alert issue into issue_reports.

    The job acts as the system reporter so reporter_id uses the system sentinel
    UUID (all-zeros).  The issue type is 'cost_alert'; severity is 'P2'.
    """
    _SYSTEM_REPORTER_ID = "00000000-0000-0000-0000-000000000001"
    issue_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO issue_reports "
            "(id, tenant_id, reporter_id, issue_type, severity, status, "
            "description, blur_acknowledged, metadata) "
            "VALUES (:id, :tenant_id, :reporter_id, 'cost_alert', 'P2', 'open', "
            ":description, false, CAST(:metadata AS jsonb))"
        ),
        {
            "id": issue_id,
            "tenant_id": tenant_id,
            "reporter_id": _SYSTEM_REPORTER_ID,
            "description": description,
            "metadata": json.dumps({"title": title, "source": "cost_alert_job"}),
        },
    )


async def _create_alert_notification(
    tenant_id: str,
    title: str,
    body: str,
    db: Any,
) -> None:
    """
    Insert a notification for all tenant_admin users of this tenant.

    Notifies every active tenant_admin so the alert is visible in-app.
    """
    result = await db.execute(
        text(
            "SELECT id FROM users "
            "WHERE tenant_id = :tid AND role = 'tenant_admin' AND status = 'active'"
        ),
        {"tid": tenant_id},
    )
    admin_rows = result.fetchall()
    for row in admin_rows:
        user_id = str(row[0])
        await db.execute(
            text(
                "INSERT INTO notifications "
                "(id, tenant_id, user_id, type, title, body, read) "
                "VALUES (:id, :tenant_id, :user_id, 'cost_alert', :title, :body, false)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "title": title,
                "body": body,
            },
        )


# ---------------------------------------------------------------------------
# Per-tenant evaluation logic
# ---------------------------------------------------------------------------


async def _evaluate_tenant(tenant_id: str, target_date: date, db: Any) -> None:
    """
    Evaluate cost alerts for one tenant for target_date.

    Sets platform RLS context before any queries.
    Issues are only created when they do not already exist for this date.
    """
    await db.execute(text("SET LOCAL app.current_scope = 'platform'"))
    await db.execute(text("SET LOCAL app.user_role = 'platform_admin'"))
    # notifications RLS uses app.tenant_id for row-level filtering.
    await db.execute(
        text("SET LOCAL app.tenant_id = :tid"),
        {"tid": tenant_id},
    )

    # 1. Get yesterday's cost summary
    summary = await _get_cost_summary(tenant_id, target_date, db)
    if summary is None:
        logger.debug(
            "cost_alert_job_no_summary",
            tenant_id=tenant_id,
            target_date=str(target_date),
        )
        return

    # 2. Get resolved alert config
    config = await _get_alert_config(tenant_id, db)
    spend_threshold = config["daily_spend_threshold_usd"]
    margin_floor = config["margin_floor_pct"]

    # If no thresholds configured, nothing to evaluate
    if spend_threshold is None and margin_floor is None:
        return

    tenant_name = await _get_tenant_name(tenant_id, db)
    actual_spend = summary["total_cost_usd"]
    actual_margin = summary["gross_margin_pct"]

    # 3. Check daily spend threshold
    if spend_threshold is not None and actual_spend > spend_threshold:
        title = _TITLE_SPEND
        description = (
            f"Tenant {tenant_name} spent ${actual_spend:.2f} vs "
            f"threshold ${spend_threshold:.2f} on {target_date}"
        )
        already_exists = await _issue_already_exists(tenant_id, title, target_date, db)
        if not already_exists:
            await _create_alert_issue(tenant_id, title, description, db)
            await _create_alert_notification(tenant_id, title, description, db)
            logger.info(
                "cost_alert_job_spend_alert_created",
                tenant_id=tenant_id,
                target_date=str(target_date),
                actual_spend=actual_spend,
                threshold=spend_threshold,
            )
        else:
            logger.debug(
                "cost_alert_job_spend_alert_suppressed",
                tenant_id=tenant_id,
                target_date=str(target_date),
            )

    # 4. Check gross margin floor
    if (
        margin_floor is not None
        and actual_margin is not None
        and actual_margin < margin_floor
    ):
        title = _TITLE_MARGIN
        description = (
            f"Tenant {tenant_name} margin {actual_margin:.1f}% "
            f"below floor {margin_floor:.1f}% on {target_date}"
        )
        already_exists = await _issue_already_exists(tenant_id, title, target_date, db)
        if not already_exists:
            await _create_alert_issue(tenant_id, title, description, db)
            await _create_alert_notification(tenant_id, title, description, db)
            logger.info(
                "cost_alert_job_margin_alert_created",
                tenant_id=tenant_id,
                target_date=str(target_date),
                actual_margin=actual_margin,
                floor=margin_floor,
            )
        else:
            logger.debug(
                "cost_alert_job_margin_alert_suppressed",
                tenant_id=tenant_id,
                target_date=str(target_date),
            )

    await db.commit()


# ---------------------------------------------------------------------------
# Public job entrypoint
# ---------------------------------------------------------------------------


async def run_cost_alert_job() -> None:
    """
    Execute one full cost alert evaluation run across all active tenants.

    Reads yesterday's cost_summary_daily rows and fires P2 issues / notifications
    when spend or margin thresholds are breached.

    Per-tenant errors are isolated — one failed tenant never stops others.
    Never raises — all top-level exceptions are logged.
    """
    job_start = time.monotonic()
    target_date = date.today() - timedelta(days=1)
    processed = 0
    alerts_fired = 0
    errors = 0

    # Fetch active tenants
    try:
        async with async_session_factory() as db:
            await db.execute(text("SET LOCAL app.current_scope = 'platform'"))
            await db.execute(text("SET LOCAL app.user_role = 'platform_admin'"))
            result = await db.execute(
                text("SELECT id FROM tenants WHERE status = 'active'")
            )
            tenant_rows = result.fetchall()
    except Exception as exc:
        logger.error(
            "cost_alert_job_tenant_fetch_failed",
            error=str(exc),
        )
        return

    tenant_ids = [str(row[0]) for row in tenant_rows]

    if not tenant_ids:
        logger.info("cost_alert_job_no_active_tenants")
        return

    for tenant_id in tenant_ids:
        try:
            async with async_session_factory() as db:
                await _evaluate_tenant(tenant_id, target_date, db)
            processed += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "cost_alert_job_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

    duration_ms = round((time.monotonic() - job_start) * 1000, 1)
    logger.info(
        "cost_alert_job_complete",
        target_date=str(target_date),
        total_tenants=len(tenant_ids),
        processed=processed,
        errors=errors,
        duration_ms=duration_ms,
    )

    return processed


# ---------------------------------------------------------------------------
# Scheduler (daily at 04:00 UTC)
# ---------------------------------------------------------------------------


async def start_cost_alert_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_cost_alert_job() daily at 04:00 UTC.

    Designed to be launched as an asyncio background task via asyncio.create_task()
    in app/main.py lifespan. Exits gracefully on CancelledError.
    Never raises.
    """
    logger.info(
        "cost_alert_scheduler_started",
        schedule="daily at 04:00 UTC",
    )

    while True:
        try:
            sleep_secs = seconds_until_utc(4, 0)
            logger.debug(
                "cost_alert_next_run_in",
                seconds=round(sleep_secs, 0),
            )
            await asyncio.sleep(sleep_secs)
            async with DistributedJobLock("cost_alert", ttl=1800) as acquired:
                if not acquired:
                    logger.debug(
                        "cost_alert_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    async with job_run_context("cost_alert") as ctx:
                        processed = await run_cost_alert_job()
                        ctx.records_processed = processed or 0
        except asyncio.CancelledError:
            logger.info("cost_alert_scheduler_cancelled")
            return
        except Exception as exc:
            # Never crash the scheduler loop — log and retry on next cycle.
            logger.error(
                "cost_alert_scheduler_loop_error",
                error=str(exc),
            )
