# 22 — Distributed Background Job Scheduling — User Flows

**Generated**: 2026-03-20
**Feature**: Distributed Background Job Scheduling (Redis Lock Pattern)
**Related research**: `01-analysis/01-research/47-background-job-scheduling-architecture.md`
**Actors**: Platform Admin, Tenant Admin, System (infrastructure / background tasks)

---

## Flow Index

| #    | Flow                                     | Actor          | Trigger                                           |
| ---- | ---------------------------------------- | -------------- | ------------------------------------------------- |
| F-01 | View all job execution history           | Platform Admin | Daily operations review / audit                   |
| F-02 | Diagnose duplicate job execution         | Platform Admin | Anomaly detected in logs or cost spike            |
| F-03 | Manual job re-trigger                    | Platform Admin | New provider added; immediate health check needed |
| F-04 | Clear a stuck lock                       | Platform Admin | Stale lock alert; job has not run for >2× interval|
| F-05 | View job status for my tenant            | Tenant Admin   | Checking sync health or job recency               |
| F-06 | Job failure notification                 | Tenant Admin   | Receives alert after 3 consecutive failures       |
| F-07 | Normal distributed execution (happy path)| System         | Scheduled interval fires across 3-pod cluster     |
| F-08 | Pod crash mid-job                        | System         | Pod OOM-killed or evicted holding an active lock  |
| F-09 | Redis unavailable                        | System         | Redis connection refused / timeout                |
| F-10 | Cold start — first deploy                | System         | No prior job history; all jobs eligible to run    |
| F-11 | Clock skew between pods                  | System (edge)  | Pods have divergent system times                  |
| F-12 | Job duration exceeds lock TTL            | System (edge)  | External API rate-limit causes job to stall       |
| F-13 | Tenant deleted mid-job                   | System (edge)  | Tenant hard-deleted during health score batch run |

---

## F-01: Platform Admin Views All Job Execution History

**Trigger**: Platform Admin opens the job history dashboard during morning operations review, or after a customer reports a missing sync.
**Actor**: Platform Admin
**Entry**: Platform Admin Console → Operations → Job History

```
STEP 1: Navigate to Job History
  Admin clicks "Operations" in the Platform Admin sidebar.
  Clicks "Job History" sub-item.
  [FastAPI] GET /api/v1/platform/jobs
    — Queries job_run_log ORDER BY started_at DESC, LIMIT 200
    — Returns: job_name, tenant_id (null for platform-scope jobs), started_at,
      finished_at, status, records_processed, error_detail, metadata (JSONB)

STEP 2: Review the Job Table
  Table renders with columns:
    Job Name | Tenant | Started | Duration | Status | Records | Pod / metadata
  Rows are grouped by job_name with the most recent run at top.
  Status badges:
    completed  → accent green
    running    → accent pulsing
    failed     → alert orange
    skipped    → text-faint (lock not acquired)
  Duration shown in DM Mono (e.g., "1m 42s").

STEP 3: Filter and Search
  Admin applies filters:
    - Job name dropdown (all 13 jobs listed)
    - Status filter (completed / failed / skipped / running)
    - Tenant filter (platform-scope or specific tenant_id)
    - Date range picker (default: last 7 days)
  [FastAPI] GET /api/v1/platform/jobs?job_name=health_score&status=failed&since=7d
    — DB query: WHERE job_name = 'health_score' AND status = 'failed'
      AND started_at > NOW() - INTERVAL '7 days'

STEP 4: Expand a Row for Detail
  Admin clicks any row to expand an inline detail panel.
  Detail panel shows:
    - Full metadata JSONB rendered as key-value pairs
      (e.g., duration_ms: 92340, tenant_count: 24, failed_tenants: ["uuid1"])
    - error_detail (if any): monospace block
    - Pod instance ID from metadata.instance_id
  No navigation away from the table — detail is inline.

STEP 5: Export (optional)
  Admin clicks "Export CSV" at top-right.
  [FastAPI] GET /api/v1/platform/jobs?format=csv
    — Streams CSV with the same filtered result set.
```

**Expected result**: Platform Admin can answer "when did health_score last run, how long did it take, which tenants failed" within 5 seconds without access to Datadog or raw logs.

**Components involved**: FastAPI endpoint, PostgreSQL `job_run_log` table.

---

## F-02: Platform Admin Diagnoses Duplicate Job Execution

**Trigger**: Cost spike alert fires (token usage 2× normal), or Platform Admin notices two `completed` rows for the same job in the same minute window.
**Actor**: Platform Admin
**Entry**: Platform Admin Console → Operations → Job History

```
STEP 1: Spot the Anomaly
  Admin reviews the job history table (F-01).
  Sees two rows for 'health_score' with started_at within 10 seconds of each other:
    health_score | null | 02:00:01 UTC | completed | 24 tenants
    health_score | null | 02:00:04 UTC | completed | 24 tenants

STEP 2: Inspect Instance IDs
  Admin expands both rows.
  Row 1 metadata: { "instance_id": "pod-backend-abc12", "duration_ms": 91000 }
  Row 2 metadata: { "instance_id": "pod-backend-xyz34", "duration_ms": 89000 }
  Two different pods ran the same job simultaneously.
  This indicates the Redis distributed lock was NOT in place when these runs occurred
  (pre-migration deployment or a Redis outage degraded to no-lock mode).

STEP 3: Check Lock Status
  Admin navigates to Operations → Active Locks.
  [FastAPI] GET /api/v1/platform/jobs/locks
    — Queries Redis: KEYS mingai:_platform:job_lock:*
    — Returns: lock_key, owner_id (pod instance), ttl_remaining_seconds
  If no locks are active: normal (jobs completed and released locks).
  If a lock for 'health_score' is active with a very recent acquired_at: indicates the system
  is now lock-protected; the duplicate was from a prior unprotected deployment.

STEP 4: Confirm Root Cause
  Admin cross-references the duplicate run timestamps against the deploy history:
    - If timestamps fall within a rolling deploy window: the new pod started before the lock
      migration was applied to the old pod's running scheduler. Expected transient behavior.
    - If timestamps are post-migration: lock is not working. Escalate to engineering.

STEP 5: Assess Impact
  Admin uses the cost dashboard (Platform Admin → Finance → Cost Analytics) to check if
  usage_events records for those tenants show double the expected token consumption for that hour.
  If cost doubling is confirmed: open an internal incident note. Log the duplicate run IDs.
  If cost is normal: the lock prevented external API calls from doubling (upsert deduplication
  in DB prevented data duplication), no customer-visible impact.
```

