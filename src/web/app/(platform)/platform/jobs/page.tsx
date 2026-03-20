"use client";

import { useState, useCallback } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import {
  useJobHistory,
  type JobHistoryFilters,
} from "@/lib/hooks/useJobHistory";
import { JobHistoryFiltersBar } from "./elements/JobHistoryFilters";
import { JobHistoryTable } from "./elements/JobHistoryTable";

const ROWS_PER_PAGE = 50;
const EMPTY_FILTERS: JobHistoryFilters = {};

/**
 * SCHED-028: Platform Admin job execution history panel.
 *
 * Shows a paginated, filterable table of all background job runs
 * from job_run_log. Filters: job_name, status, date range.
 */
export default function JobHistoryPage() {
  const [offset, setOffset] = useState(0);
  const [draftFilters, setDraftFilters] =
    useState<JobHistoryFilters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] =
    useState<JobHistoryFilters>(EMPTY_FILTERS);

  const { data, isPending, error } = useJobHistory(
    offset,
    ROWS_PER_PAGE,
    appliedFilters,
  );

  const handleApply = useCallback(() => {
    setAppliedFilters({ ...draftFilters });
    setOffset(0);
  }, [draftFilters]);

  const handleClear = useCallback(() => {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setOffset(0);
  }, []);

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">
            Scheduler History
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Background job execution log — runs, durations, and errors across
            all pods
          </p>
        </div>

        <div className="mb-5">
          <JobHistoryFiltersBar
            filters={draftFilters}
            onFiltersChange={setDraftFilters}
            onApply={handleApply}
            onClear={handleClear}
          />
        </div>

        <ErrorBoundary>
          <JobHistoryTable
            data={data}
            isPending={isPending}
            error={error}
            offset={offset}
            limit={ROWS_PER_PAGE}
            onOffsetChange={setOffset}
          />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
