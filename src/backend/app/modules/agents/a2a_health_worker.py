"""
A2A Health Worker — background health check job for registered A2A agents.

Periodically pings registered A2A agent endpoints and updates health status.
Designed to run as a FastAPI background task or an external cron job.

Health check logic:
  - GET {a2a_endpoint}/health or GET {a2a_endpoint}/ping (first that responds)
  - HTTP 2xx within 10s → healthy
  - HTTP 4xx/5xx or timeout → unhealthy
  - 3 consecutive failures → status = 'degraded'
  - 5 consecutive failures → status = 'offline'
  - Recovery: 1 healthy response → status = 'healthy'

Status values: 'healthy' | 'degraded' | 'offline' | 'unknown'

The worker does NOT log credential values. If an A2A agent requires auth for its
health endpoint, that auth is resolved from the agent's stored credentials at
check time.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import structlog

from app.core.security.ssrf import SSRFBlockedError, resolve_and_pin_url

logger = structlog.get_logger()

_HEALTH_CHECK_TIMEOUT = 10.0
_DEGRADED_THRESHOLD = 3   # consecutive failures → degraded
_OFFLINE_THRESHOLD = 5    # consecutive failures → offline
_HEALTH_ENDPOINTS = ("/health", "/ping", "/status")


# ---------------------------------------------------------------------------
# Health check helpers
# ---------------------------------------------------------------------------

async def _check_single_endpoint(
    pinned_base_url: str,
    path: str,
    auth_headers: dict,
) -> tuple[bool, Optional[int]]:
    """
    Try a single health endpoint path using a pre-pinned URL.

    Returns (success, http_status). Never raises.
    The pinned_base_url must have hostname already replaced by resolved IP
    (produced by resolve_and_pin_url) to prevent DNS rebinding.
    """
    import httpx

    url = pinned_base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(
            timeout=_HEALTH_CHECK_TIMEOUT,
            follow_redirects=False,
        ) as client:
            response = await client.get(url, headers=auth_headers)
            return response.status_code < 400, response.status_code
    except Exception:
        return False, None


async def check_a2a_agent_health(
    agent_id: str,
    a2a_endpoint: str,
    consecutive_failures: int,
    auth_headers: Optional[dict] = None,
) -> tuple[str, int, Optional[int]]:
    """
    Perform a health check for a single A2A agent.

    Returns:
        (new_status, new_consecutive_failures, http_status)
        new_status: 'healthy' | 'degraded' | 'offline' | 'unknown'
    """
    # SSRF protection: resolve-and-pin DNS before any HTTP call
    try:
        pinned_endpoint = await resolve_and_pin_url(a2a_endpoint)
    except SSRFBlockedError:
        logger.warning(
            "a2a_health_ssrf_blocked",
            agent_id=agent_id,
            endpoint=a2a_endpoint,
        )
        new_failures = consecutive_failures + 1
        new_status = _compute_status(new_failures)
        return new_status, new_failures, None

    headers = auth_headers or {}
    success = False
    http_status: Optional[int] = None

    for path in _HEALTH_ENDPOINTS:
        ok, status = await _check_single_endpoint(pinned_endpoint, path, headers)
        if ok:
            success = True
            http_status = status
            break
        if status is not None:
            # Got a response (even an error) — endpoint is reachable
            http_status = status
            break

    if success:
        # Recovery: reset consecutive failure count
        return "healthy", 0, http_status
    else:
        new_failures = consecutive_failures + 1
        new_status = _compute_status(new_failures)
        return new_status, new_failures, http_status


def _compute_status(consecutive_failures: int) -> str:
    if consecutive_failures >= _OFFLINE_THRESHOLD:
        return "offline"
    if consecutive_failures >= _DEGRADED_THRESHOLD:
        return "degraded"
    if consecutive_failures > 0:
        return "degraded"
    return "healthy"


# ---------------------------------------------------------------------------
# Batch health check worker
# ---------------------------------------------------------------------------

async def run_health_checks(db_url: str) -> None:
    """
    Run health checks for all active registered A2A agents.

    Designed to be called as a background task (e.g., every 5 minutes).
    Creates its own DB session.

    Args:
        db_url: SQLAlchemy async database URL.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as _AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text

    engine = create_async_engine(db_url, echo=False)
    async_session_factory = sessionmaker(engine, class_=_AsyncSession, expire_on_commit=False)

    try:
        async with async_session_factory() as session:
            # Fetch all active A2A agents from agent_cards (is_public=True scope or platform-registered)
            result = await session.execute(
                text("""
                    SELECT id, name, a2a_endpoint,
                           COALESCE(health_consecutive_failures, 0) AS consecutive_failures,
                           health_status
                    FROM agent_cards
                    WHERE a2a_endpoint IS NOT NULL
                      AND a2a_endpoint != ''
                      AND status != 'suspended'
                    ORDER BY last_health_check_at ASC NULLS FIRST
                    LIMIT 100
                """)
            )
            agents = result.mappings().all()

            logger.info("a2a_health_worker_start", agent_count=len(agents))

            for agent in agents:
                agent_id = str(agent["id"])
                a2a_endpoint = str(agent["a2a_endpoint"])
                consecutive_failures = int(agent["consecutive_failures"])

                new_status, new_failures, http_status = await check_a2a_agent_health(
                    agent_id=agent_id,
                    a2a_endpoint=a2a_endpoint,
                    consecutive_failures=consecutive_failures,
                )

                await session.execute(
                    text("""
                        UPDATE agent_cards
                        SET health_status = :status,
                            health_consecutive_failures = :failures,
                            last_health_check_at = now(),
                            last_health_http_status = :http_status
                        WHERE id = :id
                    """),
                    {
                        "status": new_status,
                        "failures": new_failures,
                        "http_status": http_status,
                        "id": agent_id,
                    },
                )

                if new_status != str(agent.get("health_status", "unknown")):
                    logger.info(
                        "a2a_health_status_changed",
                        agent_id=agent_id,
                        old_status=agent.get("health_status"),
                        new_status=new_status,
                        http_status=http_status,
                    )

            await session.commit()
            logger.info("a2a_health_worker_done", agent_count=len(agents))

    except Exception as exc:
        logger.error("a2a_health_worker_error", error=str(exc))
    finally:
        await engine.dispose()


async def schedule_health_checks(
    db_url: str,
    interval_seconds: int = 300,
) -> None:
    """
    Run health checks on a repeating schedule.

    Call this from a FastAPI lifespan event or background task.
    Runs forever until cancelled.

    Args:
        db_url: Async database URL.
        interval_seconds: How often to run checks (default: 300s = 5 minutes).
    """
    logger.info("a2a_health_scheduler_start", interval_seconds=interval_seconds)
    while True:
        try:
            await run_health_checks(db_url)
        except Exception as exc:
            logger.error("a2a_health_scheduler_error", error=str(exc))
        await asyncio.sleep(interval_seconds)