**Decision points**:
- Duplicate during rolling deploy window → expected; no action required.
- Duplicate post-migration with Redis healthy → lock implementation bug; escalate.
- Duplicate with Redis outage in logs → Redis degraded to no-lock mode; see F-09.

**Components involved**: FastAPI job history endpoint, Redis KEYS scan, `job_run_log`, `usage_events`.

---

## F-03: Platform Admin Manually Re-Triggers a Job

**Trigger**: Platform Admin adds a new LLM provider and wants the provider health check to run immediately instead of waiting up to 10 minutes for the next scheduled cycle.
**Actor**: Platform Admin
**Entry**: Platform Admin Console → Operations → Job History → [Job Row] → Re-trigger

```
STEP 1: Locate the Target Job
  Admin opens Job History. Filters by job_name = 'provider_health'.
  Most recent row shows: started_at 7 minutes ago, status: completed.
  Admin clicks the row action menu (⋯) → "Run Now".

STEP 2: Confirm Re-trigger
  Confirmation dialog:
    "Force-run 'provider_health' now?
     This will attempt to acquire the distributed lock. If another pod is currently
     running this job, this request will be queued until the lock is free."
  [Run Now] [Cancel]
  Admin clicks "Run Now".

STEP 3: API Request
  [FastAPI] POST /api/v1/platform/jobs/provider_health/trigger
    — Auth: requires platform_admin or platform_operator role
    — Spawns asyncio.create_task() for run_provider_health_job()
    — Wrapper: async with distributed_job_lock("provider_health", ttl_seconds=480) as acquired:
        if acquired: await run_provider_health_job()
        else: return {"status": "lock_held", "message": "Another pod is running this job"}

STEP 4: Response Handling
  Scenario A — Lock acquired, job starts:
    API returns 202 Accepted: { "status": "started", "run_id": "uuid" }
    Admin sees a toast: "provider_health job started. Run ID: uuid"
    Job History table auto-refreshes every 5 seconds.
    New row appears with status "running" (pulsing accent).
    Row transitions to "completed" or "failed" when job finishes.

  Scenario B — Lock held by another pod:
    API returns 200 OK: { "status": "lock_held", "retry_in_seconds": 120 }
    Toast: "Job is currently running on another pod. Check back in ~2 minutes."
    Admin can manually refresh or wait for the next cycle.

STEP 5: Verify Result
  Admin expands the new completed row.
  metadata.provider_ids_checked lists the UUIDs of all providers tested.
  Any newly-added provider now has its first health_status entry.
```

**Expected result**: The newly-added provider's status transitions from "unchecked" to "healthy" or "error" within 2 minutes of the re-trigger instead of waiting up to 10 minutes.

**Components involved**: FastAPI trigger endpoint, Redis lock (`job_lock.py`), `job_run_log`, `llm_providers`.

---

## F-04: Platform Admin Clears a Stuck Lock

**Trigger**: Platform Admin receives an automated alert: "health_score job has not run in 48+ hours" (monitored via `job_run_log` — no `completed` row in the last 26 hours for a daily job). Investigation reveals a stale lock key in Redis.
**Actor**: Platform Admin
**Entry**: Platform Admin Console → Operations → Active Locks

```
STEP 1: Alert Fires
  Monitoring check runs every hour:
    [FastAPI background task or pg_cron]
    SELECT job_name, MAX(finished_at) as last_run
    FROM job_run_log
    WHERE status = 'completed'
    GROUP BY job_name
    HAVING MAX(finished_at) < NOW() - INTERVAL '26 hours'
      AND job_name IN ('health_score', 'query_warming', 'cost_summary', ...)
  Alert written to: platform_alerts table, platform admin notified via in-app notification.

STEP 2: Navigate to Active Locks
  Admin navigates to Operations → Active Locks.
  [FastAPI] GET /api/v1/platform/jobs/locks
    — For each key matching mingai:_platform:job_lock:*:
        HGETALL or GET the lock value (owner_id / instance_id)
        TTL via Redis TTL command
  Table renders:
    Lock Key             | Owner Pod             | TTL Remaining | Acquired ~
    job_lock:health_score| pod-backend-crashed99 | 47 minutes    | ~2 days ago*

  *Note: TTL remaining of 47 minutes with an acquired_at of 2 days ago is impossible under
  normal operation. This indicates the lock was re-set by something after the crash, OR the
  TTL was manually extended. The key detail is: job has not completed in 48 hours.

STEP 3: Investigate the Lock Owner
  Admin notes the owner pod ID: pod-backend-crashed99.
  Checks Kubernetes pod list (via link in admin console or separate k8s dashboard):
    pod-backend-crashed99 → Status: Terminated (OOMKilled 47 hours ago)
  The pod died before it could release the lock. The lock TTL (1800 seconds) should have
  expired automatically within 30 minutes of the crash — but did not.
  Possible cause: the lock was re-acquired by a new pod running a non-standard re-trigger
  (F-03) that set a very long TTL, or a manual Redis SET extended the TTL.

STEP 4: Clear the Lock
  Admin clicks "Clear Lock" next to the stale entry.
  Confirmation dialog:
    "Clear lock 'job_lock:health_score'?
     Owner pod: pod-backend-crashed99 (terminated)
     This will allow the next scheduler cycle to acquire the lock and run the job.
     Do NOT clear a lock for a pod that is still running — this risks duplicate execution."
  [Clear Lock] [Cancel]
  Admin clicks "Clear Lock".
  [FastAPI] DELETE /api/v1/platform/jobs/locks/health_score
    — Executes Redis DEL mingai:_platform:job_lock:health_score
    — Writes audit entry: { "action": "manual_lock_clear", "cleared_by": admin_id,
        "lock_key": "job_lock:health_score", "former_owner": "pod-backend-crashed99",
        "timestamp": now() }

STEP 5: Verify Recovery
  Admin waits for the next scheduler cycle (≤ interval for that job, max 24 hours for daily).
  To force immediate execution: use F-03 (manual re-trigger).
  Job History shows a new "running" → "completed" row.
  Active Locks table no longer lists the cleared key.
  In-app notification: "health_score job resumed after manual lock clear."
```

