# 13. Distributed Job Scheduling — Implementation Plan

> **Status**: Implementation Plan
> **Version**: v1.1
> **Date**: 2026-03-20
> **Purpose**: Authoritative implementation plan for replacing APScheduler with a distributed Redis-lock-based scheduling system. Incorporates all findings from `01-analysis/01-research/47-background-job-scheduling-architecture.md` and the red team remediation pass (v1.1).
> **Depends on**: Research doc 47

---

## Executive Summary

mingai currently runs 13 background jobs as `asyncio.create_task()` from the FastAPI lifespan — except for two outliers (`provider_health_job.py` and `tool_health_job.py`) that use APScheduler's `AsyncIOScheduler`. All 13 jobs execute independently on every pod, so a second Kubernetes pod causes duplicate execution, double notifications, and double LLM cost. APScheduler is imported conditionally (guarded by `ImportError`), meaning provider and tool health checks are silently disabled if the library is not installed — currently the case, since APScheduler is **not listed in `pyproject.toml`**. Additionally, `tool_health_scheduler` is never wired into `main.py` at all — another silent failure.

**Solution**: Implement a thin `DistributedJobLock` context manager backed by Redis `SET NX EX` + a Lua check-and-delete on release. Wrap every job entrypoint with the lock. Introduce a `job_run_log` table for durable execution history. Extract a shared `seconds_until_utc()` utility to eliminate duplicated timing logic across 8 daily scheduler loops. Remove APScheduler entirely and convert the two outlier jobs to the canonical `asyncio.create_task` pattern.

**Expected outcome**:
- Exactly-once job execution across any number of pods.
- Self-healing lock recovery: a crashed pod's lock expires via TTL, unblocking the next pod within one job interval.
- Queryable per-tenant job history for platform and tenant admin UIs.
- APScheduler dependency eliminated; provider and tool health jobs reliably started on every deployment.
- Zero new infrastructure: uses the existing Redis instance already critical to the stack.

---

## Phase 1: Foundation (Sprint 1)

**Goal**: Introduce the scheduling infrastructure. Deployable independently — no job behaviour changes yet.

### 1.1 New File: `app/core/scheduler/__init__.py`

Empty init to make `scheduler` a package.

```
src/backend/app/core/scheduler/__init__.py  (empty)
```

### 1.2 New File: `app/core/scheduler/job_lock.py`

Implement the `distributed_job_lock` async context manager **with heartbeat renewal built in from day one** (C1 — heartbeat moved from Phase 4 to Phase 1).

```python
# app/core/scheduler/job_lock.py
import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import structlog
from app.core.redis_client import get_redis

logger = structlog.get_logger()

# Platform-scope lock prefix — mirrors the _platform pseudo-tenant used
# by _set_platform_scope_sql() in provider_health_job.py.
# Full key: mingai:_platform:job_lock:{job_name}
# IMPORTANT: this prefix is included in the Redis AOF/RDB persistence policy.
# See deployment checklist §C2.
_LOCK_KEY_PREFIX = "mingai:_platform:job_lock"

# Lua script: atomic check-and-delete (prevents releasing a lock we no longer own
# after TTL expiry + re-acquisition by another pod).
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


@asynccontextmanager
async def distributed_job_lock(
    job_name: str,
    ttl_seconds: int,
    *,
    instance_id: Optional[str] = None,
    heartbeat: bool = True,
    heartbeat_interval: Optional[int] = None,
) -> AsyncIterator[bool]:
    """
    Acquire a Redis distributed lock before running a background job.

    Yields True  — this pod acquired the lock and should run the job.
    Yields False — another pod holds the lock; skip this cycle.

    TTL must be > expected job runtime + 20% safety margin.

    Heartbeat renewal (C1): a background asyncio task extends the lock TTL
    every heartbeat_interval seconds while the job runs. This prevents lock
    expiry mid-run for long-running jobs. The heartbeat is cancelled and the
    lock is released atomically when the context exits (normal or CancelledError).

    Lock key  : mingai:_platform:job_lock:{job_name}
    Lock value: instance_id (UUID per pod startup — aids debugging)
    """
    redis = get_redis()
    lock_key = f"{_LOCK_KEY_PREFIX}:{job_name}"
    owner_id = instance_id or str(uuid.uuid4())

    acquired = await redis.set(lock_key, owner_id, nx=True, ex=ttl_seconds)

    if not acquired:
        logger.debug(
            "job_lock_skipped",
            job_name=job_name,
            reason="another_pod_holds_lock",
        )
        yield False
        return

    logger.debug("job_lock_acquired", job_name=job_name, owner_id=owner_id)

    # C1: Launch heartbeat task to extend TTL while job runs.
    # Interval defaults to ttl_seconds // 2 (renew before expiry, not ttl_seconds // 3,
    # to handle slow Redis round-trips under load).
    _hb_interval = heartbeat_interval or max(ttl_seconds // 2, 10)
    _hb_task: Optional[asyncio.Task] = None

    if heartbeat:
        async def _extend_lock():
            while True:
                await asyncio.sleep(_hb_interval)
                current = await redis.get(lock_key)
                if current == owner_id:
                    await redis.expire(lock_key, ttl_seconds)
                    logger.debug("job_lock_ttl_extended", job_name=job_name)
                else:
                    logger.warning(
                        "job_lock_lost",
                        job_name=job_name,
                        reason="lock_expired_or_stolen",
                    )
                    return
        _hb_task = asyncio.create_task(_extend_lock())

    try:
        yield True
    finally:
        # Cancel heartbeat before releasing lock to prevent a post-release re-extend.
        if _hb_task is not None and not _hb_task.done():
            _hb_task.cancel()
            try:
                await _hb_task
            except asyncio.CancelledError:
                pass
        released = await redis.eval(_RELEASE_SCRIPT, 1, lock_key, owner_id)
        if released:
            logger.debug("job_lock_released", job_name=job_name)
        else:
            logger.warning(
                "job_lock_release_skipped",
                job_name=job_name,
                reason="lock_expired_or_stolen",
            )
```

**Key design choices**:
- `SET NX EX` is a single atomic Redis command — no separate `SETNX` + `EXPIRE` race condition.
- The Lua release script is safe against lock re-acquisition during long jobs: if the TTL expired and another pod re-acquired it, the delete is skipped.
- `instance_id` defaults to a per-call UUID but callers can pass a stable pod ID (e.g., hostname) for observability.
- Heartbeat uses `ttl_seconds // 2` interval (C1): gives a full half-TTL buffer on each renewal cycle, more robust than `ttl_seconds // 3` under Redis connection latency.

### 1.3 New File: `app/core/scheduler/timing.py`

Shared `seconds_until_utc()` — replaces 8 identical `_seconds_until_next_run()` implementations.

```python
# app/core/scheduler/timing.py
from datetime import datetime, timedelta, timezone


def seconds_until_utc(hour: int, minute: int = 0) -> float:
    """
    Compute seconds until the next occurrence of hour:minute UTC.

    Returns at least 60 seconds to guard against double-fire on startup
    (prevents a pod that starts at 02:00:30 UTC from firing immediately
    and then again 24 hours later, skipping the scheduled window).

    Cold-start / missed-job note (M4): this 60s floor means a pod that starts
    at 02:00:30 UTC will NOT run the 02:00 job immediately — it will wait until
    02:00 the following day. This is the documented "drain-window miss" behaviour.
    Phase 3 adds a job_run_log check to detect and recover missed jobs; until then,
    operators should be aware that a startup within 60s of a scheduled window causes
    a 24-hour miss for that job.
    """
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max((target - now).total_seconds(), 60.0)
```

This consolidates the duplicated logic currently in:
- `app/modules/cache/query_warming.py` — `_seconds_until_next_run()` (lines 227–253)
- `app/modules/platform/cost_summary_job.py` — `_seconds_until_next_run()` (lines 325–347)
- `app/modules/platform/cost_alert_job.py` — `_seconds_until_next_run()` (lines 391–413)
- `app/modules/platform/health_score_job.py` — equivalent function
- `app/modules/platform/azure_cost_job.py` — equivalent function
- `app/modules/platform/miss_signals_job.py` — equivalent function (via `run_miss_signals_scheduler`)
- `app/modules/documents/credential_expiry_job.py` — equivalent function

### 1.4 Alembic Migration: `v042_job_run_log.py`

