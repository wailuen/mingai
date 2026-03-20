"""
SCHED-003 / SCHED-025: Shared timing utilities for scheduled background jobs.

Replaces the 8 identical _seconds_until_next_run() implementations that are
copy-pasted across daily job files (health_score, cost_summary, azure_cost,
cost_alert, miss_signals, credential_expiry, query_warming, and any future
daily jobs).

Usage:
    from app.core.scheduler import seconds_until_utc
    from app.core.scheduler.timing import check_missed_job

    delay = seconds_until_utc(hour=3, minute=30)
    await asyncio.sleep(delay)

    # At startup, before first sleep:
    if await check_missed_job(db, "health_score", scheduled_hour=2):
        pass  # skip the sleep — run immediately
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_FLOOR_SECONDS = 60.0  # M-01: cold-start guard (drain-window miss behaviour)


def seconds_until_utc(hour: int, minute: int = 0) -> float:
    """
    Return the number of seconds until the next occurrence of HH:MM UTC.

    If the target time has already passed today the result is always positive
    (i.e. we schedule for the same time tomorrow).  If the current time is
    exactly HH:MM the next run is 24 hours away to avoid double-firing.

    A 60-second floor is enforced (M-01 drain-window-miss behaviour): a pod
    that starts at 02:00:30 UTC will not immediately fire the 02:00 job — it
    waits 24 hours for the next occurrence.  SCHED-025 adds
    `check_missed_job()` to recover jobs that were skipped due to this floor.

    Args:
        hour:   Target hour in UTC (0-23).
        minute: Target minute in UTC (0-59).  Defaults to 0.

    Returns:
        Seconds as a float, always >= 60.0.
    """
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    raw = (target - now).total_seconds()
    return max(raw, _FLOOR_SECONDS)


async def check_missed_job(
    db: Any,
    job_name: str,
    scheduled_hour: int,
    scheduled_minute: int = 0,
) -> bool:
    """
    SCHED-025: Return True if the job missed its scheduled run and should fire immediately.

    Queries job_run_log for a 'completed' row since today's scheduled slot.
    - Returns True  if current time >= scheduled time AND no completed row today.
    - Returns False if a completed row already exists (job ran, no action needed).
    - Returns False if current time < scheduled time (job not yet due today).
    - Returns False on any DB error (conservative — no spurious immediate run).

    Callers should invoke this before the first await asyncio.sleep(seconds_until_utc(...))
    in the scheduler loop.  If True, skip the sleep and run immediately (still
    under the distributed lock) to recover from M-01 / M-04 cold-start misses.

    Args:
        db:               Active async DB session (must have app.scope set to 'platform').
        job_name:         The job_run_log.job_name value to check.
        scheduled_hour:   UTC hour of the scheduled run.
        scheduled_minute: UTC minute of the scheduled run (default 0).

    Returns:
        bool — True to run immediately; False to wait for next scheduled slot.
    """
    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    today_slot = now.replace(
        hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0
    )

    # Job has not yet been due today — no miss possible.
    if now < today_slot:
        return False

    try:
        result = await db.execute(
            text(
                "SELECT 1 FROM job_run_log "
                "WHERE job_name = :job_name "
                "AND status = 'completed' "
                "AND started_at >= :since "
                "LIMIT 1"
            ),
            {"job_name": job_name, "since": today_slot},
        )
        row = result.fetchone()
        if row is not None:
            # Job ran successfully today — nothing to recover.
            return False
        # Due today but no completed row found — missed.
        logger.info(
            "scheduler_missed_job_detected",
            job_name=job_name,
            scheduled_hour=scheduled_hour,
            scheduled_minute=scheduled_minute,
        )
        return True
    except Exception as exc:
        logger.warning(
            "scheduler_missed_job_check_failed",
            job_name=job_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False
