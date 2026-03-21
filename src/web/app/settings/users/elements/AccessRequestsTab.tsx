"use client";

import { useState } from "react";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { TableRowSkeleton } from "@/components/shared/LoadingState";
import { cn } from "@/lib/utils";
import {
  useAccessRequests,
  useUpdateAccessRequest,
  type AccessRequestItem,
  type AccessRequestStatus,
} from "@/lib/hooks/useAccessRequests";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadgeClass(status: AccessRequestStatus): string {
  switch (status) {
    case "pending":
      return "border-warn/30 bg-warn-dim text-warn";
    case "approved":
      return "border-accent/30 bg-accent/10 text-accent";
    case "denied":
      return "border-border bg-bg-elevated text-text-faint";
  }
}

function resourceTypeBadgeClass(type: string): string {
  return type === "kb"
    ? "border-accent/30 bg-accent/5 text-accent"
    : "border-border bg-bg-elevated text-text-muted";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Row-level approve/deny
// ---------------------------------------------------------------------------

function RequestActions({ request }: { request: AccessRequestItem }) {
  const updateMutation = useUpdateAccessRequest();
  const [noteInput, setNoteInput] = useState("");
  const [showDenyForm, setShowDenyForm] = useState(false);

  if (request.status !== "pending") {
    return (
      <span className="font-mono text-data-value text-text-faint">
        {request.admin_note ?? "\u2014"}
      </span>
    );
  }

  if (showDenyForm) {
    return (
      <div className="flex flex-col gap-1.5">
        <input
          type="text"
          value={noteInput}
          onChange={(e) => setNoteInput(e.target.value)}
          maxLength={200}
          placeholder="Reason (optional)"
          className="rounded-control border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
        />
        <div className="flex gap-1.5">
          <button
            type="button"
            disabled={updateMutation.isPending}
            onClick={() =>
              updateMutation.mutate({
                id: request.id,
                payload: { status: "denied", note: noteInput || undefined },
              })
            }
            className="flex items-center gap-1 rounded-control bg-alert px-2.5 py-1 text-[11px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {updateMutation.isPending ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <XCircle size={10} />
            )}
            Deny
          </button>
          <button
            type="button"
            onClick={() => setShowDenyForm(false)}
            className="rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        disabled={updateMutation.isPending}
        onClick={() =>
          updateMutation.mutate({
            id: request.id,
            payload: { status: "approved" },
          })
        }
        className="flex items-center gap-1 rounded-control bg-accent px-2.5 py-1 text-[11px] font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
      >
        {updateMutation.isPending ? (
          <Loader2 size={10} className="animate-spin" />
        ) : (
          <CheckCircle2 size={10} />
        )}
        Approve
      </button>
      <button
        type="button"
        disabled={updateMutation.isPending}
        onClick={() => setShowDenyForm(true)}
        className="flex items-center gap-1 rounded-control border border-border px-2.5 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim disabled:opacity-40"
      >
        <XCircle size={10} />
        Deny
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter tabs
// ---------------------------------------------------------------------------

const STATUS_FILTERS: {
  value: AccessRequestStatus | "all";
  label: string;
}[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "denied", label: "Denied" },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AccessRequestsTab() {
  const [statusFilter, setStatusFilter] = useState<AccessRequestStatus | "all">(
    "pending",
  );

  const { data, isLoading, error } = useAccessRequests(statusFilter);
  const requests = data?.items ?? [];

  return (
    <div>
      {/* Filter tabs */}
      <div className="mb-5 flex gap-0 border-b border-border">
        {STATUS_FILTERS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setStatusFilter(tab.value)}
            className={cn(
              "px-3.5 py-2 text-[12px] font-medium transition-colors",
              statusFilter === tab.value
                ? "border-b-2 border-accent text-text-primary"
                : "border-b-2 border-transparent text-text-faint hover:text-text-muted",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <p className="mb-4 text-body-default text-alert">
          Failed to load access requests: {error.message}
        </p>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-card border border-border">
        <table className="w-full min-w-[640px]">
          <thead>
            <tr className="border-b border-border bg-bg-surface">
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Requester
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Resource
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Type
              </th>
              <th className="hidden px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint sm:table-cell">
                Justification
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Status
              </th>
              <th className="hidden px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint sm:table-cell">
                Requested
              </th>
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRowSkeleton key={i} columns={7} />
              ))
            ) : requests.length === 0 ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No access requests{" "}
                  {statusFilter !== "all"
                    ? `with status "${statusFilter}"`
                    : ""}
                  .
                </td>
              </tr>
            ) : (
              requests.map((req) => (
                <tr
                  key={req.id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  {/* Requester */}
                  <td className="px-3.5 py-3">
                    <div>
                      {req.requester_name && (
                        <p className="text-body-default font-medium text-text-primary">
                          {req.requester_name}
                        </p>
                      )}
                      <p className="font-mono text-data-value text-text-faint">
                        {req.requester_email ?? req.user_id}
                      </p>
                    </div>
                  </td>

                  {/* Resource */}
                  <td className="px-3.5 py-3">
                    <span className="font-mono text-data-value text-text-muted">
                      {req.resource_id.slice(0, 8)}&hellip;
                    </span>
                  </td>

                  {/* Type */}
                  <td className="px-3.5 py-3">
                    <span
                      className={cn(
                        "inline-block rounded-badge border px-2 py-0.5 text-[11px] font-medium uppercase",
                        resourceTypeBadgeClass(req.resource_type),
                      )}
                    >
                      {req.resource_type === "kb" ? "KB" : "Agent"}
                    </span>
                  </td>

                  {/* Justification — hidden on mobile */}
                  <td className="hidden px-3.5 py-3 sm:table-cell">
                    <span
                      className="block max-w-[200px] truncate text-body-default text-text-muted"
                      title={req.justification}
                    >
                      {req.justification || "\u2014"}
                    </span>
                  </td>

                  {/* Status */}
                  <td className="px-3.5 py-3">
                    <span
                      className={cn(
                        "inline-block rounded-badge border px-2 py-0.5 text-[11px] font-medium capitalize",
                        statusBadgeClass(req.status),
                      )}
                    >
                      {req.status}
                    </span>
                  </td>

                  {/* Requested date — hidden on mobile */}
                  <td className="hidden px-3.5 py-3 sm:table-cell">
                    <span className="font-mono text-data-value text-text-faint">
                      {formatDate(req.created_at)}
                    </span>
                  </td>

                  {/* Actions */}
                  <td className="px-3.5 py-3">
                    <RequestActions request={req} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {data && data.total > 0 && (
          <div className="border-t border-border px-4 py-2.5">
            <p className="font-mono text-data-value text-text-faint">
              {data.total} total request{data.total !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