**Decision points**:
- Lock TTL should auto-expire without manual intervention in the normal pod-crash scenario (F-08). This flow applies only when TTL expiry did not occur or a new long-TTL lock was set incorrectly.
- Admin must confirm the owner pod is terminated before clearing. Clearing an active lock risks concurrent execution.

**Components involved**: FastAPI locks endpoint, Redis DEL, `job_run_log` (last-run check), `platform_alerts`.

---

## F-05: Tenant Admin Views Job Status for Their Tenant

**Trigger**: Tenant Admin wants to know when their SharePoint sync, glossary warmup, or embedding warming last ran successfully. Investigating a user complaint about stale search results.
**Actor**: Tenant Admin
**Entry**: Tenant Admin Console → Settings → Integrations & Sync

> **Note**: Tenant-facing signals are derived from `tenant_configs` and a `tenant_job_status` view, not raw `job_run_log` rows. The view translates internal job outcomes into the outcome-centric language that a Tenant Admin can act on. Raw metrics (duration_ms, records_processed, health_score job identifiers) are never surfaced here.

```
STEP 1: Navigate to Integrations & Sync
  Tenant Admin clicks "Settings" in the Tenant Admin sidebar.
  Clicks "Integrations & Sync" tab.
  [FastAPI] GET /api/v1/tenant/sync-status
    Auth: JWT must include tenant_id claim.
    — Queries tenant_job_status view (derived from job_run_log + tenant_configs):
        SELECT signal_name, last_success_at, status, credential_expires_at,
               actionable_message
        FROM tenant_job_status
        WHERE tenant_id = :tenant_id

STEP 2: Review the Outcome Signal Cards
  Page shows signal cards — each card describes a tenant-observable outcome, NOT a job name.
  Language is operational ("last synced", "credentials valid") not technical ("job ran"):

    ┌──────────────────────────────────────────────────┐
    │ ● SharePoint last synced: 2 hours ago  ✓         │
    │   Credentials: valid (expires in 14 days)        │
    └──────────────────────────────────────────────────┘
    ┌──────────────────────────────────────────────────┐
    │ ● AI query warmup: completed this morning  ✓     │
    │   Search responses are up to date               │
    └──────────────────────────────────────────────────┘
    ┌──────────────────────────────────────────────────┐
    │ ● Google Drive last synced: 6 hours ago  ✓       │
    │   Credentials: valid                             │
    └──────────────────────────────────────────────────┘
    ┌──────────────────────────────────────────────────┐
    │ ⚠ Glossary: 3 terms not found in recent queries  │
    │   Review your glossary to improve accuracy       │
    └──────────────────────────────────────────────────┘

  Status indicators:
    ✓ (accent green)  — last run successful, credentials valid
    ⚠ (warn yellow)   — action recommended (e.g., expiring credential, glossary gaps)
    ✗ (alert orange)  — action required (e.g., credential expired, sync failed 3× in a row)

STEP 3: Credential Expiry Warning
  If tenant_configs.sharepoint_token_expires_at < NOW() + INTERVAL '30 days':
    Card shows: "Credentials: valid (expires in N days)"
    If < 7 days: card border shifts to warn yellow.
    If expired: card shifts to alert orange with CTA: "Reconnect SharePoint →"
  This data comes from tenant_configs, not from job_run_log.

STEP 4: Actionable Error State
  If the most recent sync attempt failed (e.g., SharePoint 401):
    Card shows:
      ✗ SharePoint last synced: 3 days ago
        "Authentication expired. Reconnect to resume syncing."
        → [Reconnect SharePoint]
    The error message is written in tenant-actionable language.
    The underlying error_detail from job_run_log is NOT shown (no raw stack traces).

STEP 5: "What does this mean?" Link
  Each card has a small "?" link that opens a tooltip:
    SharePoint card: "mingai syncs your SharePoint documents regularly so that your team's
    AI queries reflect the latest content. If sync is delayed, search results may be stale."
  No internal terminology (job names, pod IDs, lock TTLs) appears in this view.
```

**What Tenant Admin CANNOT see**:
- Raw `job_run_log` rows, duration_ms, records_processed counts, pod identifiers.
- Platform-scope job names (health_score, cost_summary, provider_health).
- Job run counts, skip/lock-not-acquired statuses, or multi-pod scheduling details.

**Data model note**: The `tenant_job_status` view joins `job_run_log` (last completed/failed per job per tenant) with `tenant_configs` (credential expiry timestamps) to produce the `signal_name`, `last_success_at`, `status`, and `actionable_message` columns that power this UI.

**Components involved**: FastAPI `/tenant/sync-status` endpoint, `tenant_job_status` DB view, `tenant_configs`, `job_run_log` (read-only, via view).

---

## F-06: Tenant Admin Receives a Job Failure Notification

**Trigger**: The `health_score` or sync job fails for a specific tenant 3 consecutive times (tracked in `job_run_log`). The failure notification system fires.
**Actor**: Tenant Admin (receiver), System (sender)
**Entry**: In-app notification bell / email alert

