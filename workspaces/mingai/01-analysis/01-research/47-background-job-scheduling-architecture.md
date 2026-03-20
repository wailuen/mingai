# Background Job Scheduling for Multi-Tenant SaaS
**Research file 47 — mingai platform**
**Date: 2026-03-20**

---

## Executive Summary

mingai already runs **13 distinct background jobs** launched as `asyncio.create_task()` from the FastAPI lifespan. This is the canonical in-process scheduler pattern. It works correctly for a single-instance deployment but carries four structural risks that become acute the moment a second pod is added in Kubernetes: duplicate execution, clock drift, in-memory state loss on restart, and zero tenant-level observability.

This document synthesises the problem space, evaluates all meaningful alternatives for a FastAPI + PostgreSQL + Redis stack, and produces a concrete recommendation calibrated to mingai's current scale and roadmap.

---

## 1. The Core Problem: Why In-Process Schedulers Break at Scale

### 1.1 What mingai Currently Does

Every job in `app/main.py` follows the same pattern:

```python
_task = asyncio.create_task(run_some_scheduler())
```

Each scheduler is an infinite `while True` loop with `asyncio.sleep(seconds_until_next_run())`. The loop exists entirely inside the single OS process running the FastAPI application. There is no coordination layer outside that process.

### 1.2 The Four Failure Modes

**Duplicate execution (thundering herd at scale)**
When Kubernetes runs two pods of the FastAPI backend — whether for HA, rolling deploy, or load — both pods launch all 13 jobs independently. The `run_health_score_job()` that iterates every active tenant and writes `tenant_health_scores` will fire from both pods simultaneously. The `ON CONFLICT ... DO UPDATE` upsert prevents data corruption but wastes double the LLM/DB cost. Jobs that send notifications (credential expiry, approval timeout) will send double notifications. Jobs that call external APIs (Azure cost pull, provider health check) will double-count rate-limit budgets.

**Split-brain (inconsistent schedule)**
Each pod computes `_seconds_until_next_run()` independently from its local clock. In a rolling deploy the new pod starts at an arbitrary time relative to the schedule. If pod A has been running since 01:58 UTC and pod B starts at 02:04 UTC, pod A will fire the `02:00 UTC` health score job and pod B will compute a 24-hour wait. For the next 24 hours only one pod runs the job. If that pod is drained, the job does not run until the following day — a 48-hour gap in health score data.

**In-memory state loss on restart**
The `provider_health_job.py` uses APScheduler (`AsyncIOScheduler`) stored entirely in process memory. On pod restart, APScheduler loses its job store. Any pending misfire within the `misfire_grace_time=60` window is silently dropped. More critically, no scheduler in the current codebase records its last execution time to a durable store. If the semantic cache cleanup pod restarts at 02:59 UTC it will sleep for 3600 seconds from restart time, not from the last actual run.

**No tenant-level job observability**
The structured log events (`health_score_job_tenant_processed`, `query_warming_tenant_complete`, etc.) are excellent for developer debugging but are inaccessible to tenant admins and platform operators through any UI or API. There is no way to answer: "When did the credential expiry job last run for tenant X? Did it succeed? How many credentials were flagged?" This is a product gap as mingai moves toward enterprise SLAs.

---

## 2. Alternative Solutions and Trade-offs

### 2.1 pg_cron (PostgreSQL-native)

**What it is**: A PostgreSQL extension that executes SQL or function calls on a cron schedule directly inside Postgres. Available on AWS RDS, Azure Database for PostgreSQL Flexible Server, and Cloud SQL.

**Strengths**:
- Zero additional infrastructure. The scheduler lives in the database.
- Exactly-once execution guaranteed by the single Postgres leader.
- Execution log in `cron.job_run_details` — queryable by tenant.
- Survives application restarts because it runs in the DB process.

**Weaknesses**:
- Can only execute SQL or stored procedures. Cannot run Python business logic (embedding calls, HTTP requests, LLM synthesis).
- Not available on all managed Postgres tiers. Cloud SQL requires superuser; some RDS parameter groups disallow it.
- Distributed multi-region deployments have a single pg_cron scheduler — cross-region latency is opaque.
- Each job row is global; tenant-specific schedules require one row per tenant (unscalable at 100+ tenants).

