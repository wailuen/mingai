# 12 — Distributed Job Scheduling

**Generated**: 2026-03-20
**Phase**: Infrastructure — Distributed Redis-lock-based job scheduling
**Numbering**: SCHED-001 through SCHED-038
**Stack**: Redis (SET NX EX + Lua) + PostgreSQL (job_run_log) + asyncio + FastAPI lifespan
**Related plan**: `workspaces/mingai/02-plans/13-distributed-job-scheduling-plan.md`
**Related research**: `workspaces/mingai/01-analysis/01-research/47-background-job-scheduling-architecture.md`
**Red team**: `workspaces/mingai/01-analysis/01-research/48-distributed-job-scheduling-redteam.md`
**Status**: COMPLETE — all 38 items done. Commit: `6e6237d` (2026-03-20)
**Moved to completed/**: 2026-03-20

---

## Overview

mingai currently runs 13 background jobs as `asyncio.create_task()` from the FastAPI lifespan, plus two outliers (`provider_health_job.py` and `tool_health_job.py`) that use APScheduler's `AsyncIOScheduler`. All 13 jobs execute on every pod — a second Kubernetes pod causes duplicate execution, double notifications, and doubled LLM cost.

APScheduler is not listed in `pyproject.toml`. It is only imported inside a conditional `try/except ImportError` block, which means provider and tool health checks are silently disabled today. `start_tool_health_scheduler()` is also never wired into `main.py` at all — tool health monitoring has never run in any environment (H-07, confirmed by reading the lifespan code).

**Solution**: Introduce a thin `DistributedJobLock` context manager backed by Redis `SET NX EX` with TTL heartbeat renewal, wrap every job, add a `job_run_log` table for execution history, extract a shared `seconds_until_utc()` utility, remove APScheduler, and fix the pre-existing bugs surfaced by the red team.

**Red team severity summary**: 2 CRITICAL · 7 HIGH · 4 MEDIUM · 2 LOW. All C and H findings are addressed by Phase 1 (foundation) and Phase 2 (conversion). M and L findings are addressed in Phase 2–3.

---

## Phase 1 — Foundation

These items introduce the scheduling infrastructure without changing any job behaviour. Phase 1 is deployable independently and is a prerequisite before any second pod is added.

**Pre-Phase 1 deployment checklist (C-02 remediation)**:
- Redis AOF persistence must be enabled: `CONFIG GET appendonly` must return `yes`
- Managed Redis must be Standard tier or above (not Basic)
- Key prefix `mingai:_platform:job_lock:*` must not be excluded from persistence scope
- Document the 60-second startup floor in the ops runbook (M-01 partial mitigation)

---

### SCHED-001: Create `app/core/scheduler/__init__.py`

**Status**: [x] complete
**Priority**: P0
**Effort**: 5 minutes
**Depends on**: None
**File**: `src/backend/app/core/scheduler/__init__.py`

**Description**:

Create the `scheduler` package by adding an empty `__init__.py`. This is a structural prerequisite for SCHED-002 and SCHED-003.

**Acceptance criteria**:

- [x] File exists at `src/backend/app/core/scheduler/__init__.py`
- [x] File is empty (no imports, no code)
- [x] `from app.core.scheduler.job_lock import distributed_job_lock` resolves without error after SCHED-002
- [x] Phase 1 startup AOF check in `main.py` lifespan — BEFORE the first scheduler starts: `CONFIG GET appendonly` → if returns `no`, log `redis_aof_disabled` at WARNING level with message "Job lock correctness requires Redis AOF persistence. Set appendonly=yes in redis.conf." (See also SCHED-037 for the Phase 4 CI enforcement of this check.)

---

### SCHED-002: Implement `DistributedJobLock` in `app/core/scheduler/job_lock.py`

**Status**: [x] complete
**Priority**: P0
**Effort**: 3h
**Depends on**: SCHED-001
**File**: `src/backend/app/core/scheduler/job_lock.py`
**Addresses**: C-01 (lock TTL expiry mid-run), C-02 (Redis persistence prerequisite check)

**Description**:

Implement the `distributed_job_lock` async context manager backed by Redis `SET NX EX`. This is the core primitive for all distributed scheduling. Yields `True` if the lock was acquired (job should run), `False` if another pod holds the lock (skip this cycle).

Lock key format: `mingai:_platform:job_lock:{job_name}`

**C-01 remediation**: Heartbeat renewal is built in from day one (not deferred). A background `asyncio.Task` calls `EXPIRE` every `ttl_seconds // 2` seconds while the job runs, preventing TTL expiry mid-run for long-running jobs like `cost_summary`. The heartbeat checks token identity before extending — if the token no longer matches (lock stolen after expiry), it logs `job_lock_lost` at WARNING and stops. The heartbeat task is cancelled before the lock is released in the `finally` block.

**C-02 remediation**: Add a startup check that reads `CONFIG GET appendonly` from Redis and logs a WARNING if persistence is disabled. Do not block startup — log and continue.

Lua release script: atomic check-and-delete. If `GET lock_key != owner_id`, the delete is skipped and `job_lock_release_skipped` is logged. This prevents releasing a lock we no longer own after TTL expiry and re-acquisition by another pod.

**Structured log events**:
- `job_lock_acquired` — DEBUG — emitted when lock is acquired
- `job_lock_skipped` — DEBUG — emitted when another pod holds the lock
- `job_lock_released` — DEBUG — emitted on clean release
- `job_lock_release_skipped` — WARNING — emitted when Lua script finds token mismatch (lock expired or stolen)
- `job_lock_lost` — WARNING — emitted by heartbeat when token no longer matches (lock expired mid-run)
- `job_lock_ttl_extended` — DEBUG — emitted each time heartbeat renews TTL

**Acceptance criteria**:

- [x] `distributed_job_lock` is an async context manager that yields `bool`
- [x] `acquired = await redis.set(lock_key, owner_id, nx=True, ex=ttl_seconds)` — single atomic command, no separate SETNX + EXPIRE
- [x] When key is free: yields `True`, key is set in Redis with correct TTL
- [x] When key is held: yields `False`, no attempt to acquire, no error
- [x] Heartbeat task is created when `heartbeat=True` (the default)
- [x] Heartbeat interval defaults to `max(ttl_seconds // 2, 10)` seconds
- [x] Heartbeat calls `EXPIRE lock_key ttl_seconds` only if `GET lock_key == owner_id`
- [x] Heartbeat logs `job_lock_lost` at WARNING if token no longer matches and stops the loop
- [x] Heartbeat task is cancelled in `finally` block before Lua release
- [x] Lua script performs atomic check-and-delete: `GET == owner_id → DEL`, else `return 0`
- [x] `job_lock_release_skipped` logged at WARNING when Lua returns 0
- [x] Startup AOF check: logs WARNING if `CONFIG GET appendonly` returns `no`
- [x] `owner_id` defaults to a fresh `uuid.uuid4()` per invocation; callers may pass `socket.gethostname()` for stable instance identity
- [x] All log events include `job_name` field; `job_lock_acquired`/`job_lock_released` include `owner_id`
- [x] Self-termination: the heartbeat task holds a reference to the outer job's `asyncio.Task`. When it detects token mismatch (`job_lock_lost`), it calls `job_task.cancel()` to stop the in-flight job
- [x] `DistributedJobLock.__aenter__` stores `asyncio.current_task()` at acquisition time and passes it to the heartbeat so the heartbeat can cancel the outer job task on token mismatch

---

### SCHED-003: Implement `seconds_until_utc()` in `app/core/scheduler/timing.py`

**Status**: [x] complete
**Priority**: P0
**Effort**: 1h
**Depends on**: SCHED-001
**File**: `src/backend/app/core/scheduler/timing.py`
**Addresses**: Code duplication — replaces 8 identical `_seconds_until_next_run()` implementations

**Description**:

Extract the repeated "seconds until next UTC hour:minute occurrence" calculation into a single shared utility. The function currently exists verbatim in at least 8 scheduler modules:
- `app/modules/cache/query_warming.py`
- `app/modules/platform/cost_summary_job.py`
- `app/modules/platform/cost_alert_job.py`
- `app/modules/platform/health_score_job.py`
- `app/modules/platform/azure_cost_job.py`
- `app/modules/platform/miss_signals_job.py` (via `run_miss_signals_scheduler`)
- `app/modules/documents/credential_expiry_job.py`

The 60-second floor is an intentional cold-start guard: a pod that starts at 02:00:30 UTC will not fire the 02:00 job immediately — it waits until the next day. This is the documented "drain-window miss" behaviour (M-01). Phase 3 adds `job_run_log` detection to recover missed jobs; until then, document the floor with a clear comment.

**Acceptance criteria**:

- [x] `seconds_until_utc(hour, minute=0) -> float` is importable from `app.core.scheduler.timing`
- [x] Returns seconds until the next occurrence of `hour:minute` UTC, treating "past" as "tomorrow"
- [x] Returns at least `60.0` — the 60-second floor guard is enforced
- [x] The 60-second floor is documented with a comment explaining M-01 behaviour
- [x] `seconds_until_utc(2, 0)` called at 02:00:00 UTC returns ~86400 (not 0)
- [x] `seconds_until_utc(2, 0)` called at 01:59:30 UTC returns ~30 → floor clamps to 60.0
- [x] `seconds_until_utc(2, 0)` called at 01:00:00 UTC returns ~3600
- [x] No external dependencies beyond stdlib `datetime`

---

### SCHED-004: Alembic migration v042 — create `job_run_log` table

**Status**: [x] complete
**Priority**: P0
**Effort**: 2h
**Depends on**: None (schema change, no application code dependency)
**File**: `src/backend/alembic/versions/v042_job_run_log.py`
**Addresses**: H-03 (missing composite index), H-04 (zombie row cleanup on startup)

**Description**:

Create the `job_run_log` table for durable background job execution history. `tenant_id` is nullable — platform-scope jobs (health score, cost summary, provider health) set `tenant_id = NULL`; per-tenant iterating jobs write one row per tenant per execution.

**Columns**:
- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `job_name VARCHAR(100) NOT NULL`
- `instance_id VARCHAR(100)` — hostname of the pod that ran the job; aids multi-pod debugging
- `tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL` — nullable
- `status VARCHAR(20) NOT NULL DEFAULT 'running'` — CHECK: running, completed, failed, abandoned
- `started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `completed_at TIMESTAMPTZ`
- `duration_ms INTEGER`
- `records_processed INTEGER`
- `error_message TEXT`
- `metadata JSONB NOT NULL DEFAULT '{}'`

**Indexes (H-03 remediation — no year-based partitioning)**:
- `CREATE INDEX idx_jrl_job_name_time ON job_run_log(job_name, started_at DESC)` — per-job history and M-01 missed-job check
- `CREATE INDEX idx_jrl_tenant_time ON job_run_log(tenant_id, started_at DESC) WHERE tenant_id IS NOT NULL` — tenant admin history page
- `CREATE INDEX idx_jrl_started_at ON job_run_log(started_at DESC)` — platform admin all-jobs view
- `CREATE INDEX CONCURRENTLY idx_jrl_running ON job_run_log(started_at) WHERE status = 'running'` — partial index for the zombie cleanup query performance; must be in the migration DDL

**No year-based partitioning**: 90-day retention cleanup (SCHED-022) keeps the table well under 5M rows at realistic tenant counts. Partitioning adds operational complexity with no query benefit for the tenant-id-filtered access pattern.

**Acceptance criteria**:

- [x] `alembic upgrade head` runs clean after v041 (pgvector migration)
- [x] `alembic downgrade -1` drops the table and all indexes cleanly
- [x] `down_revision = "041"` — no version gap
- [x] All four indexes created in the `upgrade()` function — the fourth is `CREATE INDEX CONCURRENTLY idx_jrl_running ON job_run_log(started_at) WHERE status = 'running'` (partial index, not composite on status)
- [x] `status` CHECK constraint rejects values outside the allowed set
- [x] `tenant_id` is nullable with `ON DELETE SET NULL`
- [x] `metadata` column has `DEFAULT '{}'` (valid JSONB empty object)
- [x] Migration includes no RLS policy (job_run_log is a platform-internal table with no tenant data)

---

### SCHED-005: Startup zombie row cleanup in `main.py` lifespan

**Status**: [x] complete
**Priority**: P0
**Effort**: 1h
**Depends on**: SCHED-004
**File**: `src/backend/app/main.py`
**Addresses**: H-04 (zombie `running` rows accumulate on every pod restart)

**Description**:

On every pod startup, before any scheduler tasks are created, run a single SQL UPDATE that marks all `status = 'running'` rows older than 1 hour as `status = 'abandoned'`. This prevents zombie rows from prior restarts from polluting monitoring queries.

The UPDATE must execute in the lifespan startup block, after the DB engine is initialized, before the first `asyncio.create_task()` for any scheduler. Log the count of rows updated at INFO level.

This is the startup reconciliation described in H-04's remediation direction. The 1-hour threshold is conservative — no legitimate job should run for more than 1 hour without completing (the longest jobs have TTLs of 7200s = 2 hours, but that is the lock TTL not expected runtime).

**Acceptance criteria**:

- [x] UPDATE executes before any `asyncio.create_task(run_*_scheduler())` call in lifespan
- [x] Query: `UPDATE job_run_log SET status='abandoned', completed_at=NOW() WHERE status='running' AND started_at < NOW() - INTERVAL '1 hour'`
- [x] Count of abandoned rows logged at INFO: `job_run_log_zombie_cleanup` with field `rows_abandoned`
- [x] If count is 0, log is still emitted (confirms cleanup ran)
- [x] Wrapped in `try/except` — a DB failure during cleanup logs a WARNING but does not abort startup
- [x] Does not require a new DB session beyond the startup block's existing DB access pattern

---

### SCHED-006: Convert `provider_health_job.py` to asyncio loop + `DistributedJobLock`

**Status**: [x] complete
**Priority**: P0
**Effort**: 2h
**Depends on**: SCHED-002, SCHED-003, SCHED-007
**File**: `src/backend/app/modules/platform/provider_health_job.py`
**Also updates**: `src/backend/app/main.py`
**Addresses**: M-02 (APScheduler never shut down), silent APScheduler import failure

**Note**: SCHED-007 (APScheduler shutdown) must be merged first to prevent a race condition during rolling deploy where old pods lose teardown path.

**Description**:

Replace `start_provider_health_scheduler(app)` with `run_provider_health_scheduler()` — an async loop function that matches the canonical pattern of all other schedulers in the codebase (infinite `while True` / `await asyncio.sleep` loop).

**Pattern**:
```
async def run_provider_health_scheduler() -> None:
    while True:
        await asyncio.sleep(seconds_with_jitter)
        async with distributed_job_lock("provider_health", ttl_seconds=1200):
            if acquired:
                result = await run_provider_health_job()
                logger.info("provider_health_job_complete", **result)
```

Interval: 600 seconds with ±30s jitter (preserving existing behaviour). TTL: 1200s (2× interval, safe margin for provider connectivity tests). The jitter must remain to prevent thundering herd across providers.

`main.py` change: replace `start_provider_health_scheduler(app)` with `asyncio.create_task(run_provider_health_scheduler())` alongside the other scheduler tasks, storing the task handle for cancellation in the shutdown block.

The old `start_provider_health_scheduler(app)` function and all APScheduler imports (`AsyncIOScheduler`, `IntervalTrigger`) must be removed.

**Acceptance criteria**:

- [x] `run_provider_health_scheduler()` is an `async def` with an infinite `while True` loop
- [x] `start_provider_health_scheduler(app)` function is removed
- [x] No `from apscheduler` imports remain in the file
- [x] Lock TTL is 1200s (2× the 600s interval)
- [x] Jitter of ±30s applied to `asyncio.sleep` (same as existing behaviour)
- [x] `async with distributed_job_lock("provider_health", ttl_seconds=1200)` wraps the job call
- [x] `CancelledError` propagates cleanly (the `while True` loop terminates on cancel)
- [x] `main.py` stores the task: `_provider_health_task = asyncio.create_task(run_provider_health_scheduler())`
- [x] `main.py` shutdown block cancels `_provider_health_task` and awaits it with `except CancelledError: pass`
- [x] `main.py` no longer calls `start_provider_health_scheduler(app)`
- [x] No `app.state.provider_health_scheduler` attribute is set

---

### SCHED-007: Add APScheduler `.shutdown()` calls to `main.py` lifespan teardown

**Status**: [x] complete
**Priority**: P0
**Effort**: 30 minutes
**Depends on**: None (pre-existing code, belt-and-suspenders for rolling deploy safety)
**File**: `src/backend/app/main.py`
**Addresses**: M-02 (APScheduler.shutdown() never called in lifespan)

**Description**:

Belt-and-suspenders safety for the Phase 1→2 transition during rolling deploys. An older pod (not yet upgraded to Phase 2) may have `app.state.provider_health_scheduler` or `app.state.tool_health_scheduler` set to an `AsyncIOScheduler` instance. Add graceful shutdown calls for these attributes in the lifespan teardown block.

These calls execute before the Phase 2 conversion is complete. Once SCHED-006 and SCHED-008 are merged, `app.state.{job}_health_scheduler` will no longer exist, and `hasattr()` will return `False` — these lines become no-ops.

**Acceptance criteria**:

- [x] In the shutdown block: `if hasattr(app.state, 'provider_health_scheduler'): app.state.provider_health_scheduler.shutdown(wait=False)` — wrapped in `try/except`
- [x] Same pattern for `app.state.tool_health_scheduler`
- [x] Both checks placed after the existing task-cancellation block, before Redis/DB teardown
- [x] Log line `apscheduler_legacy_shutdown` at INFO if the attribute exists and shutdown() is called
- [x] If the attribute does not exist, no log line is emitted (silent no-op)

---

## Phase 2 — Convert All Jobs + Fix Pre-existing Bugs

Phase 2 converts all remaining jobs to use `DistributedJobLock`, fixes the pre-existing bugs found by the red team, and wires the previously silent `tool_health_scheduler` into `main.py`. All items in this phase address HIGH severity red team findings.

---

### SCHED-008: Convert `tool_health_job.py` + fix H-01, H-02, H-06, H-07

**Status**: [x] complete
**Priority**: P0
**Effort**: 5h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/platform/tool_health_job.py`
**Also updates**: `src/backend/app/main.py`, tool catalog DELETE route
**Addresses**: H-01 (INCR equality race), H-02 (stale counter TTL), H-06 (non-deterministic P1 assignment), H-07 (scheduler never started)

**Description**:

This item bundles the tool_health_job conversion with four pre-existing bug fixes that would otherwise be blocked until Phase 2.

**H-07 fix (CRITICAL — tool health monitoring never ran)**: Wire `asyncio.create_task(run_tool_health_scheduler())` in `main.py` lifespan. The `start_tool_health_scheduler(app)` function currently exists but is never called. This single gap means tool health monitoring has been completely inactive since the feature was written.

**H-01 fix (INCR equality race skips P1 creation)**: Replace `count == _DEGRADED_THRESHOLD` and `count == _UNAVAILABLE_THRESHOLD` equality checks with `>= threshold`. The current implementation uses an in-process `dict` (`_failure_counts`) which will be replaced by Redis counters as part of this item. The Redis-backed version uses an atomic Lua script that increments the counter and checks `>= threshold` in a single round-trip, preventing the race where multiple pods increment through the threshold without any single pod observing it.

Lua script pattern:
```lua
local new_val = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return new_val
```
The caller checks `new_val >= threshold` — not `== threshold`. This ensures at least one pod fires the P1 even if pods increment simultaneously.

Counter key format: `mingai:_platform:tool_health:failures:{tool_id}`

**H-02 fix (stale counter keys for deleted tools)**: Set a 7-day TTL on all counter keys (EXPIRE called in the same Lua script as INCR). Add a `DEL mingai:_platform:tool_health:failures:{tool_id}` call to the tool catalog DELETE route so deletion immediately clears the counter.

**H-06 fix (non-deterministic P1 assignment)**: The `_CREATE_P1_ISSUE_QUERY` currently uses `SELECT id FROM users WHERE role = 'platform_admin' LIMIT 1` with no `ORDER BY`. This returns a non-deterministic platform admin. Replace with `ORDER BY created_at ASC LIMIT 1` to select the oldest (most senior) platform admin deterministically. The insert also currently uses `u.tenant_id` as the `tenant_id` for the issue row — platform tool health issues are platform-scope and should use a platform sentinel tenant UUID (or NULL). Use NULL for `tenant_id` in the INSERT.

**Scheduler conversion**: Replace `start_tool_health_scheduler(app)` and APScheduler imports with `run_tool_health_scheduler()` asyncio loop. TTL: `max(600, agent_count_from_db × 15)` — query the count of tools with `health_check_url IS NOT NULL` at lock acquisition time. This implements the dynamic TTL pattern from H-05's remediation direction adapted for tool health.

**Acceptance criteria**:

- [x] `run_tool_health_scheduler()` is an `async def` with an infinite `while True` loop
- [x] `start_tool_health_scheduler(app)` removed
- [x] No `from apscheduler` imports remain in the file
- [x] `_failure_counts` in-process dict replaced by Redis counter keys `mingai:_platform:tool_health:failures:{tool_id}`
- [x] Redis increment uses Lua script that atomically INCRs and sets EXPIRE in one round-trip
- [x] Counter TTL is 7 days (604800 seconds)
- [x] `_DEGRADED_THRESHOLD` check uses `>= 3` (not `== 3`)
- [x] `_UNAVAILABLE_THRESHOLD` check uses `>= 10` (not `== 10`)
- [x] `_CREATE_P1_ISSUE_QUERY` uses `ORDER BY created_at ASC LIMIT 1`
- [x] `_CREATE_P1_ISSUE_QUERY` inserts `tenant_id = NULL` for platform-scope issues
- [x] Tool catalog DELETE route calls `await redis.delete(f"mingai:_platform:tool_health:failures:{tool_id}")` after the DB DELETE
- [x] `main.py` wires `asyncio.create_task(run_tool_health_scheduler())` in lifespan startup
- [x] `main.py` shutdown block cancels and awaits the tool health task
- [x] `main.py` no longer calls `start_tool_health_scheduler(app)`
- [x] Dynamic TTL: queries `COUNT(*) FROM tool_catalog WHERE health_check_url IS NOT NULL` before acquiring lock; TTL = `max(600, count × 15)`

---

### SCHED-009: Wrap `semantic_cache_cleanup_loop` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002
**File**: `src/backend/app/core/cache/cleanup_job.py`

**Description**:

The semantic cache cleanup job runs hourly. Wrap the job body with `distributed_job_lock("semantic_cache_cleanup", ttl_seconds=7200)`. TTL is 2 hours — cleanup is idempotent but may take up to 1 hour for large caches. The lock prevents two pods from running cleanup simultaneously and doubling pgvector DELETE load.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("semantic_cache_cleanup", ttl_seconds=7200) as acquired:` wraps the cleanup call
- [x] If `not acquired`: log at DEBUG and skip (do not raise)
- [x] Interval remains 3600s (1 hour)
- [x] `seconds_until_utc()` is NOT used here — this is an interval job, not a fixed-time daily job. Retain `await asyncio.sleep(3600)` pattern.
- [x] `CancelledError` propagates cleanly

---

### SCHED-010: Wrap `run_query_warming_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/cache/query_warming.py`

**Description**:

Query warming fires daily at 03:00 UTC. Wrap with `distributed_job_lock("query_warming", ttl_seconds=3600)`. Replace the local `_seconds_until_next_run()` function with `seconds_until_utc(3, 0)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("query_warming", ttl_seconds=3600) as acquired:` wraps the warming call
- [x] Local `_seconds_until_next_run()` function removed
- [x] `from app.core.scheduler.timing import seconds_until_utc` added
- [x] `await asyncio.sleep(seconds_until_utc(3, 0))` used in the loop
- [x] If `not acquired`: skip with DEBUG log
- [x] `CancelledError` propagates cleanly
- [x] Phase 3 addendum (SCHED-025 dependency): `check_missed_job(job_name)` call added before the first `await asyncio.sleep()` in the scheduler loop.

---

### SCHED-011: Wrap `run_health_score_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/platform/health_score_job.py`

**Description**:

Tenant health score job fires daily at 02:00 UTC. Wrap with `distributed_job_lock("health_score", ttl_seconds=3600)`. Replace local `_seconds_until_next_run()` with `seconds_until_utc(2, 0)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("health_score", ttl_seconds=3600) as acquired:` wraps the job call
- [x] Local `_seconds_until_next_run()` function removed
- [x] `from app.core.scheduler.timing import seconds_until_utc` added
- [x] `await asyncio.sleep(seconds_until_utc(2, 0))` used in the loop
- [x] If `not acquired`: skip with DEBUG log
- [x] Phase 3 addendum (SCHED-025 dependency): `check_missed_job(job_name)` call added before the first `await asyncio.sleep()` in the scheduler loop.

---

### SCHED-012: Wrap `start_cost_summary_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/platform/cost_summary_job.py`

**Description**:

Cost summary job fires daily at 03:30 UTC. Wrap with `distributed_job_lock("cost_summary", ttl_seconds=1800)`. Note: the red team (C-01) identified that the cost_summary job can run for 30+ minutes against tenants with dense Azure tagging. The heartbeat in `DistributedJobLock` (SCHED-002) addresses this — the 1800s TTL is renewed every 900s as long as the job is alive. Replace local `_seconds_until_next_run()` with `seconds_until_utc(3, 30)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("cost_summary", ttl_seconds=1800) as acquired:` wraps the job call
- [x] Local `_seconds_until_next_run()` function removed
- [x] `from app.core.scheduler.timing import seconds_until_utc` added
- [x] `await asyncio.sleep(seconds_until_utc(3, 30))` used in the loop
- [x] If `not acquired`: skip with DEBUG log
- [x] Comment in code references C-01 and explains heartbeat guards against 30-min+ Azure jobs
- [x] Phase 3 addendum (SCHED-025 dependency): `check_missed_job(job_name)` call added before the first `await asyncio.sleep()` in the scheduler loop.

---

### SCHED-013: Wrap `start_azure_cost_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/platform/azure_cost_job.py`

**Description**:

Azure Cost Management pull job fires daily at 03:45 UTC. Wrap with `distributed_job_lock("azure_cost", ttl_seconds=1200)`. Replace local timing function with `seconds_until_utc(3, 45)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("azure_cost", ttl_seconds=1200) as acquired:` wraps the job call
- [x] Local timing function removed, `seconds_until_utc(3, 45)` used
- [x] If `not acquired`: skip with DEBUG log
- [x] Phase 3 addendum (SCHED-025 dependency): `check_missed_job(job_name)` call added before the first `await asyncio.sleep()` in the scheduler loop.

---

### SCHED-014: Wrap `start_cost_alert_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/platform/cost_alert_job.py`

**Description**:

Cost alert evaluation job fires daily at 04:00 UTC. Wrap with `distributed_job_lock("cost_alert", ttl_seconds=1800)`. Replace local timing function with `seconds_until_utc(4, 0)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("cost_alert", ttl_seconds=1800) as acquired:` wraps the job call
- [x] Local timing function removed, `seconds_until_utc(4, 0)` used
- [x] If `not acquired`: skip with DEBUG log
- [x] Phase 3 addendum (SCHED-025 dependency): `check_missed_job(job_name)` call added before the first `await asyncio.sleep()` in the scheduler loop.

---

### SCHED-015: Wrap `run_miss_signals_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/glossary/miss_signals_job.py`

**Description**:

Glossary miss signals batch job fires daily at 04:30 UTC. Wrap with `distributed_job_lock("miss_signals", ttl_seconds=1800)`. Replace local timing function with `seconds_until_utc(4, 30)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("miss_signals", ttl_seconds=1800) as acquired:` wraps the job call
- [x] Local timing function removed, `seconds_until_utc(4, 30)` used
- [x] If `not acquired`: skip with DEBUG log
- [x] Phase 3 addendum (SCHED-025 dependency): `check_missed_job(job_name)` call added before the first `await asyncio.sleep()` in the scheduler loop.

---

### SCHED-016: Wrap `run_credential_expiry_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002, SCHED-003
**File**: `src/backend/app/modules/documents/credential_expiry_job.py`

**Description**:

Credential expiry monitoring job fires daily at 05:00 UTC. Wrap with `distributed_job_lock("credential_expiry", ttl_seconds=1800)`. This job sends expiry notification emails — duplicate execution would send duplicate emails to tenant admins. The lock is therefore correctness-critical (not just cost-reducing). Replace local timing function with `seconds_until_utc(5, 0)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("credential_expiry", ttl_seconds=1800) as acquired:` wraps the job call
- [x] Local timing function removed, `seconds_until_utc(5, 0)` used
- [x] If `not acquired`: skip with DEBUG log
- [x] Comment in code notes that duplicate execution would send duplicate expiry emails
- [x] Phase 3 addendum (SCHED-025 dependency): `check_missed_job(job_name)` call added before the first `await asyncio.sleep()` in the scheduler loop.

---

### SCHED-017: Wrap `run_url_health_monitor_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 2h
**Depends on**: SCHED-002
**File**: `src/backend/app/modules/registry/url_health_monitor.py`
**Addresses**: H-05 (url_health_monitor TTL shorter than worst-case runtime)

**Description**:

URL health monitor runs every ~5 minutes (300s with ±60s jitter). TTL must be calculated dynamically at lock acquisition time — not hardcoded — because the worst-case runtime is proportional to the number of registered agents.

**H-05 remediation**: The worst-case runtime is `total_agents_with_health_check_url × per_agent_timeout_seconds`. With a 10-second per-agent timeout and 50 agents, worst case is 500 seconds — already longer than a 240s TTL. Query the count of agent cards with `health_check_url IS NOT NULL` from the DB at the start of each loop iteration. TTL = `max(600, agent_count × 15)`. This gives a 15-second buffer per agent beyond the 10-second timeout, with a 600s floor.

The heartbeat in `DistributedJobLock` (SCHED-002) provides additional protection: if the job legitimately runs past the initial TTL, the heartbeat will renew it.

**Acceptance criteria**:

- [x] TTL is computed dynamically: `max(600, count_of_agents_with_health_url × 15)` — not hardcoded
- [x] DB query for agent count executes before the `distributed_job_lock()` call
- [x] `async with distributed_job_lock("url_health_monitor", ttl_seconds=dynamic_ttl) as acquired:` wraps the monitor call
- [x] Interval remains 300s ± 60s jitter
- [x] If `not acquired`: skip with DEBUG log
- [x] Comment in code references H-05 and documents the TTL calculation

---

### SCHED-018: Wrap `run_approval_timeout_scheduler` with `DistributedJobLock`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002
**File**: `src/backend/app/modules/har/approval_timeout_job.py`

**Description**:

Approval timeout job runs every ~1 hour (3600s with ±60s jitter). This job auto-expires HAR transaction approvals that have exceeded the 48-hour window. Duplicate execution would double the timeout notifications. Wrap with `distributed_job_lock("approval_timeout", ttl_seconds=3600)`.

**Acceptance criteria**:

- [x] `async with distributed_job_lock("approval_timeout", ttl_seconds=3600) as acquired:` wraps the job call
- [x] Interval remains 3600s ± 60s jitter (preserving existing behaviour)
- [x] If `not acquired`: skip with DEBUG log

---

### SCHED-019: Convert `AgentHealthMonitor` to canonical asyncio function pattern

**Status**: [x] complete
**Priority**: P1
**Effort**: 2h
**Depends on**: SCHED-002
**Phase**: Phase 3 (moved from Phase 2 — must complete before SCHED-024 all-13 integration is considered done)
**File**: `src/backend/app/modules/har/health_monitor.py`
**Also updates**: `src/backend/app/main.py`
**Addresses**: L-01 (AgentHealthMonitor is a third scheduling pattern omitted from migration scope)

**Description**:

Replace with:
```python
from app.modules.har.health_monitor import run_agent_health_scheduler
_health_monitor_task = asyncio.create_task(run_agent_health_scheduler())
```

The class itself can be kept as an internal implementation detail if needed, but the public interface exposed to `main.py` must be the standalone function.

**Acceptance criteria**:

- [x] `run_agent_health_scheduler()` is an `async def` with a `while True` loop
- [x] `async with distributed_job_lock("agent_health", ttl_seconds=7200) as acquired:` wraps the health computation
- [x] Interval remains 3600s
- [x] `main.py` imports and calls `run_agent_health_scheduler()`, not `AgentHealthMonitor(...).start()`
- [x] `AgentHealthMonitor` class may remain as internal implementation but is not the entrypoint
- [x] If `not acquired`: skip with DEBUG log
- [x] `CancelledError` propagates cleanly from the loop

---

### SCHED-020: Convert `warm_up_glossary_cache()` from blocking `await` to `asyncio.create_task()`

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002
**File**: `src/backend/app/main.py`
**Addresses**: M-03 (warm_up_glossary_cache blocks startup; not covered by distributed lock)

**Description**:

`warm_up_glossary_cache()` is currently called as `await warm_up_glossary_cache()` in the lifespan startup block, blocking the FastAPI application from accepting requests until warm-up completes for all tenants. On a rolling deploy with 3 pods, this sends 3 simultaneous warm-up passes to pgvector.

Change to `asyncio.create_task(warm_up_glossary_cache())` so the application becomes ready immediately and warm-up runs in the background.

The glossary cache warm-up writes are idempotent Redis SET operations. Two pods running simultaneously produces correct results — the last write wins, and both writes are identical for the same glossary data. A distributed lock is therefore not required, but the comment should document this explicitly.

Store the task handle and cancel it in the shutdown block.

**Acceptance criteria**:

- [x] `await warm_up_glossary_cache()` replaced with `asyncio.create_task(warm_up_glossary_cache())`
- [x] Task handle stored: `_glossary_warmup_task = asyncio.create_task(...)`
- [x] Shutdown block cancels `_glossary_warmup_task` if not done
- [x] Comment in code: "No distributed lock needed — glossary cache writes are idempotent Redis SETs. Duplicate warm-up from a second pod is harmless."
- [x] The `try/except` wrapper around the create_task call is preserved

---

### SCHED-021: Confirm APScheduler is absent from `pyproject.toml`

**Status**: [x] complete
**Priority**: P2
**Effort**: 15 minutes
**Depends on**: SCHED-006, SCHED-008
**File**: `src/backend/pyproject.toml`

**Description**:

After SCHED-006 and SCHED-008 remove all APScheduler imports from the codebase, confirm that `apscheduler` is not listed in `pyproject.toml` dependencies. The plan confirms it was never declared — verify this and add a note in the changelog.

If APScheduler somehow appears in `pyproject.toml`, remove it. If it appears transitively in `poetry.lock` as a dependency of another package, document that it cannot be removed at this time.

**Acceptance criteria**:

- [x] `grep -r "apscheduler" src/backend/pyproject.toml` returns no results
- [x] `grep -r "from apscheduler" src/backend/app/` returns no results after SCHED-006 and SCHED-008
- [x] `grep -r "import apscheduler" src/backend/app/` returns no results
- [x] Changelog entry added noting APScheduler removal

---

### SCHED-022: Add 90-day `job_run_log` retention cleanup to `semantic_cache_cleanup_loop`

**Status**: [x] complete
**Priority**: P2
**Effort**: 30 minutes
**Depends on**: SCHED-004, SCHED-009
**File**: `src/backend/app/core/cache/cleanup_job.py`

**Description**:

Piggyback the `job_run_log` retention cleanup onto the existing semantic cache cleanup loop (which already runs hourly under a distributed lock). This avoids creating a new scheduler for a trivial maintenance query.

Add at the end of the cleanup function body:
```sql
DELETE FROM job_run_log WHERE started_at < NOW() - INTERVAL '90 days'
```

Log the count of deleted rows at DEBUG level.

**Acceptance criteria**:

- [x] `DELETE FROM job_run_log WHERE started_at < NOW() - INTERVAL '90 days'` executes inside the cleanup function
- [x] Count of deleted rows logged at DEBUG: `job_run_log_retention_cleanup` with field `rows_deleted`
- [x] If 0 rows deleted, log is still emitted
- [x] DELETE is wrapped in `try/except` — failure does not abort the main cleanup logic
- [x] The DELETE runs after the semantic cache cleanup completes (not before)

---

## Phase 3 — Observability

Phase 3 adds the `job_run_context()` context manager for durable execution logging, integrates it into all 13 jobs, implements missed-job detection, and exposes job history via API endpoints and the Platform Admin UI.

---

### SCHED-023: Implement `job_run_context()` in `app/core/scheduler/job_run_log.py`

**Status**: [x] complete
**Priority**: P1
**Effort**: 3h
**Depends on**: SCHED-004
**File**: `src/backend/app/core/scheduler/job_run_log.py`
**Addresses**: H-04 (zombie rows on SIGTERM with async finally-block failure)

**Description**:

Implement the `job_run_context()` async context manager that wraps each job's body. On enter: INSERT a `status='running'` row. On exit: UPDATE to `completed`, `failed`, or `abandoned`. The `records_processed` field is set by the job via `ctx.records_processed = N` on the yielded context object.

**H-04 remediation (SIGTERM / CancelledError in finally block)**: The standard Python pattern of `await db.execute(UPDATE ...)` inside a `finally` block is vulnerable to `CancelledError` propagation during event loop shutdown. Use `asyncio.shield()` to protect the status UPDATE from cancellation:

```python
finally:
    try:
        await asyncio.shield(_write_final_status(new_db_conn, row_id, ...))
    except (asyncio.CancelledError, Exception):
        pass  # Best-effort — startup zombie cleanup (SCHED-005) handles missed rows
```

The `_write_final_status` function must open a new DB connection (the original may be in a cancelled state). This is the approach recommended by H-04's remediation direction.

**Context object interface**:
```python
async with job_run_context("health_score", tenant_id=None) as ctx:
    result = await run_health_score_job(db)
    ctx.records_processed = result["tenants_scored"]
```

**Acceptance criteria**:

- [x] `job_run_context(job_name: str, tenant_id: Optional[str] = None)` is an async context manager — NO `db` parameter
- [x] The context manager opens its own session via `async_session_factory()` — it does NOT accept or use an externally passed session
- [x] On enter: INSERT row with `status='running'`, `started_at=NOW()`, `instance_id=socket.gethostname()`
- [x] On exit (success): UPDATE `status='completed'`, `completed_at`, `duration_ms`, `records_processed`
- [x] On exit (exception): UPDATE `status='failed'`, `error_message=str(exc)`
- [x] On exit (CancelledError): UPDATE `status='abandoned'` using `asyncio.shield(_write_final_status(...))` around a fresh connection — not the original session which may be in a cancelled state
- [x] `asyncio.shield()` wraps the abandoned-status UPDATE in the CancelledError branch; on CancelledError in the finally block, use `asyncio.shield(db.execute(...))` or a fresh connection (not the cancelled session)
- [x] Yielded context object is a dataclass with a `.records_processed: int` attribute (default `None`) — NOT a plain dict
- [x] A DB failure during the enter INSERT logs a WARNING and does not raise (the job runs without a log row)
- [x] A DB failure during the exit UPDATE logs a WARNING and does not re-raise the original exception

---

### SCHED-024: Integrate `job_run_context()` into all 13 jobs

**Status**: [x] complete
**Priority**: P1
**Effort**: 3h
**Depends on**: SCHED-009–018, SCHED-019 (Phase 3 — must complete before all-13 integration), SCHED-023
**Files**: All 13 scheduler job files

**Note**: SCHED-024 is only considered "complete" when all 13 jobs are wrapped including `agent_health_monitor` (SCHED-019). SCHED-019 is Phase 3; do not mark SCHED-024 complete until SCHED-019 is merged.

**Description**:

Wrap the main job body in each of the 13 schedulers with `async with job_run_context(job_name, tenant_id=str(tenant_id)) as ctx:`. The job body is the code that runs after the `distributed_job_lock` yields `True`.

For per-tenant iterating jobs (health score, cost summary, etc.), write one row per tenant: `job_name = "health_score"`, `tenant_id = tenant.id`.

For platform-scope jobs (provider health, url health monitor, etc.), write one row per run: `job_name = "provider_health"`, `tenant_id = None`.

Set `ctx.records_processed` at the end of each job using the most meaningful metric:
- health_score: tenants scored
- cost_summary: tenant-days processed
- provider_health: providers checked
- url_health_monitor: agent URLs checked
- credential_expiry: credentials checked

**Acceptance criteria**:

- [x] All 13 job entrypoints have `async with job_run_context(...)` wrapping the job body
- [x] All 13 jobs set `ctx.records_processed` with a meaningful count
- [x] Per-tenant jobs write one `job_run_log` row per tenant
- [x] Platform-scope jobs write one row per run
- [x] `ctx.records_processed` is set before the context exits
- [x] Unit tests for these 3 specific jobs confirm `job_run_log` rows are written correctly:
  - `credential_expiry` (per-tenant iteration, multiple tenant_id rows)
  - `cost_summary` (long-running, verifies CancelledError branch writes `status='failed'`)
  - `url_health_monitor` (dynamic TTL variation, single platform-scope row)

---

### SCHED-025: Missed-job detection in `seconds_until_utc()` / scheduler loops

**Status**: [x] complete
**Priority**: P1
**Effort**: 2h
**Depends on**: SCHED-003, SCHED-004, SCHED-023
**File**: `src/backend/app/core/scheduler/timing.py`
**Addresses**: M-01 (60s floor causes cold-start job skip), M-04 (cold-start missed-job on rolling deploy)

**Description**:

Add a `check_missed_job()` helper to `timing.py` that each daily scheduler calls at startup before entering its `while True` loop. The helper queries `job_run_log` for the most recent `status='completed'` row for the given job name. If no completed row exists for today AND the current time is past the scheduled time, return `True` (run immediately). The distributed lock (SCHED-002) ensures only one pod acts on the missed-job detection.

This is the Phase 3 remediation for M-01 and M-04. Until this item ships, the 60s floor causes a 24-hour miss when a pod starts within 60 seconds of the scheduled window; this item detects the miss and fires immediately under lock protection.

```python
async def check_missed_job(db, job_name: str, scheduled_hour: int, scheduled_minute: int = 0) -> bool:
    """
    Return True if the job missed its scheduled run today and should fire immediately.
    Checks job_run_log for a completed row since today's scheduled time.
    """
```

Each daily scheduler loop should call `check_missed_job()` before the first `await asyncio.sleep(seconds_until_utc(...))`. If `True`, skip the sleep and run immediately (still under the distributed lock).

**Acceptance criteria**:

- [x] `check_missed_job(db, job_name, scheduled_hour, scheduled_minute=0) -> bool` implemented
- [x] Queries `job_run_log` for `status='completed'` rows since today's scheduled time
- [x] Returns `True` if current time >= scheduled time AND no completed row found since the scheduled slot
- [x] Returns `False` if a completed row exists today (job ran, all good)
- [x] Returns `False` if current time < scheduled time (job has not yet been due today)
- [x] All 7 daily schedulers call `check_missed_job()` before first sleep
- [x] If `check_missed_job()` fails (DB error), logs WARNING and returns `False` (conservative: no spurious immediate run)
- [x] Unit tests cover: missed job returns True, completed job returns False, pre-scheduled returns False

---

### SCHED-026: `GET /api/v1/platform/jobs/history` — Platform Admin job history endpoint

**Status**: [x] complete
**Priority**: P1
**Effort**: 3h
**Depends on**: SCHED-004, SCHED-024
**File**: `src/backend/app/modules/platform/jobs_history.py` (new file, router registered in platform router)
**Addresses**: L-02 (partial — platform operator view)

**Description**:

Platform Admin endpoint for querying `job_run_log`. Supports filtering by `job_name`, `status`, and date range. Returns raw execution metadata (not outcome-centric — the outcome-centric view is SCHED-027 for Tenant Admin).

**Query parameters**: `job_name` (optional string), `status` (optional: running|completed|failed|abandoned), `from_date` (optional ISO date), `to_date` (optional ISO date), `limit` (default 50, max 200), `offset` (default 0)

**Response shape per row**:
```json
{
  "id": "uuid",
  "job_name": "health_score",
  "instance_id": "pod-abc123",
  "tenant_id": null,
  "status": "completed",
  "started_at": "2026-03-20T02:00:15Z",
  "completed_at": "2026-03-20T02:03:42Z",
  "duration_ms": 207000,
  "records_processed": 47,
  "error_message": null
}
```

Auth: Platform Admin scope only (same JWT scope check pattern as other platform routes).

**Acceptance criteria**:

- [x] `GET /api/v1/platform/jobs/history` returns 200 with paginated results
- [x] Filtering by `job_name` returns only matching rows
- [x] Filtering by `status` returns only matching rows
- [x] Filtering by `from_date` and `to_date` is inclusive on both ends
- [x] `limit` defaults to 50; values above 200 are clamped to 200
- [x] `offset` enables pagination
- [x] Non-platform-admin JWT receives 403
- [x] Response includes `total_count` field for pagination
- [x] Uses the `(job_name, started_at DESC)` index (no full-table scan)
- [x] 3 unit tests: no auth → 403, valid filter → correct rows, pagination → correct offset

---

### SCHED-027: `GET /api/v1/tenant/sync-status` — Tenant Admin outcome-centric endpoint

**Status**: [x] complete
**Priority**: P1
**Effort**: 3h
**Depends on**: SCHED-004, SCHED-024
**File**: `src/backend/app/modules/admin/sync_status.py` (new file, registered in tenant admin router)
**Addresses**: L-02 (tenant-facing outcome-centric view)

**Description**:

Tenant Admin endpoint that returns outcome signals derived from `job_run_log`, not raw execution rows. Enterprise tenants do not care about `duration_ms` — they care about "are my documents current?" and "have my credentials been checked recently?".

**Response shape**:
```json
{
  "last_credentials_checked_at": "2026-03-20T05:00:22Z",
  "credentials_expiry_days_remaining": 12,
  "last_query_warming_completed_at": "2026-03-20T03:01:45Z",
  "last_health_score_calculated_at": "2026-03-20T02:03:42Z",
  "glossary_terms_active": 47
}
```

All fields are nullable — if a job has never run for this tenant, the field is `null`.

Auth: Tenant Admin scope only.

**Acceptance criteria**:

- [x] `GET /api/v1/tenant/sync-status` returns 200 with outcome-centric fields
- [x] `last_credentials_checked_at` derived from most recent `completed` row for `job_name='credential_expiry'` with this `tenant_id`
- [x] `last_query_warming_completed_at` derived from most recent `completed` row for `job_name='query_warming'` (platform-scope, tenant_id IS NULL)
- [x] `last_health_score_calculated_at` derived from most recent `completed` row for `job_name='health_score'` with this `tenant_id`
- [x] `credentials_expiry_days_remaining` derived from tenant's integration credential records (not from job_run_log)
- [x] `glossary_terms_active` derived from live query against `glossary_terms` table for this tenant
- [x] Non-tenant-admin JWT receives 403
- [x] All fields are nullable when no data available
- [x] No raw `job_run_log` internals (duration_ms, instance_id, etc.) exposed
- [x] 2 unit tests: no auth → 403, populated state → all fields present

---

### SCHED-028: Frontend — Platform Admin job history panel

**Status**: [x] complete
**Priority**: P2
**Effort**: 4h
**Depends on**: SCHED-026
**File**: `src/web/app/(platform)/platform/jobs/page.tsx` (new page, or new tab in existing Operations section)

**Description**:

Platform Admin UI for browsing `job_run_log` history via SCHED-026's endpoint. Located in the existing Platform Admin console under the Operations section (new tab or new sub-page — follow the `showTAPanel()` / `ta-panel-{name}` pattern established in the design system).

**Table columns**: job_name, last_run (started_at), duration (formatted), status badge, instance_id, records_processed.

**Filters**: job_name dropdown (populated from distinct job names), date range picker (from/to), status filter chips.

Status badge colors follow the design system severity tokens:
- `completed` → accent green
- `running` → warn yellow
- `failed` → alert orange
- `abandoned` → text-muted grey

**Acceptance criteria**:

- [x] Table renders rows from `GET /api/v1/platform/jobs/history`
- [x] `job_name` filter dropdown populated dynamically (distinct values from API or hardcoded list of known job names)
- [x] Date range filter controls `from_date` / `to_date` query params
- [x] Status filter uses outlined filter chips (not filled accent — follows design system)
- [x] Status badges use correct design system color tokens
- [x] Duration column formats ms as "2m 07s" (not raw ms)
- [x] Pagination: "Load more" or page controls using `limit` / `offset`
- [x] `instance_id` column truncated with tooltip showing full value
- [x] Loading state rendered while fetching
- [x] Empty state message when no rows match filters
- [x] Uses `DM Mono` for duration, `instance_id`, `records_processed` values (data columns per design system)
- [x] 0 TypeScript errors

---

## Phase 4 — Hardening

---

### SCHED-029: Add Redis AOF check to deployment CI pipeline

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: SCHED-002
**File**: CI pipeline configuration + deployment runbook/README
**Supersedes**: The runtime WARNING added in SCHED-001/SCHED-037 is the immediate runtime guard; this item adds CI enforcement so the deploy fails early if the target Redis instance has `appendonly=no`.

**Description**:

SCHED-001 adds a startup `redis_aof_disabled` WARNING log at runtime. SCHED-037 adds the startup AOF check to `main.py` lifespan. This item (Phase 4) upgrades the guard to fail the deploy in CI if the target Redis instance has `appendonly=no` — preventing the mis-configured instance from ever reaching production.

Add a pre-deploy CI step that runs `redis-cli CONFIG GET appendonly` against the target Redis instance and exits non-zero if the result is `no`. Document the requirement in the deployment checklist (README or ops runbook).

**Acceptance criteria**:

- [x] CI pipeline has a pre-deploy step that checks `CONFIG GET appendonly` on the target Redis instance
- [x] Step exits with non-zero status (fails the deploy) if result is `no`
- [x] Step passes if result is `yes`
- [x] Deployment documentation updated to note the AOF persistence requirement and CI enforcement
- [x] The CI step is clearly labeled "Redis AOF persistence check — required for distributed job lock correctness"

---

### SCHED-030: Add `terminationGracePeriodSeconds: 120` to Kubernetes deployment config

**Status**: [x] complete
**Priority**: P1
**Effort**: 1h
**Depends on**: None
**File**: `infra/k8s/deployment.yaml` (or equivalent) + `docker-compose.yml`

**Description**:

Kubernetes by default gives pods 30 seconds between SIGTERM and SIGKILL. The longest job (cost_summary, up to 30 minutes) will always be killed mid-run if the grace period is not extended. Set `terminationGracePeriodSeconds: 120` in the pod spec to give jobs 120 seconds to complete after receiving SIGTERM before Kubernetes force-kills.

Also set `stop_grace_period: 2m0s` in `docker-compose.yml` for local/Docker deployments.

Note: 120 seconds does not protect against the 30-minute cost_summary scenario, but it does protect the majority of jobs (which run in under 2 minutes). The distributed lock heartbeat (SCHED-002) and startup zombie cleanup (SCHED-005) handle the graceful degradation for jobs that are killed mid-run.

**Acceptance criteria**:

- [x] `terminationGracePeriodSeconds: 120` present in the Kubernetes pod spec
- [x] `stop_grace_period: 2m0s` present in `docker-compose.yml` for the backend service
- [x] Comment in both files explains the reason: "Background jobs may run up to 2 minutes; grace period ensures clean shutdown"
- [x] If no K8s deployment YAML exists yet, add a comment in `main.py` noting the requirement

---

## Testing

Testing items are shipped with their respective phase items, not as a separate phase. The grouping here is for tracking purposes.

---

### SCHED-031: Unit tests for `DistributedJobLock`

**Status**: [x] complete
**Priority**: P0
**Effort**: 3h
**Depends on**: SCHED-002
**File**: `src/backend/tests/unit/test_job_lock.py`

**Description**:

Unit tests for `app/core/scheduler/job_lock.py`. All tests use a fake/mock Redis client — no real Redis connection.

**Acceptance criteria**:

- [x] `acquire when key free` → `acquired=True`, `redis.set` called with `nx=True, ex=ttl`
- [x] `acquire when key held` → `acquired=False`, `redis.set` not called after first acquire
- [x] `context manager yields True when acquired` → body executes
- [x] `context manager yields False when skipped` → body still executes (but `acquired` is False)
- [x] `release with correct owner` → Lua script called, key deleted
- [x] `release after TTL expiry (token mismatch)` → Lua returns 0 → `job_lock_release_skipped` logged, no exception
- [x] `heartbeat extends TTL` → `redis.expire` called every `ttl // 2` seconds while job runs
- [x] `heartbeat stops when token stolen` → `redis.get` returns wrong value → heartbeat logs `job_lock_lost` and stops
- [x] `heartbeat cancelled in finally before release` → task is done before Lua script runs
- [x] `heartbeat detects stolen token → job task cancelled`: simulate token mismatch in heartbeat → assert outer job task receives `CancelledError` within `ttl // 2 + 1` seconds
- [x] All 10 test cases pass with `pytest src/backend/tests/unit/test_job_lock.py`

---

### SCHED-032: Unit tests for `timing.py`

**Status**: [x] complete
**Priority**: P0
**Effort**: 1h
**Depends on**: SCHED-003
**File**: `src/backend/tests/unit/test_scheduler_timing.py`

**Description**:

Unit tests for `app/core/scheduler/timing.py`. All tests mock `datetime.now()`.

**Acceptance criteria**:

- [x] `seconds_until_utc(2, 0)` at 01:00 UTC → returns ~3600 (within 5s tolerance)
- [x] `seconds_until_utc(2, 0)` at 01:59:30 UTC → returns 60.0 (60s floor applied)
- [x] `seconds_until_utc(2, 0)` at 02:00:00 UTC → returns ~86400 (next day)
- [x] `seconds_until_utc(2, 0)` at 02:00:30 UTC → returns ~86370 (not 0)
- [x] `seconds_until_utc(3, 30)` at 03:29 UTC → returns ~60 (30s away, floor applies)
- [x] All 5 test cases pass

---

### SCHED-033: Unit tests for `tool_health_job.py`

**Status**: [x] complete
**Priority**: P0
**Effort**: 3h
**Depends on**: SCHED-008
**File**: `src/backend/tests/unit/test_tool_health_job.py`

**Description**:

Unit tests specifically targeting the three H-0x bug fixes in SCHED-008.

**Acceptance criteria**:

- [x] `H-01 threshold check uses >= not ==`: counter jumping from 9 to 11 (2 pods increment simultaneously) still triggers unavailable state at 11
- [x] `H-01 counter at exactly threshold`: counter at exactly 10 triggers unavailable state
- [x] `H-02 counter TTL set on INCR`: Redis key has 7-day TTL after increment (mock Redis verifies EXPIRE called)
- [x] `H-02 counter deleted on tool DELETE`: DELETE route handler calls `redis.delete(counter_key)`
- [x] `H-06 P1 issue uses ORDER BY created_at ASC`: platform admin subquery includes `ORDER BY created_at ASC LIMIT 1`
- [x] `H-06 P1 issue uses NULL tenant_id`: INSERT does not propagate a platform admin's `tenant_id` to the issue row
- [x] All 6 test cases pass with `pytest src/backend/tests/unit/test_tool_health_job.py`

---

### SCHED-034: Integration tests for distributed lock

**Status**: [x] complete
**Priority**: P0
**Effort**: 3h
**Depends on**: SCHED-002
**File**: `src/backend/tests/integration/test_distributed_lock.py`

**Description**:

Integration tests using a real Redis instance (test environment Redis, no mocking). These tests verify the actual SET NX EX / Lua script / heartbeat behaviour against a live Redis.

**Acceptance criteria**:

- [x] `two concurrent coroutines, only one acquires`: run two tasks simultaneously, assert exactly one gets `acquired=True`
- [x] `second coroutine acquires after TTL expiry`: set short TTL (2s), wait 3s, assert second coroutine acquires
- [x] `heartbeat prevents TTL expiry`: set TTL=4s, heartbeat_interval=2s, hold lock for 6s, assert lock still held at 6s
- [x] `release clears key`: after context exits, key no longer exists in Redis
- [x] `skipped lock does not leave key`: when lock is not acquired, no new key is written
- [x] All 5 test cases pass against real Redis with `pytest src/backend/tests/integration/test_distributed_lock.py`
- [x] No mocking of Redis client — uses real Redis connection from test environment

---

### SCHED-035: Integration test — `tool_health_scheduler` is wired in `main.py`

**Status**: [x] complete
**Priority**: P0
**Effort**: 1h
**Depends on**: SCHED-008
**File**: `src/backend/tests/integration/test_tool_health_integration.py`

**Description**:

A regression test to prevent silent recurrence of H-07 (scheduler never started). Verify that `run_tool_health_scheduler` is registered in the `main.py` lifespan startup. This test should be a code-inspection test (not a full lifespan integration) — import `main.py`, inspect the lifespan function's source or mock `asyncio.create_task` and verify it is called with the tool health scheduler function.

**Acceptance criteria**:

- [x] Test imports `main` module and verifies `asyncio.create_task` is called with a coroutine from `run_tool_health_scheduler`
- [x] Test fails if `run_tool_health_scheduler` is removed from the lifespan without also removing this test
- [x] Alternative acceptable approach: run the full lifespan startup with mocked DB/Redis and assert `tool_health_job_started` log event is emitted
- [x] Test passes with `pytest src/backend/tests/integration/test_tool_health_integration.py`

---

### SCHED-036: Unit tests for startup zombie row cleanup (SCHED-005)

**Status**: [x] complete
**Priority**: P0
**Effort**: 1h
**Depends on**: SCHED-004, SCHED-005
**File**: `src/backend/tests/unit/test_zombie_cleanup.py`

**Description**:

Unit tests that verify the startup zombie row cleanup query in `main.py` behaves correctly under all boundary conditions.

**Acceptance criteria**:

- [x] (1) Insert 3 `status='running'` rows older than 1 hour → run startup cleanup → assert all 3 rows have `status='abandoned'`
- [x] (2) Insert 1 `status='running'` row 30 minutes old → run startup cleanup → assert row still has `status='running'` (not yet stale, threshold is 1 hour)
- [x] (3) Insert rows with statuses `completed`, `failed`, `abandoned` → run startup cleanup → assert all are untouched (only `running` rows are updated)
- [x] All 3 test cases pass

---

### SCHED-037: Startup AOF persistence check in `main.py` lifespan

**Status**: [x] complete (part of SCHED-001)
**Priority**: P1
**Effort**: 30 minutes
**Depends on**: SCHED-001
**File**: `src/backend/app/main.py`
**Addresses**: C-02 (Redis restart flushes lock keys — runtime early warning)

**Description**:

Add a dedicated `CONFIG GET appendonly` check to `main.py` lifespan startup — BEFORE the first scheduler task is created. This is the runtime guard; SCHED-029 (Phase 4) adds the CI enforcement layer on top.

**Acceptance criteria**:

- [x] `CONFIG GET appendonly` executes in the lifespan startup block before the first `asyncio.create_task()` for any scheduler
- [x] If result is `no`: log event `redis_aof_disabled` at WARNING with message "Job lock correctness requires Redis AOF persistence. Set appendonly=yes in redis.conf."
- [x] If result is `yes`: no warning emitted (silent pass)
- [x] Check is wrapped in `try/except` — if Redis is unreachable during the check, log WARNING and continue (non-blocking)
- [x] Check executes after DB zombie cleanup (SCHED-005) and before first scheduler task

---

### SCHED-038: Per-tenant job throttling for `query_warming`

**Status**: [x] complete
**Priority**: P2
**Effort**: 2h
**Depends on**: SCHED-010
**File**: `src/backend/app/core/scheduler/tenant_throttle.py` (new), `src/backend/app/modules/cache/query_warming.py`

**Description**:

Implement `app/core/scheduler/tenant_throttle.py` — a simple semaphore that limits concurrent per-tenant iterations in `query_warming.py`. Without throttling, query warming for 100 tenants launches 100 simultaneous LLM calls on pod startup, overwhelming the embedding service. Config: `SCHEDULER_MAX_CONCURRENT_TENANTS` env var, default 5. Integrate the semaphore into the `query_warming.py` job loop.

**Acceptance criteria**:

- [x] `src/backend/app/core/scheduler/tenant_throttle.py` exists
- [x] File exports a semaphore or throttle primitive keyed on `SCHEDULER_MAX_CONCURRENT_TENANTS` env var (default 5)
- [x] `query_warming.py` imports and applies the semaphore to its per-tenant iteration loop — at most `SCHEDULER_MAX_CONCURRENT_TENANTS` tenants run concurrently
- [x] Unit test: 10 tenants, semaphore=3, assert max 3 run concurrently at any given moment

---

## Completion Criteria

All SCHED-001 through SCHED-038 complete with:

- `alembic upgrade head` clean (v042 applied, head = 042)
- All unit tests passing: `pytest src/backend/tests/unit/test_job_lock.py src/backend/tests/unit/test_scheduler_timing.py src/backend/tests/unit/test_tool_health_job.py`
- All integration tests passing: `pytest src/backend/tests/integration/test_distributed_lock.py test_tool_health_integration.py`
- No `from apscheduler` imports anywhere in `src/backend/app/`
- All 13 jobs wrapped with `distributed_job_lock`
- `warm_up_glossary_cache()` converted to `asyncio.create_task()`
- `tool_health_scheduler` wired in `main.py` (H-07 permanently fixed)
- `job_run_log` rows written for every job execution
- Platform Admin job history panel renders correctly
- Tenant Admin sync-status endpoint returns outcome signals
- `terminationGracePeriodSeconds: 120` set in K8s deployment config
- Redis AOF startup check warns if persistence disabled

**COMPLETION STATUS**: ALL 38 ITEMS COMPLETE — commit `6e6237d` (2026-03-20)

---

## Red Team Remediation Map

| Finding | Severity | Addressed by | Phase |
|---------|----------|-------------|-------|
| C-01: Lock TTL expiry orphans in-flight jobs | CRITICAL | SCHED-002 (heartbeat) | 1 |
| C-02: Redis restart flushes lock keys | CRITICAL | SCHED-002 (AOF check), SCHED-029 | 1, 4 |
| H-01: INCR equality race skips P1 creation | HIGH | SCHED-008 (>= check + Lua) | 2 |
| H-02: Stale Redis failure counters | HIGH | SCHED-008 (7-day TTL + DELETE hook) | 2 |
| H-03: Missing composite index on job_run_log | HIGH | SCHED-004 | 1 |
| H-04: Zombie rows on SIGTERM | HIGH | SCHED-005 (startup cleanup), SCHED-023 (asyncio.shield) | 1, 3 |
| H-05: url_health_monitor TTL < worst-case | HIGH | SCHED-017 (dynamic TTL) | 2 |
| H-06: P1 assigned to non-deterministic tenant | HIGH | SCHED-008 (ORDER BY + NULL tenant_id) | 2 |
| H-07: tool_health_scheduler never started | HIGH | SCHED-008, SCHED-035 (regression test) | 2 |
| M-01: 60s floor causes cold-start job skip | MEDIUM | SCHED-025 (missed-job detection) | 3 |
| M-02: APScheduler.shutdown() never called | MEDIUM | SCHED-007 (belt-and-suspenders) | 1 |
| M-03: warm_up_glossary_cache blocks startup | MEDIUM | SCHED-020 (create_task) | 2 |
| M-04: Cold-start missed-job on rolling deploy | MEDIUM | SCHED-025 (job_run_log check) | 3 |
| L-01: AgentHealthMonitor is a third pattern | LOW | SCHED-019 | 2 |
| L-02: job_run_log is job-centric not outcome-centric | LOW | SCHED-027 (outcome endpoint) | 3 |
