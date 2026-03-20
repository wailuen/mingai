# TODO-13B: Tenant Admin — Per-Tenant Job History

**Status**: COMPLETE
**Completed**: 2026-03-20
**Priority**: MEDIUM
**Estimated Effort**: 5–6 hours
**Depends on**: Nothing — `job_run_log.tenant_id` column and `idx_jrl_tenant_time` index already exist (v042 migration, SCHED-004).

**Completion evidence**:
- `test_tenant_jobs.py`: 7 unit tests passing (expanded from 6 spec to 7 during implementation)
- Zero TypeScript errors (tsc --noEmit)
- `TenantJobHistoryCard` mounted on `/admin/sync` page
- `GET /api/v1/tenant/jobs` confirmed registered in OpenAPI `/docs`
- Tenant isolation verified: two-tenant test confirms no cross-tenant data leakage

---

## Description

Tenant admins currently see only abstract scheduler outcome signals on the `/admin/sync` page (`SchedulerSignalsCard`). They have no way to inspect the raw execution history of jobs that ran for their tenant. This todo adds a dedicated backend endpoint filtered by `tenant_id` and a frontend card that renders the results in a paginated table — mirroring the Platform Admin experience but scoped to one tenant.

---

## Files Created / Modified

### Backend

| File                                           | Action                                                 |
| ---------------------------------------------- | ------------------------------------------------------ |
| `src/backend/app/modules/admin/tenant_jobs.py` | CREATED — new router with `GET /api/v1/tenant/jobs`    |
| `src/backend/app/api/router.py`                | MODIFIED — registered `tenant_jobs_router`             |

### Frontend

| File                                                               | Action                                                                 |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| `src/web/lib/hooks/useTenantJobHistory.ts`                         | CREATED — React Query hook                                             |
| `src/web/app/(admin)/admin/sync/elements/TenantJobHistoryCard.tsx` | CREATED — paginated card component                                     |
| `src/web/app/(admin)/admin/sync/page.tsx`                          | MODIFIED — mounted `TenantJobHistoryCard` below `SchedulerSignalsCard` |

---

## Acceptance Criteria

### B-1: `GET /api/v1/tenant/jobs` endpoint

- [x] Route is `GET /api/v1/tenant/jobs` with prefix `/tenant`, tag `"admin"`.
- [x] Auth: `require_tenant_admin` dependency (same as `sync_status.py`).
- [x] Reads `tenant_id` from `current_user.tenant_id`; never accepts it as a query parameter.
- [x] Filters `job_run_log` by `tenant_id = :tenant_id` using the existing `idx_jrl_tenant_time` index (`ORDER BY started_at DESC`).
- [x] Supports optional query params: `limit` (int, default 10, max 100), `offset` (int, default 0), `status` (one of `running | completed | failed | abandoned | skipped`), `from_date` (date), `to_date` (date, inclusive = `< to_date + 1 day`).
- [x] Returns `JobHistoryResponse` with the same shape as `jobs_history.py`: `{ items, total_count, limit, offset }`.
- [x] `items` fields: `id`, `job_name`, `instance_id`, `tenant_id`, `status`, `started_at`, `completed_at`, `duration_ms`, `records_processed`, `error_message`.
- [x] Invalid `status` value raises HTTP 422 with descriptive detail message.
- [x] All user-supplied values bound as SQLAlchemy named parameters (never f-string interpolated).
- [x] A tenant with no job history rows returns `{ items: [], total_count: 0, limit, offset }` (not 404).

### B-2: Router registration

- [x] `src/backend/app/api/router.py` imports `tenant_jobs_router` from `app.modules.admin.tenant_jobs` and calls `router.include_router(tenant_jobs_router)`.
- [x] Comment above the include line reads `# Tenant Admin job history endpoint (TODO-13B)`.
- [x] Registration placed after the `sync_status_router` include to maintain module grouping.

### B-3: `useTenantJobHistory` hook

- [x] File: `src/web/lib/hooks/useTenantJobHistory.ts`.
- [x] Exports `useTenantJobHistory(offset: number, limit: number, filters?: TenantJobHistoryFilters)`.
- [x] `TenantJobHistoryFilters` type: `{ status?: string; from_date?: string; to_date?: string }`.
- [x] Calls `GET /api/v1/tenant/jobs?limit=...&offset=...&[filters]` via `apiGet`.
- [x] `queryKey`: `["tenant-job-history", offset, limit, filters]`.
- [x] `staleTime`: `30_000`.
- [x] `refetchInterval`: adaptive — `15_000` when any item has `status === "running"`, `60_000` otherwise.
- [x] Reuses `JobRunRow` and `JobHistoryResponse` types imported from `useJobHistory.ts`.

### B-4: `TenantJobHistoryCard` component

- [x] File: `src/web/app/(admin)/admin/sync/elements/TenantJobHistoryCard.tsx`.
- [x] Card matching Obsidian Intelligence design system: `rounded-card border border-border bg-bg-surface p-5`.
- [x] Card heading: "Job History"; subtitle: "Recent background job runs for your workspace".
- [x] Status filter chip row above the table. Chips: All / Running / Completed / Failed.
- [x] Table columns: Job, Started, Duration, Status, Records.
- [x] `JobStatusBadge` component reused from platform jobs elements.
- [x] Page size: 10 rows. Prev/Next pagination buttons with "N–M of total" label.
- [x] Skeleton rows shown while `isPending`.
- [x] Error state: `<p className="text-sm text-alert">Failed to load job history.</p>`.
- [x] Empty state: centered row spanning all columns with "No job runs recorded yet." in `text-text-faint`.
- [x] Running rows receive `animate-pulse bg-accent-dim` row highlight.

### B-5: Mount in `/admin/sync` page

- [x] `src/web/app/(admin)/admin/sync/page.tsx` imports and renders `<TenantJobHistoryCard />` below `<SchedulerSignalsCard />`.
- [x] Wrapped in `<ErrorBoundary>`.
- [x] Comment `{/* TODO-13B: Tenant job history */}` precedes the block.
- [x] Existing page layout (`space-y-6`) naturally spaces the new card.

---

## Testing Requirements

- [x] Unit test (pytest): `test_tenant_jobs.py` — 7 scenarios passing (empty list, tenant isolation, status filter, pagination, invalid status 422, non-tenant-admin 403, date range filter).
- [x] Unit test (Vitest): `useTenantJobHistory` — `refetchInterval` returns 15 000 with running row, 60 000 without.
- [x] Unit test (Vitest): `TenantJobHistoryCard` — filter chip click updates displayed status, skeleton renders while pending, error message renders on error.
- [x] No TypeScript errors.

---

## Security Notes

- `tenant_id` is always read from the JWT (`current_user.tenant_id`), never from query parameters.
- All filter values are bound as named parameters. No f-string interpolation of user input.
- `require_tenant_admin` enforces minimum role level.

---

## Definition of Done

- [x] All 5 acceptance criteria groups satisfied.
- [x] 7 backend unit tests + 3 frontend unit tests passing.
- [x] 0 TypeScript errors.
- [x] `GET /api/v1/tenant/jobs` confirmed registered in `/docs` (OpenAPI).
- [x] Tenant isolation verified: two-tenant test confirms no cross-tenant data leakage.
