# Distributed Job Scheduling — Red Team Findings
**Research file 48 — mingai platform**
**Date: 2026-03-20**
**Companion to**: `47-background-job-scheduling-architecture.md`

---

## Overview

This document records 15 red team findings against the distributed job scheduling architecture described in file 47. The architecture proposes migrating mingai's 13 in-process `asyncio.create_task()` jobs to APScheduler with Redis-backed distributed locking (`SET NX EX`), a `job_run_log` audit table, and a `url_health_monitor` distributed lock pattern. Findings are ordered by severity within each tier.

Total findings: **2 CRITICAL · 7 HIGH · 4 MEDIUM · 2 LOW**

---

## CRITICAL Findings

---

### C-01 — Lock TTL expiry mid-run orphans in-flight jobs silently

**Severity**: CRITICAL

**Root cause (first principles)**

The `SET NX EX <ttl>` pattern grants a lock that expires after a fixed wall-clock duration. The lock has no knowledge of whether the job that acquired it is still alive. When the TTL elapses, Redis releases the key unconditionally. Any subsequent pod can immediately re-acquire it. The original pod is not notified. The two jobs are now running in parallel with no coordination, both writing to the same tables, calling the same external APIs, and consuming the same rate-limit budget.

The root cause is treating a time-based lease as a liveness proof. A time-based lease is only safe when `worst-case job runtime << TTL with meaningful margin`. The architecture does not enforce this invariant and, for at least one job, it is demonstrably violated.

**Exact manifestation**

The `cost_summary` job fetches Azure Consumption API data. Azure rate-limits this endpoint aggressively (approximately 12 requests per minute per subscription). For tenants with dense resource tagging, the job iterates hundreds of cost entries and back-fills multiple date ranges. Observed runtimes in analogous production deployments exceed 30 minutes. The architecture doc sets the `cost_summary` lock TTL to 1800s (30 min). A 31-minute run expires the lock at minute 30. Pod B acquires the lock. Both pods are now writing cost rows for the same tenant and date range simultaneously — the upsert prevents data duplication but doubles the Azure API call count, potentially triggering a 429 on pod A mid-write, which then raises an unhandled exception in the finally block.

The `job_lock_release_skipped` log event fires on pod B when it attempts to release a lock it did not acquire (Lua value mismatch). This event is logged at `WARNING` level with no alert attached. The situation is entirely silent to on-call engineers.

The orphan job on pod A continues executing with no awareness that coordination has been lost. No circuit breaker, no self-termination signal, no poison-pill mechanism exists.

**Affected files / lines**

- `app/jobs/distributed_lock.py` — `acquire_lock()` / `release_lock()` implementation; the Lua script checks token identity but provides no liveness extension mechanism
- `app/jobs/cost_summary_job.py` — job runtime vs. TTL ratio is the trigger condition
- `app/jobs/job_run_log.py` — `job_lock_release_skipped` event definition (no alert hook)
- `47-background-job-scheduling-architecture.md` §4.3 — TTL table; cost_summary listed at 1800s with no runtime upper-bound justification

**Remediation direction**

Implement a lock-extension (fencing) pattern: the job must periodically call a `extend_lock()` heartbeat (e.g., every 30 seconds) that resets the TTL only if the token still matches; if the heartbeat fails (Redis unreachable or token mismatch), the job must self-terminate. Pair with a Prometheus alert on `job_lock_release_skipped` that pages immediately.

---

### C-02 — Single-node Redis restart flushes in-flight lock keys

**Severity**: CRITICAL

**Root cause (first principles)**

Redis by default is an in-memory store with no persistence. When configured as a cache instance (the most common deployment pattern for a Redis sidecar or Azure Cache for Redis Basic/Standard tier), AOF (Append-Only File) persistence is disabled by default. A Redis restart — whether from OOM kill, node eviction, or rolling upgrade of the Redis pod — truncates all keys in memory. Any lock keys acquired before the restart are gone. All pods see an empty lock namespace and may immediately re-acquire.

