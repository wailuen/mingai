"use client";

import { useState, useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import {
  useJobHistory,
  type JobHistoryFilters,
} from "@/lib/hooks/useJobHistory";
import { JobHistoryFiltersBar } from "./elements/JobHistoryFilters";
import { JobHistoryTable } from "./elements/JobHistoryTable";
import { RunNowButton } from "./elements/RunNowButton";
import { Loader2, RefreshCw } from "lucide-react";

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
  const [notification, setNotification] = useState<{
    kind: "success" | "error";
    message: string;
  } | null>(null);

  const { data, isPending, isFetching, error } = useJobHistory(
    offset,
    ROWS_PER_PAGE,
    appliedFilters,
  );

  const queryClient = useQueryClient();
  const runningCount =
    data?.items.filter((r) => r.status === "running").length ?? 0;

  useEffect(() => {
    if (notification) {
      const t = setTimeout(() => setNotification(null), 4000);
      return () => clearTimeout(t);
    }
  }, [notification]);

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
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h1 className="text-page-title text-text-primary">
                Scheduler History
              </h1>
              {runningCount > 0 && (
                <span className="flex items-center gap-1.5 rounded-badge border border-accent-ring bg-accent-dim px-2 py-0.5">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                  <span className="font-mono text-data-value text-accent">
                    {runningCount} running
                  </span>
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() =>
                  queryClient.invalidateQueries({
                    queryKey: ["platform-job-history"],
                  })
                }
                disabled={isFetching}
                className="flex items-center gap-1.5 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isFetching ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <RefreshCw size={13} />
                )}
                Refresh
              </button>
              <RunNowButton
                onNotify={(kind, message) => setNotification({ kind, message })}
              />
            </div>
          </div>
          <p className="mt-1 text-body-default text-text-muted">
            Background job execution log — runs, durations, and errors across
            all pods
          </p>
        </div>

        {notification && (
          <div
            className={`mb-4 rounded-control border px-4 py-2.5 text-body-default ${
              notification.kind === "success"
                ? "border-accent-ring bg-accent-dim text-accent"
                : "border-alert/30 bg-alert/10 text-alert"
            }`}
          >
            {notification.message}
          </div>
        )}

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
