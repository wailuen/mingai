"use client";

import { useState, useMemo } from "react";
import {
  Search,
  Lock,
  ChevronDown,
  ChevronRight,
  Wrench,
  Globe,
  Cpu,
} from "lucide-react";
import { usePlatformTools } from "@/lib/hooks/useTools";
import type { PlatformTool, ToolExecutor } from "@/lib/hooks/useTools";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EXECUTOR_LABELS: Record<ToolExecutor, string> = {
  builtin: "Built-in",
  http_wrapper: "HTTP API",
  mcp_sse: "MCP",
};

const EXECUTOR_COLORS: Record<ToolExecutor, string> = {
  builtin: "text-accent bg-accent/10 border-accent/30",
  http_wrapper: "text-text-muted bg-bg-elevated border-border",
  mcp_sse: "text-warn bg-warn-dim border-warn/30",
};

const EXECUTOR_ICONS: Record<ToolExecutor, typeof Wrench> = {
  builtin: Cpu,
  http_wrapper: Globe,
  mcp_sse: Wrench,
};

const FALLBACK_EXECUTOR: ToolExecutor = "builtin";

const PLAN_COLORS: Record<string, string> = {
  starter: "text-text-muted bg-bg-elevated border-border",
  professional: "text-warn bg-warn-dim border-warn/30",
  enterprise: "text-accent bg-accent-dim border-accent/30",
};

// ---------------------------------------------------------------------------
// Expanded row component
// ---------------------------------------------------------------------------

function SchemaDisplay({ schema }: { schema: Record<string, unknown> }) {
  const json = JSON.stringify(schema, null, 2);
  return (
    <pre className="overflow-x-auto rounded-control border border-border bg-bg-deep p-3 font-mono text-data-value text-text-muted">
      {json}
    </pre>
  );
}

