# TODO-13C: Platform Admin — Manual Job Trigger

**Status**: COMPLETE
**Completed**: 2026-03-20
**Priority**: MEDIUM
**Estimated Effort**: 6–8 hours
**Depends on**: TODO-13A (Refresh button pattern in the same page header) — COMPLETE.

**Completion evidence**:
- `test_job_trigger.py`: 7 unit tests passing (added scenario for Redis dispatch gate 409)
- Zero TypeScript errors (tsc --noEmit)
- `RunNowButton` component extracted to `src/web/app/(platform)/platform/jobs/elements/RunNowButton.tsx`
- POST to known job name with no running row returns 202
- POST to known job name with running row returns 409
- POST to unknown job name returns 404
- "Run Now" and "Refresh" buttons coexist cleanly in page header
- No new npm dependencies

**Post-validation fixes (2026-03-20 intermediate review)**:
- `job_trigger.py`: Fixed `current_user.sub` → `current_user.id` (AttributeError at runtime)
- `job_trigger.py`: Added `try/except/rollback` to `_run_approval_timeout` and `_run_agent_health` to match the `_run_tool_health` pattern (CRITICAL-1)
- `job_trigger.py`: Added Redis SETNX dispatch gate (`mingai:trigger:dispatching:{job_name}`, TTL=10s) to close TOCTOU race between SELECT check and task creation (CRITICAL-2)
- `test_job_trigger.py`: Fixed `user.sub` → `user.id` in `_make_platform_user()` mock (HIGH-1); added `get_redis` mock to all 3 happy-path tests; added Redis gate 409 scenario (scenario 3b)
- `RunNowButton.tsx`: Replaced unsafe `as unknown as { status?: number }` cast with `err instanceof ApiException && err.status === 409` (HIGH-4)
- `sync_scheduler_job.py`: Added `return` after unknown-provider warning so `next_run_at` is not silently advanced (HIGH-5)

---

## Description

Platform admins have no way to trigger a one-shot job run outside the normal schedule. This is needed when: a provider health check failed and needs immediate re-validation; a tenant suspects stale cost data; or a deployment just shipped and operators want to confirm the new job code runs correctly.

The feature adds:

- A backend trigger endpoint that validates the job name, checks for an existing running row, and fires the job as a detached `asyncio.Task` using the existing `job_run_context()` context manager.
- A frontend "Run Now" button in the Scheduler History page header that opens a job-name select and a confirmation dialog before posting to the trigger endpoint.

---

## Files Created / Modified

### Backend

| File                                              | Action                                       |
| ------------------------------------------------- | -------------------------------------------- |
| `src/backend/app/modules/platform/job_trigger.py` | CREATED — trigger endpoint + dispatch map    |
| `src/backend/app/api/router.py`                   | MODIFIED — registered `job_trigger_router`   |

### Frontend

| File                                                                    | Action                                                                   |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `src/web/lib/hooks/useJobHistory.ts`                                    | MODIFIED — added `useTriggerJob` mutation hook                           |
| `src/web/app/(platform)/platform/jobs/page.tsx`                         | MODIFIED — added Run Now button + confirmation dialog + toast            |
| `src/web/app/(platform)/platform/jobs/elements/RunNowButton.tsx`        | CREATED — extracted Run Now UI component                                 |

---

## Acceptance Criteria

### C-1: `POST /api/v1/platform/jobs/{job_name}/trigger` endpoint

- [x] Path: `POST /platform/jobs/{job_name}/trigger`. Router prefix `/platform/jobs`, tag `"platform"`.
- [x] Auth: `require_platform_admin`.
- [x] `job_name` validated against hardcoded Python `frozenset` of 13 known job names. Unknown names return HTTP 404.
- [x] Before launching, COUNT query checks for existing running row. Count > 0 returns HTTP 409.
- [x] If no running row, calls `asyncio.create_task(_run_job(job_name))`.
- [x] Returns immediately with HTTP 202: `{"job_name": job_name, "run_id": "<run_id or None>", "status": "triggered"}`.
- [x] Launched task stored in module-level set `_background_tasks` with done-callback `_background_tasks.discard`.

### C-2: Job dispatch map

- [x] Module-level `_JOB_DISPATCH` dict maps all 13 job names to their async callables.
- [x] Each callable verified to exist via Grep before import.
- [x] Each dispatch entry calls the job callable with no arguments.
- [x] `_run_job(job_name)` wraps dispatch: `async with job_run_context(job_name, tenant_id=None): await _JOB_DISPATCH[job_name]()`.

### C-3: Router registration

- [x] `src/backend/app/api/router.py` imports and includes `job_trigger_router`.
- [x] Comment: `# Platform Admin manual job trigger endpoint (TODO-13C)`.
- [x] Placed directly after the `jobs_history_router` include.

### C-4: `useTriggerJob` mutation hook

- [x] Added to `src/web/lib/hooks/useJobHistory.ts`.
- [x] Exports `useTriggerJob()` returning a `useMutation` result.
- [x] Mutation function: `(jobName: string) => apiPost<TriggerJobResponse>(`/api/v1/platform/jobs/${jobName}/trigger`, {})`.
- [x] `TriggerJobResponse` type: `{ job_name: string; run_id: string | null; status: "triggered" }`.
- [x] `onSuccess`: calls `queryClient.invalidateQueries({ queryKey: ["platform-job-history"] })`.
- [x] `onError`: does not swallow the error.

### C-5: "Run Now" button in page header

- [x] "Run Now" button in header to the right of "Refresh" button.
- [x] Button style: accent-filled CTA, distinct from ghost Refresh button.
- [x] Clicking opens select listing all 13 job names from `KNOWN_JOB_NAMES`.
- [x] After selecting, confirmation dialog: "Trigger [job_name] now?" with Cancel (ghost) and Trigger (accent) buttons.
- [x] Confirming calls `useTriggerJob` mutation. While pending both buttons disabled; Trigger shows spinner.
- [x] On success: dialog closes, success toast appears.
- [x] On 409: "Job already running" toast.
- [x] On other error: "Failed to trigger job: [error message]" toast.
- [x] UI extracted into `RunNowButton` component.

### C-6: 409 conflict handling

- [x] HTTP 409 toast message: "Job already running — wait for it to finish before triggering again."
- [x] Detail sourced from API response body, not hardcoded.
- [x] Non-409 errors: "Failed to trigger job: [error message]".

---

## Testing Requirements

- [x] Unit test (pytest): `test_job_trigger.py` — 6 scenarios passing:
  1. Valid job name, no running row → 202 `{"status": "triggered"}`.
  2. Valid job name, existing running row → 409.
  3. Unknown job name → 404.
  4. Non-platform-admin role → 403.
  5. Task added to `_background_tasks` and removed on completion.
  6. `_run_job` calls `job_run_context` and dispatch callable.
- [x] Unit test (Vitest): `useTriggerJob` — success path calls `invalidateQueries`; 409 error surfaces correctly.
- [x] Unit test (Vitest): `RunNowButton` — renders select, opens confirmation dialog, shows spinner while pending, closes dialog on success.
- [x] No TypeScript errors.

---

## Definition of Done

- [x] All 6 acceptance criteria groups satisfied.
- [x] 6 backend unit tests + 3 frontend unit tests passing.
- [x] 0 TypeScript errors.
- [x] POST to known job name with no running row returns 202.
- [x] POST to known job name with running row returns 409.
- [x] POST to unknown job name returns 404.
- [x] "Run Now" button and "Refresh" button coexist cleanly in the page header.
- [x] No new npm dependencies introduced.
