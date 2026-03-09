"use client";

import { useState } from "react";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { useIssues } from "@/lib/hooks/useAnalytics";
import type { Issue } from "@/lib/hooks/useAnalytics";

interface IssueQueueProps {
  onSelectIssue: (issue: Issue) => void;
  selectedIssueId: string | null;
}

const SEVERITY_OPTIONS = ["all", "P0", "P1", "P2", "P3", "P4"] as const;
const STATUS_OPTIONS = [
  "all",
  "open",
  "in_progress",
  "resolved",
  "escalated",
] as const;

function severityBadge(severity: Issue["severity"]) {
  const colorMap: Record<Issue["severity"], string> = {
    P0: "border-[#FF3547]/30 bg-[#FF3547]/8 text-[#FF3547]",
    P1: "border-alert/30 bg-alert-dim text-alert",
    P2: "border-warn/30 bg-warn-dim text-warn",
    P3: "border-border bg-bg-elevated text-text-faint",
    P4: "border-border bg-bg-elevated text-text-faint",
  };

  return (
    <span
      className={`inline-block rounded-badge border px-1.5 py-0.5 font-mono text-[10px] font-medium ${colorMap[severity]}`}
    >
      {severity}
    </span>
  );
}

function statusBadge(status: Issue["status"]) {
  const colorMap: Record<Issue["status"], string> = {
    open: "text-text-muted",
    in_progress: "text-accent",
    resolved: "text-text-faint",
    escalated: "text-alert",
  };
  const labelMap: Record<Issue["status"], string> = {
    open: "Open",
    in_progress: "In Progress",
    resolved: "Resolved",
    escalated: "Escalated",
  };

  return (
    <span className={`text-[12px] font-medium ${colorMap[status]}`}>
      {labelMap[status]}
    </span>
  );
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * FE-037: Tenant-level issue queue list.
 *
 * Shows reports from this tenant with severity badges (P0-P4),
 * status, created_at. Filter by severity and status.
 * Clicking a row selects the issue for detail/workflow actions.
 */
export function IssueQueue({
  onSelectIssue,
  selectedIssueId,
}: IssueQueueProps) {
  const [severityFilter, setSeverityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const filters = {
    severity: severityFilter === "all" ? undefined : severityFilter,
    status: statusFilter === "all" ? undefined : statusFilter,
  };

  const { data, isPending, error } = useIssues(filters);

  if (error) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <h2 className="mb-2 text-[15px] font-semibold text-text-primary">
          Issue Queue
        </h2>
        <p className="text-sm text-alert">
          Failed to load issues: {error.message}
        </p>
      </div>
    );
  }

  const issues = data?.items ?? [];

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-[15px] font-semibold text-text-primary">
          Issue Queue
        </h2>
        {data?.total !== undefined && (
          <span className="font-mono text-xs text-text-faint">
            {data.total} total
          </span>
        )}
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-2">
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="rounded-control border border-border bg-bg-elevated px-2 py-1.5 text-xs text-text-primary transition-colors focus:border-accent focus:outline-none"
        >
          {SEVERITY_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt === "all" ? "All Severity" : opt}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-control border border-border bg-bg-elevated px-2 py-1.5 text-xs text-text-primary transition-colors focus:border-accent focus:outline-none"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt === "all"
                ? "All Status"
                : opt.charAt(0).toUpperCase() + opt.slice(1).replace("_", " ")}
            </option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border">
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Severity
              </th>
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Title
              </th>
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Status
              </th>
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Created
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRowSkeleton key={i} columns={4} />
              ))
            ) : issues.length === 0 ? (
              <tr>
                <td
                  colSpan={4}
                  className="py-12 text-center text-sm text-text-faint"
                >
                  No issues found
                </td>
              </tr>
            ) : (
              issues.map((issue: Issue) => (
                <tr
                  key={issue.id}
                  onClick={() => onSelectIssue(issue)}
                  className={`cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim ${
                    selectedIssueId === issue.id ? "bg-accent-dim" : ""
                  }`}
                >
                  <td className="py-3 pr-3">{severityBadge(issue.severity)}</td>
                  <td className="py-3 pr-4 text-[13px] font-medium text-text-primary">
                    {issue.title}
                  </td>
                  <td className="py-3 pr-4">{statusBadge(issue.status)}</td>
                  <td className="py-3 font-mono text-[12px] text-text-muted">
                    {formatDate(issue.created_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
