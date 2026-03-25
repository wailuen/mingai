"""
PA-032 / SCHED-008: Continuous tool health monitoring job.

Pings each tool's health_check_url every 5 minutes (with ±30s jitter) using a
HEAD request.  Tracks consecutive failures per tool in Redis (7-day TTL) so
counters survive pod restarts and multi-instance deployments.

State transitions:
  healthy    → 0 consecutive failures (reset on any success)
  degraded   → >= 3 consecutive failures (no issue created)
  unavailable → >= 10 consecutive failures → creates P1 issue in issue_reports
  unavailable → healthy → auto-closes the open P1 issue

Pre-existing bugs fixed (SCHED-008):
  H-01: threshold check was `== threshold` (could skip exact value under
        concurrent INCR). Fixed to `>= threshold`.
  H-02: _failure_counts was an in-process dict; lost on restart.  Migrated to
        Redis with atomic Lua INCR + 7-day TTL.
  H-06: P1 issue was inserted with non-deterministic tenant via `LIMIT 1`
        with no ORDER BY.  Fixed to platform-scope insert with ORDER BY created_at.
  H-07: start_tool_health_scheduler() was never called in main.py.  Fixed by
        replacing with run_tool_health_scheduler() which is wired in lifespan.

Public API:
  run_tool_health_job()      — one-shot check (called by scheduler + tests)
  run_tool_health_scheduler() — asyncio loop, called from app lifespan
"""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduler import DistributedJobLock, job_run_context

logger = structlog.get_logger()

# ── Thresholds ────────────────────────────────────────────────────────────────
_DEGRADED_THRESHOLD = 3
_UNAVAILABLE_THRESHOLD = 10
_HEALTH_CHECK_TIMEOUT = 10      # seconds
_CHECK_INTERVAL_SECONDS = 300   # 5 minutes
_LOCK_TTL_SECONDS = 400         # > interval + max jitter (300 + 30 + 70 headroom)
_JITTER_SECONDS = 30
_COUNTER_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# Redis key prefix for failure counters
_COUNTER_KEY_PREFIX = "mingai:scheduler:tool_failures:"

# Lua script: INCR key and set TTL if key is new (atomic).
# Returns new counter value.
_LUA_INCR_TTL = """
local val = redis.call('INCR', KEYS[1])
if val == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return val
"""

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

_INSERT_HEALTH_CHECK = text(
    """
    INSERT INTO tool_health_checks (tool_id, checked_at, status, latency_ms, error_msg)
    VALUES (:tool_id, NOW(), :status, :latency_ms, :error_msg)
    """
)

_CLEANUP_OLD_HEALTH_CHECKS = text(
    "DELETE FROM tool_health_checks WHERE checked_at < NOW() - INTERVAL '30 days'"
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

# H-06 fix: platform-scope insert — tenant_id = NULL (platform-level issue,
# not tenant-specific) + deterministic reporter via ORDER BY created_at ASC.
_CREATE_P1_ISSUE_QUERY = text(
    """
    INSERT INTO issue_reports
        (id, tenant_id, reporter_id, issue_type, description, severity,
         status, blur_acknowledged, metadata)
    SELECT
        :id, NULL, u.id, 'tool_health',
        :description, 'critical', 'open', false,
        CAST(:metadata AS jsonb)
    FROM users u
    WHERE u.role = 'platform_admin'
    ORDER BY u.created_at ASC
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
    FROM users u WHERE u.role = 'platform_admin'
    ORDER BY u.created_at ASC
    LIMIT 1
    """
)


# ── Redis counter helpers ─────────────────────────────────────────────────────


async def _get_failure_count(tool_id: str) -> int:
    """Read the current consecutive failure count for a tool from Redis."""
    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        val = await redis.get(f"{_COUNTER_KEY_PREFIX}{tool_id}")
        return int(val) if val else 0
    except Exception as exc:
        logger.warning("tool_health_counter_read_error", tool_id=tool_id, error=str(exc))
        return 0


async def _incr_failure_count(tool_id: str) -> int:
    """Atomically increment the failure counter and set TTL on first write.
    Returns the new counter value."""
    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        script = redis.register_script(_LUA_INCR_TTL)
        val = await script(
            keys=[f"{_COUNTER_KEY_PREFIX}{tool_id}"],
            args=[str(_COUNTER_TTL_SECONDS)],
        )
        return int(val)
    except Exception as exc:
        logger.warning("tool_health_counter_incr_error", tool_id=tool_id, error=str(exc))
        return 0


async def _reset_failure_count(tool_id: str) -> None:
    """Reset (delete) the failure counter for a tool in Redis."""
    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
        await redis.delete(f"{_COUNTER_KEY_PREFIX}{tool_id}")
    except Exception as exc:
        logger.warning(
            "tool_health_counter_reset_error", tool_id=tool_id, error=str(exc)
        )


# ── Core logic ────────────────────────────────────────────────────────────────


async def _ping_tool(health_check_url: str) -> tuple[bool, Optional[int], Optional[str]]:
    """Return (is_healthy, latency_ms, error_msg) for the HEAD request.

    latency_ms is None on exception.  error_msg is None on success.
    """
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_CHECK_TIMEOUT) as client:
            resp = await client.head(health_check_url)
            latency_ms = int(resp.elapsed.total_seconds() * 1000) if resp.elapsed else None
            is_healthy = resp.status_code < 500
            error_msg = None if is_healthy else f"HTTP {resp.status_code}"
            return is_healthy, latency_ms, error_msg
    except Exception as exc:
        return False, None, str(exc)[:500]