```
STEP 1: Job Fails — First and Second Time
  Background job (e.g., query_warming) runs for tenant T1.
  Per-tenant exception is caught: SharePoint token has expired.
  [DB write] job_run_log INSERT: status='failed', error_detail='SharePoint token expired',
    tenant_id=T1.
  No notification sent yet. structlog event written: query_warming_tenant_failed.

STEP 2: Failure Count Check (after each failure)
  After writing the failed job_run_log row:
    [FastAPI background task or inline job logic]
    SELECT COUNT(*) FROM job_run_log
    WHERE tenant_id = :tenant_id
      AND job_name = :job_name
      AND status = 'failed'
      AND started_at > NOW() - INTERVAL '7 days'
      — Consecutive check: ensure the most recent N rows are all 'failed',
        not interspersed with successes.
  Count = 1: no notification.
  Count = 2: no notification.

STEP 3: Third Consecutive Failure — Notification Fires
  Count = 3 (and last 3 rows are all 'failed', not interrupted by a success):
  [FastAPI] NotificationService.send_tenant_job_alert(
      tenant_id=T1,
      job_name='query_warming',
      failure_count=3,
      last_error='SharePoint token expired'
  )
  Notification written to tenant_notifications table.
  In-app notification bell shows badge count (+1).
  Email sent to Tenant Admin's registered email (if email notifications enabled in settings).
  Email subject: "Action required: Embedding warmup has failed 3 times for your workspace"

STEP 4: Tenant Admin Opens the Notification
  Tenant Admin clicks the notification bell in the topbar.
  Notification reads:
    "The Embedding Warmup job has failed 3 consecutive times for your workspace.
     Last error: SharePoint authentication token expired.
     This may cause slower search response times for your team.
     → Reconnect SharePoint integration to resolve"
  Link in notification goes directly to Settings → Integrations → SharePoint.

STEP 5: Tenant Admin Resolves the Issue
  Tenant Admin clicks the link, re-authenticates SharePoint.
  [DB write] Integration credential updated, status='active'.
  Next scheduler cycle runs the job for this tenant:
    job_run_log INSERT: status='completed'.
  Notification badge clears (system detects a successful run after failure streak).
  No further alerts for this job unless a new 3-failure streak begins.
```

**Decision points**:
- "Consecutive" means the last N rows for that (job_name, tenant_id) are all 'failed'. A single success resets the counter.
- Notification is sent at failure count 3, then again at count 10 (escalation — signals unresolved issue), then suppressed until resolved.
- Platform Admin also sees the failure in their Job History (F-01) and in the tenant health score drop.

**Components involved**: `job_run_log`, `tenant_notifications`, NotificationService, email service.

---

## F-07: Normal Distributed Execution (Happy Path)

**Trigger**: Scheduled interval fires for `health_score` job (daily at 02:00 UTC). Three pods are running: pod-1, pod-2, pod-3.
**Actor**: System (all three pods, Redis, DB)

```
T=02:00:00 UTC — All three pods wake up

STEP 1: Each Pod Computes Sleep Duration
  [pod-1] seconds_until_utc(hour=2, minute=0) → 0 seconds (already past target, fires now)
  [pod-2] Same calculation (started at 01:58, same next-fire result)
  [pod-3] Same calculation
  All three pods exit their asyncio.sleep() call within a few seconds of each other.
  Jitter (random 0-30s) applied: pod-1 jitter=2s, pod-2 jitter=8s, pod-3 jitter=14s.

STEP 2: Lock Acquisition Race
  T=02:00:02 — pod-1 attempts lock:
    [Redis] SET mingai:_platform:job_lock:health_score "pod-1-instance-id" NX EX 1800
    Result: OK (lock acquired, TTL = 1800 seconds)
    [pod-1] Lock acquired. Proceed to run job.
    structlog: job_lock_acquired { job_name: "health_score", owner_id: "pod-1-instance-id" }

  T=02:00:08 — pod-2 attempts lock:
    [Redis] SET mingai:_platform:job_lock:health_score "pod-2-instance-id" NX EX 1800
    Result: nil (key already exists — NX condition not met)
    [pod-2] Lock not acquired. Skip.
    structlog: job_lock_not_acquired { job_name: "health_score", reason: "another_pod_holds_lock" }

  T=02:00:14 — pod-3 attempts lock:
    [Redis] SET mingai:_platform:job_lock:health_score "pod-3-instance-id" NX EX 1800
    Result: nil
    [pod-3] Lock not acquired. Skip.

STEP 3: pod-1 Runs the Job
  [DB] INSERT INTO job_run_log (id, job_name, started_at, status)
    VALUES (run_id, 'health_score', NOW(), 'running')
  pod-1 iterates active tenants: SELECT id FROM tenants WHERE status = 'active'
  For each tenant:
    - Reads query_counts, confidence_scores, feature_usage, error_rates
    - Computes composite health score (usage*0.30 + features*0.20 + satisfaction*0.35 + errors*0.15)
    - Upserts: INSERT INTO tenant_health_scores ... ON CONFLICT DO UPDATE
    - Writes per-tenant job_run_log row: status='completed' or 'failed'
  Per-tenant exceptions are isolated: one tenant's failure does not abort the loop.

STEP 4: Lock Release
  [pod-1] Job completes. Elapsed: 92 seconds.
  Lua script (atomic check-and-delete):
    if GET(lock_key) == "pod-1-instance-id" then DEL(lock_key)
  [Redis] Lock deleted. TTL was 1800 - 92 = 1708 seconds remaining (well within TTL).
  [DB] UPDATE job_run_log SET finished_at=NOW(), status='completed',
    records_processed=24, metadata='{"duration_ms":92000,"tenant_count":24}'
  structlog: job_lock_released { job_name: "health_score" }

STEP 5: pod-2 and pod-3 Continue Normally
  pod-2 and pod-3 log their skips and return to the scheduler sleep loop.
  seconds_until_utc(2, 0) → ~86400 seconds (sleep until next 02:00 UTC).
  No further action from pod-2 or pod-3 this cycle.
```

**Expected result**: Exactly one execution per cycle. 24 tenants processed once. `job_run_log` has one `completed` platform row and 24 per-tenant rows. No double token spend. Lock TTL never tested (job completed in 5% of TTL).

**Components involved**: Redis (`SET NX EX`, Lua DEL), PostgreSQL (`job_run_log`, `tenant_health_scores`), asyncio scheduler, `distributed_job_lock` context manager.

