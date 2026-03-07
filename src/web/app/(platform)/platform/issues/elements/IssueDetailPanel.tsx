"use client";

import { X } from "lucide-react";
import { useIssueDetail } from "@/lib/hooks/usePlatformIssues";
import { IssueSeverityBadge } from "./IssueSeverityBadge";
import { IssueActions } from "./IssueActions";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function DetailSkeleton() {
  return (
    <div className="space-y-6 p-5">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="space-y-2">
          <div className="h-3 w-24 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="h-4 w-full animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

interface IssueDetailPanelProps {
  issueId: string;
  onClose: () => void;
}

export function IssueDetailPanel({ issueId, onClose }: IssueDetailPanelProps) {
  const { data, isPending, error } = useIssueDetail(issueId);

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-bg-deep/60"
        onClick={onClose}
        role="presentation"
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 z-40 flex h-full w-[520px] max-w-full animate-slide-in-right flex-col border-l border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-border px-5 py-4">
          <div className="flex-1 pr-4">
            {data && (
              <div className="flex items-center gap-2 mb-1.5">
                <IssueSeverityBadge severity={data.severity} />
                <span className="font-mono text-[11px] text-text-faint">
                  {data.status.toUpperCase().replace("_", " ")}
                </span>
              </div>
            )}
            <h2 className="text-section-heading text-text-primary">
              {data?.title ?? "Loading..."}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="p-5">
              <p className="text-sm text-alert">
                Failed to load issue details: {error.message}
              </p>
            </div>
          )}

          {isPending && <DetailSkeleton />}

          {data && (
            <div className="space-y-5 p-5">
              {/* Description */}
              <section>
                <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Description
                </h3>
                <p className="text-[13px] leading-relaxed text-text-primary">
                  {data.description}
                </p>
              </section>

              {/* Reporter context */}
              <section>
                <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Reporter Context
                </h3>
                <div className="space-y-1.5 rounded-card bg-bg-elevated p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-text-faint">Email</span>
                    <span className="font-mono text-data-value text-text-muted">
                      {data.reporter_email}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-text-faint">
                      Session ID
                    </span>
                    <span className="font-mono text-data-value text-text-muted">
                      {data.session_data}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-text-faint">Browser</span>
                    <span className="font-mono text-data-value text-text-muted">
                      {data.browser_info}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-text-faint">Tenant</span>
                    <span className="text-[13px] font-medium text-text-primary">
                      {data.tenant_name}
                    </span>
                  </div>
                </div>
              </section>

              {/* AI Assessment */}
              <section>
                <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  AI Assessment
                </h3>
                <div className="rounded-card bg-bg-elevated p-4">
                  <p className="text-[13px] leading-relaxed text-text-muted">
                    {data.ai_assessment}
                  </p>
                </div>
              </section>

              {/* Status timeline */}
              <section>
                <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Timeline
                </h3>
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                    <span className="text-[12px] text-text-muted">Created</span>
                    <span className="font-mono text-[11px] text-text-faint">
                      {formatDate(data.created_at)}
                    </span>
                  </div>
                </div>
              </section>

              {/* Actions */}
              <section className="border-t border-border pt-4">
                <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Actions
                </h3>
                <IssueActions issueId={issueId} onActionComplete={onClose} />
              </section>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
