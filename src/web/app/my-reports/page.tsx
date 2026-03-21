"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useMyReports } from "@/hooks/useMyReports";
import { ReportList } from "./elements/ReportList";
import { Bug } from "lucide-react";

/**
 * FE-024: My Reports page.
 * End-user view of submitted issue reports with status tracking.
 * Orchestrator only -- business logic in elements/.
 */
export default function MyReportsPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError } = useMyReports(page);

  return (
    <AppShell>
      <div className="p-7">
        {/* Header */}
        <div className="mb-1">
          <h1 className="text-section-heading text-text-primary">My Reports</h1>
        </div>
        <p className="mb-6 text-body-default text-text-muted">
          Track status and updates on issues you&apos;ve submitted
        </p>

        <ErrorBoundary>
          {/* Loading skeleton */}
          {isLoading && <LoadingSkeleton />}

          {/* Error state */}
          {isError && (
            <div className="rounded-card border border-alert-dim bg-alert-dim px-5 py-4">
              <p className="text-body-default text-alert">
                Failed to load reports. Please try again later.
              </p>
            </div>
          )}

          {/* Empty state */}
          {data && data.items.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Bug size={32} className="mb-3 text-text-faint" />
              <p className="text-body-default text-text-muted">
                No reports yet. Use the{" "}
                <span className="text-text-primary font-medium">bug icon</span>{" "}
                in the bottom right to report an issue.
              </p>
            </div>
          )}

          {/* Report list */}
          {data && data.items.length > 0 && (
            <ReportList
              reports={data.items}
              total={data.total}
              page={page}
              pageSize={data.page_size}
              onPageChange={setPage}
            />
          )}
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="animate-pulse rounded-card border border-border bg-bg-surface px-5 py-4"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="h-4 w-10 rounded-badge bg-bg-elevated" />
              <div className="h-4 w-8 rounded-badge bg-bg-elevated" />
              <div className="h-4 w-48 rounded-badge bg-bg-elevated" />
            </div>
            <div className="flex items-center gap-3">
              <div className="h-4 w-16 rounded-badge bg-bg-elevated" />
              <div className="h-4 w-20 rounded-badge bg-bg-elevated" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