---

## F-08: Pod Crash Mid-Job

**Trigger**: pod-1 acquires the `query_warming` lock and begins iterating tenants. At T+3 minutes, Kubernetes OOM-kills pod-1. The lock was not released.
**Actor**: System (Redis TTL, pod-2, pod-3)

```
T=02:00:01 — pod-1 acquires lock
  [Redis] SET mingai:_platform:job_lock:query_warming "pod-1-xyz" NX EX 1800
  [DB] job_run_log: status='running', run_id=R1
  pod-1 begins iterating 24 tenants. Processes tenants 1-7 successfully.

T=02:03:12 — pod-1 OOMKilled
  Kubernetes sends SIGKILL. asyncio event loop terminates.
  The finally: block in distributed_job_lock DOES NOT execute (process killed, not exited cleanly).
  [Redis] Lock key still exists: mingai:_platform:job_lock:query_warming = "pod-1-xyz"
  [DB] job_run_log run_id=R1: status still 'running', finished_at = NULL.

T=02:00:01 + 1800s = 02:30:01 — Lock TTL expires
  [Redis] Automatic TTL expiry: key mingai:_platform:job_lock:query_warming deleted.
  No application code needed. Redis self-heals.

T=02:30:01 — pod-2 next scheduler cycle
  pod-2's scheduler loop wakes (it has been sleeping since its skip at 02:00:08).
  pods use seconds_until_utc() which re-fires after the interval, not at fixed clock times.
  If pod-2's sleep expires before the lock TTL: pod-2 will attempt the lock and find it still
  held → skip again. This repeats until TTL expires.
  Once TTL has expired: pod-2 successfully acquires the lock.

  [Redis] SET mingai:_platform:job_lock:query_warming "pod-2-abc" NX EX 1800 → OK
  [DB] INSERT job_run_log: new run_id=R2, status='running'
  pod-2 iterates ALL 24 tenants from scratch (tenants 1-7 re-processed, idempotent upserts).
  Job completes. Lock released. R2: status='completed'.

STEP — Startup Zombie Row Cleanup (runs BEFORE scheduler tasks start)
  On startup, app/main.py lifespan queries for any job_run_log rows with status='running'
  that are older than 2× the job's configured TTL. These are zombie rows left by pods that
  crashed without completing. This cleanup runs before any asyncio.create_task() scheduler
  calls, so no scheduler can acquire a lock until the orphan rows are resolved.

    UPDATE job_run_log
    SET status = 'abandoned',
        finished_at = NOW(),
        error_detail = 'pod_crashed_no_completion_detected_on_startup'
    WHERE status = 'running'
      AND started_at < NOW() - (ttl_seconds * 2) * INTERVAL '1 second'
      AND finished_at IS NULL

  R1 (pod-1's orphaned row) is detected by pod-2 on startup:
    R1.started_at = 02:00:01, pod-2 starts at 02:30:01 → elapsed = 1800s = 1× TTL.
    If 1× TTL < 2× TTL threshold: R1 is not yet marked abandoned on this pod's first startup.
    When pod-2 starts again after full TTL has elapsed (or any pod restarts later):
      R1.started_at is now older than 2× TTL → R1 transitions to status='abandoned'.

  structlog: job_zombie_rows_cleaned { count: 1, run_ids: ["R1-uuid"] }
  This ensures the job_run_log never accumulates indefinitely-stuck 'running' rows
  regardless of how many pod crashes occur.
```

**Gap between crash and recovery**: 30 minutes (1800s TTL). Acceptable for daily jobs. For the 5-minute interval jobs (url_health_monitor, provider_health), the TTL is 240-480s, so recovery is within 8 minutes.

**Key property**: Tenants 1-7 processed by pod-1 before the crash are re-processed by pod-2. All job logic uses `ON CONFLICT DO UPDATE` upserts — idempotent by design. No data duplication.

**Components involved**: Redis TTL auto-expiry, pod-2 scheduler loop, `job_run_log` (orphan cleanup query).

---

## F-09: Redis Unavailable

**Trigger**: Redis instance is unreachable (connection refused, network partition, maintenance restart). All three pods cannot connect to Redis.
**Actor**: System (all pods)

```
STEP 1: Redis Connection Fails at Lock Acquisition
  Scheduler cycle fires. pod-1 calls distributed_job_lock():
    redis.set(lock_key, owner_id, nx=True, ex=ttl_seconds)
  Redis client raises: redis.exceptions.ConnectionError (or asyncio.TimeoutError)

STEP 2: Exception Handling in distributed_job_lock
  The context manager catches the Redis exception.
  Behavior configured by REDIS_LOCK_DEGRADED_MODE env var (default: 'skip'):
    skip    → log warning, yield False (do not run the job)
    run_once → log warning, yield True (run the job without locking — RISK: duplicate execution)

  Default (skip) mode:
    structlog: job_lock_redis_unavailable { job_name, mode: "skip" }
    Yields False. Job does not run on any pod.
    All pods receive ConnectionError and skip.
    [DB] No job_run_log row written (skip without lock is not logged as a run).

STEP 3: Job Backlog
  If Redis is down for longer than the job interval:
    Daily jobs (e.g., health_score): miss one or more daily runs.
    5-minute jobs (e.g., url_health_monitor): miss multiple cycles.
  When Redis recovers: all pods attempt the lock at their next scheduled cycle.
  First pod acquires the lock; others skip. Job runs once. Normal cadence resumes.

STEP 4: Platform Admin Visibility
  structlog events are written to the application log, not to job_run_log
  (since no run record was created in skip mode).
  Platform Admin alert: "Redis connection errors detected" fires from the existing
  Redis circuit breaker monitoring (separate from job scheduling).
  Job History table will show a gap in completed rows for the affected window.
  Admin can use F-03 (manual re-trigger) once Redis recovers to backfill critical jobs.

STEP 5: Chat / API Impact
  Redis is already a critical dependency (JWT invalidation, semantic cache, circuit breakers).
  A Redis outage affects the entire application, not just job scheduling.
  Job scheduling degradation is the least-urgent impact of a Redis outage.
```

