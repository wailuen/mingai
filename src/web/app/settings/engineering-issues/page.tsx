"use client";

import { useState, useCallback } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { cn } from "@/lib/utils";
import type {
  TenantIssueSeverity,
  TenantIssueStatus,
  TenantIssueFilters,
} from "@/lib/hooks/useEngineeringIssues";
import { IssueTable } from "./elements/IssueTable";

const SEVERITIES: TenantIssueSeverity[] = ["P0", "P1", "P2", "P3", "P4"];

const STATUSES: { value: TenantIssueStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "in_review", label: "In Review" },
  { value: "escalated", label: "Escalated" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

/**
 * FE-054: Engineering Issue Queue View (Tenant Admin).
 * Shows issues reported by workspace users with severity/status filtering.
 */
export default function EngineeringIssuesPage() {
  const [selectedSeverities, setSelectedSeverities] = useState<
    TenantIssueSeverity[]
  >([]);
  const [selectedStatuses, setSelectedStatuses] = useState<TenantIssueStatus[]>(
    [],
  );

  const filters: TenantIssueFilters = {
    severity: selectedSeverities.length > 0 ? selectedSeverities : undefined,
    status: selectedStatuses.length > 0 ? selectedStatuses : undefined,
  };

  const toggleSeverity = useCallback((sev: TenantIssueSeverity) => {
    setSelectedSeverities((prev) =>
      prev.includes(sev) ? prev.filter((s) => s !== sev) : [...prev, sev],
    );
  }, []);

  const toggleStatus = useCallback((status: TenantIssueStatus) => {
    setSelectedStatuses((prev) =>
      prev.includes(status)
        ? prev.filter((s) => s !== status)
        : [...prev, status],
    );
  }, []);

  return (
    <AppShell>
      <div className="p-4 sm:p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Issue Queue</h1>
          <p className="mt-1 text-body-default text-text-muted">
            Issues reported by your workspace users
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
                  "rounded-control border px-2 py-0.5 font-mono text-data-value uppercase transition-colors",
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
          <IssueTable filters={filters} />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
