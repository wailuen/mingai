"""
Distributed job scheduling infrastructure.

Provides:
  DistributedJobLock      — Redis-backed distributed lock with heartbeat renewal
                            and job self-termination on token theft.
  seconds_until_utc       — Timing utility shared by all daily-scheduled jobs.
  job_run_context         — Async context manager for durable job execution logging.
  run_tenants_throttled   — Semaphore-gated fan-out for per-tenant jobs.

Usage:
    from app.core.scheduler import DistributedJobLock, seconds_until_utc
    from app.core.scheduler import job_run_context, run_tenants_throttled
"""
from app.core.scheduler.job_lock import DistributedJobLock
from app.core.scheduler.job_run_log import job_run_context
from app.core.scheduler.tenant_throttle import run_tenants_throttled
from app.core.scheduler.timing import seconds_until_utc

__all__ = [
    "DistributedJobLock",
    "job_run_context",
    "run_tenants_throttled",
    "seconds_until_utc",
]