**Design note**: The `skip` default is correct for most jobs. The `run_once` mode (which allows un-locked execution) is available as a break-glass configuration for environments with unreliable Redis, at the cost of accepting duplicate execution risk during outages.

**Heartbeat cascade when Redis goes down**: If Redis becomes unavailable while a job is already in-flight and running with a heartbeat (see F-12), the heartbeat task will also fail — it cannot refresh the lock's EXPIRE. Any job that has been running for longer than its lock TTL at the time Redis connectivity is lost will have its lock expire. When Redis recovers, another pod (on its next scheduler cycle) will see no lock key and acquire it, starting a duplicate run while the original pod may still be executing. This is the same duplicate-execution scenario as F-12 triggered by Redis failure rather than Azure rate-limiting.

**Cascade sequence — Redis down with in-flight job**:
```
Redis goes down
  → heartbeat task: redis.execute_command("EXPIRE", ...) raises ConnectionError
  → heartbeat task logs warning and exits silently
  → lock TTL is no longer being refreshed
  → lock expires (after remaining TTL drains)
  → original pod continues executing (unaware lock is gone)
  → Redis recovers
  → next pod scheduler cycle fires, acquires lock (no key exists)
  → DUPLICATE EXECUTION: original pod + new pod both processing
```

This is why **C2 (Redis AOF persistence) is a deployment prerequisite**, not an optional enhancement. AOF persistence ensures Redis survives a restart without losing lock keys — meaning a Redis restart does not cause lock expiry for in-flight jobs. Without AOF, any Redis restart (maintenance, OOM, container eviction) triggers the cascade above.

**Components involved**: `distributed_job_lock` exception handler, Redis circuit breaker, structlog, heartbeat task (see F-12).

---

## F-10: Cold Start — First Deploy

**Trigger**: mingai backend starts for the first time (or after a full data wipe). No `job_run_log` rows exist. No Redis lock keys exist. All scheduler loops launch simultaneously from the FastAPI lifespan.
**Actor**: System (all pods at startup)

```
STEP 1: FastAPI Lifespan Starts
  app/main.py lifespan function:
    asyncio.create_task(run_semantic_cache_cleanup_scheduler())
    asyncio.create_task(run_health_score_scheduler())
    ... (13 tasks total)
  All 13 scheduler loops start simultaneously on each pod.

STEP 2: Scheduler Timing on First Start
  Each scheduler calls seconds_until_utc(target_hour, target_minute).
  Result: the next occurrence of the target hour in UTC.
  Example at T=09:15 UTC:
    health_score (target 02:00 UTC) → 59,700 seconds until next fire (~16.6 hours)
    query_warming (target 03:00 UTC) → 63,900 seconds (~17.75 hours)
    semantic_cache_cleanup (interval 3600s) → first fire in 3600 seconds (1 hour)
  Minimum 60-second floor enforced to prevent immediate double-fire on startup.

STEP 3: Jitter Applied
  Each scheduler adds random jitter (0 to 30 seconds for interval jobs,
  0 to 120 seconds for daily jobs) to its first sleep.
  This staggers the initial fires across pods even if they started at the same millisecond.

STEP 4: First Lock Acquisition (Each Job, First Cycle)
  When the first job fires (e.g., semantic_cache_cleanup at T+3600s):
    [Redis] Key mingai:_platform:job_lock:semantic_cache_cleanup → does not exist (cold Redis)
    pod-1 acquires the lock. Other pods skip.
    [DB] job_run_log: first row ever written for this job.

STEP 5: No Prior State to Read
  Jobs that check prior run state (e.g., "skip if already ran today"):
    SELECT MAX(finished_at) FROM job_run_log WHERE job_name=:job_name AND status='completed'
    → returns NULL on first run.
  Correct behavior: NULL means "never run" → run unconditionally.
  This is the intended cold-start behavior: all jobs run on their first cycle.

STEP 6: Daily Jobs on First Deployment
  If deployment happens at 09:15 UTC and the daily health_score target is 02:00 UTC:
  The first run will occur at 02:00 UTC the following day (~17 hours after deploy).
  This is correct. If an immediate run is needed: use F-03 (manual re-trigger).
```

**Expected result**: No crashes, no duplicate execution, no errors. All 13 job loops start cleanly with staggered first-fires. First actual executions happen at their scheduled times. Lock keys are created and deleted normally on first fire.

**Components involved**: FastAPI lifespan, `seconds_until_utc()`, jitter logic, Redis (empty on cold start), `job_run_log` (empty on cold start).

---

## F-11: Clock Skew Between Pods (Edge Case)

**Trigger**: pod-1 system clock is 4 minutes ahead of pod-2 (NTP misconfiguration or container clock drift).
**Actor**: System

```
SCENARIO: daily health_score job, target 02:00:00 UTC

T=02:00:00 (wall clock, pod-1's view)
  pod-1 local time: 02:00:04 (4 minutes fast)
  seconds_until_utc(2, 0) → pod-1 fires at what it thinks is 02:00 UTC.
  [Redis] SET job_lock:health_score "pod-1" NX EX 1800 → OK (lock acquired)
  pod-1 starts running health_score job.

T=02:00:00 (wall clock)
  pod-2 local time: 01:56:00 (4 minutes slow relative to pod-1)
  pod-2's seconds_until_utc(2, 0) → still 4 minutes until next target.
  pod-2 stays asleep.

T=02:04:00 (wall clock) — pod-2 wakes up
  seconds_until_utc(2, 0) from pod-2's perspective: 0 seconds → fires.
  [Redis] SET job_lock:health_score "pod-2" NX EX 1800 → nil (pod-1 still holds lock)
  pod-2 skips. Correct outcome.

ANALYSIS:
  The SET NX EX race condition is always won by whichever pod fires first.
  With a 4-minute clock skew:
    - pod-1 fires 4 minutes before pod-2.
    - pod-1 runs the job.
    - By the time pod-2 fires, pod-1's lock is active.
    - Pod-2 skips.
  Result: one execution, correct behavior, no duplicate.
  The clock skew causes a 4-minute drift in run time (02:00:04 instead of 02:00:00) — cosmetic.

RISKY EDGE: extreme skew (> lock TTL / 2)
  If pod-1 is 900 seconds fast and the lock TTL is 1800 seconds:
    pod-1 fires at wall-clock 01:45, acquires lock, lock expires at wall-clock 02:15.
    pod-2 fires at wall-clock 02:00, lock is still held → skips. Correct.
  If pod-1 is 1800 seconds fast (30 minutes):
    pod-1 fires at wall-clock 01:30, lock expires at 02:00.
    pod-2 fires at wall-clock 02:00, lock is gone → acquires, runs again.
    DUPLICATE EXECUTION. Two runs in the same calendar day.
  Mitigation: NTP must be configured correctly in container spec. Alert if clock offset > 60s.
  The recommended lock TTL (set to 2× expected runtime, capped at half the job interval)
  provides a safety margin. NTP drift of >1800 seconds (30 minutes) is an infrastructure failure.
```

