"use client";

import { useSyncJobs } from "@/lib/hooks/useSyncHealth";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

interface SyncJobHistoryProps {
  integrationId: string | null;
}

function statusBadgeClasses(status: string): string {
  switch (status) {
    case "completed":
      return "bg-accent-dim text-accent";
    case "failed":
      return "bg-alert-dim text-alert";
    case "queued":
    case "running":
      return "bg-warn-dim text-warn";
    default:
      return "bg-bg-elevated text-text-muted";
  }
}

function formatJobDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function SyncJobHistory({ integrationId }: SyncJobHistoryProps) {
  const { data, isPending, error } = useSyncJobs(integrationId);

  if (!integrationId) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-5">
        <h2 className="mb-3 text-[15px] font-semibold text-text-primary">
          Sync Job History
        </h2>
        <p className="text-body-default text-text-faint">
          Select a source to see sync history
        </p>
      </div>
    );
  }

  if (isPending) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-5">
        <h2 className="mb-3 text-[15px] font-semibold text-text-primary">
          Sync Job History
        </h2>
        <div className="flex items-center gap-2 text-body-default text-text-muted">
          <Loader2 size={14} className="animate-spin" />
          Loading sync jobs...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-5">
        <h2 className="mb-3 text-[15px] font-semibold text-text-primary">
          Sync Job History
        </h2>
        <p className="text-body-default text-alert">
          Failed to load sync jobs: {error.message}
        </p>
      </div>
    );
  }

  const jobs = (data?.jobs ?? []).slice(0, 10);

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-5">
      <h2 className="mb-3 text-[15px] font-semibold text-text-primary">
        Sync Job History
      </h2>

      {jobs.length === 0 ? (
        <p className="text-body-default text-text-faint">
          No sync jobs found for this source
        </p>
      ) : (
        <ScrollableTableWrapper
          maxHeight="none"
          className="rounded-none border-0"
        >
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-bg-surface">
              <tr className="border-b border-border-faint">
                <th className="pb-2 pr-4 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Job ID
                </th>
                <th className="pb-2 pr-4 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Status
                </th>
                <th className="pb-2 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                  Created
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr
                  key={job.id}
                  className="border-b border-border-faint last:border-b-0"
                >
                  <td className="py-2.5 pr-4 font-mono text-xs text-text-muted">
                    {job.id.slice(0, 8)}
                  </td>
                  <td className="py-2.5 pr-4">
                    <span
                      className={cn(
                        "rounded-badge px-1.5 py-0.5 text-[11px] font-medium",
                        statusBadgeClasses(job.status),
                      )}
                    >
                      {job.status}
                    </span>
                  </td>
                  <td className="py-2.5 font-mono text-xs text-text-muted">
                    {formatJobDate(job.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollableTableWrapper>
      )}

      {data && data.total > 10 && (
        <p className="mt-3 text-[11px] text-text-faint">
          Showing 10 of <span className="font-mono">{data.total}</span> jobs
        </p>
      )}
    </div>
  );
}