```python
"""042 — job_run_log table for durable background job execution history."""
from alembic import op

revision = "042"
down_revision = "041"


def upgrade():
    op.execute("""
        CREATE TABLE job_run_log (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_name         TEXT NOT NULL,
            tenant_id        UUID REFERENCES tenants(id) ON DELETE SET NULL,
            started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at      TIMESTAMPTZ,
            status           TEXT NOT NULL DEFAULT 'running'
                             CHECK (status IN ('running', 'completed', 'failed', 'skipped', 'abandoned')),
            records_processed INT,
            error_detail      TEXT,
            metadata          JSONB
        )
    """)
    # H3: Composite indexes for the two primary query patterns.
    # (tenant_id, started_at DESC) — tenant admin history page
    # (job_name, started_at DESC)  — per-job history and M1 missed-job check
    # started_at DESC alone        — platform admin all-jobs view
    # Drop the year-partition recommendation; use simple 90-day retention via cleanup job.
    op.execute("CREATE INDEX idx_jrl_started_at      ON job_run_log(started_at DESC)")
    op.execute("CREATE INDEX idx_jrl_job_name_time   ON job_run_log(job_name, started_at DESC)")
    op.execute("CREATE INDEX idx_jrl_tenant_time     ON job_run_log(tenant_id, started_at DESC) WHERE tenant_id IS NOT NULL")


def downgrade():
    op.execute("DROP TABLE IF EXISTS job_run_log")
```

`tenant_id` is nullable: platform-scope jobs (health score, cost summary, provider health) set `tenant_id = NULL`; per-tenant iterating jobs write one row per tenant per execution.

**H3 index notes**: The composite `(job_name, started_at DESC)` index serves both the platform admin filter-by-job-name query and the Phase 3 M1 "did this job run today?" check. No year-based partitioning — 90-day row retention (Phase 2 cleanup) keeps the table well under 5M rows at any realistic tenant count.

### 1.5 APScheduler Removal

APScheduler is not in `pyproject.toml` (confirmed — it was only imported conditionally inside `start_provider_health_scheduler` and `start_tool_health_scheduler`). The `ImportError` guard in both files is the only reason the application starts today without it.

**Actions in this phase**:
1. Do **not** add APScheduler to `pyproject.toml`.
2. Phase 2 will replace the `start_*_scheduler()` functions that import it. Until Phase 2 completes, the `ImportError` guard continues to suppress the warning on startup.
3. After Phase 2, the import is gone entirely and no APScheduler reference remains.

**M2 note**: even though APScheduler is being removed, add explicit `.shutdown()` calls on `app.state.provider_health_scheduler` and `app.state.tool_health_scheduler` in the shutdown block during the Phase 2 transition if those attributes exist. Belt-and-suspenders: if an older pod is still using APScheduler during a rolling deploy, the shutdown block should clean up correctly.

### 1.6 Phase 1 Prerequisites — Deployment Checklist (C2)

Before deploying Phase 1, verify:

- **C2a — Redis AOF/RDB persistence enabled**: Job locks use the key prefix `mingai:_platform:job_lock:*`. This prefix MUST be included in the Redis persistence policy (AOF or RDB). On Redis restart, a stale lock key would block the next job cycle for its full TTL. With persistence, the key either survives (and the TTL continues correctly) or it is flushed if the Redis restart causes an RDB reload from a pre-lock snapshot — acceptable because the TTL guards against double-acquisition.

  Verify: `redis-cli CONFIG GET save` returns non-empty values, or `redis-cli CONFIG GET appendonly` returns `yes`. For managed Redis (ElastiCache, Azure Cache), confirm persistence tier is "Standard" or "Premium" (not "Basic").

- **C2b — Key prefix in persistence scope**: If Redis is configured with key-space notifications or selective flushing, confirm that keys matching `mingai:_platform:*` are not excluded.

- **C2c — Document the 60s startup floor** (M4): add to runbook — a pod that starts within 60 seconds of a scheduled job time will miss that job for 24 hours. This is by design. Phase 3 adds a `job_run_log` check to detect and run missed jobs immediately (with distributed lock protection).

### 1.7 Deliverables — Phase 1

| File | Change type |
|---|---|
| `src/backend/app/core/scheduler/__init__.py` | NEW (empty) |
| `src/backend/app/core/scheduler/job_lock.py` | NEW (with heartbeat — C1) |
| `src/backend/app/core/scheduler/timing.py` | NEW |
| `src/backend/alembic/versions/v042_job_run_log.py` | NEW (with composite indexes — H3; `abandoned` status — H4) |

Phase 1 introduces no behaviour changes. The new files are unused until Phase 2. Migration v042 can be applied to production independently.

---

## Phase 2: Conversion (Sprint 1–2)

**Goal**: Convert `provider_health_job.py` and `tool_health_job.py` to the canonical asyncio pattern; wrap all 13 jobs with `distributed_job_lock`; replace all `_seconds_until_next_run()` calls with `seconds_until_utc()`; migrate tool failure counters to Redis; fix the silent `tool_health_scheduler` gap; mark zombie `running` rows as `abandoned` on startup.

### 2.1 Convert `provider_health_job.py`

Replace `start_provider_health_scheduler(app)` with an asyncio loop function `run_provider_health_scheduler()` that matches the pattern of all other job schedulers.

**Before** (lines 152–194):
```python
def start_provider_health_scheduler(app) -> None:
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler = AsyncIOScheduler()
        ...
        scheduler.start()
        if hasattr(app, "state"):
            app.state.provider_health_scheduler = scheduler
    except ImportError:
        logger.warning("provider_health_scheduler_skipped", ...)
```

**After**:
```python
async def run_provider_health_scheduler() -> None:
    """
    Interval scheduler loop for provider health checks.
    Runs run_provider_health_job() every 600 seconds.
    Exits cleanly on CancelledError (SIGTERM / lifespan shutdown).
    """
    from app.core.scheduler.job_lock import distributed_job_lock

    logger.info("provider_health_scheduler_started", interval_seconds=_CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
            async with distributed_job_lock("provider_health", ttl_seconds=480) as acquired:
                if acquired:
                    summary = await run_provider_health_job()
                    logger.info("provider_health_job_complete", **summary)
        except asyncio.CancelledError:
            logger.info("provider_health_scheduler_stopped")
            return
        except Exception as exc:
            logger.error("provider_health_job_failed", error=str(exc))
```

Update `app/main.py` (lines 297–312): replace `start_provider_health_scheduler(app)` with:
```python
_provider_health_task = None
try:
    from app.modules.platform.provider_health_job import run_provider_health_scheduler
    _provider_health_task = asyncio.create_task(run_provider_health_scheduler())
    logger.info("provider_health_scheduler_started", interval_seconds=600)
except Exception as exc:
    logger.warning("provider_health_scheduler_startup_failed", error=str(exc))
```

Add corresponding cancellation block in the shutdown section of `main.py`:
```python
if _provider_health_task is not None and not _provider_health_task.done():
    _provider_health_task.cancel()
    try:
        await _provider_health_task
    except asyncio.CancelledError:
        pass
    logger.info("provider_health_scheduler_stopped")
```

**M2**: also add to shutdown block (belt-and-suspenders during rolling-deploy transition):
```python
# M2: Shut down APScheduler if still running on this pod (transition period only).
if hasattr(app.state, "provider_health_scheduler"):
    app.state.provider_health_scheduler.shutdown(wait=False)
```

### 2.2 Convert `tool_health_job.py` — Migrate Failure Counters to Redis

`tool_health_job.py` holds failure counts in an in-process dict `_failure_counts: Dict[str, int]`. On pod restart, all counters reset. With distributed scheduling, only one pod runs the job, but pod restarts still lose counter state. Counter state must survive restarts and be consistent across deployments.

**Migration**: Replace `_failure_counts` with Redis keys.

Key pattern: `mingai:_platform:tool_health:failures:{tool_id}`
TTL: 7 days (H2 — auto-expire stale entries for deleted tools)

```python
# Replace module-level dict with Redis-backed accessors:

async def _get_failure_count(tool_id: str) -> int:
    from app.core.redis_client import get_redis
    redis = get_redis()
    val = await redis.get(f"mingai:_platform:tool_health:failures:{tool_id}")
    return int(val) if val else 0


async def _increment_failure_count(tool_id: str) -> int:
    """H1: Atomic INCR + TTL refresh. Returns the new count."""
    from app.core.redis_client import get_redis
    redis = get_redis()
    key = f"mingai:_platform:tool_health:failures:{tool_id}"
    # Lua script: INCR and reset TTL atomically.
    _incr_script = """
    local n = redis.call("INCR", KEYS[1])
    redis.call("EXPIRE", KEYS[1], ARGV[1])
    return n
    """
    return int(await redis.eval(_incr_script, 1, key, str(604800)))  # 7-day TTL


async def _reset_failure_count(tool_id: str) -> None:
    from app.core.redis_client import get_redis
    redis = get_redis()
    await redis.delete(f"mingai:_platform:tool_health:failures:{tool_id}")
```

