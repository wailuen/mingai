"""
HAR-004: URL Health Monitor background job.

Periodically checks the health_check_url of all active, public agent cards
via HTTP HEAD request. Tracks consecutive failures in Redis; after 3 failures
updates health_status to 'UNAVAILABLE'. On recovery resets to 'AVAILABLE'.

On status change: creates an in-app notification to the owner tenant admin(s).

Schedule: runs every 5 minutes with ±60s jitter.
Retry logic is per-agent — one agent's failure never aborts others.

Redis key pattern: mingai:{tenant_id}:har_health:{agent_id}:failures
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Optional

import httpx
import structlog

from app.core.redis_client import build_redis_key
from app.core.session import async_session_factory

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_HEALTH_CHECK_TIMEOUT_SECONDS = 5
_MAX_CONSECUTIVE_FAILURES = 3
_HEALTH_STATUS_AVAILABLE = "AVAILABLE"
_HEALTH_STATUS_UNAVAILABLE = "UNAVAILABLE"
_JITTER_SECONDS = 60
_BASE_INTERVAL_SECONDS = 300  # 5 minutes base interval
# TTL for failure counter key: 24 hours (failures reset if no checks run for a day)
_FAILURE_KEY_TTL_SECONDS = 86400


# ---------------------------------------------------------------------------
# Redis key helper
# ---------------------------------------------------------------------------


def _failure_key(tenant_id: str, agent_id: str) -> str:
    """Redis key for consecutive failure count for an agent."""
    return build_redis_key(tenant_id, "har_health", agent_id, "failures")


# ---------------------------------------------------------------------------
# Health check for a single agent
# ---------------------------------------------------------------------------


async def check_agent_health(
    url: str, timeout: float = _HEALTH_CHECK_TIMEOUT_SECONDS
) -> bool:
    """
    Perform an HTTP HEAD request to url.

    Returns True if the response status code < 500, False on any error
    or 5xx status code.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.head(url)
            return response.status_code < 500
    except Exception as exc:
        logger.debug(
            "har_health_check_request_failed",
            url=url,
            error_type=type(exc).__name__,
        )
        return False


# ---------------------------------------------------------------------------
# Failure counter helpers
# ---------------------------------------------------------------------------


async def get_failure_count(tenant_id: str, agent_id: str, redis) -> int:
    """Read consecutive failure count from Redis. Returns 0 if key absent."""
    key = _failure_key(tenant_id, agent_id)
    val = await redis.get(key)
    return int(val) if val else 0


async def increment_failure_count(tenant_id: str, agent_id: str, redis) -> int:
    """Increment and return the consecutive failure count. Sets TTL on first set."""
    key = _failure_key(tenant_id, agent_id)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _FAILURE_KEY_TTL_SECONDS)
    return count


async def reset_failure_count(tenant_id: str, agent_id: str, redis) -> None:
    """Reset the consecutive failure count (agent recovered)."""
    key = _failure_key(tenant_id, agent_id)
    await redis.delete(key)


# ---------------------------------------------------------------------------
# Status update in DB
# ---------------------------------------------------------------------------


async def update_agent_health_status(
    agent_id: str,
    tenant_id: str,
    new_status: str,
    db,
) -> bool:
    """
    Update health_status on agent_cards only if the value actually changed.

    Returns True if the status was changed (for notification triggering).
    """
    from sqlalchemy import text

    # Read current status first to avoid spurious updates
    result = await db.execute(
        text(
            "SELECT health_status FROM agent_cards "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"agent_id": agent_id, "tenant_id": tenant_id},
    )
    row = result.mappings().first()
    if row is None:
        return False

    current = row["health_status"]
    if current == new_status:
        return False

    await db.execute(
        text(
            "UPDATE agent_cards SET health_status = :status, updated_at = NOW() "
            "WHERE id = :agent_id AND tenant_id = :tenant_id"
        ),
        {"status": new_status, "agent_id": agent_id, "tenant_id": tenant_id},
    )
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Notify tenant admin on status change
# ---------------------------------------------------------------------------