function ToolRow({ tool }: { tool: PlatformTool }) {
  const [expanded, setExpanded] = useState(false);
  const executorKey = (tool.executor_type ?? FALLBACK_EXECUTOR) as ToolExecutor;
  const ExecutorIcon = EXECUTOR_ICONS[executorKey] ?? Wrench;
  const hasDetail =
    (tool.input_schema && Object.keys(tool.input_schema).length > 0) ||
    tool.rate_limit_rpm != null;

  return (
    <div>
      {/* Main row */}
      <div
        className={cn(
          "grid items-center gap-4 px-4 py-3 transition-colors",
          hasDetail
            ? "cursor-pointer hover:bg-bg-elevated"
            : "hover:bg-bg-elevated/50",
        )}
        style={{
          gridTemplateColumns: "1fr 130px 140px 120px 1fr",
        }}
        onClick={() => hasDetail && setExpanded((p) => !p)}
        role={hasDetail ? "button" : undefined}
        tabIndex={hasDetail ? 0 : undefined}
        onKeyDown={
          hasDetail
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setExpanded((p) => !p);
                }
              }
            : undefined
        }
        aria-expanded={hasDetail ? expanded : undefined}
      >
        {/* Name + expand chevron */}
        <div className="flex min-w-0 items-center gap-2">
          {hasDetail ? (
            <span className="shrink-0 text-text-faint">
              {expanded ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
            </span>
          ) : (
            <span className="w-3.5 shrink-0" />
          )}
          <span className="truncate text-body-default font-medium text-text-primary">
            {tool.name}
          </span>
        </div>

        {/* Executor badge */}
        <div>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-badge border px-2 py-0.5 font-mono text-data-value",
              EXECUTOR_COLORS[executorKey],
            )}
          >
            <ExecutorIcon size={11} />
            {EXECUTOR_LABELS[executorKey]}
          </span>
        </div>

        {/* Credential source */}
        <div>
          <span className="text-body-default text-text-muted">
            {!tool.credential_source || tool.credential_source === "none" ? (
              <span className="text-text-faint">None</span>
            ) : tool.credential_source === "platform_managed" ? (
              "Platform-managed"
            ) : (
              "Required at deployment"
            )}
          </span>
        </div>

        {/* Plan gate */}
        <div>
          {tool.plan_required ? (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-badge border px-2 py-0.5 font-mono text-data-value uppercase",
                PLAN_COLORS[tool.plan_required],
              )}
            >
              <Lock size={10} />
              {tool.plan_required}+
            </span>
          ) : (
            <span className="text-body-default text-text-faint">All plans</span>
          )}
        </div>

        {/* Description */}
        <div className="min-w-0">
          {tool.description ? (
            <p className="truncate text-body-default text-text-muted">
              {tool.description}
            </p>
          ) : (
            <span className="text-body-default text-text-faint">—</span>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && hasDetail && (
        <div className="border-t border-border-faint bg-bg-deep px-6 py-4 space-y-4">
          {tool.rate_limit_rpm != null && (
            <div>
              <p className="mb-1 text-label-nav uppercase tracking-wider text-text-faint">
                Rate Limit
              </p>
              <span className="font-mono text-data-value text-text-primary">
                {tool.rate_limit_rpm} req/min
              </span>
            </div>
          )}
          {tool.input_schema && Object.keys(tool.input_schema).length > 0 && (
            <div>
              <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
                Input Schema
              </p>
              <SchemaDisplay schema={tool.input_schema} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PlatformToolsTab() {
  const [search, setSearch] = useState("");

  const { data, isPending, error } = usePlatformTools();
  const allTools = data?.items ?? [];

  const filtered = useMemo(() => {
    if (!search.trim()) return allTools;
    const q = search.toLowerCase();
    return allTools.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.description?.toLowerCase().includes(q) ||
        t.executor_type.toLowerCase().includes(q),
    );
  }, [allTools, search]);

  if (error) {
    return (
      <div className="py-12 text-center">
        <p className="text-body-default text-alert">
          Failed to load platform tools.{" "}
          {error instanceof Error ? error.message : "Unknown error."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search bar */}
      <div className="relative" style={{ maxWidth: 340 }}>
        <Search
          size={14}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint"
        />
        <input
          type="text"
          placeholder="Search tools..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-control border border-border bg-bg-elevated py-2 pl-8 pr-3 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
        />
      </div>

      {/* Loading skeleton */}
      {isPending && (
        <div className="animate-pulse divide-y divide-border rounded-card border border-border bg-bg-surface">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-12" />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isPending && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Wrench size={32} className="mb-3 text-text-faint" />
          <p className="text-body-default text-text-faint">
            {allTools.length === 0
              ? "No platform tools have been published yet."
              : "No tools match your search."}
          </p>
          {allTools.length > 0 && search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="mt-2 text-body-default text-accent hover:underline"
            >
              Clear search
            </button>
          )}
        </div>
      )}

      {/* Table */}
      {!isPending && filtered.length > 0 && (
        <div className="divide-y divide-border rounded-card border border-border bg-bg-surface overflow-hidden">
          {/* Header */}
          <div
            className="grid items-center gap-4 border-b border-border bg-bg-elevated px-4 py-2.5"
            style={{
              gridTemplateColumns: "1fr 130px 140px 120px 1fr",
            }}
          >
            <span className="text-label-nav uppercase tracking-wider text-text-faint pl-5">
              Name
            </span>
            <span className="text-label-nav uppercase tracking-wider text-text-faint">
              Executor
            </span>
            <span className="text-label-nav uppercase tracking-wider text-text-faint">
              Credentials
            </span>
            <span className="text-label-nav uppercase tracking-wider text-text-faint">
              Plan Gate
            </span>
            <span className="text-label-nav uppercase tracking-wider text-text-faint">
              Description
            </span>
          </div>

          {/* Rows */}
          {filtered.map((tool) => (
            <ToolRow key={tool.id} tool={tool} />
          ))}
        </div>
      )}

      {/* Footer count */}
      {!isPending && allTools.length > 0 && (
        <p className="text-label-nav text-text-faint">
          {filtered.length} of {allTools.length} tool
          {allTools.length !== 1 ? "s" : ""}
        </p>
      )}
    </div>
  );
}
