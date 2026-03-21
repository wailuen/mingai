"use client";

import { useState } from "react";
import { useTenantJobHistory } from "@/lib/hooks/useTenantJobHistory";
import type { JobRunRow } from "@/lib/hooks/useTenantJobHistory";

// ---------------------------------------------------------------------------
// Inline status badge (mirrors platform JobStatusBadge — not imported across
// route groups to keep Next.js App Router boundaries clean)
// ---------------------------------------------------------------------------

type JobStatus = JobRunRow["status"];

const STATUS_STYLES: Record<JobStatus, { label: string; className: string }> = {
  completed: {
    label: "Completed",
    className: "bg-accent-dim text-accent",
  },
  running: {
    label: "Running",
    className: "bg-warn-dim text-warn",
  },
  failed: {
    label: "Failed",
    className: "bg-alert-dim text-alert",
  },
  abandoned: {
    label: "Abandoned",
    className: "bg-bg-elevated text-text-muted",
  },
  skipped: {
    label: "Skipped",
    className: "bg-bg-elevated text-text-faint",
  },
};

function JobStatusBadge({ status }: { status: JobStatus }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.skipped;
  return (
    <span
      className={`inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${style.className}`}
    >
      {style.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Filter chip
// ---------------------------------------------------------------------------

const STATUS_CHIPS = [
  { label: "All", value: "" },
  { label: "Running", value: "running" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
] as const;

// ---------------------------------------------------------------------------
// Skeleton rows
// ---------------------------------------------------------------------------

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 5 }).map((__, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const ROWS_PER_PAGE = 10;

/**
 * TODO-13B: Tenant job history card for the Sync Health page.
 * Shows paginated background job runs scoped to the current workspace.
 */
export function TenantJobHistoryCard() {
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");

  const filters = statusFilter ? { status: statusFilter } : undefined;

  const { data, isPending, error } = useTenantJobHistory(
    offset,
    ROWS_PER_PAGE,
    filters,
  );

  const totalCount = data?.total_count ?? 0;
  const hasPrev = offset > 0;
  const hasNext = data ? offset + data.items.length < totalCount : false;

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h3 className="mb-0.5 text-section-heading text-text-primary">
        Job History
      </h3>
      <p className="mb-4 text-xs text-text-faint">
        Recent background job runs for your workspace
      </p>

      {/* Status filter chips */}
      <div className="mb-4 flex flex-wrap gap-2">
        {STATUS_CHIPS.map((chip) => {
          const isActive = statusFilter === chip.value;
          return (
            <button
              key={chip.value}
              onClick={() => {
                setStatusFilter(chip.value);
                setOffset(0);
              }}
              className={`rounded-control border px-3 py-1 text-xs transition-colors ${
                isActive
                  ? "border-accent-ring bg-accent-dim text-accent"
                  : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary"
              }`}
            >
              {chip.label}
            </button>
          );
        })}
      </div>

      {error && (
        <p className="text-body-default text-alert">
          Failed to load job history: {error.message}
        </p>
      )}

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
            </tr>
          </thead>
          <tbody>
            {isPending ? (
              <SkeletonRows />
            ) : !data || data.items.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-3.5 py-8 text-center text-body-default text-text-faint"
                >
                  No job history found.
                </td>
              </tr>
            ) : (
              data.items.map((row) => (
                <tr
                  key={row.id}
                  className={`border-b border-border-faint ${
                    row.status === "running"
                      ? "animate-pulse bg-accent-dim"
                      : "hover:bg-accent-dim"
                  }`}
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
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
        <span className="text-xs text-text-faint">
          {totalCount > 0
            ? `${offset + 1}–${Math.min(offset + ROWS_PER_PAGE, totalCount)} of ${totalCount}`
            : "0 results"}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - ROWS_PER_PAGE))}
            disabled={!hasPrev}
            className="rounded-control border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            ← Prev
          </button>
          <button
            onClick={() => setOffset(offset + ROWS_PER_PAGE)}
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
