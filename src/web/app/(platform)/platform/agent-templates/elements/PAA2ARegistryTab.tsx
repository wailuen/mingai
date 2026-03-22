"use client";

import { useState } from "react";
import { Plus, RefreshCw, Trash2, AlertTriangle, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  usePlatformA2AAgents,
  useA2ARegistrySummary,
  useVerifyPlatformA2AAgent,
  useDeprecatePlatformA2AAgent,
  useDeletePlatformA2AAgent,
  calcHealthDot,
  type PlatformA2AAgent,
} from "@/lib/hooks/usePlatformA2ARegistry";
import { PAA2ARegistrationPanel } from "./PAA2ARegistrationPanel";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const HEALTH_COLORS = {
  green: "bg-accent",
  yellow: "bg-warn",
  red: "bg-alert",
};

const HEALTH_LABEL = {
  green: "Healthy",
  yellow: "Aging",
  red: "Stale",
};

function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function SummaryBar() {
  const { data } = useA2ARegistrySummary();

  const stats = [
    { label: "Platform Agents", value: data?.platform_count ?? 0 },
    { label: "Tenant Private Agents", value: data?.tenant_count ?? 0 },
    {
      label: "Invocations (30d)",
      value: (data?.total_invocations_30d ?? 0).toLocaleString(),
    },
  ];

  return (
    <div className="mb-5 grid grid-cols-3 gap-4">
      {stats.map((s) => (
        <div
          key={s.label}
          className="rounded-card border border-border bg-bg-surface px-4 py-3"
        >
          <p className="text-label-nav uppercase tracking-wider text-text-faint">
            {s.label}
          </p>
          <p className="mt-1 font-mono text-[22px] font-semibold text-text-primary">
            {s.value}
          </p>
        </div>
      ))}
    </div>
  );
}

