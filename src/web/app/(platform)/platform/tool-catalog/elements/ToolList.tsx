"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import {
  useTools,
  useRetireTool,
  classifyTools,
  type Tool,
  type HealthStatus,
  type SafetyClass,
} from "@/lib/hooks/useToolCatalog";
import { SafetyClassificationBadge } from "./SafetyClassificationBadge";
import { ToolHealthMonitor } from "./ToolHealthMonitor";
import { IntegrationGroupRow } from "./IntegrationGroupRow";

interface ToolListProps {
  onView: (tool: Tool) => void;
}

const HEALTH_DOT: Record<HealthStatus, string> = {
  healthy: "bg-accent",
  degraded: "bg-warn",
  unavailable: "bg-alert",
};

const HEALTH_TEXT: Record<HealthStatus, string> = {
  healthy: "text-accent",
  degraded: "text-warn",
  unavailable: "text-alert",
};

function HealthIndicator({ status }: { status: HealthStatus }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={cn("inline-block h-2 w-2 rounded-full", HEALTH_DOT[status])}
      />
      <span
        className={cn(
          "text-[12px] capitalize font-medium",
          HEALTH_TEXT[status],
        )}
      >
        {status}
      </span>
    </div>
  );
}

function SkeletonSection() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="h-12 animate-pulse rounded-control bg-bg-elevated"
        />
      ))}
    </div>
  );
}

