"use client";

import { JobStatusBadge } from "./JobStatusBadge";
import type { JobHistoryResponse } from "@/lib/hooks/useJobHistory";

interface JobHistoryTableProps {
  data: JobHistoryResponse | undefined;
  isPending: boolean;
  error: Error | null;
  offset: number;
  limit: number;
  onOffsetChange: (offset: number) => void;
}

/** Format milliseconds as "2m 07s" or "45s" */
function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 10 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 7 }).map((__, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

export function JobHistoryTable({
  data,
  isPending,
  error,
  offset,
  limit,
  onOffsetChange,
}: JobHistoryTableProps) {
  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load job history: {error.message}
      </p>
    );
  }

  const totalCount = data?.total_count ?? 0;
  const hasPrev = offset > 0;
  const hasNext = data ? offset + data.items.length < totalCount : false;

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Job
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Started
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Duration
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Status
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Records
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Instance
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Error
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending ? (
              <SkeletonRows />
            ) : !data || data.items.length === 0 ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-3.5 py-8 text-center text-body-default text-text-faint"
                >
                  No job history matches the current filters.
                </td>
              </tr>
            ) : (
              data.items.map((row) => (
                <tr
                  key={row.id}
                  className={`border-b border-border-faint ${row.status === "running" ? "animate-pulse bg-accent-dim" : "hover:bg-accent-dim"}`}
                >
                  <td className="px-3.5 py-3 text-body-default font-medium text-text-primary">
                    {row.job_name}
                  </td>
                  <td className="px-3.5 py-3 font-mono text-data-value text-text-muted">
                    {formatTimestamp(row.started_at)}
                  </td>
                  <td className="px-3.5 py-3 font-mono text-data-value text-text-muted">
                    {formatDuration(row.duration_ms)}
                  </td>
                  <td className="px-3.5 py-3">
                    <JobStatusBadge status={row.status} />
                  </td>
                  <td className="px-3.5 py-3 font-mono text-data-value text-text-muted">
                    {row.records_processed ?? "—"}
                  </td>
                  <td
                    className="px-3.5 py-3 font-mono text-data-value text-text-faint"
                    title={row.instance_id ?? undefined}
                  >
                    {row.instance_id
                      ? row.instance_id.length > 20
                        ? row.instance_id.slice(0, 20) + "…"
                        : row.instance_id
                      : "—"}
                  </td>
                  <td
                    className="px-3.5 py-3 max-w-[200px] truncate font-mono text-data-value text-alert"
                    title={row.error_message ?? undefined}
                  >
                    {row.error_message ?? "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      <div className="flex items-center justify-between border-t border-border px-4 py-3">
        <span className="text-xs text-text-faint">
          {totalCount > 0
            ? `${offset + 1}–${Math.min(offset + limit, totalCount)} of ${totalCount}`
            : "0 results"}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => onOffsetChange(Math.max(0, offset - limit))}
            disabled={!hasPrev}
            className="rounded-control border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            ← Prev
          </button>
          <button
            onClick={() => onOffsetChange(offset + limit)}
            disabled={!hasNext}
            className="rounded-control border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}
