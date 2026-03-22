"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useTenantIssues,
  useUpdateIssueStatus,
  type TenantIssue,
  type TenantIssueFilters,
  type TenantIssueSeverity,
  type TenantIssueStatus,
} from "@/lib/hooks/useEngineeringIssues";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";

// ---------------------------------------------------------------------------
// Severity badge color map
// ---------------------------------------------------------------------------

function severityBadgeClass(severity: TenantIssueSeverity): string {
  switch (severity) {
    case "P0":
      return "border-red-400/30 bg-red-400/10 text-red-400";
    case "P1":
      return "border-alert/30 bg-alert-dim text-alert";
    case "P2":
      return "border-warn/30 bg-warn-dim text-warn";
    case "P3":
      return "border-border bg-bg-elevated text-text-muted";
    case "P4":
      return "border-border bg-bg-elevated text-text-faint";
  }
}

// ---------------------------------------------------------------------------
// Status config
// ---------------------------------------------------------------------------

const STATUS_OPTIONS: { value: TenantIssueStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "in_review", label: "In Review" },
  { value: "escalated", label: "Escalated" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

// ---------------------------------------------------------------------------
// StatusDropdown
// ---------------------------------------------------------------------------

function StatusDropdown({
  issueId,
  currentStatus,
}: {
  issueId: string;
  currentStatus: TenantIssueStatus;
}) {
  const updateMutation = useUpdateIssueStatus();

  function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const newStatus = e.target.value as TenantIssueStatus;
    if (newStatus !== currentStatus) {
      updateMutation.mutate({ id: issueId, status: newStatus });
    }
  }

  return (
    <select
      value={currentStatus}
      onChange={handleChange}
      disabled={updateMutation.isPending}
      onClick={(e) => e.stopPropagation()}
      className="rounded-control border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary transition-colors focus:border-accent focus:outline-none disabled:opacity-50"
    >
      {STATUS_OPTIONS.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Expandable row detail
// ---------------------------------------------------------------------------

function IssueDetailRow({ issue }: { issue: TenantIssue }) {
  return (
    <tr>
      <td
        colSpan={6}
        className="border-b border-border-faint bg-bg-elevated px-6 py-4"
      >
        <p className="text-[11px] font-medium uppercase tracking-wider text-text-faint">
          Description
        </p>
        <p className="mt-1 text-body-default leading-relaxed text-text-muted">
          {issue.description || "No description provided."}
        </p>
        <div className="mt-3 flex items-center gap-4 text-xs text-text-faint">
          <span>
            Last updated:{" "}
            <span className="font-mono text-text-muted">
              {issue.updated_at
                ? new Date(issue.updated_at).toLocaleString()
                : new Date(issue.created_at).toLocaleString()}
            </span>
          </span>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// IssueTable
// ---------------------------------------------------------------------------

interface IssueTableProps {
  filters: TenantIssueFilters;
}

export function IssueTable({ filters }: IssueTableProps) {
  const { data: issues, isPending, error } = useTenantIssues(filters);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  function toggleRow(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load issues: {error.message}
      </p>
    );
  }

  return (
    <ScrollableTableWrapper>
      <table className="w-full">
        <thead className="sticky top-0 z-10 bg-bg-surface">
          <tr className="border-b border-border bg-bg-surface">
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Severity
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Title
            </th>
            <th className="hidden px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint sm:table-cell">
              Reporter
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Status
            </th>
            <th className="hidden px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint sm:table-cell">
              Reported
            </th>
            <th className="w-8 px-3.5 py-3" />
          </tr>
        </thead>
        <tbody>
          {isPending ? (
            Array.from({ length: 5 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={6} />
            ))
          ) : !issues || issues.length === 0 ? (
            <tr>
              <td
                colSpan={6}
                className="px-3.5 py-12 text-center text-body-default text-text-faint"
              >
                No issues found matching the current filters.
              </td>
            </tr>
          ) : (
            issues.map((issue) => (
              <IssueRow
                key={issue.id}
                issue={issue}
                expanded={expandedId === issue.id}
                onToggle={() => toggleRow(issue.id)}
              />
            ))
          )}
        </tbody>
      </table>
    </ScrollableTableWrapper>
  );
}

// ---------------------------------------------------------------------------
// IssueRow
// ---------------------------------------------------------------------------

function IssueRow({
  issue,
  expanded,
  onToggle,
}: {
  issue: TenantIssue;
  expanded: boolean;
  onToggle: () => void;
}) {
  const ExpandIcon = expanded ? ChevronDown : ChevronRight;

  return (
    <>
      <tr
        onClick={onToggle}
        className={cn(
          "cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim",
          expanded && "bg-bg-elevated",
        )}
      >
        <td className="px-3.5 py-3">
          <span
            className={cn(
              "inline-block rounded-badge border px-1.5 py-0.5 font-mono text-data-value font-medium",
              severityBadgeClass(issue.severity),
            )}
          >
            {issue.severity}
          </span>
        </td>
        <td className="px-3.5 py-3 text-body-default font-medium text-text-primary">
          {issue.title}
        </td>
        <td className="hidden px-3.5 py-3 font-mono text-xs text-text-muted sm:table-cell">
          {issue.reporter?.name ?? issue.reporter_email ?? "—"}
        </td>
        <td className="px-3.5 py-3">
          <StatusDropdown issueId={issue.id} currentStatus={issue.status} />
        </td>
        <td className="hidden px-3.5 py-3 font-mono text-xs text-text-muted sm:table-cell">
          {new Date(issue.created_at).toLocaleDateString()}
        </td>
        <td className="px-3.5 py-3">
          <ExpandIcon size={14} className="text-text-faint" />
        </td>
      </tr>
      {expanded && <IssueDetailRow issue={issue} />}
    </>
  );
}