function AgentRow({ agent }: { agent: PlatformA2AAgent }) {
  const dot = calcHealthDot(agent);
  const verifyMutation = useVerifyPlatformA2AAgent();
  const deprecateMutation = useDeprecatePlatformA2AAgent();
  const deleteMutation = useDeletePlatformA2AAgent();

  const isDeprecated = !!agent.deprecation_at;

  return (
    <tr className="border-b border-border-faint transition-colors hover:bg-accent-dim">
      {/* Name */}
      <td className="px-3.5 py-3">
        <div className="flex items-center gap-2">
          <Bot size={14} className="shrink-0 text-text-faint" />
          <span className="text-body-default font-medium text-text-primary">
            {agent.name}
          </span>
          {isDeprecated && (
            <span className="rounded-badge border border-alert/30 px-1.5 py-0.5 font-mono text-[10px] uppercase text-alert">
              Deprecated
            </span>
          )}
        </div>
      </td>

      {/* Card URL */}
      <td className="px-3.5 py-3">
        <span className="font-mono text-data-value text-text-faint">
          {agent.source_card_url.replace(/^https?:\/\//, "").slice(0, 40)}
          {agent.source_card_url.length > 50 ? "…" : ""}
        </span>
      </td>

      {/* Plan Gate */}
      <td className="px-3.5 py-3">
        {agent.plan_required ? (
          <span className="rounded-badge border border-warn/30 px-2 py-0.5 font-mono text-[10px] uppercase text-warn">
            {agent.plan_required}+
          </span>
        ) : (
          <span className="text-body-default text-text-faint">All plans</span>
        )}
      </td>

      {/* Assignment */}
      <td className="px-3.5 py-3">
        <span className="text-body-default text-text-muted">
          {agent.assigned_tenants.length === 0
            ? "All eligible"
            : `${agent.assigned_tenants.length} tenant${agent.assigned_tenants.length !== 1 ? "s" : ""}`}
        </span>
      </td>

      {/* Health */}
      <td className="px-3.5 py-3">
        <div className="flex items-center gap-1.5">
          <span className={cn("h-2 w-2 rounded-full", HEALTH_COLORS[dot])} />
          <span className="text-body-default text-text-muted">
            {HEALTH_LABEL[dot]}
          </span>
        </div>
      </td>

      {/* Last Verified */}
      <td className="px-3.5 py-3">
        <span className="font-mono text-data-value text-text-faint">
          {formatDate(agent.last_verified_at)}
        </span>
      </td>

      {/* Actions */}
      <td className="px-3.5 py-3">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => verifyMutation.mutate(agent.id)}
            disabled={verifyMutation.isPending}
            title="Verify now"
            className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
          >
            <RefreshCw size={10} />
            Verify
          </button>

          {!isDeprecated && (
            <button
              type="button"
              onClick={() => {
                if (
                  confirm(
                    `Deprecate "${agent.name}"? A 30-day deprecation window will begin and affected tenants will be notified.`,
                  )
                ) {
                  deprecateMutation.mutate(agent.id);
                }
              }}
              disabled={deprecateMutation.isPending}
              title="Start 30-day deprecation"
              className="inline-flex items-center gap-1 rounded-control border border-warn/30 px-2 py-1 text-[11px] text-warn transition-colors hover:bg-warn-dim disabled:opacity-30"
            >
              <AlertTriangle size={10} />
              Deprecate
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              if (
                confirm(
                  `Delete "${agent.name}"? This will fail if tenants have active deployments.`,
                )
              ) {
                deleteMutation.mutate(agent.id);
              }
            }}
            disabled={deleteMutation.isPending}
            title="Delete"
            className="inline-flex items-center gap-1 rounded-control border border-alert/30 px-2 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim disabled:opacity-30"
          >
            <Trash2 size={10} />
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PAA2ARegistryTab() {
  const [registerOpen, setRegisterOpen] = useState(false);
  const { data, isPending, error } = usePlatformA2AAgents();
  const agents = data?.items ?? [];

  return (
    <div>
      {registerOpen && (
        <PAA2ARegistrationPanel onClose={() => setRegisterOpen(false)} />
      )}

      {/* Summary */}
      <SummaryBar />

      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-section-heading text-text-primary">
            Platform A2A Agents
          </h2>
          <p className="mt-0.5 text-body-default text-text-faint">
            Available to tenants based on plan gate and assignment
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRegisterOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-control bg-accent px-3 py-2 text-body-default font-medium text-bg-base transition-opacity hover:opacity-90"
        >
          <Plus size={14} />
          Register A2A Agent
        </button>
      </div>

      {/* Error */}
      {error && (
        <p className="py-4 text-body-default text-alert">
          Failed to load registry:{" "}
          {error instanceof Error ? error.message : "Unknown error"}
        </p>
      )}

      {/* Table */}
      <div className="rounded-card border border-border bg-bg-surface overflow-hidden">
        <table className="w-full">
          <thead className="bg-bg-elevated">
            <tr className="border-b border-border">
              {[
                "Name",
                "Card URL",
                "Plan Gate",
                "Assignment",
                "Health",
                "Last Verified",
                "Actions",
              ].map((h) => (
                <th
                  key={h}
                  className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isPending &&
              Array.from({ length: 3 }).map((_, i) => (
                <tr key={i} className="border-b border-border-faint">
                  {Array.from({ length: 7 }).map((__, j) => (
                    <td key={j} className="px-3.5 py-3">
                      <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
                    </td>
                  ))}
                </tr>
              ))}

            {!isPending && agents.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-3.5 py-12 text-center text-body-default text-text-faint"
                >
                  No platform A2A agents registered yet
                </td>
              </tr>
            )}

            {agents.map((agent) => (
              <AgentRow key={agent.id} agent={agent} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Tenant section */}
      <div className="mt-6 rounded-card border border-border-faint bg-bg-elevated/50 px-5 py-4">
        <p className="text-label-nav uppercase tracking-wider text-text-faint">
          Tenant Private Agents
        </p>
        <p className="mt-1 text-body-default text-text-muted">
          Tenant-registered A2A agents are private to each tenant. Aggregate
          count is shown in the summary above — individual tenant agents are not
          accessible from this view.
        </p>
      </div>
    </div>
  );
}