function BuiltinToolRow({
  tool,
  onView,
}: {
  tool: Tool;
  onView: (t: Tool) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div>
      <div
        onClick={() => onView(tool)}
        className={cn(
          "flex cursor-pointer items-center gap-4 px-4 py-3 transition-colors hover:bg-accent-dim",
          tool.is_active === false && "opacity-50",
        )}
        style={{ transition: "background 220ms ease" }}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-body-default font-medium text-text-primary">
              {tool.name}
            </span>
            {tool.is_active === false && (
              <span className="rounded-badge bg-bg-deep px-1.5 py-0.5 text-[10px] font-semibold text-text-faint">
                Retired
              </span>
            )}
            <span className="rounded-badge bg-bg-elevated px-2 py-0.5 text-[10px] font-semibold text-text-faint uppercase tracking-wide">
              Built-in
            </span>
          </div>
          {tool.description && (
            <p className="mt-0.5 text-[11px] text-text-faint line-clamp-1">
              {tool.description}
            </p>
          )}
        </div>
        <SafetyClassificationBadge safetyClass={tool.safety_class} />
        <HealthIndicator status={tool.health_status} />
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
          className="ml-2 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          {expanded ? "Hide stats" : "Stats"}
        </button>
      </div>
      {expanded && (
        <div className="border-t border-border bg-bg-elevated/50 px-6 py-4">
          <div className="grid grid-cols-3 gap-6">
            <div>
              <p className="text-[11px] uppercase tracking-wider text-text-faint">
                Invocations
              </p>
              <p className="mt-1 font-mono text-body-default text-text-primary">
                {tool.invocation_count.toLocaleString()}
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-text-faint">
                Error Rate
              </p>
              <p
                className={cn(
                  "mt-1 font-mono text-body-default",
                  tool.error_rate_pct > 5
                    ? "text-alert"
                    : "text-text-primary",
                )}
              >
                {tool.error_rate_pct.toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-text-faint">
                P50 Latency
              </p>
              <p className="mt-1 font-mono text-body-default text-text-primary">
                {tool.p50_latency_ms}ms
              </p>
            </div>
          </div>
          <div className="mt-3">
            <p className="text-[11px] uppercase tracking-wider text-text-faint">
              Health (Last 24 Checks)
            </p>
            <div className="mt-2">
              <ToolHealthMonitor
                toolId={tool.id}
                currentStatus={tool.health_status}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Retire confirmation modal
// ---------------------------------------------------------------------------

interface RetireModalProps {
  target: { id: string; name: string };
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}

function RetireModal({ target, onConfirm, onCancel, isPending }: RetireModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-bg-deep/60"
        onClick={onCancel}
        role="presentation"
      />
      <div className="relative w-[440px] rounded-control border border-border bg-bg-surface p-6">
        <h3 className="text-section-heading text-text-primary mb-2">
          Retire {target.name}?
        </h3>
        <p className="text-body-default text-text-muted mb-6">
          This removes it from all tenant agent assignments. This action marks
          the tool as unavailable and cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-control border border-border px-4 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className="rounded-control bg-alert px-4 py-1.5 text-body-default font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            Retire Tool
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ToolList({ onView }: ToolListProps) {
  const { data, isPending, error } = useTools();
  const retireMutation = useRetireTool();

  const [expandedProviders, setExpandedProviders] = useState<
    Record<string, boolean>
  >({});
  const [safetyFilter, setSafetyFilter] = useState<SafetyClass | "all">("all");
  const [statusFilter, setStatusFilter] = useState<
    "all" | "active" | "retired"
  >("all");
  const [retireTarget, setRetireTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const filteredTools = useMemo(() => {
    if (!data) return [];
    return data.filter((t) => {
      if (safetyFilter !== "all" && t.safety_class !== safetyFilter)
        return false;
      if (statusFilter === "active" && t.is_active === false) return false;
      if (statusFilter === "retired" && t.is_active !== false) return false;
      return true;
    });
  }, [data, safetyFilter, statusFilter]);

  const classified = useMemo(
    () => classifyTools(filteredTools),
    [filteredTools],
  );

  function handleRetireConfirm() {
    if (!retireTarget) return;
    retireMutation.mutate(retireTarget.id);
    setRetireTarget(null);
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load tools: {error.message}
      </p>
    );
  }

  const totalCount = data?.length ?? 0;

  return (
    <>
      {/* Filter bar */}
      <div className="mb-6 flex flex-wrap items-center gap-2">
        {/* Safety filter */}
        <div className="flex items-center gap-1">
          {(
            [
              { value: "all", label: "All Safety" },
              { value: "read_only", label: "Read-only" },
              { value: "write", label: "Write" },
              { value: "destructive", label: "Destructive" },
            ] as { value: SafetyClass | "all"; label: string }[]
          ).map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setSafetyFilter(opt.value)}
              className={cn(
                "rounded-control border px-3 py-1 text-[12px] transition-colors",
                safetyFilter === opt.value
                  ? "border-accent bg-accent-dim text-accent"
                  : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
              )}
              style={{ transition: "background 220ms ease, color 220ms ease, border-color 220ms ease" }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="h-4 w-px bg-border" />

        {/* Status filter */}
        <div className="flex items-center gap-1">
          {(
            [
              { value: "all", label: "All Status" },
              { value: "active", label: "Active" },
              { value: "retired", label: "Retired" },
            ] as { value: "all" | "active" | "retired"; label: string }[]
          ).map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setStatusFilter(opt.value)}
              className={cn(
                "rounded-control border px-3 py-1 text-[12px] transition-colors",
                statusFilter === opt.value
                  ? "border-accent bg-accent-dim text-accent"
                  : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
              )}
              style={{ transition: "background 220ms ease, color 220ms ease, border-color 220ms ease" }}
            >
              {opt.label}
            </button>
          ))}
        </div>

        <div className="ml-auto font-mono text-[12px] text-text-faint">
          {isPending ? "Loading…" : `${totalCount} tool${totalCount !== 1 ? "s" : ""} total`}
        </div>
      </div>

      {/* Sections */}
      <div className="space-y-8">
        {/* Section 1: Built-in Tools */}
        <section>
          <h2 className="text-section-heading text-text-primary mb-3">
            Built-in Tools
          </h2>
          {isPending ? (
            <SkeletonSection />
          ) : classified.builtins.length === 0 ? (
            <p className="text-body-default text-text-faint">
              No built-in tools configured. Contact support.
            </p>
          ) : (
            <div className="divide-y divide-border rounded-control border border-border overflow-hidden">
              {classified.builtins.map((tool) => (
                <BuiltinToolRow key={tool.id} tool={tool} onView={onView} />
              ))}
            </div>
          )}
        </section>

        {/* Section 2: MCP Integrations */}
        <section>
          <h2 className="text-section-heading text-text-primary mb-3">
            MCP Integrations
          </h2>
          {isPending ? (
            <SkeletonSection />
          ) : Object.keys(classified.mcpIntegrations).length === 0 ? (
            <p className="text-body-default text-text-faint">
              No MCP integrations registered. Use &apos;Register Tool&apos; to
              add one.
            </p>
          ) : (
            <div className="divide-y divide-border rounded-control border border-border overflow-hidden">
              {Object.entries(classified.mcpIntegrations).map(
                ([provider, tools]) => (
                  <IntegrationGroupRow
                    key={provider}
                    provider={provider}
                    tools={tools}
                    isExpanded={expandedProviders[provider] ?? false}
                    onToggle={() =>
                      setExpandedProviders((prev) => ({
                        ...prev,
                        [provider]: !prev[provider],
                      }))
                    }
                    onRetire={(tool) =>
                      setRetireTarget({ id: tool.id, name: tool.name })
                    }
                    onView={onView}
                  />
                ),
              )}
            </div>
          )}
        </section>

        {/* Section 3: Tenant Tools — aggregate only (no per-tool detail per product spec) */}
        <section>
          <h2 className="text-section-heading text-text-primary mb-3">
            Tenant Tools
          </h2>
          {isPending ? (
            <SkeletonSection />
          ) : classified.tenantTools.length === 0 ? (
            <p className="text-body-default text-text-faint">
              No tenant tools registered yet.
            </p>
          ) : (
            <div className="rounded-control border border-border px-5 py-4">
              {(() => {
                const serverIds = new Set(
                  classified.tenantTools
                    .map((t) => t.source_mcp_server_id)
                    .filter(Boolean),
                );
                const serverCount = serverIds.size;
                const toolCount = classified.tenantTools.length;
                return (
                  <div className="flex items-center gap-6">
                    <div>
                      <p className="text-[11px] uppercase tracking-wider text-text-faint">
                        Private MCP Servers
                      </p>
                      <p className="mt-1 font-mono text-[18px] font-semibold text-text-primary">
                        {serverCount}
                      </p>
                    </div>
                    <div className="h-8 w-px bg-border" />
                    <div>
                      <p className="text-[11px] uppercase tracking-wider text-text-faint">
                        Unique Tools
                      </p>
                      <p className="mt-1 font-mono text-[18px] font-semibold text-text-primary">
                        {toolCount}
                      </p>
                    </div>
                    <p className="ml-2 text-body-default text-text-muted">
                      tools registered across tenant workspaces
                    </p>
                  </div>
                );
              })()}
            </div>
          )}
        </section>
      </div>

      {/* Retire confirmation modal */}
      {retireTarget && (
        <RetireModal
          target={retireTarget}
          onConfirm={handleRetireConfirm}
          onCancel={() => setRetireTarget(null)}
          isPending={retireMutation.isPending}
        />
      )}
    </>
  );
}