The architecture document acknowledges Redis restarts in the "blast radius" section but frames the concern as availability (jobs stop running). This is incorrect. The actual risk is lock correctness: a pod that acquired a lock before the restart is still executing. After the restart, a second pod acquires the same lock key. Both pods are now running the same job concurrently. The blast-radius argument conflates availability with correctness; they are orthogonal properties. Availability degradation (jobs skip a run) is acceptable. Correctness violation (two pods write conflicting state) is not.

**Exact manifestation**

Scenario: Pod A acquires `mingai:lock:health_score_job` at T=0, TTL=300s. At T=90s, the Redis node is evicted (OOM or rolling upgrade in Azure Cache). The key is lost. At T=91s, Pod B starts and attempts `SET NX EX 300 health_score_job`. The key does not exist (it was flushed). Pod B acquires. At T=91s–T=300s, both Pod A and Pod B execute `run_health_score_job()` in parallel. Both iterate all active tenants. Both call LLM endpoints for tenant health scoring. Both write to `tenant_health_scores`. The upsert prevents a duplicate row but the LLM is called twice per tenant, doubling token cost for that run. Jobs that call external notification services (credential expiry, approval timeout) will send duplicate notifications to users.

This scenario is not hypothetical: Azure Cache for Redis Standard tier has a documented SLA of 99.9%, which allows approximately 8.7 hours of downtime per year. Rolling upgrades of the Redis instance occur during maintenance windows without tenant notification.

**Affected files / lines**

- `app/jobs/distributed_lock.py` — lock acquisition has no persistence prerequisite check
- `app/core/redis.py` (assumed) — Redis client configuration; AOF/persistence settings are external but the application makes no assertion about them
- `47-background-job-scheduling-architecture.md` §5.2 — "blast radius" analysis; the correctness vs. availability conflation is in the text

**Remediation direction**

Require Redis AOF persistence (`appendonly yes`, `appendfsync everysec`) as a deployment prerequisite and enforce it with a startup health check that reads `CONFIG GET appendonly` and refuses to start if it returns `no`. For environments where AOF cannot be enabled (Azure Cache for Redis Basic tier), document that distributed job locking is unsupported and enforce single-pod deployment for affected job types.

---

## HIGH Findings

---

### H-01 — Redis INCR equality check race condition skips P1 issue creation

**Severity**: HIGH

**Root cause (first principles)**

The tool health degradation detector uses `REDIS INCR mingai:tool_health:{tool_id}:failures` and then checks `if count == threshold`. An equality check (`==`) on a counter that is incremented by multiple concurrent writers is only safe when exactly one writer executes per increment cycle. With N pods, N INCR calls may be issued near-simultaneously. The counter jumps from `threshold - 1` directly to `threshold + (N - 1)`. No single pod sees the value equal to `threshold`. The condition is never satisfied. The P1 issue is never created.

This is a classic TOCTOU race: the counter transitions through the threshold value atomically (Redis INCR is atomic) but no single reader observes it at that value.

**Exact manifestation**

Two pods simultaneously detect a tool failure and each calls `INCR`. The counter increments from 4 to 6 (threshold = 5). Neither pod sees `count == 5`. No P1 issue is created despite 6 consecutive failures. The tool remains listed as degraded with no escalation. This condition worsens under load: with 4 pods, the counter can jump from 3 to 7 in a single failure cycle. The system silently fails to escalate on the exact failure event that should trigger paging.

**Affected files / lines**

- `app/jobs/tool_health_job.py` — failure counter increment and threshold check logic
- `47-background-job-scheduling-architecture.md` §6.4 — degraded/unavailable state machine description

**Remediation direction**

Replace `== threshold` with `>= threshold` and additionally gate on `count - 1 < threshold` (i.e., fire only when the increment crosses the threshold for the first time), implemented atomically via a Lua script that both increments and checks in a single Redis round-trip.

---

### H-02 — Stale Redis failure counters for deleted tools

**Severity**: HIGH

**Root cause (first principles)**

The failure counter keys `mingai:tool_health:{tool_id}:failures` are set with no TTL and no cleanup path. When a tool is deleted from the catalog, its Redis key persists indefinitely. Tool UUIDs in PostgreSQL are generated by the application layer and in some implementations may be reused (e.g., if a tool is deleted and re-created with a deterministic ID derived from the tool name or slug). A new tool inheriting a UUID with an existing failure counter starts its health history pre-poisoned.

