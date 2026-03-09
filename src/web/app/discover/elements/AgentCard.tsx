"use client";

import { cn } from "@/lib/utils";
import { type PublicAgent } from "@/lib/hooks/usePublicRegistry";

interface AgentCardProps {
  agent: PublicAgent;
  onRequestAccess: (agentId: string) => void;
  requesting: boolean;
}

/**
 * FE-049: Card for a single public registry agent.
 * Shows name, publisher, description, capabilities, satisfaction rate, and install count.
 */
export function AgentCard({
  agent,
  onRequestAccess,
  requesting,
}: AgentCardProps) {
  return (
    <div className="flex flex-col rounded-card border border-border bg-bg-surface p-5 transition-[var(--t)] hover:border-accent-ring">
      {/* Header */}
      <div className="mb-2">
        <h3 className="text-[15px] font-semibold text-text-primary">
          {agent.name}
        </h3>
        <p className="text-[11px] text-text-faint">{agent.publisher}</p>
      </div>

      {/* Description */}
      <p className="mb-3 line-clamp-2 text-sm text-text-muted">
        {agent.description}
      </p>

      {/* Capabilities */}
      {agent.capabilities.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {agent.capabilities.map((cap) => (
            <span
              key={cap}
              className="rounded-badge bg-bg-elevated px-2 py-0.5 text-[10px] font-medium text-text-muted"
            >
              {cap}
            </span>
          ))}
        </div>
      )}

      {/* Metrics row */}
      <div className="mt-auto flex items-center gap-4 border-t border-border-faint pt-3">
        <span
          className={cn(
            "font-mono text-xs",
            agent.satisfaction_rate >= 80 ? "text-accent" : "text-text-muted",
          )}
        >
          {agent.satisfaction_rate}% satisfaction
        </span>
        <span className="font-mono text-xs text-text-faint">
          {agent.install_count.toLocaleString()} installs
        </span>
      </div>

      {/* Action */}
      <div className="mt-3">
        {agent.is_installed ? (
          <span className="inline-block rounded-control border border-accent/30 bg-accent-dim px-3 py-1.5 text-xs font-medium text-accent">
            Installed
          </span>
        ) : (
          <button
            type="button"
            onClick={() => onRequestAccess(agent.id)}
            disabled={requesting}
            className={cn(
              "rounded-control border border-accent px-3 py-1.5 text-xs font-medium text-accent transition-[var(--t)] hover:bg-accent-dim",
              requesting && "opacity-50",
            )}
          >
            {requesting ? "Requesting..." : "Request Access"}
          </button>
        )}
      </div>
    </div>
  );
}