**Decision point**: Clock skew under 30 minutes does not cause duplicate execution for daily jobs (1800s TTL). For the 5-minute jobs (url_health_monitor, provider_health, TTL=240-480s), the threshold is clock skew > 120-240 seconds. NTP is required infrastructure.

**Components involved**: `seconds_until_utc()` (shared utility), Redis SET NX EX, NTP (external dependency).

---

## F-12: Job Duration Exceeds Lock TTL (Edge Case)

**Trigger**: The `cost_summary` job normally runs in 8 minutes. Today, Azure Cost Management API is rate-limiting responses at 1 request per 10 seconds for 50 active tenants. Estimated job duration: 50 × 10s = 500 seconds (~8.3 minutes). The lock TTL is 1800 seconds. Actually: the rate limit is more severe — each tenant requires 3 API calls, and Azure returns 429 with `Retry-After: 60` headers. Effective duration: 50 × 3 × 60s = 9000 seconds (~2.5 hours), far exceeding the 1800s TTL.
**Actor**: System

> **Phase 1 change**: The heartbeat lock renewal pattern is now implemented in Phase 1, not deferred to Phase 2. The "TTL expires, second pod acquires" duplicate execution scenario described in the original flow is now **prevented** by the heartbeat. The original scenario is preserved below only as a degraded fallback path when the heartbeat itself fails.

```
T=02:00:01 — pod-1 acquires lock
  [Redis] SET job_lock:cost_summary "pod-1" NX EX 1800 → OK
  [DB] job_run_log: status='running', run_id=R1
  structlog: job_lock_acquired { job_name: "cost_summary", owner_id: "pod-1", ttl: 1800 }

T=02:00:01 — Heartbeat task starts in background
  Immediately after lock acquisition, the distributed_job_lock context manager spawns
  an asyncio background task: heartbeat_task.

  heartbeat_task logic (runs on pod-1, inside the same event loop):
    renewal_interval = TTL / 2  # = 900 seconds for this job
    while job_is_running:
        await asyncio.sleep(renewal_interval)
        [Redis] EXPIRE mingai:_platform:job_lock:cost_summary 1800
          — Refreshes the TTL back to 1800 seconds.
          — Uses the same owner_id check: only refresh if GET(lock_key) == "pod-1"
            (prevents refreshing a lock that has been manually cleared by Platform Admin).
        structlog: job_lock_heartbeat { job_name: "cost_summary", ttl_refreshed_to: 1800 }

  The heartbeat keeps the lock alive indefinitely as long as pod-1 is running the job.

T=02:00:01 to T=~04:30:00 — Job runs long due to Azure rate limiting
  Azure returns 429 with Retry-After: 60 for many tenant API calls.
  pod-1 continues processing, respecting backoff.
  Heartbeat fires at T+0:15:00 → EXPIRE refreshed to 1800s.
  Heartbeat fires at T+0:30:00 → EXPIRE refreshed to 1800s.
  ... (every 900 seconds throughout the job duration)
  pod-2 and pod-3 attempt the lock on their scheduler cycles:
    [Redis] SET job_lock:cost_summary "pod-2" NX EX 1800 → nil (lock still held)
    pod-2 skips. pod-3 skips.
  No duplicate execution. Heartbeat prevents the TTL from expiring.

T=~04:30:00 — Job completes normally
  pod-1 finishes processing all 50 tenants.
  Heartbeat task is cancelled (via asyncio.Task.cancel() in the context manager __aexit__).
  Lua script atomic release:
    if GET(lock_key) == "pod-1" then DEL(lock_key)
  [DB] UPDATE job_run_log: status='completed', finished_at=NOW(),
    metadata='{"duration_ms": 9000000, "tenant_count": 50}'
  structlog: job_lock_released { job_name: "cost_summary", duration_ms: 9000000 }

STEP — Duration Alert (still applies)
  Monitoring detects a job_run_log row with:
    started_at < NOW() - (ttl_seconds * 0.5) AND status = 'running'
  Alert fires: "cost_summary has been running for 15+ minutes (50% of TTL)."
  This is informational — the heartbeat prevents actual lock expiry, but the alert
  helps Platform Admin identify chronic Azure rate-limit issues worth investigating.

ERROR PATH — Heartbeat task itself crashes (Redis connection lost)
  If the Redis connection is lost while the job is in-flight:
    heartbeat_task: redis EXPIRE raises ConnectionError.
    Heartbeat task logs warning and exits:
      structlog: job_lock_heartbeat_failed { job_name, error: "ConnectionError" }
    The lock is no longer being refreshed.
    Remaining TTL drains to zero → lock key expires in Redis.
    pod-1 continues executing (it does not poll the lock during job execution).

  When Redis recovers:
    pod-2 or pod-3 scheduler cycle fires, finds no lock key.
    [Redis] SET job_lock:cost_summary "pod-2" NX EX 1800 → OK
    pod-2 starts a new run (duplicate execution).
    This is the old F-12 scenario — now a degraded fallback, not the normal path.

  Duplicate execution consequence:
    Both pods write to tenant_cost_summary via ON CONFLICT DO UPDATE (idempotent).
    Data is not corrupted. Double the Azure API quota is consumed for the overlap window.
    Platform Admin sees two 'running' rows in Job History (F-01) if both are still active.

  Recovery:
    Platform Admin can use F-04 (Clear Stuck Lock) once the situation is visible.
    The zombie row from the original pod will be cleaned up by the startup orphan
    cleanup (see F-08) when that pod eventually restarts.

  This degraded path is why C2 (Redis AOF persistence) is a deployment prerequisite.
  AOF persistence means Redis survives a restart without losing keys — so a Redis
  restart (the most common "Redis connection lost" event) does not trigger this path.
  See F-09 for the full Redis unavailability cascade.
```