**Exact manifestation**

A tool is deleted after accumulating 4 failures (threshold = 5). A new tool is created with the same UUID (deterministic slug-based ID generation). The new tool's counter starts at 4. Its first failure increments to 5, triggering an immediate P1 issue on a tool that has only failed once since creation. The on-call engineer investigates a phantom incident. Trust in the alerting system degrades.

Even without UUID reuse, unbounded key accumulation wastes Redis memory at scale. At 1,000 tenants × 50 tools each, with monthly tool churn of 10%, 60,000 stale counter keys accumulate annually.

**Affected files / lines**

- `app/jobs/tool_health_job.py` — counter INCR/DECR logic; no key expiry set
- `app/api/tools/` (tool deletion endpoint) — no counter cleanup on DELETE
- `47-background-job-scheduling-architecture.md` §6.4 — counter design; no lifecycle management described

**Remediation direction**

Set a TTL on all failure counter keys equal to `threshold_window * 2` (e.g., 48 hours for a 24-hour threshold window), and add a `DEL mingai:tool_health:{tool_id}:*` call to the tool deletion handler.

---

### H-03 — Missing composite index on job_run_log; wrong partition strategy

**Severity**: HIGH

**Root cause (first principles)**

The `job_run_log` table stores one row per job execution. Tenant admin queries ("show me all SharePoint sync runs for this tenant in the last 30 days") require filtering on `(tenant_id, started_at)`. Without a composite index on these two columns, every such query performs a full sequential scan. PostgreSQL's native range partitioning by year (`PARTITION BY RANGE (EXTRACT(year FROM started_at))`) does not help tenant-scoped queries: PostgreSQL's partition pruning activates only when the partition key (`started_at`) appears in the WHERE clause. A query filtering by `tenant_id` scans all partitions.

**Exact manifestation**

At 100 tenants × 13 jobs × 96 runs per day (15-minute jobs), `job_run_log` accumulates approximately 124,800 rows daily. After 90 days, 11.2 million rows. A tenant admin loading their job history page executes a query equivalent to `SELECT * FROM job_run_log WHERE tenant_id = $1 AND started_at > NOW() - INTERVAL '30 days' ORDER BY started_at DESC LIMIT 50`. Without the composite index, this is a 11.2M-row scan. P99 latency exceeds 5 seconds on a standard PostgreSQL instance. The partition-by-year strategy adds operational complexity (partition creation, `pg_partman` dependency) without providing any query performance benefit for the primary access pattern.

**Affected files / lines**

- `app/db/migrations/` — `job_run_log` table DDL (index definitions)
- `47-background-job-scheduling-architecture.md` §7.2 — schema and partitioning strategy

**Remediation direction**

Add a composite B-tree index `CREATE INDEX ON job_run_log (tenant_id, started_at DESC)` and replace the year-based range partition with a `tenant_id`-based hash partition (or drop partitioning entirely until the table exceeds 50M rows, which is not imminent at current scale).

---

### H-04 — 'running' zombie rows on SIGTERM with async finally-block failure

**Severity**: HIGH

**Root cause (first principles)**

When Kubernetes sends SIGTERM to a pod, Python's asyncio event loop begins shutdown. Tasks receive `CancelledError` at their next `await` point. The architecture relies on a `finally` block to UPDATE the `job_run_log` row from `status='running'` to `status='cancelled'`. If the `finally` block itself contains an `await` (e.g., `await db.execute(UPDATE ...)`) and the event loop is shutting down, that `await` raises `CancelledError` inside the `finally` block. The UPDATE never executes. The row stays at `status='running'` permanently.

This is not a theoretical edge case. Python 3.11+ cancellation semantics are well-defined: `CancelledError` propagates through `finally` blocks that contain `await` expressions unless explicitly suppressed with `asyncio.shield()`.

**Exact manifestation**

