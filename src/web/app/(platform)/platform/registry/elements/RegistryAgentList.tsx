"use client";

import { useState } from "react";
import {
  useRegistryAgents,
  usePublishAgent,
  useUnpublishAgent,
  type RegistryAgent,
  type RegistryStatus,
} from "@/lib/hooks/useTenantRegistry";
import { RegistryStatusBadge } from "./RegistryStatusBadge";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 7 }).map((_, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

interface RegistryAgentListProps {
  statusFilter: RegistryStatus | "all";
}

/**
 * FE-050: Table listing registry agents with publish/unpublish actions.
 */
export function RegistryAgentList({ statusFilter }: RegistryAgentListProps) {
  const { data: agents, isPending, error } = useRegistryAgents();
  const publishMutation = usePublishAgent();
  const unpublishMutation = useUnpublishAgent();
  const [confirmUnpublishId, setConfirmUnpublishId] = useState<string | null>(
    null,
  );

  const filteredAgents: RegistryAgent[] = (agents ?? []).filter((agent) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "published") return agent.status === "published";
    if (statusFilter === "pending_review")
      return agent.status === "pending_review";
    return true;
  });

  function handlePublish(agentId: string) {
    publishMutation.mutate(agentId);
  }

  function handleUnpublish(agentId: string) {
    unpublishMutation.mutate(agentId, {
      onSettled: () => setConfirmUnpublishId(null),
    });
  }

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load registry agents: {error.message}
      </p>
    );
  }

  return (
    <>
      <div className="rounded-card border border-border bg-bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Name
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Category
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Publisher
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Status
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Installs
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Created
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {isPending && <SkeletonRows />}

              {!isPending && filteredAgents.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    className="px-3.5 py-12 text-center text-sm text-text-faint"
                  >
                    No registry agents found.
                  </td>
                </tr>
              )}

              {filteredAgents.map((agent) => (
                <tr
                  key={agent.id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="px-3.5 py-3">
                    <span className="text-[13px] font-medium text-text-primary">
                      {agent.name}
                    </span>
                  </td>
                  <td className="px-3.5 py-3">
                    <span className="text-[13px] text-text-muted">
                      {agent.category}
                    </span>
                  </td>
                  <td className="px-3.5 py-3">
                    <span className="text-[13px] text-text-muted">
                      {agent.publisher_tenant}
                    </span>
                  </td>
                  <td className="px-3.5 py-3">
                    <RegistryStatusBadge status={agent.status} />
                  </td>
                  <td className="px-3.5 py-3">
                    <span className="font-mono text-data-value text-text-muted">
                      {agent.install_count.toLocaleString()}
                    </span>
                  </td>
                  <td className="px-3.5 py-3">
                    <span className="font-mono text-data-value text-text-muted">
                      {formatDate(agent.created_at)}
                    </span>
                  </td>
                  <td className="px-3.5 py-3">
                    {(agent.status === "draft" ||
                      agent.status === "pending_review") && (
                      <button
                        type="button"
                        onClick={() => handlePublish(agent.id)}
                        disabled={publishMutation.isPending}
                        className="rounded-control border border-accent px-2 py-1 text-[11px] font-medium text-accent transition-colors hover:bg-accent-dim disabled:opacity-50"
                      >
                        Publish
                      </button>
                    )}
                    {agent.status === "published" && (
                      <button
                        type="button"
                        onClick={() => setConfirmUnpublishId(agent.id)}
                        disabled={unpublishMutation.isPending}
                        className="rounded-control border border-alert/40 px-2 py-1 text-[11px] font-medium text-alert transition-colors hover:bg-alert-dim disabled:opacity-50"
                      >
                        Unpublish
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination info */}
        {!isPending && filteredAgents.length > 0 && (
          <div className="border-t border-border px-5 py-2.5">
            <p className="font-mono text-[11px] text-text-faint">
              Showing {filteredAgents.length} agent
              {filteredAgents.length !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </div>

      {/* Unpublish confirmation dialog */}
      {confirmUnpublishId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/80">
          <div className="w-full max-w-sm rounded-card border border-border bg-bg-surface p-6">
            <h3 className="text-[15px] font-semibold text-text-primary">
              Confirm Unpublish
            </h3>
            <p className="mt-2 text-sm text-text-muted">
              This will remove the agent from the public registry. Existing
              installations will not be affected.
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setConfirmUnpublishId(null)}
                className="rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleUnpublish(confirmUnpublishId)}
                disabled={unpublishMutation.isPending}
                className="rounded-control border border-alert bg-alert-dim px-3 py-1.5 text-xs font-medium text-alert transition-colors hover:bg-alert/20 disabled:opacity-50"
              >
                {unpublishMutation.isPending ? "Unpublishing..." : "Unpublish"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