**H1 — threshold check**: update `_handle_tool_result()` to replace the `== _UNAVAILABLE_THRESHOLD` equality check with `>= _UNAVAILABLE_THRESHOLD`. The existing check fires only once (on the exact 10th failure); if a counter somehow exceeds 10 (e.g., a counter pre-populated from a previous deployment), the condition never triggers. Use `>= _UNAVAILABLE_THRESHOLD` throughout:

```python
# Before:
elif count == _UNAVAILABLE_THRESHOLD and current_status != "unavailable":

# After:
elif count >= _UNAVAILABLE_THRESHOLD and current_status != "unavailable":
```

The atomic Lua `INCR + EXPIRE` in `_increment_failure_count` ensures no TOCTOU race between incrementing and reading the counter.

**H2 — stale counter cleanup**: the 7-day TTL on each counter key handles tools that are checked infrequently. Additionally, add a counter delete to the tool catalog DELETE route:

In `app/modules/platform/routes.py` (or the tool catalog DELETE handler), after the DB delete:
```python
# H2: Clean up Redis failure counter when a tool is deleted.
from app.core.redis_client import get_redis
redis = get_redis()
await redis.delete(f"mingai:_platform:tool_health:failures:{tool_id}")
```

**H6 — P1 issue tenant assignment**: update `_CREATE_P1_ISSUE_QUERY` to use a platform-scoped insert. The current query uses `SELECT ... FROM users WHERE role = 'platform_admin' LIMIT 1` without ordering, meaning the assigned `tenant_id` is non-deterministic. Replace with:

```sql
-- H6: Use platform sentinel UUID for tenant_id; assign to lowest-ID platform admin.
INSERT INTO issue_reports
    (id, tenant_id, reporter_id, issue_type, description, severity,
     status, blur_acknowledged, metadata)
SELECT
    :id,
    NULL,           -- platform-scope: no tenant_id (or use PLATFORM_SENTINEL_UUID if schema requires non-null)
    u.id,
    'tool_health',
    :description, 'critical', 'open', false,
    CAST(:metadata AS jsonb)
FROM users u
WHERE u.role = 'platform_admin'
ORDER BY u.created_at ASC   -- H6: deterministic assignment
LIMIT 1
```

If `issue_reports.tenant_id` has a NOT NULL constraint, use a platform sentinel UUID stored in env as `PLATFORM_SENTINEL_TENANT_ID` rather than NULL.

**H5 — url_health_monitor TTL**: the `url_health_monitor` job currently uses a static 240s lock TTL. Recalculate to `(agent_count × timeout_per_agent) + buffer`. Apply dynamic TTL at lock acquisition time:

In `run_url_health_monitor_scheduler()` (Phase 2 lock wrapping):
```python
# H5: Dynamic TTL based on registered agent count.
from app.core.session import async_session_factory
async with async_session_factory() as db:
    result = await db.execute(text("SELECT COUNT(*) FROM registry_agents WHERE status = 'active'"))
    agent_count = result.scalar() or 0
timeout_per_agent = 10  # seconds (HEAD request timeout)
buffer = 60  # seconds
dynamic_ttl = max((agent_count * timeout_per_agent) + buffer, 600)  # minimum 600s

async with distributed_job_lock("url_health_monitor", ttl_seconds=dynamic_ttl) as acquired:
    ...
```

Replace `start_tool_health_scheduler(app)` with an asyncio loop:

```python
async def run_tool_health_scheduler() -> None:
    from app.core.scheduler.job_lock import distributed_job_lock
    from app.core.session import AsyncSessionLocal

    logger.info("tool_health_scheduler_started", interval_seconds=_CHECK_INTERVAL_SECONDS)
    while True:
        try:
            jitter = random.randint(-_JITTER_SECONDS, _JITTER_SECONDS)
            await asyncio.sleep(max(0, _CHECK_INTERVAL_SECONDS + jitter))
            async with distributed_job_lock("tool_health", ttl_seconds=480) as acquired:
                if acquired:
                    async with AsyncSessionLocal() as db:
                        summary = await run_tool_health_job(db)
                        await db.commit()
                    logger.info("tool_health_job_complete", **summary)
        except asyncio.CancelledError:
            logger.info("tool_health_scheduler_stopped")
            return
        except Exception as exc:
            logger.error("tool_health_job_failed", error=str(exc))
```

**H7 — tool_health_scheduler never started**: add `asyncio.create_task(run_tool_health_scheduler())` to `main.py` lifespan. This is a pre-existing bug — `start_tool_health_scheduler` was never called from `main.py`. Fix in Phase 2 alongside the provider health task:

```python
# H7: Fix pre-existing gap — tool_health_scheduler was never wired into lifespan.
_tool_health_task = None
try:
    from app.modules.platform.tool_health_job import run_tool_health_scheduler
    _tool_health_task = asyncio.create_task(run_tool_health_scheduler())
    logger.info("tool_health_scheduler_started", interval_seconds=300)
except Exception as exc:
    logger.warning("tool_health_scheduler_startup_failed", error=str(exc))
```

Add shutdown cancellation:
```python
if _tool_health_task is not None and not _tool_health_task.done():
    _tool_health_task.cancel()
    try:
        await _tool_health_task
    except asyncio.CancelledError:
        pass
    logger.info("tool_health_scheduler_stopped")
```

### 2.3 Zombie Row Cleanup on Startup (H4)

Any `job_run_log` row with `status = 'running'` after a pod crash is a zombie — the job never completed but the row was never updated. On the next pod startup, these rows mislead observability queries.

Add to `main.py` lifespan **before** the `yield` (during startup, after the DB engine dispose):

```python
# H4: Mark zombie 'running' rows as 'abandoned'.
# Longest job TTL is 1800s (health_score, query_warming, cost_summary).
# Any row still 'running' after 2× that (3600s = 1 hour) is a zombie.
try:
    from app.core.session import async_session_factory
    from sqlalchemy import text as _text
    async with async_session_factory() as _db:
        await _db.execute(_text("""
            UPDATE job_run_log
            SET status = 'abandoned',
                finished_at = NOW(),
                error_detail = 'Pod crashed or restarted before job completed'
            WHERE status = 'running'
              AND started_at < NOW() - INTERVAL '1 hour'
        """))
        await _db.commit()
    logger.info("zombie_job_rows_abandoned")
except Exception as exc:
    logger.warning("zombie_job_cleanup_failed", error=str(exc))
```

Note: the `abandoned` status is added to the `job_run_log.status` CHECK constraint in migration v042 (Phase 1, Section 1.4 above).

### 2.4 Warm-Up Glossary Cache as Non-Blocking Task (M3)

`warm_up_glossary_cache()` is currently awaited directly in the lifespan startup, blocking the application from accepting requests until it completes. Move to a background task:

```python
# M3: Move glossary warm-up to background task — do not block startup.
# Note: warm_up_glossary_cache is a one-shot function (not a scheduler loop),
# so no distributed lock is needed. If two pods start simultaneously both will
# warm the cache — this is intentional (idempotent Redis SET operations).
try:
    from app.modules.glossary.warmup import warm_up_glossary_cache
    asyncio.create_task(warm_up_glossary_cache())
    logger.info("glossary_warmup_scheduled_background")
except Exception as exc:
    logger.warning("glossary_warmup_startup_failed", error=str(exc))
```

### 2.5 Wrap All 11 Existing Asyncio Schedulers

For each of the 11 remaining jobs, apply the lock wrapper at the execution site inside the `while True` loop. Lock TTLs from research doc 47, Section 5.2:

| Job function | Scheduler file | Lock name | TTL (s) |
|---|---|---|---|
| `run_semantic_cache_cleanup_loop` | `app/core/cache/cleanup_job.py` | `semantic_cache_cleanup` | 600 |
| `run_query_warming_scheduler` | `app/modules/cache/query_warming.py` | `query_warming` | 1800 |
| `run_health_score_scheduler` | `app/modules/platform/health_score_job.py` | `health_score` | 1800 |
| `start_cost_summary_scheduler` | `app/modules/platform/cost_summary_job.py` | `cost_summary` | 1800 |
| `start_azure_cost_scheduler` | `app/modules/platform/azure_cost_job.py` | `azure_cost_pull` | 900 |
| `start_cost_alert_scheduler` | `app/modules/platform/cost_alert_job.py` | `cost_alert` | 600 |
| `run_miss_signals_scheduler` | `app/modules/glossary/miss_signals_job.py` | `glossary_miss_signals` | 600 |
| `run_credential_expiry_scheduler` | `app/modules/documents/credential_expiry_job.py` | `credential_expiry` | 600 |
| `run_url_health_monitor_scheduler` | `app/modules/registry/url_health_monitor.py` | `url_health_monitor` | dynamic (H5) |
| `run_approval_timeout_scheduler` | `app/modules/har/approval_timeout_job.py` | `approval_timeout` | 600 |
| `AgentHealthMonitor.start()` | `app/modules/har/health_monitor.py` | `agent_health_monitor` | 600 |

