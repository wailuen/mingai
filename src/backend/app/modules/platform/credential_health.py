"""
ATA-036: Credential health check scheduled job.

Checks that all agent credentials stored in vault are still accessible.
Emits admin notifications for unreachable credentials.

RULE A2A-05: Uses DistributedJobLock with name pattern
f"cred_health:{tenant_id}" and TTL 86000s (just under 24 hours) to prevent
duplicate execution across workers. Without this lock, multiple pods would
each send notifications for the same credential failure, creating alert
storms.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import build_redis_key, get_redis
from app.core.scheduler import DistributedJobLock, seconds_until_utc
from app.core.scheduler.timing import check_missed_job
from app.core.session import async_session_factory

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Per-tenant health check
# ---------------------------------------------------------------------------

_LOCK_TTL_SECONDS = 86000  # just under 24 hours
# Dedup TTL: suppress repeat notifications for the same agent failure for 7 days.
# Prevents notification storms when vault is unreachable for multiple consecutive days.
_NOTIF_DEDUP_TTL_SECONDS = 7 * 24 * 3600  # 7 days


async def run_daily_credential_health_check(
    tenant_id: str,
    db: AsyncSession,
    vault_client: Any,
) -> dict:
    """
    Check that all agent credentials stored in vault are still accessible
    for the given tenant.

    RULE A2A-05: Acquires DistributedJobLock(f"cred_health:{tenant_id}",
    ttl=86000) before any vault operations to prevent duplicate execution
    across workers.

    Args:
        tenant_id:    UUID string of the tenant to check.
        db:           AsyncSession — RLS context is set by the caller.
        vault_client: VaultClient instance (Azure or local-dev).

    Returns:
        Summary dict: {checked: N, unhealthy: N, notifications_sent: N}
    """
    async with DistributedJobLock(
        f"cred_health:{tenant_id}", ttl=_LOCK_TTL_SECONDS
    ) as acquired:
        if not acquired:
            logger.debug(
                "credential_health_check_skipped",
                tenant_id=tenant_id,
                reason="lock_held_by_another_pod",
            )
            return {"checked": 0, "unhealthy": 0, "notifications_sent": 0}

        # RLS bypass: must set platform scope to read all tenant agent_cards
        await db.execute(sa.text("SET LOCAL app.current_scope = 'platform'"))
        await db.execute(sa.text("SET LOCAL app.user_role = 'platform_admin'"))

        result = await db.execute(
            sa.text(
                """
                SELECT id, name, credentials_vault_path
                FROM agent_cards
                WHERE tenant_id = :tenant_id
                  AND credentials_vault_path IS NOT NULL
                ORDER BY id
                """
            ),
            {"tenant_id": tenant_id},
        )
        agents = result.fetchall()

        checked = 0
        unhealthy = 0
        notifications_sent = 0

        for agent in agents:
            checked += 1
            agent_id = str(agent[0])
            agent_name = agent[1]
            vault_path = agent[2]

            try:
                # Attempt to retrieve the secret — if it raises, the path is
                # unreachable or expired.  Use asyncio.to_thread() because
                # VaultClient.get_secret() is synchronous (network I/O) and
                # would block the event loop if called directly.
                await asyncio.to_thread(vault_client.get_secret, vault_path)
            except Exception as exc:
                unhealthy += 1
                logger.warning(
                    "credential_health_check_unreachable",
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    # vault_path intentionally omitted from logs — reveals internal path schema
                    error=str(exc),
                )

                # Deduplication: skip notification if already sent within the last 7 days.
                # Prevents notification storms when vault is unreachable for multiple days.
                _notified = False
                try:
                    _redis = get_redis()
                    _dedup_key = build_redis_key(tenant_id, "cred_health_notified", agent_id)
                    _already_notified = await _redis.exists(_dedup_key)
                    if _already_notified:
                        logger.debug(
                            "credential_health_notification_suppressed",
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            reason="dedup_key_exists",
                        )
                        _notified = True
                except Exception as dedup_exc:
                    logger.warning(
                        "credential_health_dedup_check_failed",
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        error=str(dedup_exc),
                    )

                if not _notified:
                    # Fetch admin users for this tenant to deliver the notification
                    try:
                        admin_result = await db.execute(
                            sa.text(
                                """
                                SELECT id FROM users
                                WHERE tenant_id = :tenant_id
                                  AND role = 'admin'
                                  AND status = 'active'
                                ORDER BY id
                                LIMIT 10
                                """
                            ),
                            {"tenant_id": tenant_id},
                        )
                        admin_rows = admin_result.fetchall()

                        from app.modules.notifications.publisher import publish_notification

                        _any_sent = False
                        for admin_row in admin_rows:
                            admin_id = str(admin_row[0])
                            try:
                                await publish_notification(
                                    user_id=admin_id,
                                    tenant_id=tenant_id,
                                    notification_type="credential_unreachable",
                                    title="Agent credential unreachable",
                                    body=(
                                        f"Agent '{agent_name}' credentials are unreachable. "
                                        "Please re-deploy the agent with valid credentials."
                                    ),
                                )
                                notifications_sent += 1
                                _any_sent = True
                            except Exception as notify_exc:
                                logger.warning(
                                    "credential_health_notification_failed",
                                    tenant_id=tenant_id,
                                    agent_id=agent_id,
                                    admin_id=admin_id,
                                    error=str(notify_exc),
                                )

                        # Mark this agent as notified to prevent repeat storms.
                        if _any_sent:
                            try:
                                _redis = get_redis()
                                _dedup_key = build_redis_key(
                                    tenant_id, "cred_health_notified", agent_id
                                )
                                await _redis.setex(_dedup_key, _NOTIF_DEDUP_TTL_SECONDS, "1")
                            except Exception as dedup_write_exc:
                                logger.warning(
                                    "credential_health_dedup_write_failed",
                                    tenant_id=tenant_id,
                                    agent_id=agent_id,
                                    error=str(dedup_write_exc),
                                )

                    except Exception as lookup_exc:
                        logger.warning(
                            "credential_health_admin_lookup_failed",
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            error=str(lookup_exc),
                        )

        logger.info(
            "credential_health_check_complete",
            tenant_id=tenant_id,
            checked=checked,
            unhealthy=unhealthy,
            notifications_sent=notifications_sent,
        )

        return {
            "checked": checked,
            "unhealthy": unhealthy,
            "notifications_sent": notifications_sent,
        }


# ---------------------------------------------------------------------------
# Public job entrypoint
# ---------------------------------------------------------------------------


async def run_credential_health_job() -> int:
    """
    Execute one full credential health run across all active tenants.

    Per-tenant errors are isolated: an exception for one tenant never stops
    processing of others. Never raises — all top-level exceptions are logged.

    Returns:
        Number of tenants processed without error.
    """
    job_start = time.monotonic()
    processed = 0
    errors = 0

    try:
        from app.core.secrets.vault_client import get_vault_client

        vault_client = get_vault_client()
    except Exception as exc:
        logger.error("credential_health_vault_client_init_failed", error=str(exc))
        return 0

    try:
        async with async_session_factory() as db:
            await db.execute(sa.text("SET LOCAL app.current_scope = 'platform'"))
            await db.execute(sa.text("SET LOCAL app.user_role = 'platform_admin'"))
            result = await db.execute(
                sa.text("SELECT id FROM tenants WHERE status = 'active' ORDER BY id")
            )
            tenant_rows = result.fetchall()
    except Exception as exc:
        logger.error(
            "credential_health_tenant_fetch_failed",
            error=str(exc),
        )
        return 0

    tenant_ids = [str(row[0]) for row in tenant_rows]

    if not tenant_ids:
        logger.info("credential_health_no_active_tenants")
        return 0

    for tenant_id in tenant_ids:
        try:
            async with async_session_factory() as db:
                await run_daily_credential_health_check(
                    tenant_id=tenant_id,
                    db=db,
                    vault_client=vault_client,
                )
            processed += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "credential_health_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

    duration_ms = round((time.monotonic() - job_start) * 1000, 1)
    logger.info(
        "credential_health_job_complete",
        total_tenants=len(tenant_ids),
        processed=processed,
        errors=errors,
        duration_ms=duration_ms,
    )
    return processed


# ---------------------------------------------------------------------------
# Scheduler (daily at 05:30 UTC — 30 min after credential expiry job)
# ---------------------------------------------------------------------------


async def run_credential_health_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_credential_health_job() daily at
    05:30 UTC.

    Designed to be launched as an asyncio background task via
    asyncio.create_task() in app/main.py lifespan. Exits gracefully on
    CancelledError.
    """
    logger.info(
        "credential_health_scheduler_started",
        schedule="daily at 05:30 UTC",
    )

    while True:
        try:
            # SCHED-025 pattern: missed-job recovery on first iteration.
            async with async_session_factory() as _db:
                if await check_missed_job(
                    _db,
                    "credential_health",
                    scheduled_hour=5,
                    scheduled_minute=30,
                ):
                    async with DistributedJobLock(
                        "credential_health_global", ttl=3600
                    ) as _acquired:
                        if _acquired:
                            await run_credential_health_job()
                            logger.info("credential_health_missed_job_recovered")

            sleep_secs = seconds_until_utc(5, 30)
            logger.debug(
                "credential_health_next_run_in",
                seconds=round(sleep_secs, 0),
            )
            await asyncio.sleep(sleep_secs)

            async with DistributedJobLock(
                "credential_health_global", ttl=3600
            ) as acquired:
                if not acquired:
                    logger.debug(
                        "credential_health_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    await run_credential_health_job()

        except asyncio.CancelledError:
            logger.info("credential_health_scheduler_cancelled")
            return
        except Exception as exc:
            # Never crash the scheduler loop — log and retry on next cycle.
            logger.error(
                "credential_health_scheduler_loop_error",
                error=str(exc),
            )