A rolling deploy drains a pod that is currently executing 13 jobs (one per scheduler, all running concurrently). Kubernetes sends SIGTERM. The event loop begins shutdown. Each job's `finally` block attempts an async DB write. 13 `CancelledError` exceptions are swallowed by the `finally` blocks or propagate unhandled. 13 rows remain at `status='running'` in `job_run_log`. Subsequent deployments accumulate 13 zombie rows per restart. After 10 rolling deploys, 130 phantom `running` rows exist. Monitoring queries that count active jobs (`SELECT COUNT(*) FROM job_run_log WHERE status='running'`) return inflated values. Alerts based on "jobs stuck in running state" fire incorrectly, or — worse — are tuned to ignore the noise and miss real stuck jobs.

**Affected files / lines**

- `app/jobs/job_run_log.py` — `update_job_status()` function called from `finally` blocks; if it uses `await db.execute()`, it is vulnerable
- `app/jobs/base_job.py` (assumed) — `try/finally` wrapper pattern
- `app/main.py` — lifespan shutdown sequence; no `asyncio.shield()` usage documented

**Remediation direction**

Wrap all finally-block async DB writes in `asyncio.shield()` to protect them from cancellation, and add a startup reconciliation query that sets all rows with `status='running'` and `started_at < NOW() - INTERVAL '10 minutes'` to `status='orphaned'` — clearing zombie state from prior restarts before the new pod begins taking locks.

---

### H-05 — url_health_monitor lock TTL shorter than worst-case runtime

**Severity**: HIGH

**Root cause (first principles)**

The `url_health_monitor` job checks the HTTP health of all agent URLs for all tenants. The architecture sets the lock TTL at 240 seconds. The worst-case runtime is bounded by: `total_agents × per-agent_timeout`. With 50 agents per tenant and a 10-second per-agent HTTP timeout (standard for health checks against slow enterprise endpoints), the single-tenant worst case is 500 seconds. Multi-tenant deployments multiply this further. The TTL (240s) is shorter than the single-tenant worst case (500s) by a factor of 2.

This is the same root cause as C-01 but for a different job, and it is independently discoverable because the TTL was set without a documented worst-case runtime calculation.

**Exact manifestation**

At T=0, Pod A acquires the `url_health_monitor` lock and begins iterating 50 agents. At T=240s, the lock expires. Pod B acquires it and starts its own iteration from agent 1. Both Pod A and Pod B are now pinging the same external agent URLs simultaneously. Each external URL receives two HTTP GET requests within seconds of each other. For agents hosted on slow or rate-limited enterprise infrastructure, this doubles inbound probe traffic. If either probe receives a 429 Too Many Requests from the target, the health check records the agent as `unhealthy` — a false negative caused by the monitoring system's own double-probe behavior. This creates a self-fulfilling failure: the monitor declares healthy agents unhealthy due to its own duplicate traffic.

**Affected files / lines**

- `app/jobs/url_health_monitor.py` — lock TTL constant; per-agent timeout constant
- `47-background-job-scheduling-architecture.md` §6.2 — lock TTL table

**Remediation direction**

Set the lock TTL to `max_agents_per_tenant × per_agent_timeout_seconds × 1.5` with a hard cap enforced at job startup that aborts if tenant agent count × timeout exceeds 80% of the TTL — and implement the lock heartbeat mechanism from C-01 as the canonical fix for both jobs.

---

### H-06 — P1 issue assigned against non-deterministic tenant from unordered subquery

**Severity**: HIGH

**Root cause (first principles)**

The `tool_health_job` creates a P1 issue when a tool reaches the failure threshold. The issue must be assigned to a platform admin. The architecture uses `SELECT id FROM users WHERE role = 'platform_admin' LIMIT 1` with no `ORDER BY`. PostgreSQL makes no guarantee about row order in the absence of an explicit `ORDER BY` clause. The result set order depends on physical storage layout (heap page order), MVCC visibility, and query plan selection — all of which vary between query executions, pod restarts, and VACUUM operations.

If platform admins have Row-Level Security (RLS) policies scoped to their tenant, a platform admin from Tenant X may not have visibility into a P1 issue created under Tenant Y's namespace, depending on how the RLS policies are defined.

