"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type {
  IssueReport,
  IssueType,
  SeverityHint,
  IssueStatus,
} from "@/lib/types/issues";
import { ReportDetail } from "./ReportDetail";

interface ReportListProps {
  reports: IssueReport[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export function ReportList({
  reports,
  total,
  page,
  pageSize,
  onPageChange,
}: ReportListProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const totalPages = Math.ceil(total / pageSize);

  return (
    <div>
      <div className="space-y-2">
        {reports.map((report) => (
          <div
            key={report.id}
            className="rounded-card border border-border bg-bg-surface"
          >
            <button
              onClick={() =>
                setExpandedId(expandedId === report.id ? null : report.id)
              }
              className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left transition-colors hover:bg-bg-elevated/50"
            >
              {/* Left: badges + title */}
              <div className="flex min-w-0 items-center gap-2.5">
                <TypeBadge type={report.issue_type} />
                <SeverityBadge severity={report.severity_hint} />
                <span className="truncate text-body-default font-medium text-text-primary">
                  {report.title}
                </span>
              </div>

              {/* Right: status + date */}
              <div className="flex flex-shrink-0 items-center gap-3">
                <StatusBadge status={report.status} />
                <span className="font-mono text-data-value text-text-faint">
                  {formatShortDate(report.created_at)}
                </span>
              </div>
            </button>

            {/* Expanded detail */}
            {expandedId === report.id && <ReportDetail reportId={report.id} />}
          </div>
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="rounded-control border border-border p-1.5 text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="font-mono text-data-value text-text-muted">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="rounded-control border border-border p-1.5 text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Badge sub-components                                               */
/* ------------------------------------------------------------------ */

const TYPE_STYLES: Record<IssueType, string> = {
  bug: "text-alert bg-alert-dim",
  performance: "text-warn bg-warn-dim",
  ux: "text-text-muted bg-bg-elevated",
  feature: "text-accent bg-accent-dim",
};

function TypeBadge({ type }: { type: IssueType }) {
  return (
    <span
      className={`inline-flex rounded-badge px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${TYPE_STYLES[type]}`}
    >
      {type}
    </span>
  );
}

const SEVERITY_STYLES: Record<SeverityHint, string> = {
  P0: "text-[#FF3547] bg-[#FF3547]/10",
  P1: "text-alert bg-alert-dim",
  P2: "text-warn bg-warn-dim",
  P3: "text-text-muted bg-bg-elevated",
  P4: "text-text-muted bg-bg-elevated",
};

function SeverityBadge({ severity }: { severity: SeverityHint }) {
  return (
    <span
      className={`inline-flex rounded-badge px-1.5 py-0.5 font-mono text-[10px] font-medium ${SEVERITY_STYLES[severity]}`}
    >
      {severity}
    </span>
  );
}

const STATUS_STYLES: Record<IssueStatus, string> = {
  received: "bg-bg-elevated text-text-muted border border-border",
  triaging: "bg-warn-dim text-warn",
  triaged: "bg-accent-dim text-accent border border-accent-ring",
  investigating: "bg-warn-dim text-warn",
  fix_in_progress: "bg-warn-dim text-warn",
  fix_merged: "bg-accent-dim text-accent",
  fix_deployed: "bg-accent-dim text-accent",
  resolved: "bg-accent-dim text-accent",
  closed: "bg-bg-elevated text-text-faint",
};

const STATUS_LABELS: Record<IssueStatus, string> = {
  received: "Received",
  triaging: "Triaging",
  triaged: "Triaged",
  investigating: "Investigating",
  fix_in_progress: "Fix In Progress",
  fix_merged: "Fix Merged",
  fix_deployed: "Deployed",
  resolved: "Resolved",
  closed: "Closed",
};

function StatusBadge({ status }: { status: IssueStatus }) {
  return (
    <span
      className={`inline-flex rounded-badge px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${STATUS_STYLES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