**Canonical wrapping pattern** (all daily schedulers):

```python
# Before:
await asyncio.sleep(sleep_secs)
await run_health_score_job()

# After:
await asyncio.sleep(sleep_secs)
async with distributed_job_lock("health_score", ttl_seconds=1800) as acquired:
    if acquired:
        await run_health_score_job()
```

**Canonical wrapping pattern** (interval schedulers — semantic cache cleanup, url health monitor):

```python
# Before:
await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
await _run_cleanup()

# After:
await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
async with distributed_job_lock("semantic_cache_cleanup", ttl_seconds=600) as acquired:
    if acquired:
        await _run_cleanup()
```

### 2.6 Replace `_seconds_until_next_run()` with `seconds_until_utc()`

For each of the 7 daily job files identified in Phase 1.3, replace the private function and its call site:

```python
# Before (example from query_warming.py):
from app.modules.cache.query_warming import _seconds_until_next_run
sleep_secs = _seconds_until_next_run()

# After:
from app.core.scheduler.timing import seconds_until_utc
sleep_secs = seconds_until_utc(hour=3, minute=0)  # 03:00 UTC for query warming
```

UTC fire times (from `main.py` log messages and existing implementations):

| Job | Fire time UTC |
|---|---|
| `health_score` | 02:00 |
| `query_warming` | 03:00 |
| `cost_summary` | 03:30 |
| `azure_cost_pull` | 03:45 |
| `cost_alert` | 04:00 |
| `glossary_miss_signals` | 04:30 |
| `credential_expiry` | 05:00 |

The `AgentHealthMonitor`, `url_health_monitor`, `approval_timeout`, `semantic_cache_cleanup`, `provider_health`, and `tool_health` jobs are interval-based (not clock-targeted) and do not use `seconds_until_utc()`.

**M1 — cold-start skip fix**: after computing `sleep_secs` with `seconds_until_utc()`, check whether the result is greater than 23 hours (indicating the scheduled time just passed). If so, and if `job_run_log` has no completed row for this job today, run the job immediately (with distributed lock protection) before entering the normal sleep loop. Implement in Phase 3 when `job_run_log` write infrastructure is available.

### 2.7 `job_run_log` 90-Day Cleanup

Add a cleanup pass for rows older than 90 days inside the existing `semantic_cache_cleanup` job (the highest-frequency job, running hourly, is the natural host for maintenance tasks):

```python
# Inside _run_cleanup() in app/core/cache/cleanup_job.py — add after semantic cache delete:
await session.execute(
    text("DELETE FROM job_run_log WHERE started_at < NOW() - INTERVAL '90 days'")
)
```

This prevents unbounded table growth at no cost — it piggybacks on an existing hourly session. (H3 note: simple time-based retention replaces the previous year-partition recommendation.)

### 2.8 Deliverables — Phase 2

| File | Change type |
|---|---|
| `src/backend/app/modules/platform/provider_health_job.py` | MODIFY — replace `start_provider_health_scheduler` with `run_provider_health_scheduler`; add M2 shutdown |
| `src/backend/app/modules/platform/tool_health_job.py` | MODIFY — replace `_failure_counts` dict with Redis-backed helpers (H1 atomic Lua, H2 7-day TTL); replace `start_tool_health_scheduler` with `run_tool_health_scheduler`; fix `>= _UNAVAILABLE_THRESHOLD` (H1); fix P1 issue query (H6) |
| `src/backend/app/modules/platform/routes.py` | MODIFY — add tool DELETE hook to flush Redis counter (H2) |
| `src/backend/app/main.py` | MODIFY — replace `start_provider_health_scheduler(app)`; add `_tool_health_task` (H7 bug fix); add H4 zombie cleanup on startup; move glossary warmup to `create_task` (M3); add M2 APScheduler shutdown; add shutdown cancellation for both health tasks; 11× add distributed lock wrapping |
| `src/backend/app/core/cache/cleanup_job.py` | MODIFY — add lock wrap; add `job_run_log` 90-day cleanup |
| `src/backend/app/modules/cache/query_warming.py` | MODIFY — replace `_seconds_until_next_run()`; add lock wrap |
| `src/backend/app/modules/platform/health_score_job.py` | MODIFY — replace `_seconds_until_next_run()`; add lock wrap |
| `src/backend/app/modules/platform/cost_summary_job.py` | MODIFY — replace `_seconds_until_next_run()`; add lock wrap |
| `src/backend/app/modules/platform/azure_cost_job.py` | MODIFY — replace `_seconds_until_next_run()`; add lock wrap |
| `src/backend/app/modules/platform/cost_alert_job.py` | MODIFY — replace `_seconds_until_next_run()`; add lock wrap |
| `src/backend/app/modules/glossary/miss_signals_job.py` | MODIFY — replace `_seconds_until_next_run()`; add lock wrap |
| `src/backend/app/modules/documents/credential_expiry_job.py` | MODIFY — replace `_seconds_until_next_run()`; add lock wrap |
| `src/backend/app/modules/registry/url_health_monitor.py` | MODIFY — add dynamic TTL (H5); add lock wrap |
| `src/backend/app/modules/har/approval_timeout_job.py` | MODIFY — add lock wrap |
| `src/backend/app/modules/har/health_monitor.py` | MODIFY — add lock wrap inside `start()` loop |

---

## Phase 3: Observability (Sprint 2)

**Goal**: Write `job_run_log` records in all 13 jobs; expose history through two API endpoints; add M1 missed-job detection; convert `AgentHealthMonitor` to match canonical scheduler pattern (L1).

### 3.1 Job Run Log Write Pattern

Implement a context manager helper to reduce boilerplate across 13 jobs:

```python
# app/core/scheduler/job_log.py
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import structlog
from sqlalchemy import text
from app.core.session import async_session_factory

logger = structlog.get_logger()


@asynccontextmanager
async def job_run_context(
    job_name: str,
    tenant_id: Optional[str] = None,
) -> AsyncIterator[dict]:
    """
    Context manager that writes job_run_log START and FINISH records.

    Usage:
        async with job_run_context("health_score") as ctx:
            processed = await run_actual_job()
            ctx["records_processed"] = processed
            ctx["metadata"] = {"tenant_count": 12}

    On exception, status is set to 'failed' and error_detail is populated.
    The exception is re-raised after the log record is written.
    """
    run_id = str(uuid.uuid4())
    ctx: dict = {"records_processed": None, "metadata": None}
    job_start = time.monotonic()

    async with async_session_factory() as db:
        await db.execute(
            text("""
                INSERT INTO job_run_log (id, job_name, tenant_id, started_at, status)
                VALUES (:id, :job_name, :tenant_id, NOW(), 'running')
            """),
            {"id": run_id, "job_name": job_name, "tenant_id": tenant_id},
        )
        await db.commit()

    exc_to_raise = None
    status = "completed"
    error_detail = None
    try:
        yield ctx
    except Exception as exc:
        status = "failed"
        error_detail = str(exc)
        exc_to_raise = exc
    finally:
        elapsed_ms = round((time.monotonic() - job_start) * 1000, 1)
        meta = ctx.get("metadata") or {}
        meta["duration_ms"] = elapsed_ms
        async with async_session_factory() as db:
            await db.execute(
                text("""
                    UPDATE job_run_log
                    SET finished_at        = NOW(),
                        status             = :status,
                        records_processed  = :processed,
                        error_detail       = :error,
                        metadata           = CAST(:meta AS jsonb)
                    WHERE id = :id
                """),
                {
                    "id": run_id,
                    "status": status,
                    "processed": ctx.get("records_processed"),
                    "error": error_detail,
                    "meta": json.dumps(meta),
                },
            )
            await db.commit()

    if exc_to_raise is not None:
        raise exc_to_raise
```

**Integration call site** in each job (example for `health_score_job.py`):