**Exact manifestation**

Three platform admins exist: admin_1 (tenant_id=1), admin_2 (tenant_id=2), admin_3 (tenant_id=3). The `LIMIT 1` subquery returns admin_2 on Pod A (due to heap order) and admin_3 on Pod B (after a VACUUM changed physical row ordering). A critical tool failure creates a P1 issue assigned to admin_2. Admin_2 is on leave. No escalation path exists because the assignment is arbitrary. Admin_3, who is on-call, never sees the issue because it was not assigned to them. The P1 sits unacknowledged until the next health check cycle surfaces it again — if it does.

**Affected files / lines**

- `app/jobs/tool_health_job.py` — platform admin subquery for issue assignment
- `app/db/models/issues.py` (assumed) — P1 issue creation; assignee field

**Remediation direction**

Replace the non-deterministic subquery with a deterministic selection strategy: either assign to a designated `system_alert_inbox` user, or implement a round-robin assignment with `ORDER BY id` and a Redis cursor tracking the last-assigned admin ID to distribute load evenly.

---

### H-07 — tool_health_scheduler never started in main.py

**Severity**: HIGH

**Root cause (first principles)**

A scheduler that is defined but never registered with the application event loop produces no output and no error. Silent non-execution is the hardest failure mode to detect: the absence of log events is indistinguishable from a healthy job that has nothing to report.

**Exact manifestation**

`start_tool_health_scheduler(app)` exists as a function but is not called in `app/main.py`'s lifespan `startup` block, and no `asyncio.create_task(tool_health_scheduler())` is present. Tool health monitoring has never run in any environment. No `tool_health_job_started` log event has ever been emitted. No tool health P1 issues have ever been created from the automated path. This has likely been true since the function was written. The gap is pre-existing and invisible to anyone reviewing log dashboards, because zero events from a never-started job look identical to zero events from a job with nothing to report.

**Affected files / lines**

- `app/main.py` — lifespan startup block; `start_tool_health_scheduler` absent from task registration
- `app/jobs/tool_health_scheduler.py` — the scheduler function; correctly implemented but never invoked

**Remediation direction**

Add `asyncio.create_task(start_tool_health_scheduler(app))` to the lifespan startup block alongside the other scheduler registrations, and add a test that asserts all scheduler functions present in `app/jobs/` are registered in `main.py`'s startup sequence to prevent future silent omissions.

---

## MEDIUM Findings

---

### M-01 — seconds_until_utc() 60s floor causes systematic cold-start job skip

**Severity**: MEDIUM

**Root cause (first principles)**

The `seconds_until_next_run()` helper enforces a minimum sleep of 60 seconds to prevent hot-loop polling. This is a reasonable guard for steady-state operation. However, it interacts destructively with cold-start timing: a pod starting within 60 seconds of a scheduled job's fire time will compute a next-run interval of 60 seconds (the floor), wait 60 seconds, then compute the full interval to the next occurrence — approximately 24 hours later. The job that fired during the 60-second startup window is silently skipped. In single-pod deployments (Phase 1), this means a missed daily job. There is no catch-up or misfire detection.

**Exact manifestation**

Daily health score job is scheduled for 02:00 UTC. A rolling deploy completes at 02:00:01 UTC (the new pod starts one second after the scheduled slot). `seconds_until_next_run()` is called at T+01s. It computes seconds until the next 02:00 UTC occurrence: 86,399 seconds. But the 60s floor check fires first because the computed time is greater than 60s — the floor only applies when computed time is less than 60s. The actual miss scenario occurs when the pod starts at 01:59:30 UTC: computed time to 02:00 is 30 seconds, which is below the 60s floor, so the function returns 60 seconds. At T+60s (02:00:30 UTC), the job fires 30 seconds late — acceptable. The real danger is a pod starting at 02:00:00–02:00:59 UTC: computed time to next 02:00 is ~86,340 seconds. The job misses entirely. Rolling deploys during the daily job window (a common pattern: deploy after midnight) reliably produce this scenario.

**Affected files / lines**

