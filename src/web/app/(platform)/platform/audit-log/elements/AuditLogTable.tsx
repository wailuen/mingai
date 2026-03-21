"use client";

import { cn } from "@/lib/utils";
import type { AuditEvent } from "@/lib/hooks/useAuditLog";
import type { PaginatedResponse } from "@/lib/api";

interface AuditLogTableProps {
  data: PaginatedResponse<AuditEvent> | undefined;
  isPending: boolean;
  error: Error | null;
  page: number;
  onPageChange: (page: number) => void;
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      year: "numeric",
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

export function AuditLogTable({
  data,
  isPending,
  error,
  page,
  onPageChange,
}: AuditLogTableProps) {
  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load audit log: {error.message}
      </p>
    );
  }

  const startIdx = data ? (data.page - 1) * data.limit + 1 : 0;
  const endIdx = data ? startIdx + data.items.length - 1 : 0;

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Timestamp
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Actor
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Action
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Resource
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Tenant
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Outcome
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                IP Address
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending && <SkeletonRows />}

            {data && data.items.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No audit events match the current filters. Adjust your
                  criteria or wait for new activity to be recorded.
                </td>
              </tr>
            )}

            {data?.items.map((event) => (
              <tr
                key={event.id}
                className="border-b border-border-faint transition-colors hover:bg-accent-dim"
              >
                <td className="px-3.5 py-3 font-mono text-data-value text-text-muted">
                  {formatTimestamp(event.timestamp)}
                </td>
                <td className="px-3.5 py-3">
                  <div className="text-body-default font-medium text-text-primary">
                    {event.actor_email}
                  </div>
                  <div className="text-[11px] text-text-faint">
                    {(event.actor_type ?? "").replace("_", " ")}
                  </div>
                </td>
                <td className="px-3.5 py-3 text-body-default text-text-primary">
                  {event.action}
                </td>
                <td className="px-3.5 py-3">
                  <span className="text-body-default text-text-muted">
                    {event.resource_type}
                  </span>
                  <span className="ml-1 font-mono text-data-value text-text-faint">
                    {event.resource_id}
                  </span>
                </td>
                <td className="px-3.5 py-3 text-body-default text-text-muted">
                  {event.tenant_name}
                </td>
                <td className="px-3.5 py-3">
                  <span
                    className={cn(
                      "inline-block rounded-badge px-2 py-0.5 text-[11px] font-medium",
                      event.outcome === "success"
                        ? "bg-accent-dim text-accent"
                        : "bg-alert-dim text-alert",
                    )}
                  >
                    {event.outcome}
                  </span>
                </td>
                <td className="px-3.5 py-3 font-mono text-data-value text-text-faint">
                  {event.ip_address}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {data && data.total > 0 && (
        <div className="flex items-center justify-between border-t border-border px-5 py-2.5">
          <p className="font-mono text-data-value text-text-faint">
            Showing {startIdx}&ndash;{endIdx} of {data.total}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
              className={cn(
                "rounded-control border border-border px-3 py-1 text-body-default text-text-muted transition-colors",
                page <= 1
                  ? "cursor-not-allowed opacity-40"
                  : "hover:bg-bg-elevated hover:text-text-primary",
              )}
            >
              Prev
            </button>
            <span className="font-mono text-data-value text-text-faint">
              {page} / {data.total_pages}
            </span>
            <button
              type="button"
              disabled={page >= data.total_pages}
              onClick={() => onPageChange(page + 1)}
              className={cn(
                "rounded-control border border-border px-3 py-1 text-body-default text-text-muted transition-colors",
                page >= data.total_pages
                  ? "cursor-not-allowed opacity-40"
                  : "hover:bg-bg-elevated hover:text-text-primary",
              )}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
