"use client";

import { useState } from "react";
import { Plus, RefreshCw, Trash2, Network } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useTenantA2AAgents,
  useVerifyA2AAgent,
  useDeregisterA2AAgent,
  type TenantA2AAgent,
  type A2AAgentStatus,
} from "@/lib/hooks/useA2AAgents";
import { A2ARegistrationPanel } from "./A2ARegistrationPanel";

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<
  A2AAgentStatus,
  { label: string; className: string }
> = {
  active: {
    label: "Active",
    className: "text-accent bg-accent/10 border border-accent/30",
  },
  unhealthy: {
    label: "Unhealthy",
    className: "text-alert bg-alert/10 border border-alert/30",
  },
  unverified: {
    label: "Unverified",
    className: "text-warn bg-warn/10 border border-warn/30",
  },
  archived: {
    label: "Archived",
    className: "text-text-faint bg-bg-elevated border border-border",
  },
};

function StatusBadge({ status }: { status: A2AAgentStatus }) {
  const config = STATUS_STYLES[status] ?? STATUS_STYLES.unverified;
  return (
    <span
      className={cn(
        "rounded-badge px-2 py-0.5 text-[11px] font-medium",
        config.className,
      )}
    >
      {config.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------

interface RowActionsProps {
  agent: TenantA2AAgent;
  onVerify: (id: string) => void;
  onDeregister: (id: string) => void;
  verifyingId: string | null;
  deregisteringId: string | null;
}

function RowActions({
  agent,
  onVerify,
  onDeregister,
  verifyingId,
  deregisteringId,
}: RowActionsProps) {
  return (
    <div
      className="flex items-center gap-2"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        disabled={verifyingId === agent.id}
        onClick={() => onVerify(agent.id)}
        className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-accent disabled:opacity-50"
        title="Re-verify agent"
      >
        <RefreshCw
          size={12}
          className={verifyingId === agent.id ? "animate-spin" : undefined}
        />
        <span className="hidden sm:inline">Re-verify</span>
      </button>

      <button
        type="button"
        disabled={deregisteringId === agent.id}
        onClick={() => onDeregister(agent.id)}
        className="flex items-center gap-1.5 rounded-control border border-alert/30 px-2.5 py-1.5 text-body-default text-alert transition-colors hover:border-alert hover:bg-alert/10 disabled:opacity-50"
        title="Deregister agent"
      >
        <Trash2 size={12} />
        <span className="hidden sm:inline">Deregister</span>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TenantA2AAgentsTab() {
  const [panelOpen, setPanelOpen] = useState(false);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [deregisteringId, setDeregisteringId] = useState<string | null>(null);

  const { data: agents = [], isPending, error } = useTenantA2AAgents();
  const verify = useVerifyA2AAgent();
  const deregister = useDeregisterA2AAgent();

  async function handleVerify(id: string) {
    setVerifyingId(id);
    try {
      await verify.mutateAsync(id);
    } finally {
      setVerifyingId(null);
    }
  }

  async function handleDeregister(id: string) {
    if (
      !window.confirm(
        "Deregister this A2A agent? Users will lose access to it.",
      )
    ) {
      return;
    }
    setDeregisteringId(id);
    try {
      await deregister.mutateAsync(id);
    } finally {
      setDeregisteringId(null);
    }
  }

  return (
    <div>
      {/* Top bar */}
      <div className="mb-5 flex items-center justify-between">
        <p className="font-mono text-data-value text-text-muted">
          {isPending
            ? "…"
            : `${agents.length} agent${agents.length !== 1 ? "s" : ""} registered`}
        </p>
        <button
          type="button"
          onClick={() => setPanelOpen(true)}
          className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
        >
          <Plus size={14} />
          Register A2A Agent
        </button>
      </div>

      {/* Error state */}
      {error && (
        <p className="py-4 text-body-default text-alert">
          Failed to load A2A agents: {String(error)}
        </p>
      )}

      {/* Loading skeleton */}
      {isPending && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-card border border-border bg-bg-surface"
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isPending && !error && agents.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-card border border-border bg-bg-surface py-16 text-center">
          <Network size={32} className="mb-3 text-text-faint" />
          <p className="text-body-default font-medium text-text-primary">
            No A2A agents registered
          </p>
          <p className="mt-1 text-body-default text-text-muted">
            Connect external agent-to-agent services by registering their Agent
            Card URLs.
          </p>
          <button
            type="button"
            onClick={() => setPanelOpen(true)}
            className="mt-4 flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={14} />
            Register A2A Agent
          </button>
        </div>
      )}

      {/* Table */}
      {!isPending && !error && agents.length > 0 && (
        <div className="rounded-card border border-border bg-bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Name
                  </th>
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Status
                  </th>
                  <th className="hidden px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint md:table-cell">
                    Operations
                  </th>
                  <th className="hidden px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint sm:table-cell">
                    Last Verified
                  </th>
                  <th className="px-4 py-3 text-left text-label-nav uppercase tracking-wider text-text-faint">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => (
                  <tr
                    key={agent.id}
                    className="border-b border-border-faint last:border-0 hover:bg-accent-dim/30"
                  >
                    {/* Name + description */}
                    <td className="px-4 py-3">
                      <p className="text-body-default font-medium text-text-primary">
                        {agent.name}
                      </p>
                      {agent.description && (
                        <p className="mt-0.5 line-clamp-1 text-body-default text-text-faint">
                          {agent.description}
                        </p>
                      )}
                    </td>

                    {/* Status */}
                    <td className="px-4 py-3">
                      <StatusBadge status={agent.status} />
                    </td>

                    {/* Operations count */}
                    <td className="hidden px-4 py-3 md:table-cell">
                      {agent.imported_card?.operations?.length != null ? (
                        <span className="font-mono text-data-value text-text-muted">
                          {agent.imported_card.operations.length}{" "}
                          {agent.imported_card.operations.length === 1
                            ? "operation"
                            : "operations"}
                        </span>
                      ) : (
                        <span className="font-mono text-data-value text-text-faint">
                          —
                        </span>
                      )}
                    </td>

                    {/* Last verified */}
                    <td className="hidden px-4 py-3 sm:table-cell">
                      {agent.last_verified_at ? (
                        <time
                          dateTime={agent.last_verified_at}
                          className="font-mono text-data-value text-text-muted"
                        >
                          {new Date(agent.last_verified_at).toLocaleDateString(
                            undefined,
                            {
                              year: "numeric",
                              month: "short",
                              day: "numeric",
                            },
                          )}
                        </time>
                      ) : (
                        <span className="font-mono text-data-value text-text-faint">
                          Never
                        </span>
                      )}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3">
                      <RowActions
                        agent={agent}
                        onVerify={handleVerify}
                        onDeregister={handleDeregister}
                        verifyingId={verifyingId}
                        deregisteringId={deregisteringId}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Registration slide-in panel */}
      {panelOpen && (
        <A2ARegistrationPanel
          onClose={() => setPanelOpen(false)}
          onRegistered={() => setPanelOpen(false)}
        />
      )}
    </div>
  );
}
