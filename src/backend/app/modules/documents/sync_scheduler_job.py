"""
SCHED-039: Document sync scheduler loop.

Runs in the background (asyncio task, started in app/main.py lifespan).
Wakes every 60 seconds, queries integrations whose next_run_at has elapsed,
and dispatches the appropriate sync for each one.

Supported providers:
  sharepoint   — creates a sync_jobs row (picked up by the SharePoint sync worker)
  google_drive — calls run_incremental_sync() directly

For each dispatched integration, next_run_at is advanced via
_next_run_from_schedule() and written back to integrations.config.

Error handling:
  - Per-integration errors are caught, logged at ERROR, and skipped —
    the loop continues to the next integration.
  - Outer loop errors are caught, logged at ERROR, and the loop continues —
    the job never dies.
  - asyncio.CancelledError breaks cleanly.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

from app.core.scheduler import DistributedJobLock, job_run_context
from app.core.session import async_session_factory

logger = structlog.get_logger()

_POLL_INTERVAL_SECONDS = 60


async def run_document_sync_scheduler() -> None:
    """
    Infinite loop: every 60 seconds, find integrations whose next_run_at has
    elapsed and dispatch a sync for each.

    Designed to be launched as an asyncio background task in main.py.
    Exits gracefully on CancelledError.
    """
    logger.info(
        "doc_sync_scheduler_started",
        poll_interval_seconds=_POLL_INTERVAL_SECONDS,
    )

    while True:
        try:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            await _poll_and_dispatch()
        except asyncio.CancelledError:
            logger.info("doc_sync_scheduler_cancelled")
            return
        except Exception as exc:
            logger.error(
                "doc_sync_scheduler_outer_loop_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )


async def _poll_and_dispatch() -> None:
    """
    Single poll cycle: query due integrations and dispatch each one.
    """
    async with async_session_factory() as db:
        result = await db.execute(
            text(
                "SELECT id, tenant_id, provider, config "
                "FROM integrations "
                "WHERE status != 'disabled' "
                "  AND config->>'schedule' IS NOT NULL "
                "  AND (config->'schedule'->>'next_run_at')::timestamptz <= NOW()"
            )
        )
        due_rows = result.fetchall()

    if not due_rows:
        return

    logger.info("doc_sync_scheduler_due_integrations", count=len(due_rows))

    for row in due_rows:
        integration_id = str(row[0])
        tenant_id = str(row[1])
        provider = row[2]
        config_raw = row[3]

        try:
            await _dispatch_integration(
                integration_id=integration_id,
                tenant_id=tenant_id,
                provider=provider,
                config_raw=config_raw,
            )
        except Exception as exc:
            logger.error(
                "doc_sync_scheduler_integration_error",
                integration_id=integration_id,
                tenant_id=tenant_id,
                provider=provider,
                error=str(exc),
                error_type=type(exc).__name__,
            )


async def _dispatch_integration(
    integration_id: str,
    tenant_id: str,
    provider: str,
    config_raw: Any,
) -> None:
    """
    Dispatch a single scheduled sync for one integration.

    Steps:
    1. Check sync_jobs for a running row — skip if found.
    2. Try to acquire a distributed lock (TTL=1800s) — skip if not acquired.
    3. Dispatch based on provider.
    4. Advance next_run_at in integrations.config.
    """
    if isinstance(config_raw, str):
        config: dict = json.loads(config_raw)
    elif isinstance(config_raw, dict):
        config = config_raw
    else:
        config = {}

    schedule = config.get("schedule", {})
    frequency: str = schedule.get("frequency", "daily")
    cron_expression: Optional[str] = schedule.get("cron_expression")

    # 1. Check for a running sync_jobs row for this integration
    async with async_session_factory() as db:
        running_check = await db.execute(
            text(
                "SELECT id FROM sync_jobs "
                "WHERE integration_id = :integration_id "
                "  AND status IN ('queued', 'running') "
                "LIMIT 1"
            ),
            {"integration_id": integration_id},
        )
        running_row = running_check.fetchone()

    if running_row is not None:
        logger.debug(
            "doc_sync_scheduler_skipped_already_running",
            integration_id=integration_id,
            tenant_id=tenant_id,
            provider=provider,
        )
        return

    # 2. Acquire distributed lock to prevent multi-pod double-dispatch
    lock_key = f"doc_sync:{integration_id}"
    async with DistributedJobLock(lock_key, ttl=1800) as acquired:
        if not acquired:
            logger.debug(
                "doc_sync_scheduler_skipped_lock_held",
                integration_id=integration_id,
                tenant_id=tenant_id,
            )
            return

        # 3. Dispatch
        job_name = f"doc_sync:{integration_id}"
        async with job_run_context(job_name, tenant_id=tenant_id) as ctx:
            if provider == "sharepoint":
                await _dispatch_sharepoint(
                    integration_id=integration_id,
                    tenant_id=tenant_id,
                    ctx=ctx,
                )
            elif provider == "google_drive":
                await _dispatch_google_drive(
                    integration_id=integration_id,
                    tenant_id=tenant_id,
                    ctx=ctx,
                )
            else:
                logger.warning(
                    "doc_sync_scheduler_unknown_provider",
                    integration_id=integration_id,
                    tenant_id=tenant_id,
                    provider=provider,
                )
                # Do not advance next_run_at for unknown providers — keep the
                # integration "due" so the repeated warning surfaces the misconfiguration.
                return

        # 4. Advance next_run_at
        await _advance_next_run_at(
            integration_id=integration_id,
            tenant_id=tenant_id,
            frequency=frequency,
            cron_expression=cron_expression,
        )


async def _dispatch_sharepoint(
    integration_id: str,
    tenant_id: str,
    ctx: Any,
) -> None:
    """
    Create a SharePoint sync_jobs row with sync_triggered_by='schedule'.
    The SharePoint sync worker picks it up from the queue.
    """
    from app.modules.documents.sharepoint import create_sync_job_db

    async with async_session_factory() as db:
        result = await create_sync_job_db(
            integration_id=integration_id,
            tenant_id=tenant_id,
            db=db,
        )
        # Annotate the sync_jobs row with triggered_by metadata
        job_id = result.get("job_id")
        if job_id:
            await db.execute(
                text(
                    "UPDATE sync_jobs "
                    "SET metadata = CAST(:metadata AS jsonb) "
                    "WHERE id = :id"
                ),
                {
                    "id": job_id,
                    "metadata": json.dumps({"sync_triggered_by": "schedule"}),
                },
            )
            await db.commit()

    ctx.records_processed = 1
    logger.info(
        "doc_sync_scheduler_sharepoint_dispatched",
        integration_id=integration_id,
        tenant_id=tenant_id,
        sync_job_id=result.get("job_id"),
    )


async def _dispatch_google_drive(
    integration_id: str,
    tenant_id: str,
    ctx: Any,
) -> None:
    """
    Run an incremental Google Drive sync directly (or seed startPageToken if first run).
    run_incremental_sync handles the no-token case internally.
    """
    from app.modules.documents.google_drive.sync_worker import run_incremental_sync

    async with async_session_factory() as db:
        result = await run_incremental_sync(
            integration_id=integration_id,
            tenant_id=tenant_id,
            trigger="schedule",
            db=db,
        )
        await db.commit()

    files_processed = result.get("files_processed", 0) if isinstance(result, dict) else 0
    ctx.records_processed = files_processed
    logger.info(
        "doc_sync_scheduler_google_drive_dispatched",
        integration_id=integration_id,
        tenant_id=tenant_id,
        result_status=result.get("status") if isinstance(result, dict) else None,
        files_processed=files_processed,
    )


async def _advance_next_run_at(
    integration_id: str,
    tenant_id: str,
    frequency: str,
    cron_expression: Optional[str],
) -> None:
    """
    Compute the next_run_at from the schedule and write it back to
    integrations.config['schedule']['next_run_at'].
    """
    from app.modules.documents.sharepoint import _next_run_from_schedule

    try:
        next_run: datetime = _next_run_from_schedule(frequency, cron_expression)
        next_run_str = next_run.isoformat()

        async with async_session_factory() as db:
            await db.execute(
                text(
                    "UPDATE integrations "
                    "SET config = jsonb_set("
                    "    jsonb_set(config, '{schedule,next_run_at}', CAST(:next_run AS jsonb)), "
                    "    '{schedule,last_triggered_at}', CAST(:now AS jsonb)"
                    ") "
                    "WHERE id = :id AND tenant_id = :tenant_id"
                ),
                {
                    "id": integration_id,
                    "tenant_id": tenant_id,
                    "next_run": json.dumps(next_run_str),
                    "now": json.dumps(datetime.now(timezone.utc).isoformat()),
                },
            )
            await db.commit()

        logger.debug(
            "doc_sync_scheduler_next_run_advanced",
            integration_id=integration_id,
            tenant_id=tenant_id,
            next_run_at=next_run_str,
        )
    except Exception as exc:
        logger.error(
            "doc_sync_scheduler_advance_next_run_failed",
            integration_id=integration_id,
            tenant_id=tenant_id,
            error=str(exc),
        )
        # Backoff: write a 1-hour fallback so a broken config does not
        # trigger an infinite 60-second re-dispatch loop.
        try:
            from datetime import timedelta

            fallback = datetime.now(timezone.utc) + timedelta(hours=1)
            async with async_session_factory() as db:
                await db.execute(
                    text(
                        "UPDATE integrations "
                        "SET config = jsonb_set(config, '{schedule,next_run_at}', CAST(:next_run AS jsonb)) "
                        "WHERE id = :id AND tenant_id = :tenant_id"
                    ),
                    {
                        "id": integration_id,
                        "tenant_id": tenant_id,
                        "next_run": json.dumps(fallback.isoformat()),
                    },
                )
                await db.commit()
        except Exception as backoff_exc:
            logger.error(
                "doc_sync_scheduler_backoff_write_failed",
                integration_id=integration_id,
                error=str(backoff_exc),
            )
