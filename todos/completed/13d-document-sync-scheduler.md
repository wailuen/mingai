# TODO-13D: Document Sync Scheduler — Periodic Automated Sync

**Status**: COMPLETE
**Completed**: 2026-03-20
**Priority**: HIGH
**Estimated Effort**: 8–10 hours
**Depends on**: TODO-13B — COMPLETE.

**Completion evidence**:
- `run_document_sync_scheduler` asyncio loop (SCHED-039) created in `src/backend/app/modules/documents/sync_scheduler_job.py`
- Wired into `src/backend/app/main.py` lifespan (startup + cancel-on-shutdown)
- `next_run_at` field added to SharePoint integration response (reviewer must-fix addressed)
- "Next scheduled sync" row added to `SchedulerSignalsCard`
- Exponential backoff added to `_advance_next_run_at` (reviewer must-fix addressed)
- Zero TypeScript errors (tsc --noEmit)
- Unit and integration tests passing

---

## Description

The `PATCH /documents/sharepoint/{id}/schedule` endpoint correctly saves a sync frequency and a computed `next_run_at` into `integrations.config['schedule']`. However, nothing ever reads `next_run_at` and fires a sync — no scheduler loop exists to act on it.

This todo closes that gap by adding an asyncio background loop that wakes every 60 seconds, queries for integrations that are due for a sync, and dispatches the appropriate sync function. It reuses the existing `job_run_context()` distributed-lock infrastructure so two pods cannot sync the same integration concurrently.

---

## Files Created / Modified

### Backend

| File                                                      | Action                                                                      |
| --------------------------------------------------------- | --------------------------------------------------------------------------- |
| `src/backend/app/modules/documents/sync_scheduler_job.py` | CREATED — asyncio scheduler loop (SCHED-039)                                |
| `src/backend/app/main.py`                                 | MODIFIED — wired into lifespan startup/shutdown                             |
| `src/backend/app/modules/documents/sharepoint.py`         | MODIFIED — `next_run_at` exposed in integration response; backoff in `_advance_next_run_at` |

### Frontend

| File                                                               | Action                                                         |
| ------------------------------------------------------------------ | -------------------------------------------------------------- |
| `src/web/lib/hooks/useSyncHealth.ts`                               | MODIFIED — `next_run_at` added to `Integration` interface      |
| `src/web/app/(admin)/admin/sync/elements/SchedulerSignalsCard.tsx` | MODIFIED — "Next scheduled sync" row added                     |

---

## Subtasks

### D-1: Backend — Sync dispatcher job (SCHED-039) — COMPLETE

- [x] Integrations with `next_run_at <= NOW()` and `status != 'disabled'` are dispatched within 60 seconds of becoming due.
- [x] `next_run_at` advances to the correct next occurrence after each dispatch (no re-trigger on the same timestamp).
- [x] Exponential backoff applied in `_advance_next_run_at` when retrying after dispatch failure (reviewer must-fix).
- [x] An integration with an already-running `sync_jobs` row is skipped without error.
- [x] An exception in one integration's dispatch block does not prevent other integrations from being processed.
- [x] `job_run_log` contains a row for each scheduler-triggered sync with `job_name = 'doc_sync:{integration_id}'`.
- [x] Google Drive uses `run_incremental_sync()` (delta) when a delta token exists; falls back to full sync otherwise.

### D-2: Backend — Wire into main.py lifespan — COMPLETE

- [x] `run_document_sync_scheduler` starts automatically when the FastAPI app starts.
- [x] Cancelling the task on shutdown does not raise an unhandled exception.
- [x] The task handle is stored so cancel can be called — not fire-and-forget without a handle.

### D-3: Backend — `sync_triggered_by` metadata — COMPLETE

- [x] Sync jobs triggered by the scheduler have `metadata.sync_triggered_by = "schedule"`.
- [x] Sync jobs triggered via the manual endpoint have `metadata.sync_triggered_by = "manual"`.
- [x] Reindex-triggered sync jobs have `metadata.sync_triggered_by = "reindex"`.
- [x] No Alembic migration file needed (`metadata` column already exists as JSONB).

### D-4: Frontend — "Next scheduled sync" indicator — COMPLETE

- [x] The Sync Health page shows "Next scheduled sync" for integrations that have a configured schedule.
- [x] The displayed time matches `integrations.config.schedule.next_run_at` from the API response.
- [x] `next_run_at` field now included in SharePoint integration response (reviewer must-fix addressed).
- [x] If no schedule is configured, the row shows "No schedule configured" in faint text.
- [x] Component renders without TypeScript errors (`next_run_at` properly typed as optional).
- [x] Design follows Obsidian Intelligence tokens (no hardcoded colours, correct typefaces).

---

## Acceptance Criteria (Feature-Level)

- [x] All integrations with a configured schedule are synced at approximately the right time (within 60 seconds of `next_run_at`).
- [x] Two pods cannot sync the same integration concurrently (distributed lock via `DistributedJobLock`).
- [x] If a sync is already running, the scheduler skips it without logging an error.
- [x] `next_run_at` advances correctly after each triggered sync.
- [x] Graceful shutdown: scheduler loop cancels cleanly with no orphaned sync jobs.
- [x] Google Drive uses incremental/delta sync when a delta token exists.
- [x] A sync triggered by the scheduler is distinguishable from a manual trigger in `sync_jobs.metadata.sync_triggered_by`.
- [x] The Sync Health UI shows the next scheduled sync time for integrations that have a schedule configured.

---

## Definition of Done

- [x] All subtasks D-1 through D-4 complete with all acceptance criteria met.
- [x] Unit and integration tests written and passing.
- [x] No TypeScript errors in modified frontend files.
- [x] `main.py` lifespan tested for clean startup and shutdown (no CancelledError leaks).
- [x] Code review completed (intermediate-reviewer). Must-fix items: `next_run_at` in SharePoint response + backoff in `_advance_next_run_at` — both addressed.
- [x] No policy violations (no hardcoded model names, no stubs, no secrets).
