"use client";

import { ChevronRight, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Tool } from "@/lib/hooks/useToolCatalog";

interface IntegrationGroupRowProps {
  provider: string;
  tools: Tool[];
  isExpanded: boolean;
  onToggle: () => void;
  onRetire: (tool: Tool) => void;
  onView: (tool: Tool) => void;
}

function HealthBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    healthy: "text-accent",
    degraded: "text-warn",
    unavailable: "text-alert",
  };
  const dotMap: Record<string, string> = {
    healthy: "bg-accent",
    degraded: "bg-warn",
    unavailable: "bg-alert",
  };
  const label = status.charAt(0).toUpperCase() + status.slice(1);
  return (
    <span
      className={cn(
        "flex items-center gap-1 text-[11px] font-medium",
        colorMap[status] ?? "text-text-muted",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          dotMap[status] ?? "bg-text-muted",
        )}
      />
      {label}
    </span>
  );
}

function ExecutorBadge({ type }: { type: string }) {
  return (
    <span className="rounded-badge bg-accent-dim px-2 py-0.5 text-[10px] font-semibold text-accent">
      {type.toUpperCase().replace("_", " ")}
    </span>
  );
}

function CredentialLabel({ authType }: { authType: string }) {
  const map: Record<string, string> = {
    api_key: "API Key",
    oauth2: "OAuth 2.0",
    none: "None",
  };
  return (
    <span className="text-[12px] text-text-muted">{map[authType] ?? authType}</span>
  );
}

export function IntegrationGroupRow({
  provider,
  tools,
  isExpanded,
  onToggle,
  onRetire,
  onView,
}: IntegrationGroupRowProps) {
  // Determine aggregate health from all tools in this group
  const statuses = tools.map((t) => t.health_status ?? "unavailable");
  const aggStatus = statuses.every((s) => s === "healthy")
    ? "healthy"
    : statuses.some((s) => s === "unavailable")
    ? "unavailable"
    : "degraded";

  return (
    <div>
      {/* Group header row */}
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-bg-elevated/50"
        style={{ transition: "background 220ms ease" }}
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center text-text-muted">
          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="flex-1 text-body-default font-medium text-text-primary">
          {provider}
        </span>
        <span className="font-mono text-[12px] text-text-faint">
          {tools.length} {tools.length === 1 ? "tool" : "tools"}
        </span>
        <HealthBadge status={aggStatus} />
      </button>

      {/* Expanded sub-table */}
      {isExpanded && (
        <div className="mx-4 mb-2 rounded-control bg-bg-elevated">
          <table className="w-full">
            <thead>
              <tr>
                <th className="px-3 py-2 text-left text-[11px] uppercase tracking-widest text-text-faint">
                  Tool
                </th>
                <th className="px-3 py-2 text-left text-[11px] uppercase tracking-widest text-text-faint">
                  Endpoint
                </th>
                <th className="px-3 py-2 text-left text-[11px] uppercase tracking-widest text-text-faint">
                  Credential
                </th>
                <th className="px-3 py-2 text-left text-[11px] uppercase tracking-widest text-text-faint">
                  Status
                </th>
                <th className="px-3 py-2 text-right text-[11px] uppercase tracking-widest text-text-faint">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {tools.map((tool) => (
                <tr
                  key={tool.id}
                  onClick={() => onView(tool)}
                  className={cn(
                    "cursor-pointer border-t border-border/50 transition-colors hover:bg-accent-dim/30",
                    tool.is_active === false && "opacity-50",
                  )}
                  style={{ transition: "background 220ms ease" }}
                >
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-body-default font-medium text-text-primary">
                        {tool.name}
                      </span>
                      {tool.is_active === false && (
                        <span className="rounded-badge bg-bg-deep px-1.5 py-0.5 text-[10px] font-semibold text-text-faint">
                          Retired
                        </span>
                      )}
                    </div>
                    {tool.description && (
                      <p className="mt-0.5 line-clamp-1 text-[11px] text-text-faint">
                        {tool.description}
                      </p>
                    )}
                  </td>
                  <td className="px-3 py-2 max-w-[220px]">
                    {tool.mcp_endpoint ? (
                      <code className="block truncate font-mono text-[10px] text-text-faint" title={`${tool.mcp_endpoint}/tools/call`}>
                        {tool.mcp_endpoint.replace(/https?:\/\//, "")}
                      </code>
                    ) : (
                      <ExecutorBadge type={tool.executor_type ?? "mcp"} />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <CredentialLabel authType={tool.auth_type} />
                  </td>
                  <td className="px-3 py-2">
                    <HealthBadge status={tool.health_status ?? "unavailable"} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    {tool.is_active !== false && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRetire(tool);
                        }}
                        className="inline-flex items-center gap-1 rounded-control border border-alert/30 px-2 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim"
                      >
                        Retire
                      </button>
                    )}
                  </td>

                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