**Verdict for mingai**: Useful as a supplementary cleanup mechanism (e.g., `DELETE FROM semantic_cache WHERE expires_at < NOW()`) but cannot replace the Python job logic. The semantic cache cleanup job is the one current job that could be moved to pg_cron today with zero application code.

### 2.2 Celery Beat + Redis

**What it is**: Celery is a distributed task queue. Celery Beat is the periodic scheduler that pushes tasks to Celery workers via Redis (or RabbitMQ). Workers execute tasks asynchronously.

**Strengths**:
- Mature, battle-tested, well-documented.
- Beat is a single-leader process that emits tasks — no duplicate execution.
- Worker pool scales horizontally independently of the API pods.
- Built-in retry, rate limiting, and task routing.
- Task state stored in Redis result backend — queryable per task.

**Weaknesses**:
- Celery is synchronous by default. Async support (`celery[eventlet]` or `celery[gevent]`) is an add-on with its own caveats. The mingai codebase is entirely async (SQLAlchemy async, httpx, asyncio); bridging to Celery adds impedance.
- Introduces two new processes (Beat + Worker) plus a result backend in addition to existing Redis.
- Celery Beat itself is a single point of failure unless you add Beat HA with a DB-backed lock (e.g., `celery-redbeat`). Without `celery-redbeat`, Beat is just as fragile as the current asyncio loop — if the Beat pod dies, no jobs fire.
- `celery-redbeat` (Redis-backed Beat) solves the SPOF but adds another dependency and its own operational complexity.
- Multi-tenant task isolation requires explicit task routing and queue-per-tenant configuration at scale.

**Verdict for mingai**: High operational overhead for the current scale. The async impedance mismatch is a real cost. Appropriate if mingai needs to move heavy workloads (document indexing, embedding batch generation) off the API process entirely — but that is a separate concern from scheduling. Reject as the primary scheduling solution at this stage.

### 2.3 Temporal / Prefect / Airflow

**What they are**: Workflow orchestration platforms. Temporal is a durable execution engine. Prefect and Airflow are workflow/DAG schedulers.

**Strengths**:
- Temporal provides durable execution: workflows survive process crashes, network partitions, and deployments. State is persisted in the Temporal service.
- Native support for long-running multi-step workflows with retry semantics.
- Rich UI for workflow history and debugging.

**Weaknesses**:
- All three require operating a separate service cluster (Temporal server + DB; Prefect server; Airflow scheduler + workers + metadata DB).
- Temporal's client SDK is well-supported in Python but adds a new abstraction layer over asyncio that conflicts with the current FastAPI+asyncio pattern.
- Operational maturity requirement is high. Temporal in production requires a dedicated Postgres or Cassandra cluster for workflow history.
- Cost and complexity are disproportionate to the current scheduling problem, which is primarily "run these 13 jobs once a day without duplication".

**Verdict for mingai**: Defer. Revisit if mingai develops multi-step, long-running workflows (e.g., tenant provisioning, document re-indexing pipelines) that need durable execution guarantees. The tenant provisioning worker in `app/modules/tenants/worker.py` is the closest candidate — it implements its own state machine manually for exactly this reason.

### 2.4 Cloud Schedulers (AWS EventBridge, Azure Logic Apps / Scheduler, GCP Cloud Scheduler)

**What they are**: Managed cron-as-a-service that triggers HTTP endpoints or cloud functions on a schedule.

**Strengths**:
- Zero infrastructure to manage. Exactly-once trigger per schedule (cloud guarantees).
- Can invoke the FastAPI backend via HTTP (e.g., `POST /internal/jobs/run-health-score`).
- No duplicate execution across pods because the trigger comes from outside all pods.
- Audit log in the cloud console.

