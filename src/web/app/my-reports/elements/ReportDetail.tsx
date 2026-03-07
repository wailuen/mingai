"use client";

import { ExternalLink } from "lucide-react";
import type { IssueStatus } from "@/lib/types/issues";
import { useReportDetail } from "@/hooks/useMyReports";
import { StatusTimeline } from "./StatusTimeline";
import { StillHappeningPrompt } from "./StillHappeningPrompt";

interface ReportDetailProps {
  reportId: string;
}

const REGRESSION_ELIGIBLE_STATUSES: readonly IssueStatus[] = [
  "fix_deployed",
  "resolved",
];

export function ReportDetail({ reportId }: ReportDetailProps) {
  const { data: report, isLoading, isError } = useReportDetail(reportId);

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-3 px-4 py-4">
        <div className="h-3 w-48 rounded-badge bg-bg-elevated" />
        <div className="h-8 w-full rounded-badge bg-bg-elevated" />
        <div className="h-3 w-32 rounded-badge bg-bg-elevated" />
      </div>
    );
  }

  if (isError || !report) {
    return (
      <div className="px-4 py-4">
        <p className="text-sm text-alert">Failed to load report details.</p>
      </div>
    );
  }

  const showRegression = REGRESSION_ELIGIBLE_STATUSES.includes(report.status);

  return (
    <div className="border-t border-border-faint bg-bg-deep px-5 py-4 animate-fade-in">
      {/* GitHub link */}
      {report.github_issue_url && (
        <a
          href={report.github_issue_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mb-3 inline-flex items-center gap-1.5 text-sm text-accent transition-colors hover:underline"
        >
          <ExternalLink size={13} />
          View on GitHub
        </a>
      )}

      {/* Status timeline */}
      <StatusTimeline status={report.status} />

      {/* Events / timeline */}
      {report.events && report.events.length > 0 && (
        <div className="mt-4 space-y-2">
          <h4 className="text-label-nav uppercase text-text-faint">Activity</h4>
          <div className="space-y-1.5">
            {report.events.map((event) => (
              <div
                key={event.id}
                className="flex items-baseline justify-between gap-4"
              >
                <span className="text-body-default text-text-muted">
                  {formatEventType(event.event_type)}
                </span>
                <span className="font-mono text-data-value text-text-faint">
                  {formatDate(event.created_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Still happening prompt */}
      {showRegression && <StillHappeningPrompt reportId={reportId} />}
    </div>
  );
}

function formatEventType(type: string): string {
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
