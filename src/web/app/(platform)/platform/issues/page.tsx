"use client";

import { useState, useCallback } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { cn } from "@/lib/utils";
import type {
  IssueSeverity,
  IssueStatus,
  IssueFilters,
} from "@/lib/hooks/usePlatformIssues";
import { IssueQueueTable } from "./elements/IssueQueueTable";
import { IssueDetailPanel } from "./elements/IssueDetailPanel";

const SEVERITIES: IssueSeverity[] = ["P0", "P1", "P2", "P3", "P4"];
const STATUSES: { value: IssueStatus; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In Progress" },
  { value: "waiting_info", label: "Waiting Info" },
  { value: "closed", label: "Closed" },
];

/**
 * FE-047: Platform Issue Queue.
 * Lists platform-wide issues with severity/status filtering
 * and a slide-in detail panel for individual issue management.
 */
export default function IssueQueuePage() {
  const [selectedSeverities, setSelectedSeverities] = useState<IssueSeverity[]>(
    [],
  );
  const [selectedStatuses, setSelectedStatuses] = useState<IssueStatus[]>([]);
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);

  const filters: IssueFilters = {
    severity: selectedSeverities.length > 0 ? selectedSeverities : undefined,
    status: selectedStatuses.length > 0 ? selectedStatuses : undefined,
  };

  const toggleSeverity = useCallback((sev: IssueSeverity) => {
    setSelectedSeverities((prev) =>
      prev.includes(sev) ? prev.filter((s) => s !== sev) : [...prev, sev],
    );
  }, []);

  const toggleStatus = useCallback((status: IssueStatus) => {
    setSelectedStatuses((prev) =>
      prev.includes(status)
        ? prev.filter((s) => s !== status)
        : [...prev, status],
    );
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedIssueId(null);
  }, []);

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Issue Queue</h1>
          <p className="mt-1 text-sm text-text-muted">
            Platform-wide issue tracking with AI-assisted classification
          </p>
        </div>

        {/* Filter bar */}
        <div className="mb-5 flex flex-wrap items-center gap-4">
          {/* Severity chips */}
          <div className="flex items-center gap-1.5">
            <span className="mr-1 text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Severity
            </span>
            {SEVERITIES.map((sev) => (
              <button
                key={sev}
                type="button"
                onClick={() => toggleSeverity(sev)}
                className={cn(
                  "rounded-control border px-2 py-0.5 font-mono text-[11px] uppercase transition-colors",
                  selectedSeverities.includes(sev)
                    ? "border-accent-ring bg-accent-dim text-accent"
                    : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
                )}
              >
                {sev}
              </button>
            ))}
          </div>

          {/* Status chips */}
          <div className="flex items-center gap-1.5">
            <span className="mr-1 text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Status
            </span>
            {STATUSES.map((st) => (
              <button
                key={st.value}
                type="button"
                onClick={() => toggleStatus(st.value)}
                className={cn(
                  "rounded-control border px-2 py-0.5 text-[11px] transition-colors",
                  selectedStatuses.includes(st.value)
                    ? "border-accent-ring bg-accent-dim text-accent"
                    : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
                )}
              >
                {st.label}
              </button>
            ))}
          </div>
        </div>

        {/* Issue table */}
        <ErrorBoundary>
          <IssueQueueTable
            filters={filters}
            onSelectIssue={setSelectedIssueId}
          />
        </ErrorBoundary>
      </div>

      {/* Slide-in detail panel */}
      {selectedIssueId && (
        <IssueDetailPanel
          issueId={selectedIssueId}
          onClose={handleCloseDetail}
        />
      )}
    </AppShell>
  );
}