```python
from app.core.scheduler.job_log import job_run_context

async def run_health_score_job() -> None:
    async with job_run_context("health_score") as ctx:
        # ... existing per-tenant loop ...
        ctx["records_processed"] = processed_tenant_count
        ctx["metadata"] = {"tenant_count": total, "skipped": skipped}
```

For per-tenant iterating jobs (health score, query warming, cost summary, etc.), one aggregate `job_run_log` row covers the full batch. Per-tenant detail lives in the existing structlog events — the API does not expose per-tenant sub-rows in Phase 3.

### 3.2 M1 — Cold-Start Missed-Job Recovery

After Phase 3 ships `job_run_log` writes, implement the missed-job check in `seconds_until_utc()` call sites. For each daily scheduler, after computing `sleep_secs`:

```python
from app.core.scheduler.timing import seconds_until_utc
from app.core.session import async_session_factory
from sqlalchemy import text

sleep_secs = seconds_until_utc(hour=2, minute=0)

# M1: If time-until-next-run > 23h, the scheduled time just passed.
# Check job_run_log: if no completed run today, run immediately.
if sleep_secs > 23 * 3600:
    async with async_session_factory() as db:
        result = await db.execute(text("""
            SELECT 1 FROM job_run_log
            WHERE job_name = :job_name
              AND status = 'completed'
              AND started_at >= NOW() - INTERVAL '24 hours'
            LIMIT 1
        """), {"job_name": "health_score"})
        if result.fetchone() is None:
            logger.info("missed_job_detected_running_immediately", job_name="health_score")
            async with distributed_job_lock("health_score", ttl_seconds=1800) as acquired:
                if acquired:
                    await run_health_score_job()
```

This check runs once at startup per scheduler. The distributed lock prevents two pods that restart simultaneously from both running the missed job.

### 3.3 L1 — Convert `AgentHealthMonitor` to Canonical Pattern

`AgentHealthMonitor` in `app/modules/har/health_monitor.py` uses a class-based `start()` method with an internal asyncio loop. Convert to a standalone `run_agent_health_scheduler()` function matching all other schedulers. This eliminates the class-level state and makes lock wrapping straightforward:

```python
async def run_agent_health_scheduler(
    db_session_factory,
    interval_seconds: int = 3600,
) -> None:
    from app.core.scheduler.job_lock import distributed_job_lock
    logger.info("agent_health_scheduler_started", interval_seconds=interval_seconds)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            async with distributed_job_lock("agent_health_monitor", ttl_seconds=600) as acquired:
                if acquired:
                    async with job_run_context("agent_health_monitor") as ctx:
                        result = await _run_agent_health_check(db_session_factory)
                        ctx["records_processed"] = result.agents_checked
        except asyncio.CancelledError:
            logger.info("agent_health_scheduler_stopped")
            return
        except Exception as exc:
            logger.error("agent_health_job_failed", error=str(exc))
```

Update `main.py` to call `asyncio.create_task(run_agent_health_scheduler(async_session_factory))` instead of `asyncio.create_task(monitor.start())`.

### 3.4 Platform Admin Endpoint: `GET /api/v1/platform/jobs/history`

Add to `app/modules/platform/routes.py` (alongside existing PA-* routes):

```python
@router.get("/jobs/history", response_model=JobHistoryResponse)
async def get_job_history(
    job_name: Optional[str] = Query(None),
    since_days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_platform_db),
    _: UserContext = Depends(require_platform_admin),
):
    """
    Return recent job_run_log entries for platform admins.

    Filterable by job_name. Defaults to last 7 days, 100 rows.
    Supports up to 90-day lookback, 500 rows per request.
    """
    params = {"since": f"-{since_days} days", "limit": limit}
    sql = """
        SELECT id, job_name, tenant_id, started_at, finished_at,
               status, records_processed, error_detail, metadata
        FROM job_run_log
        WHERE started_at >= NOW() - CAST(:since AS INTERVAL)
    """
    if job_name:
        sql += " AND job_name = :job_name"
        params["job_name"] = job_name
    sql += " ORDER BY started_at DESC LIMIT :limit"

    rows = (await db.execute(text(sql), params)).mappings().all()
    return {"items": [dict(r) for r in rows], "total": len(rows)}
```

**Response model** (`JobHistoryResponse`):
```python
class JobRunEntry(BaseModel):
    id: UUID
    job_name: str
    tenant_id: Optional[UUID]
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    records_processed: Optional[int]
    error_detail: Optional[str]
    metadata: Optional[dict]

class JobHistoryResponse(BaseModel):
    items: list[JobRunEntry]
    total: int
```

### 3.5 Tenant Admin Endpoint: `GET /api/v1/tenant/jobs` (L2)

**L2 — outcome-centric signals**: the tenant-facing job endpoint must NOT expose raw `job_run_log` rows. Tenant admins do not understand job names like `credential_expiry` or `glossary_miss_signals` — they need outcome signals. Return a purpose-built status object backed by `tenant_configs` or a view:

```python
@router.get("/jobs", response_model=TenantJobStatusResponse)
async def get_tenant_job_status(
    db: AsyncSession = Depends(get_tenant_db),
    ctx: UserContext = Depends(require_tenant_admin),
):
    """
    Return outcome-centric job status signals for tenant admins.

    Returns last_sync_completed_at, last_credentials_checked_at, etc.
    These are sourced from tenant_configs or a tenant_job_status view —
    NOT raw job_run_log rows. Tenant admins should not need to understand
    internal job names.
    """
    rows = (await db.execute(
        text("""
            SELECT
                MAX(CASE WHEN job_name = 'credential_expiry' AND status = 'completed'
                         THEN finished_at END)  AS last_credentials_checked_at,
                MAX(CASE WHEN job_name = 'query_warming' AND status = 'completed'
                         THEN finished_at END)  AS last_query_warming_completed_at,
                MAX(CASE WHEN job_name = 'glossary_miss_signals' AND status = 'completed'
                         THEN finished_at END)  AS last_glossary_signals_at
            FROM job_run_log
            WHERE tenant_id = :tenant_id
              AND started_at >= NOW() - INTERVAL '7 days'
        """),
        {"tenant_id": ctx.tenant_id},
    )).mappings().all()
    return {"status": dict(rows[0]) if rows else {}}
```

**Response model** (`TenantJobStatusResponse`):
```python
class TenantJobStatusResponse(BaseModel):
    status: dict  # keys: last_credentials_checked_at, last_query_warming_completed_at, etc.
```

This pivot may be extended in a future sprint to include SharePoint sync timestamp and document count once SharePoint sync writes to `job_run_log`.

### 3.6 Job-to-tenant_id Mapping

For Phase 3, only jobs that iterate tenants write a `tenant_id` in `job_run_log`. The mapping:

| Job | Writes tenant_id rows |
|---|---|
| `query_warming` | Yes — one row per tenant |
| `credential_expiry` | Yes — one row per tenant |
| `glossary_miss_signals` | Yes — one row per tenant |
| `health_score` | No — aggregate platform row only |
| `cost_summary` | No — aggregate platform row only |
| `azure_cost_pull` | No — platform row |
| `cost_alert` | No — platform row |
| `semantic_cache_cleanup` | No — platform row |
| `provider_health` | No — platform row |
| `tool_health` | No — platform row |
| `url_health_monitor` | No — platform row |
| `approval_timeout` | No — platform row |
| `agent_health_monitor` | No — platform row |

### 3.7 Deliverables — Phase 3

| File | Change type |
|---|---|
| `src/backend/app/core/scheduler/job_log.py` | NEW |
| `src/backend/app/modules/platform/health_score_job.py` | MODIFY — add `job_run_context`; add M1 missed-job check |
| `src/backend/app/modules/cache/query_warming.py` | MODIFY — add `job_run_context` with per-tenant rows; add M1 missed-job check |
| `src/backend/app/modules/platform/cost_summary_job.py` | MODIFY — add `job_run_context`; add M1 missed-job check |
| `src/backend/app/modules/platform/azure_cost_job.py` | MODIFY — add `job_run_context`; add M1 missed-job check |
| `src/backend/app/modules/platform/cost_alert_job.py` | MODIFY — add `job_run_context`; add M1 missed-job check |
| `src/backend/app/modules/glossary/miss_signals_job.py` | MODIFY — add `job_run_context` with per-tenant rows; add M1 missed-job check |
| `src/backend/app/modules/documents/credential_expiry_job.py` | MODIFY — add `job_run_context` with per-tenant rows; add M1 missed-job check |
| `src/backend/app/modules/registry/url_health_monitor.py` | MODIFY — add `job_run_context` |
| `src/backend/app/modules/har/approval_timeout_job.py` | MODIFY — add `job_run_context` |
| `src/backend/app/modules/har/health_monitor.py` | MODIFY — convert to `run_agent_health_scheduler()` (L1); add `job_run_context` |
| `src/backend/app/core/cache/cleanup_job.py` | MODIFY — add `job_run_context` |
| `src/backend/app/modules/platform/provider_health_job.py` | MODIFY — add `job_run_context` |
| `src/backend/app/modules/platform/tool_health_job.py` | MODIFY — add `job_run_context` |
| `src/backend/app/modules/platform/routes.py` | MODIFY — add `GET /api/v1/platform/jobs/history` |
| `src/backend/app/modules/tenant/jobs_routes.py` (or documents/routes.py) | MODIFY/NEW — add `GET /api/v1/tenant/jobs` (outcome-centric — L2) |
| `src/backend/app/main.py` | MODIFY — update `AgentHealthMonitor.start()` to `run_agent_health_scheduler()` (L1) |