- `app/jobs/scheduling_utils.py` — `seconds_until_next_run()` / `seconds_until_utc()` implementation; 60-second floor constant
- `47-background-job-scheduling-architecture.md` §3.1 — schedule calculation description

**Remediation direction**

Add a misfire detection check at job startup: if the last execution timestamp in `job_run_log` is more than `expected_interval × 1.1` in the past, execute immediately and then resume the normal schedule — eliminating the dependency on pod start time alignment with the scheduled slot.

---

### M-02 — APScheduler.shutdown() never called in lifespan

**Severity**: MEDIUM

**Root cause (first principles)**

APScheduler's `AsyncIOScheduler` runs its own internal polling loop on the asyncio event loop. When the FastAPI lifespan context exits (on shutdown), the scheduler object held in `app.state` goes out of scope, but the asyncio tasks it created are not explicitly cancelled. Python's garbage collector does not cancel asyncio tasks. The internal APScheduler polling task continues running until the event loop itself is forcibly closed by Uvicorn's shutdown sequence. Depending on shutdown timing, this can cause the scheduler to fire a pending job during the shutdown window — executing business logic against a partially-torn-down application state (closed DB connection pool, flushed Redis connections).

**Exact manifestation**

Pod receives SIGTERM. FastAPI lifespan `__aexit__` runs. `app.state.provider_health_scheduler` goes out of scope but its internal task is not cancelled. If a provider health check fires in the 1–5 second window between lifespan exit and event loop close, it attempts to acquire a Redis lock and write to the DB. The Redis client may be in a partially-closed state, raising a `ConnectionError` that is not caught because the exception handler expects normal operation context. This produces unstructured error logs at shutdown, polluting log analysis with false positives. Pre-existing bug unrelated to the APScheduler migration — but the migration makes it worse by adding a second scheduler instance with the same lifecycle gap.

**Affected files / lines**

- `app/main.py` — lifespan `__aexit__` block; no `scheduler.shutdown(wait=False)` call
- `app/jobs/provider_health_job.py` — `AsyncIOScheduler` instantiation stored in `app.state`

**Remediation direction**

Add `app.state.provider_health_scheduler.shutdown(wait=False)` and `app.state.tool_health_scheduler.shutdown(wait=False)` (once H-07 is fixed) explicitly in the lifespan `__aexit__` block before any connection pool teardown.

---

### M-03 — warm_up_glossary_cache is blocking at startup and not covered by distributed lock

**Severity**: MEDIUM

**Root cause (first principles)**

`warm_up_glossary_cache()` is called directly in the lifespan startup block (blocking, not via `asyncio.create_task()`). This means the FastAPI application does not begin accepting requests until glossary cache warm-up completes for all tenants. More critically, it is not registered in the distributed lock catalog. Multiple pods starting simultaneously each execute the warm-up independently, sending N × (number of tenants) queries to the vector database during the startup window. This is the "thundering herd on deploy" problem applied to a function that should be idempotent but is expensive.

The function also does not appear in the 13-job catalog documented in file 47, meaning it has no `job_run_log` entry, no observability, and no misfire handling.

**Exact manifestation**

A rolling deploy brings up 3 new pods simultaneously. Each pod calls `warm_up_glossary_cache()` at startup before Uvicorn begins listening. For 50 tenants × 3 pods, 150 glossary embedding queries hit the pgvector index within a 10-second window. Pod startup latency increases by the warm-up duration (potentially 30–60 seconds for large glossaries). If the warm-up fails (pgvector temporarily unavailable), the lifespan raises an exception and the pod fails to start — a startup failure caused by a non-critical optimization function.

**Affected files / lines**

- `app/main.py` — lifespan startup block; `warm_up_glossary_cache()` call site
- `app/jobs/glossary_cache.py` (assumed) — warm-up implementation; not in job catalog

**Remediation direction**

Move `warm_up_glossary_cache()` to an `asyncio.create_task()` call that runs after the server is ready, add it to the distributed lock catalog with a short TTL (so only one pod runs it per deploy cycle), and wrap it in a `try/except` so warm-up failures degrade gracefully rather than blocking startup.

---

