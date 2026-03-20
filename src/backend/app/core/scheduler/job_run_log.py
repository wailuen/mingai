"""
SCHED-023: job_run_context() — durable execution logging for scheduled jobs.

Usage:
    async with job_run_context("health_score", tenant_id=str(tenant_id)) as ctx:
        result = await run_health_score_job(db)
        ctx.records_processed = result["tenants_scored"]

On enter:  INSERT job_run_log row with status='running'.
On exit:   UPDATE to 'completed' (success) or 'failed' (exception).
           CancelledError branch writes 'abandoned' via asyncio.shield()
           using a fresh DB connection (the original may be in a cancelled state).

A DB failure during INSERT logs a WARNING and does NOT raise — the job runs
without a log row. A DB failure during UPDATE logs a WARNING and does NOT
re-raise the original job exception.

H-04 remediation: asyncio.shield() protects the abandoned-status UPDATE from
CancelledError propagation during event loop shutdown. If the shield itself
fails (e.g. event loop already stopping), startup zombie cleanup (SCHED-005)
marks orphaned 'running' rows as 'abandoned' on next pod start.
"""
from __future__ import annotations

import asyncio
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger()

_INSTANCE_ID: str = socket.gethostname()


@dataclass
class JobRunContext:
    """Yielded context object for callers to set execution metadata."""

    records_processed: Optional[int] = field(default=None)


async def _insert_run_row(
    job_name: str,
    tenant_id: Optional[str],
) -> Optional[str]:
    """
    Insert a status='running' row into job_run_log.
    Returns the new row id (UUID string), or None on failure.
    Failure is logged at WARNING and does not raise.
    """
    import uuid as _uuid

    from app.core.session import async_session_factory
    from sqlalchemy import text

    row_id = str(_uuid.uuid4())
    try:
        async with async_session_factory() as db:
            await db.execute(
                text(
                    "INSERT INTO job_run_log "
                    "(id, job_name, instance_id, tenant_id, status, started_at) "
                    "VALUES (:id, :job_name, :instance_id, :tenant_id, 'running', NOW())"
                ),
                {
                    "id": row_id,
                    "job_name": job_name,
                    "instance_id": _INSTANCE_ID,
                    "tenant_id": tenant_id,
                },
            )
            await db.commit()
        return row_id
    except Exception as exc:
        logger.warning(
            "job_run_log_insert_failed",
            job_name=job_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None


async def _write_final_status(
    row_id: str,
    status: str,
    duration_ms: int,
    records_processed: Optional[int],
    error_message: Optional[str],
) -> None:
    """
    Update the job_run_log row to its terminal status.
    Opens a fresh DB connection — the caller's session may be in a cancelled state.
    Failure is logged at WARNING and does not raise.
    """
    from app.core.session import async_session_factory
    from sqlalchemy import text

    try:
        async with async_session_factory() as db:
            await db.execute(
                text(
                    "UPDATE job_run_log "
                    "SET status = :status, "
                    "    completed_at = NOW(), "
                    "    duration_ms = :duration_ms, "
                    "    records_processed = :records_processed, "
                    "    error_message = :error_message "
                    "WHERE id = :id"
                ),
                {
                    "id": row_id,
                    "status": status,
                    "duration_ms": duration_ms,
                    "records_processed": records_processed,
                    "error_message": error_message,
                },
            )
            await db.commit()
    except Exception as exc:
        logger.warning(
            "job_run_log_update_failed",
            row_id=row_id,
            status=status,
            error_type=type(exc).__name__,
            error=str(exc),
        )


@asynccontextmanager
async def job_run_context(
    job_name: str,
    tenant_id: Optional[str] = None,
):
    """
    Async context manager for durable job execution logging.

    Inserts a 'running' row on enter. Updates to 'completed', 'failed', or
    'abandoned' on exit. Yields a JobRunContext for callers to set
    ctx.records_processed before the context exits.

    Never raises — DB failures are swallowed so they cannot abort the job.
    """
    row_id = await _insert_run_row(job_name, tenant_id)
    ctx = JobRunContext()
    started_ms = time.monotonic()

    try:
        yield ctx
    except asyncio.CancelledError:
        duration_ms = int((time.monotonic() - started_ms) * 1000)
        if row_id is not None:
            # H-04: shield the UPDATE from CancelledError propagation.
            # Use a fresh connection — the job's own session may be cancelled.
            try:
                await asyncio.shield(
                    _write_final_status(
                        row_id=row_id,
                        status="abandoned",
                        duration_ms=duration_ms,
                        records_processed=ctx.records_processed,
                        error_message="CancelledError",
                    )
                )
            except (asyncio.CancelledError, Exception):
                # Best-effort — startup zombie cleanup (SCHED-005) handles
                # orphaned 'running' rows if this fails.
                pass
        raise
    except Exception as exc:
        duration_ms = int((time.monotonic() - started_ms) * 1000)
        if row_id is not None:
            await _write_final_status(
                row_id=row_id,
                status="failed",
                duration_ms=duration_ms,
                records_processed=ctx.records_processed,
                error_message=str(exc),
            )
        raise
    else:
        duration_ms = int((time.monotonic() - started_ms) * 1000)
        if row_id is not None:
            await _write_final_status(
                row_id=row_id,
                status="completed",
                duration_ms=duration_ms,
                records_processed=ctx.records_processed,
                error_message=None,
            )