---

## Phase 4: Hardening (Sprint 3)

**Goal**: Per-tenant job throttling (heartbeat is already in Phase 1 — C1).

### 4.1 Heartbeat Extension

**Already implemented in Phase 1** (C1 remediation). The `distributed_job_lock` context manager in `job_lock.py` includes heartbeat renewal by default (`heartbeat=True`). No additional Phase 4 work for heartbeat.

For reference, the heartbeat defaults are:
- `heartbeat=True` for all locks
- `heartbeat_interval = ttl_seconds // 2` (renewed at half-TTL to guard against Redis latency)
- Heartbeat task is cancelled before lock release in the `finally` block

### 4.2 SIGTERM Graceful Lock Release

When a pod receives SIGTERM (Kubernetes drain, rolling deploy), FastAPI's lifespan shutdown cancels all background tasks via `task.cancel()`. The `asyncio.CancelledError` propagates into the `distributed_job_lock` context manager's `finally` block, which cancels the heartbeat task then calls the Lua release script before exit.

This is handled by the pattern implemented in Phase 1. No additional code is needed.

**Verify** that the heartbeat task is cancelled before the release script runs (it is — `_hb_task.cancel()` is called in the `finally` block before `redis.eval(_RELEASE_SCRIPT, ...)`). Without this ordering, the heartbeat could re-extend the lock after the main task has started to shut down.

**Kubernetes `terminationGracePeriodSeconds`**: set to at least 60 seconds in the Deployment spec to allow in-flight jobs to complete their current operation and release the lock cleanly. The longest expected job runtime is `run_health_score_job` at approximately 30 seconds for 20 tenants. 60 seconds is a safe minimum.

### 4.3 Per-Tenant Job Throttling

Prevent a single large tenant from consuming disproportionate LLM quota during background job runs. Implemented as a Redis-backed rate limiter inside the per-tenant iteration loop.

```python
# app/core/scheduler/tenant_throttle.py

async def should_throttle_tenant(
    tenant_id: str,
    job_name: str,
    max_tokens_per_hour: int,
) -> bool:
    """
    Returns True if this tenant has consumed more than max_tokens_per_hour
    tokens from background jobs in the last 60 minutes.

    Key: mingai:_platform:job_throttle:{job_name}:{tenant_id}
    TTL: 3600 seconds
    Value: cumulative token count this window
    """
    from app.core.redis_client import get_redis
    redis = get_redis()
    key = f"mingai:_platform:job_throttle:{job_name}:{tenant_id}"
    current = await redis.get(key)
    return int(current or 0) >= max_tokens_per_hour


async def record_tenant_tokens(
    tenant_id: str,
    job_name: str,
    tokens_used: int,
) -> None:
    from app.core.redis_client import get_redis
    redis = get_redis()
    key = f"mingai:_platform:job_throttle:{job_name}:{tenant_id}"
    pipe = redis.pipeline()
    pipe.incrby(key, tokens_used)
    pipe.expire(key, 3600)
    await pipe.execute()
```

Phase 4 applies throttling to `query_warming` (highest LLM cost per tenant) first. Integration in `query_warming.py` per-tenant loop:

```python
for tenant_id in tenant_ids:
    if await should_throttle_tenant(tenant_id, "query_warming", max_tokens_per_hour=50_000):
        logger.warning("query_warming_tenant_throttled", tenant_id=tenant_id)
        continue
    warmed = await warm_tenant_queries(tenant_id)
    await record_tenant_tokens(tenant_id, "query_warming", tokens_used=warmed.tokens)
```

Default throttle limit: 50,000 tokens/hour (configurable via env `JOB_WARMING_MAX_TOKENS_PER_HOUR`). Professional and Enterprise tenants can have a higher limit configured in `tenant_settings`.

### 4.4 Deliverables — Phase 4

| File | Change type |
|---|---|
| `src/backend/app/core/scheduler/tenant_throttle.py` | NEW |
| `src/backend/app/modules/cache/query_warming.py` | MODIFY — add per-tenant throttle |
| `src/backend/k8s/deployment.yaml` (or equivalent) | MODIFY — set `terminationGracePeriodSeconds: 60` |

---

## Red Team Remediation

This section documents all red team findings and their resolution across the plan. Use this as the canonical traceability record.

### CRITICAL (C) — Fixed in Phase 1

| ID | Finding | Resolution |
|---|---|---|
| C1 | Lock TTL expiry mid-run could allow two pods to run the same job concurrently. The heartbeat was deferred to Phase 4, leaving Phases 1–3 exposed. | **Moved to Phase 1.** `distributed_job_lock` in `job_lock.py` includes heartbeat renewal by default (`heartbeat=True`, interval = `ttl_seconds // 2`). Heartbeat is a background `asyncio.create_task` inside the lock context, cancelled before lock release. |
| C2 | Redis AOF/RDB persistence was not mentioned as a prerequisite. If Redis restarts without persistence, the lock key is lost but not re-checked, leading to missed lock detection (or a stale key if Redis restarts mid-run). | **Added as Phase 1 prerequisite** (Section 1.6). Deployment checklist requires AOF or RDB persistence enabled, with `mingai:_platform:job_lock:*` keys in scope. |

### HIGH (H) — Fixed in Phase 2

| ID | Finding | Resolution |
|---|---|---|
| H1 | `count == _UNAVAILABLE_THRESHOLD` equality check misses counters that skip past 10 (e.g., pre-populated counters from a previous deployment). Also, `INCR` and the counter read were not atomic. | Fixed `== 10` → `>= _UNAVAILABLE_THRESHOLD`. Added atomic Lua `INCR + EXPIRE` script in `_increment_failure_count()`. |
| H2 | Tool failure counter Redis keys had no TTL — deleted tools would accumulate stale keys indefinitely. | 7-day TTL on all counter keys (set atomically on each INCR). Counter key deleted on tool catalog DELETE route. |
| H3 | `job_run_log` only had single-column indexes. `(tenant_id, started_at DESC)` and `(job_name, started_at DESC)` composite indexes were missing, causing slow queries. Year-partition recommendation added complexity for limited benefit. | Composite indexes added in migration v042. Year-partition dropped; 90-day retention via cleanup job instead. |
| H4 | `job_run_log` rows with `status = 'running'` from crashed pods were never cleaned up, misleading observability. | Startup cleanup query in `main.py` lifespan marks rows with `status = 'running'` AND `started_at < NOW() - 1 hour` as `status = 'abandoned'`. `abandoned` status added to CHECK constraint in v042. |
| H5 | `url_health_monitor` lock TTL was static (240s) regardless of registered agent count. With many agents, the job runtime exceeds TTL. | Dynamic TTL at lock acquisition: `max((agent_count × timeout_per_agent) + buffer, 600)`. Agent count queried from DB at lock time. |
| H6 | P1 issue creation query for tool health used `LIMIT 1` without `ORDER BY`, giving non-deterministic `reporter_id` assignment. Also, `tenant_id` was inherited from a random platform admin's tenant, not a platform sentinel. | `ORDER BY u.created_at ASC` added to platform admin subquery. `tenant_id` set to NULL (or platform sentinel UUID if schema requires non-null). |
| H7 | `tool_health_scheduler` was never wired into `main.py` lifespan — a pre-existing silent failure. | Added `asyncio.create_task(run_tool_health_scheduler())` to `main.py` lifespan in Phase 2. |

### MEDIUM (M) — Fixed in Phase 2–3