**Weaknesses**:
- Cloud-provider-specific: EventBridge syntax differs from GCP Cloud Scheduler. mingai is explicitly cloud-agnostic — using a cloud scheduler couples the scheduling layer to the cloud provider.
- Requires an authenticated internal endpoint on the API. If that endpoint is not secured, it is an attack surface.
- Minimum cron granularity is 1 minute on all three platforms (not an issue for mingai's current jobs).
- Local development and testing require either mocking the trigger or manually calling the endpoint.
- Does not solve the "what happened per tenant" observability gap.

**Verdict for mingai**: Viable and simple for a cloud-committed deployment, but violates the cloud-agnostic architecture principle. Could be an operator-configured option in Phase 2 (alongside the recommended Redis lock approach below) for customers on a single cloud.

### 2.5 Redis-Based Distributed Locks (Redlock)

**What it is**: Redlock is an algorithm (and library: `redis-py-redlock`, `aioredlock`) that uses Redis `SET NX EX` to implement a distributed mutex. The first process to acquire the lock runs the job; others skip.

**How it applies**: Before each job run, a pod attempts to acquire a lock with key `mingai:_platform:job_lock:{job_name}` and TTL slightly longer than the expected job runtime. If the lock is acquired, the job runs. If not, the pod skips silently.

**Strengths**:
- Uses the Redis instance that already exists in mingai's stack. Zero new infrastructure.
- Exactly-once execution across any number of pods.
- Lock TTL provides automatic recovery: if the pod holding the lock crashes mid-job, the lock expires and the next pod can acquire it on the next cycle.
- Non-disruptive to add: wraps existing job logic with two Redis calls.

**Weaknesses**:
- Redlock safety relies on Redis being highly available. With a single Redis instance (not Redis Cluster), a Redis restart could release all locks simultaneously, causing a brief window of duplicate execution.
- The lock TTL must be set correctly. Too short: lock expires while job is running, another pod acquires it, duplicate execution. Too long: if the job hangs, no pod can run the job until TTL expires.
- Does not solve the clock-drift split-brain problem for time-targeted jobs (e.g., "fire at 02:00 UTC"). Both pods still compute `_seconds_until_next_run()` independently. The distributed lock only prevents both from executing — it does not ensure exactly-once scheduling of the wake-up.
- The algorithm provides at-least-once safety only when the Redis instance is highly available (Redis Sentinel or Cluster). For a single-node Redis, Redlock degrades to a best-effort mutex.

**For mingai's stack**: Redis is already a critical component (JWT invalidation, cache, circuit breakers). A Redis outage already takes down the application. Adding job locks to Redis does not increase the blast radius of a Redis failure.

**Verdict for mingai**: The **recommended primary solution** for the near term. Details in Section 5.

### 2.6 Custom Leader Election

**What it is**: One pod is elected leader (via a Postgres advisory lock or Redis SETNX) and only the leader runs all scheduled jobs. All other pods are followers that do nothing for scheduling.

**How Postgres advisory lock works**:
```sql
-- In a background task, attempt to acquire lock ID 12345
SELECT pg_try_advisory_lock(12345);
-- Returns TRUE to exactly one pod. Others get FALSE and skip.
-- Lock released on session close (pod restart) or explicit pg_advisory_unlock.
```

**Strengths**:
- Postgres advisory locks are transactional and survive Redis failures.
- Elegant: the leader runs all jobs sequentially; zero coordination overhead per job.
- The Postgres advisory lock API is part of the standard PostgreSQL interface — cloud-agnostic.

**Weaknesses**:
- Requires a persistent database connection held by the scheduler loop. SQLAlchemy async connection pools recycle connections, making advisory lock management non-trivial (the lock is tied to the connection, not the transaction).
- Leader failure requires the lock to be released before another pod can step up. `pg_try_advisory_lock` (session-level) releases on connection close, but connection close detection has latency in Kubernetes (TCP keepalive timeouts).
- `pg_try_advisory_lock(key)` uses a 64-bit integer key. Managing a registry of key IDs across 13+ job types requires a conventions file and human discipline.
- All jobs serialise on the single leader. A long-running job (e.g., full query warming across 50 tenants at 0.1s/query = ~5 minutes) blocks the next scheduled job.

**Verdict for mingai**: Appropriate as an upgrade path if the distributed-lock-per-job approach (Section 2.5) proves insufficient at 50+ tenants. The Postgres advisory lock model is the architecturally cleanest single-leader solution on the existing stack.

---

## 3. Multi-Tenant Context: Specific Requirements

### 3.1 Tenant Isolation

mingai's current job architecture treats all tenants as a batch: `SELECT id FROM tenants WHERE status = 'active'` followed by sequential per-tenant processing. This is correct for small tenant counts but creates two isolation problems at scale:

**Cost contamination**: A tenant with 50,000 queries per day drives 100 embedding calls in the warming job that consume Azure OpenAI rate limit quota shared with real-time queries from all other tenants. No per-tenant rate limit budget is enforced at the job level.

**Failure propagation**: If a tenant's data is corrupted (NULL in a required column, schema mismatch after a failed migration), the exception is caught and logged but the sequential iterator means that tenant's error is silently swallowed. There is no per-tenant error budget or alerting.

**Recommendation**: Each job that iterates tenants should write a `job_run_log` record per tenant per execution. This record serves as both the audit trail and the basis for per-tenant alerting.

### 3.2 Per-Tenant Job Configuration and Throttling

Currently, all tenants share the same job parameters (e.g., `_MAX_QUERIES_PER_TENANT = 100` in `query_warming.py`). Enterprise tenants on higher-tier plans should be able to configure:

- Query warming depth (100 vs 500 queries)
- Sync frequency for Google Drive / SharePoint (daily vs hourly)
- Credential expiry warning window (30 days vs 60 days)

This configuration belongs in the existing `tenant_settings` table (or `tenant_configs` JSONB). Job logic should read tenant-specific config and fall back to platform defaults.

### 3.3 Observability: Per-Tenant Job History

The current structlog events are correct for operators reading log aggregators (Datadog, CloudWatch Logs). They are insufficient for:

- **Tenant admins** who want to know "when did my SharePoint sync last complete?"
- **Platform admins** who want to know "which tenants had health score calculation failures this week?"
- **Automated alerting** that needs a queryable failure count, not a full-text log search

A minimal `job_run_log` table solves this:

```sql
CREATE TABLE job_run_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name    TEXT NOT NULL,             -- 'health_score', 'query_warming', etc.
    tenant_id   UUID REFERENCES tenants,   -- NULL for platform-scope jobs
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL,             -- 'running', 'completed', 'failed', 'skipped'
    records_processed INT,
    error_detail TEXT,
    metadata    JSONB                      -- job-specific stats (warmed_count, etc.)
);
```

This table costs roughly 200 bytes per row. At 13 jobs × 365 days × 50 tenants = ~237,000 rows per year — entirely manageable without partitioning. At 500 tenants (enterprise scale), add a `job_run_log_y{year}` partition.

### 3.4 Cost Attribution of Job Execution

mingai already tracks LLM costs through `usage_events` and `cost_summary_daily`. Background jobs that consume LLM tokens (embedding warming, glossary miss signal analysis) should write `usage_events` with `event_type = 'background_job'` and the tenant_id they processed. This enables the platform cost dashboard to show "background job cost = X% of total token cost for tenant Y" — a genuine product insight that no off-the-shelf scheduler provides.

---

## 4. The 80/15/5 Product Lens

### 80% — Agnostic Infrastructure (Platform Default)

These patterns apply to any multi-tenant SaaS on FastAPI + PostgreSQL + Redis:

- **Distributed Redis lock per job**: wrap every scheduled job entrypoint with `async with redis_job_lock(job_name, ttl_seconds=...)`. The first pod to acquire the lock runs; others skip. Redis TTL auto-recovers from crashed pods.
- **Durable job run log**: write a `job_run_log` row per job invocation (started, completed/failed, metadata). Query this from the admin API.
- **Per-tenant error isolation**: catch exceptions per tenant in iterating jobs. A single tenant failure never blocks other tenants or the overall job.
- **Idempotent job logic**: every job upsert (`ON CONFLICT DO UPDATE`) is already in place. All new jobs must follow this pattern.
- **Jitter on interval-based jobs**: already implemented in `approval_timeout_job.py` and `url_health_monitor.py`. Apply the same pattern to all jobs to prevent thundering herd on pod restarts.

### 15% — Tenant Admin Self-Service

These tenant-controlled configurations add differentiated product value:

- **Sync schedule preference**: tenant admins can select Daily / Twice-daily / Hourly for document sync jobs (subject to plan tier limits). Stored in `tenant_settings`.
- **Notification preferences**: which job events trigger in-app notifications (credential near-expiry, health score drop, sync failure). Already partially implemented in HAR approval timeout job.
- **Warming depth override**: Professional and Enterprise plan tenants can increase embedding warming depth from 100 to 500 queries.
- **Job history API**: `GET /api/v1/tenant/jobs` returns the last 30 days of `job_run_log` for the calling tenant's jobs. Tenant admins see sync success/failure history without needing log access.

### 5% — mingai-Specific

These are genuinely specific to mingai's architecture:

- **Multi-cloud job execution**: the Google Drive sync, Azure cost pull, and provider health jobs are cloud-provider-coupled. Job routing logic should read `CLOUD_PROVIDER` to skip jobs irrelevant to the deployment (no Azure cost pull on a GCP deployment). This is already partially handled inside individual jobs.
- **HAR transaction timeout semantics**: the `approval_timeout_job.py` directly manipulates HAR state machine transitions (`PENDING_APPROVAL → TIMED_OUT`). This is not generic — it encodes the trust protocol's deadline enforcement semantics.
- **Tenant health score formula**: the weighted composite formula (`usage 30% + feature breadth 20% + satisfaction 35% + error rate 15%`) is a mingai product decision, not a generic scheduling concern.
- **Semantic cache TTL management**: the cleanup job deletes rows from `semantic_cache` using an `expires_at` column that encodes mingai's tiered cache TTL policy (24h for embeddings, 7d for LLM responses). This could be a pg_cron job at scale.

---

## 5. Recommended Architecture: Distributed Redis Lock Pattern

### 5.1 Design

A thin `DistributedJobLock` context manager wraps every job entrypoint. The scheduler loop calls the job function only if the lock is acquired. If the lock is not acquired (another pod is running the job), the scheduler logs a skip and waits for the next cycle.

```python
# app/core/scheduler/job_lock.py

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import structlog
from app.core.redis_client import get_redis

logger = structlog.get_logger()

# Platform-scope lock key namespace (no tenant_id — these are cross-tenant locks)
_LOCK_KEY_PREFIX = "mingai:_platform:job_lock"


@asynccontextmanager
async def distributed_job_lock(
    job_name: str,
    ttl_seconds: int,
    *,
    instance_id: Optional[str] = None,
) -> AsyncIterator[bool]:
    """
    Acquire a Redis distributed lock for a background job.

    Yields True if the lock was acquired (this pod should run the job).
    Yields False if the lock was already held (another pod is running it).

    Lock key: mingai:_platform:job_lock:{job_name}
    Lock value: instance_id (for debugging which pod holds the lock)
    TTL: ttl_seconds (must be > expected job runtime + 20% safety margin)

    On context exit, releases the lock only if this pod still holds it
    (Lua script for atomic check-and-delete).
    """
    redis = get_redis()
    lock_key = f"{_LOCK_KEY_PREFIX}:{job_name}"
    owner_id = instance_id or str(uuid.uuid4())

    acquired = await redis.set(lock_key, owner_id, nx=True, ex=ttl_seconds)

    if not acquired:
        logger.debug(
            "job_lock_not_acquired",
            job_name=job_name,
            reason="another_pod_holds_lock",
        )
        yield False
        return

    logger.debug("job_lock_acquired", job_name=job_name, owner_id=owner_id)
    try:
        yield True
    finally:
        # Atomic: only delete if we still own the lock (guard against TTL expiry + re-acquisition)
        release_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
        """
        released = await redis.eval(release_script, 1, lock_key, owner_id)
        if released:
            logger.debug("job_lock_released", job_name=job_name)
        else:
            logger.warning(
                "job_lock_release_skipped",
                job_name=job_name,
                reason="lock_expired_or_stolen",
            )
```

### 5.2 Integration with Existing Jobs

Each scheduler loop is updated to wrap the job call:

```python
# Before (health_score_job.py):
await asyncio.sleep(sleep_secs)
await run_health_score_job()

# After:
await asyncio.sleep(sleep_secs)
async with distributed_job_lock("health_score", ttl_seconds=1800) as acquired:
    if acquired:
        await run_health_score_job()
```

TTL guidelines for existing jobs:
| Job | Current interval | Recommended lock TTL |
|---|---|---|
| semantic_cache_cleanup | 3600s (hourly) | 600s |
| query_warming | 86400s (daily) | 1800s |
| health_score | 86400s (daily) | 1800s |
| cost_summary | 86400s (daily) | 1800s |
| azure_cost_pull | 86400s (daily) | 900s |
| cost_alert | 86400s (daily) | 600s |
| glossary_miss_signals | 86400s (daily) | 600s |
| credential_expiry | 86400s (daily) | 600s |
| url_health_monitor | 300s (5 min) | 240s |
| approval_timeout | 3600s (hourly) | 600s |
| provider_health | 600s (10 min) | 480s |
| agent_health_monitor | 3600s (hourly) | 600s |
| tool_health (if active) | 600s (10 min) | 480s |

### 5.3 Job Run Log Integration

Every job entrypoint writes to `job_run_log`:

```python
# Pattern for per-tenant iterating jobs
async def run_health_score_job() -> None:
    job_start = time.monotonic()
    run_id = str(uuid.uuid4())

    async with async_session_factory() as db:
        await db.execute(text("""
            INSERT INTO job_run_log (id, job_name, started_at, status)
            VALUES (:id, 'health_score', NOW(), 'running')
        """), {"id": run_id})
        await db.commit()

    try:
        # ... existing job logic ...
        status = "completed"
        error_detail = None
    except Exception as exc:
        status = "failed"
        error_detail = str(exc)
    finally:
        elapsed_ms = round((time.monotonic() - job_start) * 1000, 1)
        async with async_session_factory() as db:
            await db.execute(text("""
                UPDATE job_run_log
                SET finished_at = NOW(),
                    status = :status,
                    records_processed = :processed,
                    error_detail = :error,
                    metadata = CAST(:meta AS jsonb)
                WHERE id = :id
            """), {
                "id": run_id, "status": status,
                "processed": processed_count,
                "error": error_detail,
                "meta": json.dumps({"duration_ms": elapsed_ms, "tenant_count": tenant_count}),
            })
            await db.commit()
```

### 5.4 Clock Drift Mitigation

The existing `_seconds_until_next_run()` pattern is preserved — it is correct for computing when to sleep. The distributed lock solves the execution duplicate problem; clock drift is now a cosmetic issue (one pod fires at 02:00:01 UTC and another might try at 02:00:04 UTC, but the second will fail to acquire the lock). However, for strict time-targeting, replace `_seconds_until_next_run()` with a common implementation:

```python
# app/core/scheduler/timing.py

from datetime import datetime, timedelta, timezone

def seconds_until_utc(hour: int, minute: int = 0) -> float:
    """
    Compute seconds until next occurrence of hour:minute UTC.
    Returns at least 60 seconds to guard against double-fire on startup.
    """
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max((target - now).total_seconds(), 60.0)
```

All 8 daily schedulers should import `seconds_until_utc(hour, minute)` from this shared module rather than each implementing its own version. This eliminates the duplicated logic currently spread across `health_score_job.py`, `query_warming.py`, `cost_summary_job.py`, etc.

---

## 6. Value Propositions: Well-Designed vs Bolted-On

### 6.1 What a Well-Designed Distributed Scheduler Provides

**Operational trust**: When a customer emails "did my sync run last night?", the platform admin can answer in 5 seconds by querying `job_run_log` — not by grepping Datadog logs. This directly reduces support ticket resolution time and builds enterprise customer confidence.

**Predictable multi-instance behaviour**: Kubernetes autoscaling during peak hours (which may coincide with a scheduled job) does not cause double-billing or double-notification. The Redis lock is the single gate.

**Self-healing without operator intervention**: A pod crash mid-job releases the Redis lock (via TTL expiry). The next pod acquires the lock and re-runs the job on the next cycle. No manual intervention, no stale lock keys.

**Cost attribution completeness**: Background job token usage attributed to tenant via `usage_events` feeds the cost dashboard. Without this, the platform margin calculation (PA-013) systematically under-reports per-tenant costs by excluding background job token consumption.

### 6.2 What Bolted-On Solutions Miss

**pg_cron** can run the SQL DELETE in the semantic cache cleanup job but cannot call the Python embedding service. It creates a two-tier scheduling system that operators must understand separately.

**Celery Beat** solves the duplicate execution problem but introduces a new deployment artifact (the Beat pod) that itself is a SPOF unless `celery-redbeat` is added. The async impedance mismatch with FastAPI adds development friction on every new job.

**Cloud schedulers** (EventBridge, Logic Apps) require an authenticated internal HTTP endpoint on the API pod, which is an additional attack surface. They violate the cloud-agnostic architecture and cannot be run locally in development without mocking.

**Temporal** is the correct long-term answer for durable multi-step workflows, but is overengineered for the current problem, which is "don't run the same daily job twice."

---

## 7. Platform Model: Jobs as Infrastructure Value Layer

### 7.1 Producers, Consumers, Partners

**Producers** (jobs that create platform value by generating data):
- `run_health_score_job` — produces `tenant_health_scores` rows consumed by the platform admin dashboard
- `run_cost_summary_job` — produces `cost_summary_daily` consumed by cost analytics
- `run_query_warming_job` — produces warm embedding cache consumed by all users on first query
- `run_miss_signals_job` — produces glossary gap reports consumed by tenant admins

**Consumers** (who benefit from job output):
- End users: lower query latency from warmed embeddings
- Tenant admins: sync health, credential status, job history
- Platform admins: margin data, health scores, at-risk signals
- Automated systems: cost alerts, credential expiry notifications

**Partners** (infrastructure that enables reliable execution):
- PostgreSQL: durable job state, execution logs, at-risk detection history
- Redis: distributed lock coordination, event streams (issue triage worker), cache targets
- Azure / GCP / AWS APIs: Azure cost management, Google Drive webhooks (not scheduler-managed but job-triggered)

### 7.2 Network Effects of Reliable Scheduling

mingai's health score algorithm (`composite = usage_trend*0.30 + feature_breadth*0.20 + satisfaction*0.35 + error_rate*0.15`) requires 3 consecutive weeks of historical data to detect `usage_trending_down`. A missed nightly job breaks this chain. The at-risk detection that drives churn prevention only works if the scheduler is reliable. Scheduling reliability is therefore a prerequisite for a platform-level product feature (tenant health monitoring) — not a pure infrastructure concern.

---

## 8. AAA Framework Applied to Background Jobs

### 8.1 Automate: Reduce Operational Costs

| Job | Manual Equivalent | Estimated Automation Value |
|---|---|---|
| `run_health_score_job` | Platform admin manually queries 7 tables per tenant per day | 2–5 analyst-hours/day at 50 tenants |
| `run_cost_summary_job` | Finance team manually exports usage_events and aggregates | 4–8 hours/week per billing cycle |
| `run_credential_expiry_job` | Support team auditing integration health | 1–3 support tickets/week avoided |
| `run_approval_timeout_job` | Operator monitoring open HAR transactions | 1 ops check/day per 20 active transactions |
| `run_miss_signals_job` | Tenant admin reviewing search quality manually | Customer success call avoided per identified gap |

Automating these jobs is what makes the platform economics viable at 25+ tenants. Without them, operational headcount scales linearly with tenant count.

### 8.2 Augment: Reduce Decision-Making Costs

**Query warming** augments the RAG retrieval decision by pre-positioning the most likely embeddings. Without warming, the first query of the day for any tenant requires a live OpenAI embedding call (200–500ms added latency). With warming, the P99 latency for returning users is reduced.

**Health score trend detection** (`usage_trending_down` rule) augments the platform admin's churn detection by surfacing at-risk tenants before the account manager would notice manually. The `at_risk_flag` surfaces in the platform dashboard as a colour signal — no analysis required.

**Cost alert job** augments the budget decision by sending automated Slack/email notifications when a tenant exceeds 80% of their token budget, preventing surprise overages that generate support escalations.

### 8.3 Amplify: Reduce Expertise Costs at Scale

**Glossary miss signals** amplify the tenant admin's domain expertise by identifying queries where the RAG pipeline failed to expand terminology (e.g., "AWS" not expanded to "Annual Wage Supplement"). Without this job, the tenant would need NLP expertise to detect these gaps. With it, a non-technical HR manager can review a weekly report and add glossary terms.

**Credential expiry monitoring** amplifies IT admin awareness by automating the 30-day integration credential check. An enterprise IT admin managing 10 SharePoint and Google Drive integrations across departments would otherwise need a manual calendar reminder for each OAuth token expiry.

**Provider health job** amplifies platform engineering awareness by continuously verifying LLM provider connectivity. At 50+ active tenants, an LLM provider degradation that would previously surface as user complaints now surfaces as a provider status change in the platform dashboard within 10 minutes.

---

## 9. Implementation Priorities

### Immediate (before scaling beyond single pod)

1. Implement `DistributedJobLock` context manager in `app/core/scheduler/job_lock.py`
2. Wrap all 13 job entrypoints with the lock (one-line change per job)
3. Add shared `seconds_until_utc(hour, minute)` utility — remove duplicated implementations
4. Create `job_run_log` table via Alembic migration
5. Write start/complete/fail records in all job entrypoints

### Near-term (before Platform Admin GA)

6. Add `GET /api/v1/platform/jobs` endpoint returning `job_run_log` with tenant breakdown
7. Add `GET /api/v1/tenant/jobs` endpoint returning tenant-scoped job history
8. Move semantic cache cleanup DELETE to pg_cron (optional — reduces Redis lock overhead for the highest-frequency job)
9. Add `PLAN_REVENUE_*` and `INFRA_COST_PER_TENANT_*` env vars to `.env.example` documentation

### Deferred (Phase 2: 50+ tenants)

10. Per-tenant job parameters from `tenant_settings` (warming depth, sync frequency)
11. Celery workers for document indexing if that workload needs to be moved off the API process
12. Temporal consideration for multi-step provisioning workflows

---

## 10. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Redis outage drops all job locks | Low (Redis is already HA dependency) | Medium (jobs run duplicate for one cycle) | Lock TTL limits exposure to one job run per cycle |
| Lock TTL too short — job exceeds TTL | Low (TTLs set to 2× expected runtime) | High (duplicate execution for that cycle) | Monitor job duration metrics, alert if `duration_ms > 0.5 * ttl_seconds` |
| `job_run_log` table grows unbounded | Low (200B/row × 237K rows/year) | Low | Add `WHERE started_at < NOW() - INTERVAL '90 days'` cleanup in semantic cache job |
| Lock key namespace collision | Very low (`_platform` prefix is distinct from tenant keys) | Low | The `build_redis_key` function enforces the namespace. Lock keys use a separate `_platform` segment. |
| pg_cron unavailable on target cloud | Low (all three supported clouds have pg_cron) | Low | pg_cron is optional only for the cleanup job; Python job handles the same case |

---

## 11. Connection to Existing Architecture

The recommended solution requires:
- **Zero new infrastructure**: uses existing Redis and PostgreSQL
- **Minimal new code**: ~100 lines for `DistributedJobLock` + `seconds_until_utc`
- **One new DB table**: `job_run_log` (Alembic migration)
- **~26 line changes** across existing job files (13 jobs × 2 lines each: lock acquisition + log write)

The `build_redis_key` function in `app/core/redis_client.py` enforces the `mingai:{tenant_id}:{key_type}` namespace. Platform-scope lock keys use a special `_platform` tenant pseudo-ID segment: `mingai:_platform:job_lock:{job_name}`. This is consistent with the existing convention for platform-scope keys (cf. `_set_platform_scope_sql()` in `provider_health_job.py`) and prevents any collision with tenant-scoped keys.

The `app/modules/platform/provider_health_job.py` already uses APScheduler (`AsyncIOScheduler`) as an alternative pattern. This is a **divergent pattern** from the other 12 jobs. The recommended migration is to replace it with the same `asyncio.create_task` + distributed lock approach, eliminating the APScheduler dependency. APScheduler is not used anywhere else in the codebase and should not proliferate.
