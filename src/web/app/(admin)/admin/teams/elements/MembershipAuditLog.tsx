"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { useTeamAuditLog } from "@/lib/hooks/useTeams";

interface MembershipAuditLogProps {
  teamId: string;
}

function formatTimestamp(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sourceBadge(source: "manual" | "auth0_sync") {
  if (source === "auth0_sync") {
    return (
      <span className="rounded-badge border border-accent/20 bg-accent-dim px-1.5 py-0.5 text-[10px] font-medium text-accent">
        Auth0
      </span>
    );
  }
  return (
    <span className="rounded-badge border border-border bg-bg-elevated px-1.5 py-0.5 text-[10px] font-medium text-text-faint">
      Manual
    </span>
  );
}

function actionBadge(action: "added" | "removed") {
  if (action === "added") {
    return (
      <span className="rounded-badge border border-accent/20 bg-accent-dim px-1.5 py-0.5 text-[10px] font-medium text-accent">
        Added
      </span>
    );
  }
  return (
    <span className="rounded-badge border border-alert/20 bg-alert-dim px-1.5 py-0.5 text-[10px] font-medium text-alert">
      Removed
    </span>
  );
}

const PAGE_SIZE = 20;

/**
 * FE-039: Team membership audit trail.
 *
 * Columns: timestamp, actor, source (manual/auth0_sync), action (added/removed), member name.
 * Server-side pagination. Fetches from GET /api/v1/admin/teams/{id}/audit-log.
 */
export function MembershipAuditLog({ teamId }: MembershipAuditLogProps) {
  const [page, setPage] = useState(1);
  const { data, isPending, error } = useTeamAuditLog(teamId, page, PAGE_SIZE);

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  if (error) {
    return (
      <div className="py-4 text-center text-sm text-alert">
        Failed to load audit log: {error.message}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-[13px] font-semibold text-text-primary">
        Membership Audit Log
      </h3>

      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border">
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Time
              </th>
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Actor
              </th>
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Source
              </th>
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Action
              </th>
              <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                Member
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRowSkeleton key={i} columns={5} />
              ))
            ) : items.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="py-8 text-center text-sm text-text-faint"
                >
                  No membership changes recorded
                </td>
              </tr>
            ) : (
              items.map((entry) => (
                <tr
                  key={entry.id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="py-2.5 pr-3 font-mono text-[12px] text-text-muted">
                    {formatTimestamp(entry.timestamp)}
                  </td>
                  <td className="py-2.5 pr-3 text-[13px] text-text-primary">
                    {entry.actor}
                  </td>
                  <td className="py-2.5 pr-3">{sourceBadge(entry.source)}</td>
                  <td className="py-2.5 pr-3">{actionBadge(entry.action)}</td>
                  <td className="py-2.5 text-[13px] font-medium text-text-primary">
                    {entry.member_name}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between pt-2">
          <span className="font-mono text-xs text-text-faint">
            Page {page} of {totalPages}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="flex h-7 w-7 items-center justify-center rounded-control border border-border text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              onClick={() => setPage(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages}
              className="flex h-7 w-7 items-center justify-center rounded-control border border-border text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
