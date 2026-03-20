"""
TA-017: Credential expiry monitoring — daily background job.

Scheduled daily at 05:00 UTC. For each active tenant:
1. Queries integrations (sharepoint + google_drive).
2. For SharePoint: reads expiry_date from vault metadata stored in config.
3. For Google Drive: reads token expires_at from integrations.config.
4. Issues P2 (30-day warning) or P1 (7-day critical) notifications + issue
   queue items to all tenant_admin users.
5. Duplicate prevention: checks for existing open notifications before creating.

Job failure for one tenant does not abort processing of other tenants.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context, seconds_until_utc
from app.core.scheduler.timing import check_missed_job
from app.core.session import async_session_factory

logger = structlog.get_logger()

# Warning thresholds (days until expiry)
_WARN_DAYS = 30  # P2 notification
_CRITICAL_DAYS = 7  # P1 notification + issue queue item

# Notification type tag used for duplicate detection
_NOTIF_TYPE = "credential_expiry"


async def run_credential_expiry_job() -> dict:
    """
    Execute the credential expiry monitoring job for all active tenants.

    Returns summary: {tenant_id: {"checked": N, "warned": N, "critical": N}}.
    """
    logger.info("credential_expiry_job_started")
    summary: dict[str, dict] = {}

    async with async_session_factory() as db:
        await db.execute(text("SET LOCAL app.scope = 'platform'"))
        result = await db.execute(
            text("SELECT id FROM tenants WHERE status = 'active'")
        )
        tenant_ids = [str(row[0]) for row in result.fetchall()]

    for tenant_id in tenant_ids:
        try:
            stats = await _process_tenant(tenant_id)
            summary[tenant_id] = stats
        except Exception as exc:
            logger.error(
                "credential_expiry_tenant_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )
            summary[tenant_id] = {"checked": 0, "warned": 0, "critical": 0}

    logger.info(
        "credential_expiry_job_completed",
        tenants_processed=len(tenant_ids),
        total_critical=sum(s.get("critical", 0) for s in summary.values()),
        total_warned=sum(s.get("warned", 0) for s in summary.values()),
    )
    return summary


async def _process_tenant(tenant_id: str) -> dict:
    """
    Check credential expiry for all SharePoint and Google Drive integrations
    belonging to one tenant. Issues notifications and issue queue items.
    """
    now = datetime.now(timezone.utc)
    stats = {"checked": 0, "warned": 0, "critical": 0}

    async with async_session_factory() as db:
        await db.execute(
            text("SET LOCAL app.tenant_id = :tid"),
            {"tid": tenant_id},
        )

        # Fetch all active integrations for this tenant
        result = await db.execute(
            text(
                "SELECT id, provider, config FROM integrations "
                "WHERE tenant_id = :tenant_id AND status != 'disabled'"
            ),
            {"tenant_id": tenant_id},
        )
        integrations = []
        for row in result.fetchall():
            config_val = row[2]
            if isinstance(config_val, str):
                config_val = json.loads(config_val)
            elif config_val is None:
                config_val = {}
            integrations.append(
                {"id": str(row[0]), "provider": row[1], "config": config_val}
            )

        if not integrations:
            return stats

        # Fetch tenant admin user IDs for notifications
        admin_result = await db.execute(
            text(
                "SELECT id FROM users "
                "WHERE tenant_id = :tenant_id "
                "  AND role = 'tenant_admin' "
                "  AND status = 'active'"
            ),
            {"tenant_id": tenant_id},
        )
        admin_ids = [str(r[0]) for r in admin_result.fetchall()]

        if not admin_ids:
            return stats

        for integration in integrations:
            stats["checked"] += 1
            expiry_dt = _extract_expiry(integration)
            if expiry_dt is None:
                continue

            days_remaining = (expiry_dt - now).days
            integration_name = integration["config"].get(
                "name", integration["provider"].title()
            )

            if days_remaining <= 0:
                # Already expired — treat same as 7-day critical
                severity = "P1"
                days_label = "has expired"
            elif days_remaining <= _CRITICAL_DAYS:
                severity = "P1"
                days_label = f"expires in {days_remaining} day(s)"
            elif days_remaining <= _WARN_DAYS:
                severity = "P2"
                days_label = f"expires in {days_remaining} day(s)"
            else:
                continue  # No action needed yet

            title = f"Credential expiry: {integration_name} — {days_label}"
            body = (
                f"The {integration['provider'].title()} integration "
                f"'{integration_name}' credential {days_label}. "
                "Please reconnect to avoid sync disruption."
            )

            # Check for existing open notification (duplicate prevention)
            existing = await db.execute(
                text(
                    "SELECT id FROM notifications "
                    "WHERE tenant_id = :tenant_id "
                    "  AND type = :type "
                    "  AND title = :title "
                    "  AND read = false "
                    "LIMIT 1"
                ),
                {
                    "tenant_id": tenant_id,
                    "type": _NOTIF_TYPE,
                    "title": title,
                },
            )
            if existing.fetchone() is not None:
                logger.debug(
                    "credential_expiry_notification_already_exists",
                    tenant_id=tenant_id,
                    integration_id=integration["id"],
                )
                continue

            # Send notification to all tenant admins
            for admin_id in admin_ids:
                await _insert_notification(
                    db=db,
                    tenant_id=tenant_id,
                    user_id=admin_id,
                    notif_type=_NOTIF_TYPE,
                    title=title,
                    body=body,
                )

            # P1 critical: also create an issue queue item
            if severity == "P1":
                await _insert_issue(
                    db=db,
                    tenant_id=tenant_id,
                    reporter_id=admin_ids[0],
                    integration_id=integration["id"],
                    title=title,
                    description=body,
                )
                stats["critical"] += 1
            else:
                stats["warned"] += 1

        await db.commit()

    logger.info(
        "credential_expiry_tenant_processed",
        tenant_id=tenant_id,
        **stats,
    )
    return stats


def _extract_expiry(integration: dict) -> Optional[datetime]:
    """
    Extract expiry datetime from integration config.

    - SharePoint: config['expiry_date'] (stored alongside credential_ref)
    - Google Drive: config['token_expires_at']

    Returns None if no expiry date is configured.
    """
    config = integration.get("config", {})
    provider = integration.get("provider", "")

    if provider == "sharepoint":
        raw = config.get("expiry_date")
    elif provider == "google_drive":
        raw = config.get("token_expires_at")
    else:
        raw = config.get("expiry_date") or config.get("token_expires_at")

    if not raw:
        return None

    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        logger.warning(
            "credential_expiry_unparseable_date",
            provider=provider,
            raw_value=str(raw),
        )
        return None


async def _insert_notification(
    db,
    tenant_id: str,
    user_id: str,
    notif_type: str,
    title: str,
    body: str,
) -> None:
    """Insert an in-app notification. Errors are logged but not re-raised."""
    try:
        await db.execute(
            text(
                "INSERT INTO notifications "
                "(id, tenant_id, user_id, type, title, body, read) "
                "VALUES (:id, :tenant_id, :user_id, :type, :title, :body, false)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "type": notif_type,
                "title": title,
                "body": body,
            },
        )
    except Exception as exc:
        logger.warning(
            "credential_expiry_notification_insert_failed",
            tenant_id=tenant_id,
            user_id=user_id,
            error=str(exc),
        )


async def _insert_issue(
    db,
    tenant_id: str,
    reporter_id: str,
    integration_id: str,
    title: str,
    description: str,
) -> None:
    """Insert a P1 issue queue item. Errors are logged but not re-raised."""
    try:
        import json as _json

        await db.execute(
            text(
                "INSERT INTO issue_reports "
                "(id, tenant_id, reporter_id, issue_type, description, "
                " severity, status, blur_acknowledged, metadata) "
                "VALUES (:id, :tenant_id, :reporter_id, :issue_type, :description, "
                "        :severity, :status, false, CAST(:metadata AS jsonb))"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "reporter_id": reporter_id,
                "issue_type": "credential_expiry",
                "description": description,
                "severity": "high",
                "status": "open",
                "metadata": _json.dumps(
                    {"title": title, "integration_id": integration_id}
                ),
            },
        )
    except Exception as exc:
        logger.warning(
            "credential_expiry_issue_insert_failed",
            tenant_id=tenant_id,
            integration_id=integration_id,
            error=str(exc),
        )


async def run_credential_expiry_scheduler() -> None:
    """
    Infinite asyncio loop that fires run_credential_expiry_job() daily at 05:00 UTC.

    Launched as an asyncio background task in app/main.py lifespan.
    Exits gracefully on CancelledError.
    """
    logger.info("credential_expiry_scheduler_started", schedule="daily at 05:00 UTC")

    while True:
        try:
            # SCHED-025: Missed-job recovery — runs immediately on the first
            # iteration if the 05:00 UTC slot passed today with no completed row.
            # On subsequent iterations check_missed_job returns False (row exists).
            async with async_session_factory() as _db:
                if await check_missed_job(
                    _db, "credential_expiry", scheduled_hour=5, scheduled_minute=0
                ):
                    async with DistributedJobLock(
                        "credential_expiry", ttl=1800
                    ) as _acquired:
                        if _acquired:
                            async with job_run_context("credential_expiry") as ctx:
                                _summary = await run_credential_expiry_job()
                                ctx.records_processed = (
                                    sum(
                                        s.get("checked", 0)
                                        for s in _summary.values()
                                    )
                                    if _summary
                                    else 0
                                )
                            logger.info("credential_expiry_missed_job_recovered")

            sleep_secs = seconds_until_utc(5, 0)
            logger.debug("credential_expiry_next_run_in", seconds=round(sleep_secs, 0))
            await asyncio.sleep(sleep_secs)
            # CORRECTNESS CRITICAL: lock prevents duplicate expiry emails to tenant admins
            async with DistributedJobLock("credential_expiry", ttl=1800) as acquired:
                if not acquired:
                    logger.debug(
                        "credential_expiry_job_skipped",
                        reason="lock_held_by_another_pod",
                    )
                else:
                    async with job_run_context("credential_expiry") as ctx:
                        summary = await run_credential_expiry_job()
                        ctx.records_processed = sum(
                            s.get("checked", 0) for s in summary.values()
                        ) if summary else 0
        except asyncio.CancelledError:
            logger.info("credential_expiry_scheduler_cancelled")
            return
        except Exception as exc:
            logger.error("credential_expiry_job_unexpected_error", error=str(exc))
            await asyncio.sleep(300)  # Back off 5 min on unexpected errors
