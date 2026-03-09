"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { cn } from "@/lib/utils";
import {
  usePlatformIssueQueue,
  useAssignIssue,
  type QueueFilter,
  type PlatformIssue,
  type TenantIssueSeverity,
  type TenantIssueStatus,
} from "@/lib/hooks/useEngineeringIssues";
import { QueueFilterTabs } from "./elements/QueueFilterTabs";
import { IssueActionBar } from "./elements/IssueActionBar";
import { BatchActionBar } from "./elements/BatchActionBar";
import { AssignDialog } from "./elements/AssignDialog";
import { SeverityOverrideDialog } from "./elements/SeverityOverrideDialog";
import { RequestInfoDialog } from "./elements/RequestInfoDialog";

// ---------------------------------------------------------------------------
// Severity badge styling
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
// Status label formatting
// ---------------------------------------------------------------------------

function formatStatusLabel(status: TenantIssueStatus): string {
  return status
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function statusBadgeClass(status: TenantIssueStatus): string {
  switch (status) {
    case "new":
      return "border-accent/30 bg-accent-dim text-accent";
    case "in_review":
      return "border-warn/30 bg-warn-dim text-warn";
    case "escalated":
      return "border-alert/30 bg-alert-dim text-alert";
    case "resolved":
      return "border-border bg-bg-elevated text-text-muted";
    case "closed":
      return "border-border bg-bg-elevated text-text-faint";
  }
}

// ---------------------------------------------------------------------------
// IssueDetailRow
// ---------------------------------------------------------------------------

function IssueDetailRow({ issue }: { issue: PlatformIssue }) {
  return (
    <tr>
      <td
        colSpan={8}
        className="border-b border-border-faint bg-bg-elevated px-6 py-4"
      >
        <p className="text-[11px] font-medium uppercase tracking-wider text-text-faint">
          Description
        </p>
        <p className="mt-1 text-sm leading-relaxed text-text-muted">
          {issue.description || "No description provided."}
        </p>
        <div className="mt-3 flex items-center gap-4 text-xs text-text-faint">
          <span>
            Assigned to:{" "}
            <span className="font-mono text-text-muted">
              {issue.assigned_to ?? "Unassigned"}
            </span>
          </span>
          <span>
            Last updated:{" "}
            <span className="font-mono text-text-muted">
              {new Date(issue.updated_at).toLocaleString()}
            </span>
          </span>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// QueueIssueRow
// ---------------------------------------------------------------------------

function QueueIssueRow({
  issue,
  expanded,
  selected,
  checked,
  onToggle,
  onSelect,
  onCheck,
}: {
  issue: PlatformIssue;
  expanded: boolean;
  selected: boolean;
  checked: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onCheck: (checked: boolean) => void;
}) {
  const ExpandIcon = expanded ? ChevronDown : ChevronRight;

  return (
    <>
      <tr
        onClick={onSelect}
        className={cn(
          "cursor-pointer border-b border-border-faint transition-colors",
          selected ? "bg-accent-dim" : "hover:bg-accent-dim",
          expanded && !selected && "bg-bg-elevated",
        )}
      >
        <td className="px-3 py-3">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => {
              e.stopPropagation();
              onCheck(e.target.checked);
            }}
            onClick={(e) => e.stopPropagation()}
            className="h-4 w-4 rounded-sm accent-accent"
          />
        </td>
        <td className="px-3.5 py-3">
          <span
            className={cn(
              "inline-block rounded-sm border px-1.5 py-0.5 font-mono text-[11px] font-medium",
              severityBadgeClass(issue.severity),
            )}
          >
            {issue.severity}
          </span>
        </td>
        <td className="px-3.5 py-3 text-sm font-medium text-text-primary">
          {issue.title}
          {issue.sla_at_risk && (
            <span className="ml-2 rounded-sm bg-alert/15 px-1.5 py-0.5 text-[10px] font-semibold text-alert">
              SLA AT RISK
            </span>
          )}
        </td>
        <td className="px-3.5 py-3 text-xs text-text-muted">
          {issue.tenant_name}
        </td>
        <td className="px-3.5 py-3 font-mono text-xs text-text-muted">
          {issue.reporter_email}
        </td>
        <td className="px-3.5 py-3">
          <span
            className={cn(
              "inline-block rounded-sm border px-1.5 py-0.5 text-[11px] font-medium",
              statusBadgeClass(issue.status),
            )}
          >
            {formatStatusLabel(issue.status)}
          </span>
        </td>
        <td className="px-3.5 py-3 font-mono text-xs text-text-muted">
          {new Date(issue.created_at).toLocaleDateString()}
        </td>
        <td className="px-3.5 py-3">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            className="text-text-faint transition-colors hover:text-text-primary"
          >
            <ExpandIcon size={14} />
          </button>
        </td>
      </tr>
      {expanded && <IssueDetailRow issue={issue} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// QueueTable
// ---------------------------------------------------------------------------

function QueueTable({
  issues,
  isPending,
  selectedId,
  expandedId,
  checkedIds,
  onSelect,
  onToggleExpand,
  onCheck,
  onCheckAll,
}: {
  issues: PlatformIssue[] | undefined;
  isPending: boolean;
  selectedId: string | null;
  expandedId: string | null;
  checkedIds: Set<string>;
  onSelect: (issue: PlatformIssue) => void;
  onToggleExpand: (id: string) => void;
  onCheck: (id: string, checked: boolean) => void;
  onCheckAll: (checked: boolean) => void;
}) {
  const allChecked =
    !!issues && issues.length > 0 && issues.every((i) => checkedIds.has(i.id));
  const someChecked =
    !!issues && issues.some((i) => checkedIds.has(i.id)) && !allChecked;
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someChecked;
    }
  }, [someChecked]);

  return (
    <div className="overflow-hidden rounded-card border border-border">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border bg-bg-surface">
            <th className="w-10 px-3 py-3">
              <input
                ref={selectAllRef}
                type="checkbox"
                checked={allChecked}
                onChange={(e) => onCheckAll(e.target.checked)}
                className="h-4 w-4 rounded-sm accent-accent"
              />
            </th>
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
              Reporter
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Status
            </th>
            <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Reported
            </th>
            <th className="w-8 px-3.5 py-3" />
          </tr>
        </thead>
        <tbody>
          {isPending ? (
            Array.from({ length: 5 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={8} />
            ))
          ) : !issues || issues.length === 0 ? (
            <tr>
              <td
                colSpan={8}
                className="px-3.5 py-12 text-center text-sm text-text-faint"
              >
                No issues found for this filter.
              </td>
            </tr>
          ) : (
            issues.map((issue) => (
              <QueueIssueRow
                key={issue.id}
                issue={issue}
                expanded={expandedId === issue.id}
                selected={selectedId === issue.id}
                checked={checkedIds.has(issue.id)}
                onToggle={() => onToggleExpand(issue.id)}
                onSelect={() => onSelect(issue)}
                onCheck={(chk) => onCheck(issue.id, chk)}
              />
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

/**
 * FE-054: Platform Engineering Issue Queue.
 * Platform-level issue triage with accept, override, assign, request-info,
 * and won't-fix actions. SLA at-risk highlighting.
 */
export default function PlatformIssueQueuePage() {
  const [filter, setFilter] = useState<QueueFilter>("incoming");
  const [selectedIssue, setSelectedIssue] = useState<PlatformIssue | null>(
    null,
  );
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [showSeverityDialog, setShowSeverityDialog] = useState(false);
  const [showRequestInfoDialog, setShowRequestInfoDialog] = useState(false);
  const [showAssignDialog, setShowAssignDialog] = useState(false);

  const { data, isPending } = usePlatformIssueQueue(filter);
  const assignMutation = useAssignIssue();

  function handleCheck(id: string, checked: boolean) {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function handleCheckAll(checked: boolean) {
    if (checked) {
      setCheckedIds(new Set(data?.items.map((i) => i.id) ?? []));
    } else {
      setCheckedIds(new Set());
    }
  }

  function handleSelect(issue: PlatformIssue) {
    setSelectedIssue((prev) => (prev?.id === issue.id ? null : issue));
  }

  function handleToggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  function handleAssignConfirm(email: string) {
    if (!selectedIssue) return;
    setShowAssignDialog(false);
    assignMutation.mutate({ id: selectedIssue.id, assignee_email: email });
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">
            Engineering Issue Queue
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Triage and manage cross-tenant engineering issues
          </p>
        </div>

        {/* Filter tabs */}
        <div className="mb-5">
          <ErrorBoundary>
            <QueueFilterTabs
              activeFilter={filter}
              onFilterChange={setFilter}
              counts={data?.counts}
            />
          </ErrorBoundary>
        </div>

        {/* Action bars */}
        <div className="mb-4 space-y-2">
          {checkedIds.size >= 2 ? (
            <BatchActionBar
              selectedIds={Array.from(checkedIds)}
              onClearSelection={() => setCheckedIds(new Set())}
            />
          ) : (
            <IssueActionBar
              selectedIssue={selectedIssue}
              onOverrideSeverity={() => setShowSeverityDialog(true)}
              onRequestInfo={() => setShowRequestInfoDialog(true)}
              onAssign={() => setShowAssignDialog(true)}
            />
          )}
        </div>

        {/* Issue table */}
        <ErrorBoundary>
          <QueueTable
            issues={data?.items}
            isPending={isPending}
            selectedId={selectedIssue?.id ?? null}
            expandedId={expandedId}
            checkedIds={checkedIds}
            onSelect={handleSelect}
            onToggleExpand={handleToggleExpand}
            onCheck={handleCheck}
            onCheckAll={handleCheckAll}
          />
        </ErrorBoundary>

        {/* Severity override modal */}
        {showSeverityDialog && selectedIssue && (
          <SeverityOverrideDialog
            issue={selectedIssue}
            onClose={() => setShowSeverityDialog(false)}
          />
        )}

        {/* Request info modal */}
        {showRequestInfoDialog && selectedIssue && (
          <RequestInfoDialog
            issue={selectedIssue}
            onClose={() => setShowRequestInfoDialog(false)}
          />
        )}

        {/* Assign dialog */}
        {showAssignDialog && selectedIssue && (
          <AssignDialog
            onConfirm={handleAssignConfirm}
            onClose={() => setShowAssignDialog(false)}
          />
        )}
      </div>
    </AppShell>
  );
}
