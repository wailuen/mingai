"use client";

import { useState } from "react";
import { CheckCircle, Loader2, RefreshCw } from "lucide-react";
import { useSyncFailures, useRetrySyncJob } from "@/lib/hooks/useSyncFailures";

/**
 * FE-031: Sync Failure List.
 * Shows all sync failures with retry capability.
 */
export function SyncFailureList({ integrationId }: { integrationId?: string }) {
  const { data, isPending, error } = useSyncFailures(integrationId);
  const retryMutation = useRetrySyncJob();
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);

  const failures = data?.items ?? [];

  async function handleRetry(jobId: string) {
    setRetryingJobId(jobId);
    try {
      await retryMutation.mutateAsync(jobId);
    } finally {
      setRetryingJobId(null);
    }
  }

  if (isPending) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Loader2 size={14} className="animate-spin" />
        Loading sync failures...
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load sync failures: {error.message}
      </p>
    );
  }

  return (
    <div>
      {/* Title row */}
      <div className="mb-4 flex items-center gap-3">
        <h2 className="text-section-heading text-text-primary">
          Sync Failures
        </h2>
        <span className="rounded-badge bg-bg-elevated px-2 py-0.5 font-mono text-xs text-text-muted">
          {failures.length}
        </span>
      </div>

      {/* Empty state */}
      {failures.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-card border border-border-faint bg-bg-surface p-8 text-center">
          <CheckCircle size={28} className="text-accent" />
          <p className="text-sm text-text-muted">
            No sync failures — all integrations healthy
          </p>
        </div>
      )}

      {/* Table */}
      {failures.length > 0 && (
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-bg-surface">
                <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Integration
                </th>
                <th className="hidden px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint sm:table-cell">
                  Type
                </th>
                <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Error Message
                </th>
                <th className="hidden px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint sm:table-cell">
                  Failed At
                </th>
                <th className="hidden px-3.5 py-3 text-right text-[11px] font-medium uppercase tracking-wider text-text-faint sm:table-cell">
                  Docs Failed
                </th>
                <th className="px-3.5 py-3 text-right text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {failures.map((failure) => (
                <tr
                  key={failure.job_id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="px-3.5 py-3 text-body-row font-medium text-text-primary">
                    {failure.integration_name}
                  </td>
                  <td className="hidden px-3.5 py-3 sm:table-cell">
                    <TypeBadge type={failure.integration_type} />
                  </td>
                  <td
                    className="max-w-[280px] truncate px-3.5 py-3 text-body-row text-alert"
                    title={failure.error_message}
                  >
                    {failure.error_message.length > 80
                      ? `${failure.error_message.slice(0, 80)}...`
                      : failure.error_message}
                  </td>
                  <td className="hidden whitespace-nowrap px-3.5 py-3 font-mono text-data-value text-text-muted sm:table-cell">
                    {new Date(failure.failed_at).toLocaleString()}
                  </td>
                  <td className="hidden px-3.5 py-3 text-right font-mono text-data-value text-text-primary sm:table-cell">
                    {failure.document_count_failed}
                    <span className="text-text-faint">
                      /{failure.document_count_attempted}
                    </span>
                  </td>
                  <td className="px-3.5 py-3 text-right">
                    <button
                      onClick={() => handleRetry(failure.job_id)}
                      disabled={retryingJobId === failure.job_id}
                      className="inline-flex items-center gap-1 rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary disabled:opacity-30"
                    >
                      <RefreshCw
                        size={12}
                        className={
                          retryingJobId === failure.job_id ? "animate-spin" : ""
                        }
                      />
                      {retryingJobId === failure.job_id
                        ? "Retrying..."
                        : "Retry"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TypeBadge({ type }: { type: "sharepoint" | "google_drive" }) {
  const label = type === "sharepoint" ? "SharePoint" : "Google Drive";

  return (
    <span className="inline-block rounded-badge bg-bg-elevated px-2 py-0.5 text-[11px] font-medium text-text-muted">
      {label}
    </span>
  );
}