async def notify_tenant_admin_health_change(
    agent_id: str,
    agent_name: str,
    tenant_id: str,
    new_status: str,
    db,
) -> None:
    """
    Send in-app notification to all tenant_admin users of the owner tenant.

    Uses publish_notification() for Redis pub/sub + persistent DB insert.
    Failure never propagates — errors are logged only.
    """
    from sqlalchemy import text

    try:
        from app.modules.notifications.publisher import publish_notification

        # Fetch all tenant_admin users for this tenant
        result = await db.execute(
            text(
                "SELECT id FROM users "
                "WHERE tenant_id = :tenant_id AND role = 'tenant_admin' "
                "AND status = 'active'"
            ),
            {"tenant_id": tenant_id},
        )
        admin_rows = result.fetchall()

        if not admin_rows:
            logger.debug(
                "har_health_no_tenant_admins_to_notify",
                tenant_id=tenant_id,
                agent_id=agent_id,
            )
            return

        status_label = (
            "unavailable" if new_status == _HEALTH_STATUS_UNAVAILABLE else "recovered"
        )
        title = f"Agent health alert: {agent_name}"
        body = (
            f"Agent '{agent_name}' is now {status_label}. "
            f"Health status changed to {new_status}."
        )
        link = f"/admin/agents/{agent_id}"

        for row in admin_rows:
            user_id = str(row[0])
            try:
                await publish_notification(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    notification_type="agent_health_change",
                    title=title,
                    body=body,
                    link=link,
                )
            except Exception as exc:
                logger.warning(
                    "har_health_notification_failed",
                    user_id=user_id,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    error_type=type(exc).__name__,
                )
    except Exception as exc:
        logger.error(
            "har_health_notify_admin_failed",
            agent_id=agent_id,
            tenant_id=tenant_id,
            new_status=new_status,
            error_type=type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# Per-agent processing
# ---------------------------------------------------------------------------


async def process_agent_health(
    agent_id: str,
    agent_name: str,
    tenant_id: str,
    health_check_url: str,
    db,
    redis,
) -> None:
    """
    Check one agent's health URL and update state.

    - On success: reset failure counter, set AVAILABLE if changed.
    - On failure: increment counter, set UNAVAILABLE after _MAX_CONSECUTIVE_FAILURES.
    - Sends notification on status change.
    """
    is_healthy = await check_agent_health(health_check_url)

    if is_healthy:
        failure_count = await get_failure_count(tenant_id, agent_id, redis)
        was_unhealthy = failure_count >= _MAX_CONSECUTIVE_FAILURES
        await reset_failure_count(tenant_id, agent_id, redis)
        changed = await update_agent_health_status(
            agent_id, tenant_id, _HEALTH_STATUS_AVAILABLE, db
        )
        if changed:
            logger.info(
                "har_agent_health_recovered",
                agent_id=agent_id,
                tenant_id=tenant_id,
            )
            await notify_tenant_admin_health_change(
                agent_id=agent_id,
                agent_name=agent_name,
                tenant_id=tenant_id,
                new_status=_HEALTH_STATUS_AVAILABLE,
                db=db,
            )
    else:
        count = await increment_failure_count(tenant_id, agent_id, redis)
        logger.debug(
            "har_agent_health_check_failed",
            agent_id=agent_id,
            tenant_id=tenant_id,
            consecutive_failures=count,
        )
        if count >= _MAX_CONSECUTIVE_FAILURES:
            changed = await update_agent_health_status(
                agent_id, tenant_id, _HEALTH_STATUS_UNAVAILABLE, db
            )
            if changed:
                logger.warning(
                    "har_agent_health_unavailable",
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    consecutive_failures=count,
                )
                await notify_tenant_admin_health_change(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    tenant_id=tenant_id,
                    new_status=_HEALTH_STATUS_UNAVAILABLE,
                    db=db,
                )


# ---------------------------------------------------------------------------
# Main job function
# ---------------------------------------------------------------------------


async def run_url_health_monitor() -> None:
    """
    Check health_check_url for all active+public agent cards with a URL set.

    Processes each agent in isolation — one failure never aborts others.
    Never raises — all top-level exceptions are logged.
    """
    from sqlalchemy import text

    job_start = time.monotonic()
    checked = 0
    skipped = 0
    errors = 0

    try:
        from app.core.redis_client import get_redis

        redis = get_redis()
    except Exception as exc:
        logger.error("har_health_monitor_redis_unavailable", error=str(exc))
        return

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                text(
                    "SELECT id, name, tenant_id, health_check_url "
                    "FROM agent_cards "
                    "WHERE is_public = true AND status = 'active' "
                    "AND health_check_url IS NOT NULL"
                )
            )
            agent_rows = result.fetchall()
    except Exception as exc:
        logger.error("har_health_monitor_fetch_failed", error=str(exc))
        return

    if not agent_rows:
        logger.debug("har_health_monitor_no_agents_to_check")
        return

    for row in agent_rows:
        agent_id = str(row[0])
        agent_name = str(row[1])
        tenant_id = str(row[2])
        health_check_url = str(row[3])

        try:
            async with async_session_factory() as db:
                await process_agent_health(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    tenant_id=tenant_id,
                    health_check_url=health_check_url,
                    db=db,
                    redis=redis,
                )
            checked += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "har_health_monitor_agent_failed",
                agent_id=agent_id,
                tenant_id=tenant_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    duration_ms = round((time.monotonic() - job_start) * 1000, 1)
    logger.info(
        "har_health_monitor_complete",
        total=len(agent_rows),
        checked=checked,
        skipped=skipped,
        errors=errors,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Jitter helper
# ---------------------------------------------------------------------------


def _jitter_interval(base_seconds: float = _BASE_INTERVAL_SECONDS) -> float:
    """Apply ±60s jitter to the base interval. Returns interval >= 1s."""
    jitter = random.uniform(-_JITTER_SECONDS, _JITTER_SECONDS)
    return max(1.0, base_seconds + jitter)


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------


async def run_url_health_monitor_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_url_health_monitor() every ~5 minutes.

    Applies ±60s jitter to avoid thundering herd.
    Designed to be launched as asyncio.create_task() in app/main.py lifespan.
    Exits gracefully on CancelledError.
    """
    logger.info(
        "url_health_monitor_scheduler_started",
        schedule="every ~5 minutes with ±60s jitter",
    )

    while True:
        try:
            interval = _jitter_interval()
            logger.debug(
                "url_health_monitor_next_run_in",
                seconds=round(interval, 0),
            )
            await asyncio.sleep(interval)
            await run_url_health_monitor()
        except asyncio.CancelledError:
            logger.info("url_health_monitor_scheduler_cancelled")
            return
        except Exception as exc:
            # Never crash the scheduler loop — log and retry on next cycle
            logger.error(
                "url_health_monitor_scheduler_loop_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
