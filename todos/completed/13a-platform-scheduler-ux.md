# TODO-13A: Platform Admin — Adaptive Polling and Manual Refresh

**Status**: COMPLETE
**Completed**: 2026-03-20
**Priority**: MEDIUM
**Estimated Effort**: 3–4 hours
**Depends on**: Nothing (all backend work already done)

**Completion evidence**:
- Zero TypeScript errors (tsc --noEmit)
- All 4 acceptance criteria groups satisfied
- Reviewer must-fix items addressed before close

---

## Description

The Platform Admin Scheduler History page (`/platform/jobs`) currently polls at a fixed 60-second interval regardless of whether any jobs are actively running. This makes the page feel stale during deployments or manual triggers when operators need near-real-time feedback. Three UX improvements address this:

1. **Adaptive polling** — tighten `refetchInterval` to 15 s when any Running rows are present in the current result set, revert to 60 s when idle.
2. **Manual refresh button** — let operators force an immediate refetch without waiting for the timer.
3. **Running badge** — a live count of in-progress jobs in the page header so operators know at a glance whether to watch the page.
4. **Row highlight** — a subtle pulse animation on Running-status rows so they stand out in a dense table.

No backend changes are required; all 13 jobs already write `job_run_log` rows via `job_run_context()`, and `GET /api/v1/platform/jobs/history` already returns `status` per row.

---

## Files Modified

| File                                                                | Change                                                                    |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `src/web/lib/hooks/useJobHistory.ts`                                | A-1: adaptive `refetchInterval`; A-4 (types): export running count helper |
| `src/web/app/(platform)/platform/jobs/page.tsx`                     | A-2: Refresh button; A-3: Running badge in header                         |
| `src/web/app/(platform)/platform/jobs/elements/JobHistoryTable.tsx` | A-4: CSS pulse class on Running rows                                      |

---

## Acceptance Criteria

### A-1: Adaptive refetchInterval in `useJobHistory`

- [x] `refetchInterval` is a function: returns `15_000` when `data?.items.some(r => r.status === "running")` is true, `60_000` otherwise.
- [x] `staleTime` remains `30_000` (no change).
- [x] When a running job transitions to completed/failed the interval automatically relaxes to 60 s on the next successful fetch.
- [x] Unit test: `useJobHistory` returns `refetchInterval` of 15 000 when at least one item has `status: "running"`.

### A-2: Manual Refresh button

- [x] A "Refresh" button appears in the Scheduler History page header, to the right of the subtitle text.
- [x] Button uses the Obsidian Intelligence design system: `border border-border bg-bg-elevated text-text-muted rounded-control px-3 py-1.5 text-xs` at rest; `hover:border-accent-ring hover:text-text-primary` on hover.
- [x] Clicking the button calls `queryClient.invalidateQueries({ queryKey: ["platform-job-history"] })`.
- [x] While the refetch is in-flight (`isFetching === true`) the button shows a `<Loader2 size={13} className="animate-spin" />` icon and is `disabled`.
- [x] After the refetch resolves the button returns to its normal state.
- [x] `useQueryClient` is imported from `@tanstack/react-query`; no new dependencies.

### A-3: Running count badge

- [x] A badge reading "N running" appears in the page header when `runningCount > 0`; it is not rendered when `runningCount === 0`.
- [x] `runningCount` is derived from `data?.items.filter(r => r.status === "running").length ?? 0`.
- [x] When `runningCount > 0` the badge uses `bg-accent-dim border border-accent-ring text-accent` with a `animate-pulse` class on a small dot indicator (6×6 px, `rounded-full bg-accent`).
- [x] Badge text uses `font-mono text-[12px]`.
- [x] Badge is positioned inline with the page title (`h1`) row, separated by a gap.

### A-4: Running row highlight

- [x] Rows where `row.status === "running"` receive an additional Tailwind class that produces a gentle background pulse: `animate-pulse bg-accent-dim`.
- [x] The pulse does not apply to any other status.
- [x] The `hover:bg-accent-dim` class already on each row is preserved for non-running rows.
- [x] No new CSS files; the animation uses the existing Tailwind `animate-pulse` utility.

---

## Testing Requirements

- [x] Unit test (Vitest): `useJobHistory` hook — `refetchInterval` callback returns 15 000 given mock data with a running row, 60 000 given no running rows.
- [x] Unit test (Vitest): `JobHistoryPage` — Refresh button renders, is disabled while `isFetching`, re-enables after fetch.
- [x] Unit test (Vitest): Running badge renders with count when running rows present, absent when count is zero.
- [x] Unit test (Vitest): `JobHistoryTable` — Running row has `animate-pulse bg-accent-dim` class; completed row does not.
- [x] No TypeScript errors (`tsc --noEmit`).

---

## Definition of Done

- [x] All 4 acceptance criteria groups satisfied.
- [x] 4 unit tests passing.
- [x] 0 TypeScript errors.
- [x] No new npm dependencies.
- [x] Design system tokens used throughout (no hardcoded colors or hex values).
