"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { cn } from "@/lib/utils";
import { AlertCircle } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PlatformIssueListItem {
  id: string;
  severity: string;
  title: string;
  type: string;
  tenant: { id: string; name: string } | null;
  reporter: { name: string } | null;
  status: string;
  created_at: string;
}

interface PlatformIssueListResponse {
  items: PlatformIssueListItem[];
  total: number;
  page: number;
  page_size: number;
  stats: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Filter tabs
// ---------------------------------------------------------------------------

type StatusFilter =
  | "all"
  | "open"
  | "assigned"
  | "in_progress"
  | "resolved"
  | "closed";

const STATUS_TABS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "assigned", label: "Assigned" },
  { value: "in_progress", label: "In Progress" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function severityBadgeClass(severity: string): string {
  switch (severity) {
    case "P0":
      return "border-red-400/30 bg-red-400/10 text-red-400";
    case "P1":
      return "border-alert/30 bg-alert-dim text-alert";
    case "P2":
      return "border-warn/30 bg-warn-dim text-warn";
    default:
      return "border-border bg-bg-elevated text-text-muted";
  }
}

function formatStatus(status: string): string {
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

function IssueQueueTable({ statusFilter }: { statusFilter: StatusFilter }) {
  const params = new URLSearchParams({ page: "1", page_size: "50" });
  if (statusFilter !== "all") params.set("status", statusFilter);

  const { data, isPending, error } = useQuery<PlatformIssueListResponse>({
    queryKey: ["platform-issues", statusFilter],
    queryFn: () =>
      apiGet<PlatformIssueListResponse>(`/api/v1/platform/issues?${params}`),
    retry: 1,
  });

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load issues: {error.message}
      </p>
    );
  }

  const issues = data?.items;

  return (
    <div className="overflow-hidden rounded-card border border-border">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border bg-bg-surface">
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Severity
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Title
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Tenant
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Status
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Reported
            </th>
          </tr>
        </thead>
        <tbody>
          {isPending ? (
            Array.from({ length: 3 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={5} />
            ))
          ) : !issues || issues.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-3.5 py-16 text-center">
                <div className="flex flex-col items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-card bg-bg-elevated">
                    <AlertCircle size={24} className="text-text-faint" />
                  </div>
                  <p className="text-sm font-medium text-text-muted">
                    No issues found
                  </p>
                  <p className="text-xs text-text-faint">
                    {statusFilter === "all"
                      ? "Issues from tenants will appear here for triage"
                      : `No issues with status "${formatStatus(statusFilter)}"`}
                  </p>
                </div>
              </td>
            </tr>
          ) : (
            issues.map((issue) => (
              <tr
                key={issue.id}
                className="border-b border-border-faint transition-colors hover:bg-accent-dim"
              >
                <td className="px-3.5 py-3">
                  <span
                    className={cn(
                      "inline-block rounded-badge border px-1.5 py-0.5 font-mono text-[11px] font-medium",
                      severityBadgeClass(issue.severity),
                    )}
                  >
                    {issue.severity}
                  </span>
                </td>
                <td className="px-3.5 py-3 text-sm font-medium text-text-primary">
                  {issue.title}
                </td>
                <td className="px-3.5 py-3 text-xs text-text-muted">
                  {issue.tenant?.name ?? "\u2014"}
                </td>
                <td className="px-3.5 py-3 text-xs text-text-muted">
                  {formatStatus(issue.status)}
                </td>
                <td className="px-3.5 py-3 font-mono text-data-value text-text-muted">
                  {new Date(issue.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function IssueQueuePage() {
  const [activeTab, setActiveTab] = useState<StatusFilter>("all");

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Issue Queue</h1>
          <p className="mt-1 text-sm text-text-muted">
            Triage and manage cross-tenant engineering issues
          </p>
        </div>

        {/* Filter tabs */}
        <div className="mb-5 border-b border-border">
          <div className="flex gap-0.5">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.value}
                onClick={() => setActiveTab(tab.value)}
                className={cn(
                  "px-3.5 py-2 text-xs font-medium transition-colors",
                  activeTab === tab.value
                    ? "border-b-2 border-accent text-text-primary"
                    : "text-text-faint hover:text-text-muted",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <ErrorBoundary>
          <IssueQueueTable statusFilter={activeTab} />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