| ID | Finding | Resolution |
|---|---|---|
| M1 | `seconds_until_utc()` 60s floor causes a startup that happens just after a scheduled time to miss that job for 24 hours (cold-start miss). | Phase 3: after computing `sleep_secs`, if `sleep_secs > 23h`, query `job_run_log` for a completed run in the last 24 hours. If none found, run immediately with distributed lock. Documented as known behaviour in runbook until Phase 3 ships. |
| M2 | `APScheduler.shutdown()` calls were absent from lifespan teardown during the transition period, potentially leaving APScheduler threads running during rolling deploys. | Added `app.state.provider_health_scheduler.shutdown(wait=False)` (and tool health equivalent) to shutdown block in Phase 2 as belt-and-suspenders during rolling-deploy window. |
| M3 | `warm_up_glossary_cache()` was awaited directly in lifespan startup, blocking application readiness until it completes. | Moved to `asyncio.create_task()` in Phase 2. One-shot function (not a loop), so no lock needed. Documented: duplicate-startup warmups are idempotent (Redis SET operations). |
| M4 | The 60s floor in `seconds_until_utc()` and the drain-window miss were undocumented. | Documented in the `seconds_until_utc()` docstring (Phase 1) and deployment runbook (Phase 1 checklist C2c). Phase 3 resolves with M1 fix. |

### LOW (L) — Fixed in Phase 3

| ID | Finding | Resolution |
|---|---|---|
| L1 | `AgentHealthMonitor` used a class-based `start()` pattern inconsistent with all other schedulers, making lock wrapping awkward and the pattern harder to follow. | Phase 3: convert to `run_agent_health_scheduler()` standalone function. `main.py` updated to call `asyncio.create_task(run_agent_health_scheduler(...))`. |
| L2 | `/api/v1/tenant/jobs` endpoint proposed to return raw `job_run_log` rows. Tenant admins cannot interpret job names or internal schema. | Phase 3: endpoint returns outcome-centric signals (`last_credentials_checked_at`, `last_query_warming_completed_at`, `last_glossary_signals_at`) backed by a `job_run_log` pivot query, not raw rows. |

---

## Migration Strategy

### Zero-Downtime Rollout

The migration is designed for zero-downtime rolling deployments:

1. **Phase 1** (migration v042 + new scheduler files): apply Alembic migration first. The new table and new Python files are inert — no job calls them yet. Old pods continue running APScheduler for provider and tool health; the other 11 jobs run without locks.

2. **Phase 2** (lock wrap + APScheduler removal): deploy new pods with the lock-wrapped scheduler loops. During the rolling deploy, a brief window exists where one old pod (no lock) and one new pod (with lock) coexist:
   - Old pod: runs a job unconditionally (as today).
   - New pod: attempts lock acquisition. If acquired, runs the job. If not (old pod ran it first), skips.
   - Worst case: one duplicate run per job during the deploy window — identical to today's behaviour. This is acceptable.
   - Once all pods are on the new version, duplicate execution is eliminated.

3. **Phase 3** (job_run_log writes): purely additive. If a write fails (transient DB error), the log helper catches and logs the exception but does not interrupt job execution. Jobs continue running correctly.

4. **Phase 4** (throttling): purely additive configuration changes. Can be rolled back by removing the throttle call.

### Backward Compatibility — Single-Instance Deployments

