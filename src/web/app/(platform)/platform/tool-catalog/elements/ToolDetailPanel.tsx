"use client";

import { useState } from "react";
import { X, Activity, Shield, Plug, Clock, Code2, ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { SafetyClassificationBadge } from "./SafetyClassificationBadge";
import { ToolHealthMonitor } from "./ToolHealthMonitor";
import type { Tool } from "@/lib/hooks/useToolCatalog";

interface ToolDetailPanelProps {
  tool: Tool;
  onClose: () => void;
}

const AUTH_LABELS: Record<string, string> = {
  none: "None",
  api_key: "API Key",
  oauth2: "OAuth 2.0",
};

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <p className="text-[11px] uppercase tracking-wider text-text-faint">{label}</p>
      <div className="text-body-default text-text-primary">{children}</div>
    </div>
  );
}

function ExecutorBadge({ type }: { type: string }) {
  return (
    <span className="rounded-badge bg-accent-dim px-2 py-0.5 text-[10px] font-semibold text-accent">
      {type.toUpperCase().replace(/_/g, " ")}
    </span>
  );
}

function HealthDot({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    healthy: "bg-accent",
    degraded: "bg-warn",
    unavailable: "bg-alert",
  };
  const textMap: Record<string, string> = {
    healthy: "text-accent",
    degraded: "text-warn",
    unavailable: "text-alert",
  };
  return (
    <span className={cn("flex items-center gap-1.5 text-[12px] font-medium capitalize", textMap[status] ?? "text-text-muted")}>
      <span className={cn("h-2 w-2 rounded-full", colorMap[status] ?? "bg-text-muted")} />
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// API Reference section component
// ---------------------------------------------------------------------------

function ApiReferenceSection({ tool }: { tool: Tool }) {
  const [schemaExpanded, setSchemaExpanded] = useState(false);
  const mcpCallUrl = tool.mcp_endpoint
    ? `${tool.mcp_endpoint.replace(/\/$/, "")}/tools/call`
    : null;

  // Upstream endpoint (e.g. https://api.pitchbook.com/calls/history)
  const upstreamUrl = tool.endpoint_url ?? null;

  return (
    <div>
      <p className="mb-3 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-faint">
        <Code2 size={11} />
        API Reference
      </p>
      <div className="space-y-3 rounded-control border border-border bg-bg-elevated overflow-hidden">
        {/* Upstream API endpoint (actual call) */}
        {upstreamUrl && (
          <div className="px-3 pt-3">
            <p className="mb-1.5 text-[10px] uppercase tracking-wider text-text-faint">
              Upstream Endpoint
            </p>
            <div className="flex items-center gap-2">
              <span className="shrink-0 rounded-badge bg-bg-deep px-2 py-0.5 font-mono text-[10px] font-semibold text-text-muted">
                GET
              </span>
              <code className="flex-1 truncate font-mono text-[11px] text-text-primary" title={upstreamUrl}>
                {upstreamUrl}
              </code>
            </div>
          </div>
        )}

        {/* MCP platform call */}
        <div className={upstreamUrl ? "border-t border-border/60 px-3 py-2.5" : "px-3 pt-3"}>
          <p className="mb-1.5 text-[10px] uppercase tracking-wider text-text-faint">
            {upstreamUrl ? "Platform Invocation (MCP)" : "Endpoint"}
          </p>
          <div className="flex items-center gap-2">
            <span className="rounded-badge bg-accent-dim px-2 py-0.5 font-mono text-[10px] font-semibold text-accent">
              POST
            </span>
            <code className="flex-1 truncate font-mono text-[11px] text-text-primary">
              {mcpCallUrl ?? `${tool.mcp_endpoint ?? "<endpoint>"}/tools/call`}
            </code>
          </div>
        </div>

        {/* Tool name (operation identifier) */}
        <div className="border-t border-border/60 px-3 py-2.5">
          <p className="mb-1 text-[10px] uppercase tracking-wider text-text-faint">
            Operation
          </p>
          <code className="font-mono text-[12px] text-text-primary">
            {tool.name}
          </code>
        </div>

        {/* Request body shape */}
        <div className="border-t border-border/60 px-3 py-2.5">
          <p className="mb-1.5 text-[10px] uppercase tracking-wider text-text-faint">
            Request Body
          </p>
          <pre className="rounded-control bg-bg-deep p-2.5 font-mono text-[11px] text-text-muted overflow-x-auto">{`{
  "name": "${tool.name}",
  "arguments": { /* tool-specific params */ }
}`}</pre>
        </div>

        {/* Capabilities as parameter hints */}
        {tool.capabilities && tool.capabilities.length > 0 && (
          <div className="border-t border-border/60 px-3 pb-3">
            <button
              type="button"
              onClick={() => setSchemaExpanded((v) => !v)}
              className="flex w-full items-center justify-between pt-2.5 text-left"
            >
              <p className="text-[10px] uppercase tracking-wider text-text-faint">
                Capabilities ({tool.capabilities.length})
              </p>
              {schemaExpanded ? (
                <ChevronDown size={12} className="text-text-faint" />
              ) : (
                <ChevronRight size={12} className="text-text-faint" />
              )}
            </button>
            {schemaExpanded && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tool.capabilities.map((cap) => (
                  <code
                    key={cap}
                    className="rounded-badge border border-border bg-bg-deep px-2 py-0.5 font-mono text-[11px] text-text-muted"
                  >
                    {cap}
                  </code>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function ToolDetailPanel({ tool, onClose }: ToolDetailPanelProps) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-bg-deep/60"
        onClick={onClose}
        role="presentation"
      />

      {/* Panel */}
      <div className="relative flex w-[520px] flex-col border-l border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-border px-5 py-4">
          <div className="flex-1 min-w-0 pr-4">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-section-heading text-text-primary">{tool.name}</h2>
              {tool.is_active === false && (
                <span className="rounded-badge bg-bg-elevated px-2 py-0.5 text-[10px] font-semibold text-text-faint">
                  Retired
                </span>
              )}
            </div>
            {tool.provider && (
              <p className="mt-0.5 text-body-default text-text-muted">{tool.provider}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-6 overflow-y-auto p-5">
          {/* Identity section */}
          <div>
            <p className="mb-3 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-faint">
              <Plug size={11} />
              Identity
            </p>
            <div className="space-y-4">
              {tool.description && (
                <DetailRow label="Description">
                  <span className="text-text-muted leading-relaxed">{tool.description}</span>
                </DetailRow>
              )}
              <div className="grid grid-cols-2 gap-4">
                <DetailRow label="Safety Classification">
                  <SafetyClassificationBadge safetyClass={tool.safety_class} />
                </DetailRow>
                <DetailRow label="Authentication">
                  <span className="text-text-muted">
                    {AUTH_LABELS[tool.auth_type] ?? tool.auth_type}
                  </span>
                </DetailRow>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <DetailRow label="Executor Type">
                  <ExecutorBadge type={tool.executor_type ?? "mcp"} />
                </DetailRow>
                <DetailRow label="Scope">
                  <span className="text-text-muted capitalize">{tool.scope ?? "platform"}</span>
                </DetailRow>
              </div>
              {tool.mcp_endpoint && (
                <DetailRow label="MCP Endpoint">
                  <code className="block truncate rounded-control bg-bg-elevated px-2 py-1 font-mono text-[12px] text-text-primary">
                    {tool.mcp_endpoint}
                  </code>
                </DetailRow>
              )}
            </div>
          </div>

          {/* Capabilities */}
          {tool.capabilities && tool.capabilities.length > 0 && (
            <div>
              <p className="mb-3 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-faint">
                <Shield size={11} />
                Capabilities
              </p>
              <div className="flex flex-wrap gap-1.5">
                {tool.capabilities.map((cap: string) => (
                  <span
                    key={cap}
                    className="rounded-badge border border-border bg-bg-elevated px-2.5 py-1 text-[12px] text-text-muted"
                  >
                    {cap}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* API Reference */}
          {tool.executor_type !== "builtin" && tool.mcp_endpoint && (
            <ApiReferenceSection tool={tool} />
          )}

          {/* Health */}
          <div>
            <p className="mb-3 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-faint">
              <Activity size={11} />
              Health
            </p>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <DetailRow label="Current Status">
                  <HealthDot status={tool.health_status ?? "unavailable"} />
                </DetailRow>
                {tool.last_ping && (
                  <DetailRow label="Last Check">
                    <span className="flex items-center gap-1 font-mono text-[12px] text-text-muted">
                      <Clock size={11} />
                      {new Date(tool.last_ping).toLocaleString()}
                    </span>
                  </DetailRow>
                )}
              </div>
              <div>
                <p className="mb-2 text-[11px] text-text-faint">Last 24 checks</p>
                <ToolHealthMonitor toolId={tool.id} currentStatus={tool.health_status} />
              </div>
            </div>
          </div>

          {/* Usage stats */}
          <div>
            <p className="mb-3 text-[11px] uppercase tracking-wider text-text-faint">
              Usage (trailing 30d)
            </p>
            <div className="grid grid-cols-3 gap-4">
              <div className="rounded-control border border-border bg-bg-elevated px-3 py-3 text-center">
                <p className="font-mono text-[18px] font-semibold text-text-primary">
                  {tool.invocation_count.toLocaleString()}
                </p>
                <p className="mt-0.5 text-[11px] text-text-faint">Invocations</p>
              </div>
              <div className="rounded-control border border-border bg-bg-elevated px-3 py-3 text-center">
                <p
                  className={cn(
                    "font-mono text-[18px] font-semibold",
                    tool.error_rate_pct > 5 ? "text-alert" : "text-text-primary",
                  )}
                >
                  {tool.error_rate_pct.toFixed(1)}%
                </p>
                <p className="mt-0.5 text-[11px] text-text-faint">Error Rate</p>
              </div>
              <div className="rounded-control border border-border bg-bg-elevated px-3 py-3 text-center">
                <p className="font-mono text-[18px] font-semibold text-text-primary">
                  {tool.p50_latency_ms}ms
                </p>
                <p className="mt-0.5 text-[11px] text-text-faint">P50 Latency</p>
              </div>
            </div>
          </div>

          {/* Registered */}
          {tool.created_at && (
            <DetailRow label="Registered">
              <span className="font-mono text-[12px] text-text-muted">
                {new Date(tool.created_at).toLocaleDateString()}
              </span>
            </DetailRow>
          )}
        </div>
      </div>
    </div>
  );
}
