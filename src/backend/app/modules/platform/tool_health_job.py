"""
PA-032: Continuous tool health monitoring job.

Pings each tool's health_check_url every 5 minutes (with ±30s jitter) using a
HEAD request. Tracks consecutive failures per tool in an in-process dict;
updates tool_catalog.health_status and last_health_check on state transitions:

  healthy    → 0 consecutive failures (reset on any success)
  degraded   → 3 consecutive failures (no issue created)
  unavailable → 10 consecutive failures → creates P1 issue in issue_reports
  unavailable → healthy → auto-closes the open P1 issue

This module provides:
  - run_tool_health_job(db) — one-shot check of all tools (called by scheduler)
  - start_tool_health_scheduler(app) — launches APScheduler job on app startup

State is held in _failure_counts: Dict[tool_id, int].  Since this is a single
process, in-memory counters survive individual check cycles but are reset on
restart (acceptable — persistent counters would require a new DB column).
"""
import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ── Thresholds ────────────────────────────────────────────────────────────────
_DEGRADED_THRESHOLD = 3
_UNAVAILABLE_THRESHOLD = 10
_HEALTH_CHECK_TIMEOUT = 10  # seconds
_CHECK_INTERVAL_SECONDS = 300  # 5 minutes
_JITTER_SECONDS = 30

# In-process failure counter: tool_id → consecutive failure count.
_failure_counts: Dict[str, int] = {}

# ── Queries ───────────────────────────────────────────────────────────────────

_LIST_TOOLS_FOR_HEALTH = text(
    """
    SELECT id, name, health_status, health_check_url
    FROM tool_catalog
    WHERE health_check_url IS NOT NULL
    """
)

_UPDATE_TOOL_STATUS = text(
    """
    UPDATE tool_catalog
    SET health_status = :health_status,
        last_health_check = NOW()
    WHERE id = :tool_id
    """
)

_OPEN_P1_ISSUE_QUERY = text(
    """
    SELECT id FROM issue_reports
    WHERE issue_type = 'tool_health'
      AND status NOT IN ('resolved', 'closed')
      AND metadata->>'tool_id' = :tool_id
    ORDER BY created_at DESC
    LIMIT 1
    """
)

_CREATE_P1_ISSUE_QUERY = text(
    """
    INSERT INTO issue_reports
        (id, tenant_id, reporter_id, issue_type, description, severity,
         status, blur_acknowledged, metadata)
    SELECT
        :id, u.tenant_id, u.id, 'tool_health',
        :description, 'critical', 'open', false,
        CAST(:metadata AS jsonb)
    FROM users u
    WHERE u.role = 'platform_admin'
    LIMIT 1
    """
)

_CLOSE_P1_ISSUE_QUERY = text(
    """
    UPDATE issue_reports
    SET status = 'resolved', updated_at = NOW()
    WHERE id = :issue_id
    """
)

_AUDIT_LOG_QUERY = text(
    """
    INSERT INTO audit_log (actor_type, actor_id, action, resource_type,
                           resource_id, details, created_at)
    SELECT 'system', u.id, :action, 'tool_catalog', :tool_id,
           CAST(:details AS jsonb), NOW()
    FROM users u WHERE u.role = 'platform_admin' LIMIT 1
    """
)


# ── Core logic ────────────────────────────────────────────────────────────────


async def _ping_tool(health_check_url: str) -> bool:
    """Return True if HEAD request to health_check_url succeeds (2xx/3xx)."""
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_CHECK_TIMEOUT) as client:
            resp = await client.head(health_check_url)
            return resp.status_code < 500
    except Exception:
        return False