For deployments running a single pod (local development, small self-hosted installations):
- The distributed lock is acquired unconditionally (no competing pods), so every job runs as before.
- Redis must be available (it already is — it's required for JWT invalidation and caching).
- If Redis is unavailable at job execution time, `get_redis()` raises an exception. The `except Exception` guard in each scheduler loop catches it, logs it, and the loop retries on the next cycle. This is the same failure mode as today for any Redis-dependent operation.

### Rollback Plan

Each phase is independently reversible:

| Phase | Rollback action |
|---|---|
| Phase 1 | Run `alembic downgrade 041` to drop `job_run_log`. Remove new scheduler files (no code references them yet). |
| Phase 2 | Revert `provider_health_job.py` and `tool_health_job.py` to use `start_*_scheduler(app)` pattern. Remove lock wrapping from all 11 other schedulers (two-line revert per file). Remove H4 zombie cleanup and M3 glossary task from `main.py`. |
| Phase 3 | Remove `job_run_context` calls from job files. Remove API endpoints. `job_run_log` table remains but is empty. |
| Phase 4 | Remove `tenant_throttle.py` imports from `query_warming.py`. |

APScheduler re-introduction (if Phase 2 rollback is needed): the `ImportError` guard in the original `start_*_scheduler()` functions means APScheduler can be added back to `pyproject.toml` without a code change — the guard will silently succeed once the package is installed.

---

## Testing Strategy

### Phase 1 — Unit Tests

**File**: `tests/unit/test_job_lock.py`

Test the `distributed_job_lock` context manager with a real Redis test instance (follow the no-mock rule for Tier 2+; this is fast enough to run with an in-process Redis fakeredis for unit tests).

```
test_lock_acquired_when_key_absent
test_lock_skipped_when_key_present
test_lock_released_after_context_exit
test_lock_not_released_if_ttl_expired_and_reacquired  (Lua script correctness)
test_heartbeat_extends_ttl_before_expiry               (C1 — heartbeat now in Phase 1)
test_heartbeat_cancelled_on_context_exit               (C1)
test_lock_released_on_cancelled_error                  (C1)
test_seconds_until_utc_returns_positive_value
test_seconds_until_utc_returns_at_least_60_seconds     (guard against double-fire)
test_seconds_until_utc_rolls_over_midnight
```

**File**: `tests/unit/test_job_run_log.py`

```
test_job_run_context_writes_start_record
test_job_run_context_writes_completed_record
test_job_run_context_writes_failed_record_on_exception
test_job_run_context_reraises_exception
test_job_run_context_writes_records_processed_and_metadata
```

### Phase 2 — Integration Tests

**File**: `tests/integration/test_distributed_scheduling.py`

Use real Redis and real test DB. No mocking.

```
test_two_concurrent_provider_health_schedulers_only_one_executes
    -- Launch two asyncio tasks both attempting the lock
    -- Assert run_provider_health_job called exactly once

test_tool_failure_counter_survives_restart
    -- Set Redis failure counter to 5
    -- Simulate restart (re-import module, new function call)
    -- Assert _get_failure_count returns 5

test_tool_failure_counter_expires_after_7_days
    -- Set Redis key with ex=1 (1 second TTL for test)
    -- Sleep 2 seconds
    -- Assert _get_failure_count returns 0

test_provider_health_scheduler_starts_via_create_task
    -- Call run_provider_health_scheduler() as asyncio.create_task
    -- Assert no APScheduler import occurs (no ImportError, no AttributeError)

test_tool_unavailable_threshold_fires_at_gte_10           (H1)
    -- Set failure counter to 11 (simulates counter skip)
    -- Assert P1 issue is created (>= check catches it)

test_tool_failure_counter_deleted_on_tool_delete          (H2)
    -- Create tool, increment counter to 5
    -- Call DELETE /api/v1/platform/tool_catalog/{tool_id}
    -- Assert Redis key no longer exists

test_zombie_running_rows_marked_abandoned_on_startup       (H4)
    -- Insert job_run_log row with status='running', started_at=NOW()-2h
    -- Simulate lifespan startup
    -- Assert row status='abandoned'

test_url_health_monitor_ttl_scales_with_agent_count        (H5)
    -- Register 100 active agents
    -- Assert lock TTL >= 100*10 + 60 = 1060s
```

**File**: `tests/integration/test_job_run_log_persistence.py`

```
test_job_run_log_written_for_health_score_job
test_job_run_log_tenant_id_null_for_platform_jobs
test_job_run_log_tenant_id_set_for_per_tenant_jobs
test_job_run_log_status_failed_on_exception
test_job_run_log_abandoned_status_valid_in_check_constraint  (H4)
```

### Phase 3 — Integration Tests

**File**: `tests/integration/test_job_history_api.py`

```
test_platform_admin_can_list_all_job_history
test_platform_admin_can_filter_by_job_name
test_platform_admin_can_filter_by_since_days
test_tenant_admin_gets_outcome_signals_not_raw_rows         (L2)
test_tenant_admin_sees_only_own_tenant_outcome_signals      (L2)
test_tenant_admin_cannot_see_other_tenant_jobs
test_unauthenticated_request_returns_401
test_non_admin_user_returns_403

test_missed_job_runs_immediately_on_cold_start              (M1)
    -- Insert no job_run_log row for "health_score" in last 24h
    -- Simulate startup where seconds_until_utc returns >23h
    -- Assert run_health_score_job called immediately

test_no_missed_job_duplicate_if_already_ran_today           (M1)
    -- Insert completed job_run_log row for "health_score" started 2h ago
    -- Assert run_health_score_job NOT called on startup
```

### Phase 4 — Integration Tests

**File**: `tests/integration/test_tenant_throttle.py`

```
test_throttle_blocks_tenant_over_limit
test_throttle_allows_tenant_under_limit
test_throttle_resets_after_window_expiry
```

### E2E Tests

**File**: `tests/e2e/test_job_history_endpoints.py`

```
test_platform_admin_views_job_history_page
    -- Log in as platform admin
    -- Navigate to job history
    -- Assert last run for each of 13 jobs is visible

test_tenant_admin_views_sync_outcome_signals
    -- Log in as tenant admin
    -- Navigate to job status page
    -- Assert last_credentials_checked_at and last_query_warming_completed_at are visible
    -- Assert no raw job_run_log data exposed (L2)
```

---

## Success Metrics

### Functional Correctness
- Zero duplicate job executions detected in logs across a 7-day multi-pod deployment.
- `job_run_log` has exactly one `completed` row per job per scheduled interval (±1 for clock drift recovery at startup).
- Provider and tool health jobs start reliably on every pod startup (no more silent `ImportError` skip or missing `create_task` call — H7).

### Observability
- Platform admin can query last 30 days of job history via `GET /api/v1/platform/jobs/history` in < 200ms (composite index on `(job_name, started_at DESC)` — H3).
- Tenant admin can see outcome signals via `GET /api/v1/tenant/jobs` without understanding internal job names (L2).
- Support team can answer "did tenant X's sync run last night?" in < 10 seconds using the platform admin UI.

### Infrastructure
- APScheduler import references: 0 (grep for `apscheduler` returns no results in `app/`).
- `_seconds_until_next_run()` private function definitions: 0 (all replaced by `seconds_until_utc()`).
- `_failure_counts` in-process dict: 0 (replaced by Redis-backed helpers with atomic Lua INCR — H1).

### Reliability
- Lock TTL expires within one interval cycle on pod crash — next pod acquires lock and runs the job at the next scheduled time. Heartbeat prevents mid-run expiry (C1).
- `job_run_log` table size: < 500,000 rows at 50 active tenants over 12 months (well within no-partition threshold with 90-day retention — H3).
- Zombie `running` rows cleaned up within 60 seconds of pod restart (H4).

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Redis unavailable at job execution time — all 13 jobs fail to acquire lock | Low (Redis is already critical path) | High for that cycle | `except Exception` guard in each scheduler loop catches `ConnectionError`; job skips for that cycle and retries at next interval. Log event `job_lock_redis_unavailable`. |
| Lock TTL too short — job exceeds TTL | Low (C1 heartbeat prevents expiry; initial TTLs set at 2× measured runtime) | Low (heartbeat renews at TTL/2) | Heartbeat implemented in Phase 1. Monitor `duration_ms` in `job_run_log.metadata`; alert if `duration_ms > 0.5 * ttl_ms`. |
| Tool failure counters reset on first deploy — P1 issue not raised for already-degraded tools | Low (only affects the first deploy post-migration) | Low (recovers within 10 check cycles = 50 min) | Document as known deploy-day behaviour. Consider a one-time migration script that reads current `tool_catalog.health_status = 'degraded'` and pre-populates Redis counters to `_DEGRADED_THRESHOLD` before Phase 2 ships. |
| `job_run_log` INSERT fails (transient DB error) — causes job to not run | Low | High | `job_run_context` does NOT gate job execution on the INSERT. The INSERT exception is caught in the helper; the job runs regardless. A separate log warning records the failure. |
| `apscheduler` accidentally re-added to `pyproject.toml` by a future contributor | Low | Low | Add a CI lint rule: `grep 'apscheduler' pyproject.toml && exit 1`. Document in the PR description for this change. |
| Rolling deploy window causes one duplicate run per job | Certain (by design) | Very Low (idempotent jobs use ON CONFLICT upsert) | Acceptable. Same frequency as today's multi-pod scenario. Notifications (credential expiry, cost alert) use deduplication via `IN ('sent', 'suppressed')` status checks. |
| `job_run_log` table grows beyond retention expectations | Low (90-day cleanup in Phase 2) | Low | Cleanup job handles this via `semantic_cache_cleanup` hourly pass. At 500 tenants × 13 jobs × 90 days = ~585K rows — well within the no-partition threshold. |
| Lua script unsupported on managed Redis (AWS ElastiCache, Azure Cache) | Very Low (all three support `EVAL`) | High (lock release fails, stale keys accumulate) | Verified: AWS ElastiCache (6.x+), Azure Cache for Redis (6.x+), and GCP Memorystore all support `EVAL`. Fallback: replace Lua script with non-atomic `GET + DEL` if a deployment target is identified that lacks `EVAL`. |
| Redis restarts without AOF/RDB — lock key lost mid-job | Low (C2 deployment checklist enforces persistence) | Medium (one missed lock detection per pod per Redis restart) | C2 deployment checklist validates persistence before Phase 1 deploy. TTL naturally expires within one job interval, restoring correct behaviour. |
| url_health_monitor dynamic TTL query adds latency to lock acquisition | Low (one COUNT query, < 5ms) | Very Low | Acceptable. Agent count changes slowly; could be cached in Redis with 5-minute TTL if query latency becomes a concern. |

---

## File Change Surface (Complete)

| File | Change type | Phase |
|---|---|---|
| `src/backend/app/core/scheduler/__init__.py` | NEW | 1 |
| `src/backend/app/core/scheduler/job_lock.py` | NEW (with heartbeat — C1) | 1 |
| `src/backend/app/core/scheduler/timing.py` | NEW | 1 |
| `src/backend/app/core/scheduler/job_log.py` | NEW | 3 |
| `src/backend/app/core/scheduler/tenant_throttle.py` | NEW | 4 |
| `src/backend/alembic/versions/v042_job_run_log.py` | NEW (composite indexes H3, abandoned status H4) | 1 |
| `src/backend/app/modules/platform/provider_health_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/platform/tool_health_job.py` | MODIFY (H1, H2, H6) | 2, 3 |
| `src/backend/app/modules/platform/routes.py` | MODIFY (H2 tool delete hook, PA jobs endpoint) | 2, 3 |
| `src/backend/app/main.py` | MODIFY (H4, H7, M2, M3) | 2 |
| `src/backend/app/core/cache/cleanup_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/cache/query_warming.py` | MODIFY | 2, 3, 4 |
| `src/backend/app/modules/platform/health_score_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/platform/cost_summary_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/platform/azure_cost_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/platform/cost_alert_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/glossary/miss_signals_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/documents/credential_expiry_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/registry/url_health_monitor.py` | MODIFY (H5) | 2, 3 |
| `src/backend/app/modules/har/approval_timeout_job.py` | MODIFY | 2, 3 |
| `src/backend/app/modules/har/health_monitor.py` | MODIFY (L1 refactor) | 2, 3 |
| `src/backend/app/modules/tenant/jobs_routes.py` | NEW or MODIFY (L2 outcome-centric) | 3 |
| `src/backend/tests/unit/test_job_lock.py` | NEW (includes C1 heartbeat tests) | 1 |
| `src/backend/tests/unit/test_job_run_log.py` | NEW | 3 |
| `src/backend/tests/integration/test_distributed_scheduling.py` | NEW (includes H1, H2, H4, H5 tests) | 2 |
| `src/backend/tests/integration/test_job_run_log_persistence.py` | NEW (includes H4 abandoned status test) | 3 |
| `src/backend/tests/integration/test_job_history_api.py` | NEW (includes L2, M1 tests) | 3 |
| `src/backend/tests/integration/test_tenant_throttle.py` | NEW | 4 |
| `src/backend/tests/e2e/test_job_history_endpoints.py` | NEW (includes L2 outcome-centric test) | 3 |

**Total**: 9 new production files, 15 modified production files, 7 new test files.

---

**Document Version**: v1.1
**Last Updated**: 2026-03-20
**Changes from v1.0**: Red team remediation incorporated — C1 (heartbeat moved to Phase 1), C2 (Redis persistence checklist), H1 (>= threshold + atomic Lua INCR), H2 (7-day TTL + tool delete cleanup), H3 (composite indexes + drop year-partition), H4 (zombie row cleanup + abandoned status), H5 (dynamic url_health TTL), H6 (deterministic P1 issue assignment), H7 (tool_health_scheduler never started — bug fix), M1 (cold-start missed-job recovery in Phase 3), M2 (APScheduler shutdown in transition), M3 (glossary warmup non-blocking), M4 (documented 60s floor), L1 (AgentHealthMonitor refactor in Phase 3), L2 (tenant endpoint outcome-centric signals).