**Components involved**: Redis `SET NX EX`, Redis `EXPIRE`, asyncio heartbeat task, Lua `check-and-delete`, `job_run_log` monitoring query, structlog alerting, Platform Admin alert system.

---

## F-13: Tenant Deleted Mid-Job (Edge Case)

**Trigger**: Platform Admin hard-deletes tenant T5 at 02:03 UTC. The `health_score` job acquired its lock at 02:00 UTC and is currently iterating tenant T5 (tenant 12 of 24).
**Actor**: System

```
SETUP:
  pod-1 runs health_score job. Tenant list loaded at 02:00 UTC:
    [tenant_ids] = [T1, T2, ..., T5, ..., T24]  (snapshot at job start)

T=02:03 UTC — Platform Admin hard-deletes T5
  DELETE FROM tenants WHERE id = T5 (CASCADE to related tables)
  This fires a cascading delete on: users, documents, tenant_health_scores, job_run_log
    where tenant_id = T5.
  Redis: FLUSHDB-pattern key deletion for namespace mingai:T5:*

T=02:03:30 UTC — pod-1 reaches T5 in the iteration
  QUERY: SELECT * FROM tenant_health_scores WHERE tenant_id = T5
  Result: empty (CASCADE deleted the health score rows, or the tenants row is gone)

  PATTERN A: Tenant row deleted before query
    SELECT id FROM tenants WHERE id = T5 → empty result set
    Per-tenant loop skips T5 (graceful): tenant_not_found logged.
    No exception. No disruption to T6-T24 processing.

  PATTERN B: Tenant row deleted mid-computation
    The job reads T5's data successfully (row still present at query time).
    Between the read and the INSERT INTO tenant_health_scores:
      DELETE FROM tenants WHERE id = T5 fires (cascade in progress).
    The INSERT/UPSERT fails with FK constraint violation:
      "insert or update on table tenant_health_scores violates foreign key constraint"
    Exception caught by per-tenant try/except block.
    [DB] Per-tenant job_run_log row: tenant_id=T5, status='failed',
      error_detail='FK_violation_tenant_deleted'
    structlog: health_score_tenant_failed { tenant_id: T5, error: FK_violation }
    Loop continues with T6. No impact on other tenants.

CLEANUP:
  Per-tenant job_run_log rows for T5 are cascade-deleted when T5 is deleted.
  The platform-scope job_run_log row (tenant_id=NULL) records:
    records_processed: 23 (not 24 — T5 was skipped/failed)
    metadata: { "tenant_count": 24, "skipped_tenants": ["T5-uuid"], "reason": "tenant_deleted" }

INVARIANT:
  A single tenant deletion MUST NOT abort the entire job run.
  Per-tenant exception isolation (separate try/except per tenant) is the enforcement mechanism.
  The platform-scope job_run_log row still shows status='completed' (23/24 tenants processed).
  T5's failure is recorded at the per-tenant level only.
```

**Decision point**: The platform-scope job is marked `completed` even if one tenant fails. This is correct — the job ran to completion; the failure was tenant-specific. A threshold rule (e.g., >20% of tenants fail → mark the platform job as `partial_failure`) can be added in Phase 2.

**Components involved**: PostgreSQL FK constraints, per-tenant try/except in job logic, `job_run_log` per-tenant rows, CASCADE deletes.

---

## Component Summary

| Component                        | Role in these flows                                               |
| -------------------------------- | ----------------------------------------------------------------- |
| Redis `SET NX EX`                | Distributed lock acquisition (F-07, F-08, F-11)                  |
| Redis TTL auto-expiry            | Lock recovery after pod crash (F-08); degraded fallback in F-12  |
| Redis `EXPIRE` (heartbeat)       | Lock renewal while long-running job is in progress (F-12)        |
| Redis Lua `check-and-delete`     | Atomic lock release — prevents stealing a re-acquired lock       |
| asyncio heartbeat task           | Background task that refreshes lock TTL every TTL/2 seconds (F-12)|
| PostgreSQL `job_run_log`         | Durable execution history (F-01, F-06, all system flows)         |
| `tenant_job_status` DB view      | Translates job outcomes to outcome-centric signals for F-05      |
| `tenant_configs`                 | Credential expiry data surfaced in F-05 sync-status cards        |
| `distributed_job_lock` context   | Wraps all 13 job entrypoints; handles acquire/skip/release/heartbeat |
| `seconds_until_utc()`            | Shared timing utility; prevents clock-drift split-brain          |
| FastAPI `/platform/jobs`         | Platform Admin job history and lock management API               |
| FastAPI `/tenant/sync-status`    | Tenant-scoped outcome signal API (F-05)                          |
| FastAPI `/platform/jobs/{}/trigger` | Manual re-trigger endpoint (F-03)                             |
| FastAPI `/platform/jobs/locks`   | Active lock inspection and manual clear (F-04)                   |
| NotificationService              | 3-consecutive-failure alert to Tenant Admin (F-06)               |
| Per-tenant try/except isolation  | Prevents one tenant's failure from aborting the full batch (F-13)|
| Startup zombie cleanup           | Marks abandoned 'running' rows before scheduler tasks start (F-08)|