async def _handle_tool_result(
    db: AsyncSession,
    tool_id: str,
    tool_name: str,
    current_status: str,
    is_healthy: bool,
) -> Optional[str]:
    """
    Update failure counter and tool status based on latest ping result.
    Returns the new status string if it changed, else None.
    """
    import json

    new_status: Optional[str] = None

    if is_healthy:
        prev_failures = _failure_counts.get(tool_id, 0)
        _failure_counts[tool_id] = 0

        if current_status != "healthy":
            new_status = "healthy"
            await db.execute(
                _UPDATE_TOOL_STATUS, {"health_status": "healthy", "tool_id": tool_id}
            )
            # Auto-close open P1 issue if exists.
            issue_result = await db.execute(_OPEN_P1_ISSUE_QUERY, {"tool_id": tool_id})
            issue_row = issue_result.fetchone()
            if issue_row:
                await db.execute(_CLOSE_P1_ISSUE_QUERY, {"issue_id": str(issue_row[0])})
                logger.info(
                    "tool_p1_issue_auto_closed",
                    tool_id=tool_id,
                    tool_name=tool_name,
                )
            await db.execute(
                _AUDIT_LOG_QUERY,
                {
                    "action": "tool_health_recovered",
                    "tool_id": tool_id,
                    "details": json.dumps(
                        {"tool_name": tool_name, "prev_failures": prev_failures}
                    ),
                },
            )
    else:
        count = _failure_counts.get(tool_id, 0) + 1
        _failure_counts[tool_id] = count

        if count == _DEGRADED_THRESHOLD and current_status == "healthy":
            new_status = "degraded"
            await db.execute(
                _UPDATE_TOOL_STATUS,
                {"health_status": "degraded", "tool_id": tool_id},
            )
            await db.execute(
                _AUDIT_LOG_QUERY,
                {
                    "action": "tool_health_degraded",
                    "tool_id": tool_id,
                    "details": json.dumps(
                        {"tool_name": tool_name, "consecutive_failures": count}
                    ),
                },
            )
            logger.warning(
                "tool_health_degraded",
                tool_id=tool_id,
                tool_name=tool_name,
                consecutive_failures=count,
            )
        elif count == _UNAVAILABLE_THRESHOLD and current_status != "unavailable":
            new_status = "unavailable"
            await db.execute(
                _UPDATE_TOOL_STATUS,
                {"health_status": "unavailable", "tool_id": tool_id},
            )
            # Create P1 issue (only if none open already).
            existing = await db.execute(_OPEN_P1_ISSUE_QUERY, {"tool_id": tool_id})
            if not existing.fetchone():
                import uuid

                description = (
                    f"Tool '{tool_name}' (id: {tool_id}) is unavailable — "
                    f"{count} consecutive health check failures."
                )
                await db.execute(
                    _CREATE_P1_ISSUE_QUERY,
                    {
                        "id": str(uuid.uuid4()),
                        "description": description,
                        "metadata": json.dumps(
                            {
                                "source": "tool_health_monitor",
                                "tool_id": tool_id,
                                "tool_name": tool_name,
                                "consecutive_failures": count,
                            }
                        ),
                    },
                )
                logger.error(
                    "tool_unavailable_p1_opened",
                    tool_id=tool_id,
                    tool_name=tool_name,
                    consecutive_failures=count,
                )
            await db.execute(
                _AUDIT_LOG_QUERY,
                {
                    "action": "tool_health_unavailable",
                    "tool_id": tool_id,
                    "details": json.dumps(
                        {"tool_name": tool_name, "consecutive_failures": count}
                    ),
                },
            )

    return new_status


async def run_tool_health_job(db: AsyncSession) -> dict:
    """
    One-shot health check for all tools with a health_check_url.

    Pings each tool via HEAD request, updates status and failure counts,
    manages P1 issues on state transitions.

    Returns summary: {checked, degraded, unavailable, recovered, errors}

    Does NOT commit — caller is responsible for commit.
    """
    await db.execute(text("SELECT set_config('app.scope', 'platform', true)"))
    await db.execute(text("SELECT set_config('app.tenant_id', '', true)"))

    rows_result = await db.execute(_LIST_TOOLS_FOR_HEALTH)
    tools = rows_result.fetchall()

    checked = 0
    degraded_count = 0
    unavailable_count = 0
    recovered_count = 0
    errors = 0

    for tool in tools:
        tool_id = str(tool[0])
        tool_name = tool[1]
        current_status = tool[2]
        health_check_url = tool[3]

        try:
            is_healthy = await _ping_tool(health_check_url)
            new_status = await _handle_tool_result(
                db, tool_id, tool_name, current_status, is_healthy
            )
            checked += 1
            if new_status == "degraded":
                degraded_count += 1
            elif new_status == "unavailable":
                unavailable_count += 1
            elif new_status == "healthy" and current_status != "healthy":
                recovered_count += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "tool_health_check_error",
                tool_id=tool_id,
                tool_name=tool_name,
                error=str(exc),
            )

    return {
        "checked": checked,
        "degraded": degraded_count,
        "unavailable": unavailable_count,
        "recovered": recovered_count,
        "errors": errors,
    }


# ── APScheduler integration ───────────────────────────────────────────────────


def start_tool_health_scheduler(app) -> None:
    """
    Register the tool health monitoring job with APScheduler.

    Called from app lifespan on startup. Schedules run_tool_health_job every
    5 minutes with ±30s jitter to prevent thundering herd across tools.
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        from app.core.session import AsyncSessionLocal

        scheduler = AsyncIOScheduler()

        async def _job_wrapper():
            jitter = random.randint(-_JITTER_SECONDS, _JITTER_SECONDS)
            await asyncio.sleep(max(0, jitter))
            async with AsyncSessionLocal() as db:
                try:
                    summary = await run_tool_health_job(db)
                    await db.commit()
                    logger.info("tool_health_job_complete", **summary)
                except Exception as exc:
                    await db.rollback()
                    logger.error("tool_health_job_failed", error=str(exc))

        scheduler.add_job(
            _job_wrapper,
            trigger=IntervalTrigger(seconds=_CHECK_INTERVAL_SECONDS),
            id="tool_health_monitor",
            replace_existing=True,
            misfire_grace_time=60,
        )
        scheduler.start()
        logger.info(
            "tool_health_scheduler_started",
            interval_seconds=_CHECK_INTERVAL_SECONDS,
            jitter_seconds=_JITTER_SECONDS,
        )

        # Store reference to allow graceful shutdown.
        if hasattr(app, "state"):
            app.state.tool_health_scheduler = scheduler

    except ImportError:
        logger.warning(
            "tool_health_scheduler_skipped",
            reason="apscheduler not installed — tool health monitoring disabled",
        )
    except Exception as exc:
        logger.error("tool_health_scheduler_start_failed", error=str(exc))