async def _handle_tool_result(
    db: AsyncSession,
    tool_id: str,
    tool_name: str,
    current_status: str,
    is_healthy: bool,
    latency_ms: Optional[int] = None,
    error_msg: Optional[str] = None,
) -> Optional[str]:
    """
    Update failure counter and tool status based on latest ping result.
    Inserts a row into tool_health_checks for every invocation.
    Returns the new status string if it changed, else None.
    """
    new_status: Optional[str] = None

    if is_healthy:
        prev_failures = await _get_failure_count(tool_id)
        await _reset_failure_count(tool_id)

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
        # H-02 fix: Redis counter instead of in-process dict.
        count = await _incr_failure_count(tool_id)

        # H-01 fix: >= threshold instead of == to handle concurrent INCR.
        # Unavailable is checked first: if a tool crosses both thresholds in a
        # single observation cycle (e.g. 10 failures since last run), the higher
        # severity wins without also writing a transient 'degraded' row.
        if count >= _UNAVAILABLE_THRESHOLD and current_status != "unavailable":
            new_status = "unavailable"
            await db.execute(
                _UPDATE_TOOL_STATUS,
                {"health_status": "unavailable", "tool_id": tool_id},
            )
            # Create P1 issue (only if none open already).
            existing = await db.execute(_OPEN_P1_ISSUE_QUERY, {"tool_id": tool_id})
            if not existing.fetchone():
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
        elif count >= _DEGRADED_THRESHOLD and current_status == "healthy":
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

    # Persist a time-series row for this check regardless of whether status changed.
    # Determine the observed status at this point in time.
    if is_healthy:
        observed_status = "healthy"
    elif new_status is not None:
        observed_status = new_status
    else:
        observed_status = current_status if current_status in ("degraded", "unavailable") else "degraded"

    try:
        await db.execute(
            _INSERT_HEALTH_CHECK,
            {
                "tool_id": tool_id,
                "status": observed_status,
                "latency_ms": latency_ms,
                "error_msg": error_msg,
            },
        )
    except Exception as exc:
        # tool_health_checks may not exist yet (migration pending) — log and continue.
        logger.warning(
            "tool_health_check_insert_failed",
            tool_id=tool_id,
            error=str(exc),
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
            is_healthy, latency_ms, ping_error = await _ping_tool(health_check_url)
            new_status = await _handle_tool_result(
                db, tool_id, tool_name, current_status, is_healthy,
                latency_ms=latency_ms, error_msg=ping_error,
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

    # Prune check history older than 30 days to keep the table bounded.
    try:
        await db.execute(_CLEANUP_OLD_HEALTH_CHECKS)
    except Exception as exc:
        logger.warning("tool_health_checks_cleanup_failed", error=str(exc))

    return {
        "checked": checked,
        "degraded": degraded_count,
        "unavailable": unavailable_count,
        "recovered": recovered_count,
        "errors": errors,
    }


# ── Asyncio scheduler loop (replaces APScheduler) ────────────────────────────


async def run_tool_health_scheduler() -> None:
    """
    Asyncio-native scheduler loop for tool health checks.

    Runs every _CHECK_INTERVAL_SECONDS with ±30s jitter.
    Uses DistributedJobLock to ensure only one pod executes per cycle.

    Replaces start_tool_health_scheduler() / APScheduler integration.
    Called from app lifespan via asyncio.create_task().  Wires H-07 fix.
    """
    logger.info(
        "tool_health_scheduler_loop_started",
        interval_seconds=_CHECK_INTERVAL_SECONDS,
    )
    while True:
        try:
            # Dynamic TTL: worst-case runtime is proportional to number of tools.
            # TTL = max(600, tool_count × 15) — 15s buffer per tool beyond 10s timeout.
            # Heartbeat in DistributedJobLock renews the lock if job runs past initial TTL.
            dynamic_ttl = _LOCK_TTL_SECONDS
            try:
                from app.core.session import async_session_factory

                async with async_session_factory() as _db:
                    from sqlalchemy import text as _text

                    await _db.execute(_text("SELECT set_config('app.scope', 'platform', true)"))
                    _count_result = await _db.execute(
                        _text(
                            "SELECT COUNT(*) FROM tool_catalog WHERE health_check_url IS NOT NULL"
                        )
                    )
                    _tool_count = _count_result.scalar() or 0
                    dynamic_ttl = max(600, int(_tool_count) * 15)
            except Exception as _ttl_exc:
                logger.warning("tool_health_ttl_query_failed", error=str(_ttl_exc))

            async with DistributedJobLock(
                "tool_health", ttl=dynamic_ttl
            ) as acquired:
                if acquired:
                    jitter = random.randint(-_JITTER_SECONDS, _JITTER_SECONDS)
                    await asyncio.sleep(max(0, jitter))

                    from app.core.session import async_session_factory

                    async with async_session_factory() as db:
                        try:
                            async with job_run_context("tool_health") as ctx:
                                summary = await run_tool_health_job(db)
                                await db.commit()
                                ctx.records_processed = summary.get("checked", 0)
                            logger.info("tool_health_job_complete", **summary)
                        except Exception as exc:
                            await db.rollback()
                            logger.error("tool_health_job_failed", error=str(exc))
                else:
                    logger.debug(
                        "tool_health_job_skipped",
                        reason="lock_held_by_another_pod",
                    )

            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            logger.info("tool_health_scheduler_loop_stopped")
            raise
        except Exception as exc:
            logger.error(
                "tool_health_scheduler_loop_error",
                error=str(exc),
            )
            await asyncio.sleep(30)