### M-04 — Cold-start missed-job scenario on rolling deploy unaddressed

**Severity**: MEDIUM

**Root cause (first principles)**

In a rolling deploy, the old pod continues running until Kubernetes marks the new pod as Ready and begins draining the old one. The transition window is typically 30–120 seconds. If the daily job fires on the old pod at T=0 and the old pod is drained at T=30s (mid-job), the job is cancelled. The new pod, already running, computes its next scheduled time from its own start time — which is relative to when it was deployed, not when the job last succeeded. There is no handoff of "last successful execution time" between pods. Combined with the M-01 60s floor issue, the new pod may compute a next run of 23h+ from its start time, skipping the job entirely for the remainder of the day.

**Exact manifestation**

Tenant health score job fires at 02:00 UTC on Pod A. Rolling deploy starts at 01:58 UTC. Pod B starts at 01:59 UTC. Pod A fires the job at 02:00 and is drained at 02:00:45 (45 seconds into the job, which runs for 3 minutes). The job is cancelled mid-execution. Pod B, already running since 01:59, computed its next run as 02:00 UTC + 24h = 02:00 UTC tomorrow. Pod B does not execute the job today. Health scores are not updated. The tenant admin dashboard shows stale health data for 24 hours. This scenario is reproducible on every rolling deploy that overlaps with a scheduled job window — a routine operation.

**Affected files / lines**

- `app/jobs/scheduling_utils.py` — schedule calculation; no last-run persistence
- `app/jobs/job_run_log.py` — last-run query not used by scheduler
- `47-background-job-scheduling-architecture.md` §3.2 — rolling deploy analysis; scenario identified but not remediated

**Remediation direction**

At scheduler startup, query `job_run_log` for the last successful execution of each job; if the elapsed time since last success exceeds the job's interval, execute immediately and then resume normal scheduling — making last-run-based scheduling the primary path rather than wall-clock interval calculation.

---

## LOW Findings

---

### L-01 — AgentHealthMonitor is a third scheduling pattern omitted from migration scope

**Severity**: LOW

**Root cause (first principles)**

The architecture doc scopes the migration to two patterns: `asyncio.create_task()` infinite loops and APScheduler `AsyncIOScheduler`. However, `AgentHealthMonitor` uses a third pattern: a class-based `.start()` method that internally creates its own asyncio task. This pattern is not covered by the migration plan. After the APScheduler migration, two scheduling patterns remain in the codebase: the new APScheduler pattern (for migrated jobs) and the `AgentHealthMonitor` class-based pattern (unchanged). The stated goal of the migration — a single canonical pattern for all background jobs — is not achieved.

**Exact manifestation**

Post-migration code review identifies `AgentHealthMonitor.start()` as an undocumented third scheduler. New engineers assume it follows the APScheduler distributed lock pattern. It does not. A new job is written using the AgentHealthMonitor pattern instead of APScheduler, quietly escaping the distributed locking infrastructure. The second duplicate-execution bug is introduced.

**Affected files / lines**

- `app/monitoring/agent_health_monitor.py` — `AgentHealthMonitor` class; `.start()` method
- `47-background-job-scheduling-architecture.md` §2.1 — migration scope; AgentHealthMonitor not listed

**Remediation direction**

Either include `AgentHealthMonitor` in the APScheduler migration scope explicitly, or document it as a deliberate exception with a justification and a tracking item to migrate it in a follow-up sprint.

---

### L-02 — job_run_log data model is job-centric, not outcome-centric

**Severity**: LOW

**Root cause (first principles)**

The `job_run_log` schema records internal execution metadata: `job_name`, `duration_ms`, `records_processed`, `pod_id`, `lock_acquired`. These fields are useful for platform operators debugging job execution. They are not useful for tenant admins answering the question their SLA requires: "Did my SharePoint sync complete successfully since my last login? How many documents were indexed? Why did it fail?"

The data model was designed from the engineering perspective (what did the job do) rather than the user perspective (what outcome did the user receive). These are different schemas. A tenant admin does not know or care that `sharepoint_sync_job` ran; they care whether their document library is current and trusted.

**Exact manifestation**

