# Completed: Phase 2 Backend — Infrastructure

**Completed**: 2026-03-07
**Commits**: 4e9cbf4, e269515, ea2c2ff
**Test evidence**: 716/716 unit tests passing
**Source file**: `todos/active/06-infrastructure.md` (items remain there, marked COMPLETED with evidence)

---

## INFRA-017: Redis Stream setup for issue reports

**Evidence**: `app/modules/issues/stream.py` — `STREAM_KEY = "issue_reports:incoming"`, `CONSUMER_GROUP = "issue_triage_workers"`, `STREAM_MAX_LEN = 10_000`, `ensure_stream_group()`, `publish_issue_to_stream()`; `tests/unit/test_issue_stream.py` — 11 tests across `TestStreamConstants` (3 tests: key value, consumer group value, max len value), `TestEnsureStreamGroup` (3 tests: creates group, idempotent on BUSYGROUP, raises on other errors), `TestPublishIssueToStream` (3 tests: calls xadd with correct fields, returns string entry id, handles None severity_hint), `TestProcessMessageFeatureType` (1 test), `TestProcessMessageBugType` (1 test). Commits: `4e9cbf4`, `e269515`.
**Commit**: e269515
**Files**: `app/modules/issues/stream.py`
**Effort**: 2h
**Depends on**: INFRA-009

**What was built**:
- `STREAM_KEY = "issue_reports:incoming"` — Redis Stream key constant
- `CONSUMER_GROUP = "issue_triage_workers"` — consumer group name constant
- `STREAM_MAX_LEN = 10_000` — enforced via `maxlen=` param on `XADD`
- `ensure_stream_group(redis)` — idempotent group creation using `XGROUP CREATE ... MKSTREAM`; swallows `BUSYGROUP` error; re-raises any other `ResponseError`
- `publish_issue_to_stream(report_id, tenant_id, issue_type, severity_hint, redis)` — validates all required fields, builds message schema `{report_id, tenant_id, issue_type, severity_hint, timestamp}`, executes `XADD` with `maxlen` trim, returns string entry ID

**Acceptance criteria** (all met):
- [x] Stream key issue_reports:incoming
- [x] Consumer group issue_triage_workers
- [x] MAXLEN 10,000 configured
- [x] Producer in app/modules/issues/stream.py
- [x] Redis Stream `issue_reports:incoming` created
- [x] Consumer group `issue_triage_workers` created
- [x] Stream max length enforced at 10,000
- [x] Intake endpoint successfully writes to stream
- [x] Message schema validated before XADD

---

## INFRA-018: Issue triage background worker (Redis Stream consumer)

**Evidence**: `app/modules/issues/worker.py` — `run_triage_worker()` (main loop with `XREADGROUP`), `process_message()` (full triage pipeline), `reclaim_abandoned_messages()` (XCLAIM); `_VISIBILITY_TIMEOUT_MS = 5 * 60 * 1000` (5-minute idle timeout); `_MAX_RETRIES = 3`, `_BASE_BACKOFF_SECONDS = 2` (exponential backoff); `create_github_issue()` for P0/P1 via `GITHUB_TOKEN`/`GITHUB_REPO` env vars; feature requests routed to `product_backlog` status bypassing triage agent. Commits: `4e9cbf4`, `e269515`.
**Commit**: e269515
**Files**: `app/modules/issues/worker.py`
**Effort**: 8h
**Depends on**: INFRA-017

**What was built**:
- `run_triage_worker(worker_id)` — infinite loop reading from `issue_reports:incoming` via `XREADGROUP` with `block=5000`ms; consumer ID derived from `worker_id + platform.node() + os.getpid()` for uniqueness
- `process_message(msg_id, fields, db_session, redis)` — loads full issue from PostgreSQL; routes feature type to `product_backlog` status; sets status to `triaging`, invokes `IssueTriageAgent`, updates to `triaged`; creates GitHub issue for P0/P1 via env-configured integration
- `reclaim_abandoned_messages(consumer_id, redis, db_session)` — uses `XPENDING_RANGE` + `XCLAIM` to reclaim messages idle > 5 minutes; processes and ACKs each reclaimed message
- Reclaim cycle runs every 10 XREADGROUP iterations (~50 seconds)
- 3-retry exponential backoff on `IssueTriageAgent` failures: 2s, 4s, 8s; marks `triage_error` on exhaustion
- `XACK` sent only after successful `process_message` completion

**Acceptance criteria** (all met):
- [x] XREADGROUP consumer in app/modules/issues/worker.py
- [x] IssueTriageAgent invocation with 3-retry exponential backoff
- [x] XCLAIM for abandoned messages (idle >5min)
- [x] XACK after successful processing
- [x] Optional GitHub issue creation for P0/P1
- [x] Worker reads from stream using consumer group
- [x] IssueTriageAgent invoked for each report
- [x] Issue report status updated after triage
- [x] GitHub issue created for non-duplicate bug reports
- [x] Abandoned messages reclaimed after 5-minute timeout
- [x] Messages ACKed after successful processing
- [x] Worker handles IssueTriageAgent failures gracefully (retry with backoff)
- [x] Feature request type routed to product backlog channel, not bug triage