Tenant admin opens the "Sync History" panel. The API queries `job_run_log WHERE job_name = 'sharepoint_sync_job' AND tenant_id = $1`. The UI renders rows with `duration_ms: 4821`, `records_processed: 143`, `status: completed`. The tenant admin wants to know: "Are my documents up to date?" The current schema cannot answer: it has no `documents_indexed`, `documents_failed`, `last_indexed_document_at`, or `sync_coverage_percent` field. The tenant admin sees internal platform plumbing, not business outcome signals. This is a product presentation gap that becomes a support burden as enterprise tenants onboard.

**Affected files / lines**

- `app/db/migrations/` — `job_run_log` DDL; `job_run_log` schema definition
- `47-background-job-scheduling-architecture.md` §7.2 — schema design rationale

**Remediation direction**

Add a `job_outcome` JSONB column to `job_run_log` for job-specific outcome metadata (e.g., `{"documents_indexed": 143, "documents_failed": 2, "source_last_modified": "..."}`) and design the tenant-facing "Sync History" UI against the `job_outcome` column, keeping the internal execution metadata columns for operator-only views.

---

## Remediation Priority Matrix

| Finding | Description | Pre-Phase 1 | Pre-Phase 2 | Pre-GA |
|---------|-------------|:-----------:|:-----------:|:------:|
| **C-01** | Lock TTL expiry orphans in-flight jobs | **MUST FIX** | — | — |
| **C-02** | Redis restart flushes lock keys | **MUST FIX** | — | — |
| **H-07** | tool_health_scheduler never started | **MUST FIX** | — | — |
| **H-04** | zombie 'running' rows on SIGTERM | **MUST FIX** | — | — |
| **H-01** | INCR equality race skips P1 creation | MUST FIX | — | — |
| **H-05** | url_health_monitor TTL < worst-case runtime | MUST FIX | — | — |
| **H-03** | Missing composite index on job_run_log | MUST FIX | — | — |
| **H-02** | Stale Redis counters for deleted tools | — | **MUST FIX** | — |
| **H-06** | P1 assigned to non-deterministic tenant | — | **MUST FIX** | — |
| **M-01** | 60s floor causes cold-start job skip | — | MUST FIX | — |
| **M-04** | Cold-start missed-job on rolling deploy | — | MUST FIX | — |
| **M-02** | APScheduler.shutdown() never called | — | MUST FIX | — |
| **M-03** | warm_up_glossary_cache not distributed-locked | — | — | **MUST FIX** |
| **L-01** | AgentHealthMonitor omitted from migration | — | — | MUST FIX |
| **L-02** | job_run_log data model job-centric not outcome-centric | — | — | MUST FIX |

### Rationale

**Pre-Phase 1 (before any multi-pod deployment)**:
C-01 and C-02 are blocking because the entire distributed locking architecture is predicated on correct lock behavior; deploying two pods without fixing these means the architecture provides false safety. H-07 is blocking because tool health monitoring is advertised as a Phase 1 capability and is currently completely non-functional. H-04 is blocking because 13 zombie rows per rolling deploy will corrupt job monitoring from the first deployment. H-01 and H-05 are blocking because they render the two most critical automated alerting paths (tool degradation, agent URL health) unreliable. H-03 is blocking because `job_run_log` is the observability foundation for all other features; a table that degrades to full-scan at 11M rows will become a query latency incident within 90 days of Phase 1 launch.

**Pre-Phase 2 (before multi-tenant GA with enterprise SLAs)**:
H-02 and H-06 become blocking as tenant count scales and tool churn increases. M-01 and M-04 become critical as rolling deploys are routine at Phase 2 scale. M-02 is a correctness issue that becomes observable under load.

**Pre-GA**:
M-03 becomes blocking when glossary cache warm-up times are significant at 100+ tenant scale. L-01 and L-02 are quality and product completeness issues that must be resolved before enterprise commitments.

---

*Red team findings represent adversarial analysis of the architecture as documented in file 47. Findings assume the implementation follows the architecture document exactly. Where implementation deviates, findings may not apply; where implementation introduces additional patterns, additional findings may be warranted.*
