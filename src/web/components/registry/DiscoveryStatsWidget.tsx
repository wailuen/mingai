"use client";

import { Eye, Zap } from "lucide-react";
import { useDiscoveryStats } from "@/lib/hooks/useRegistry";

interface DiscoveryStatsWidgetProps {
  agentId: string;
}

/**
 * HAR-006: Inline discovery stats for a single registered agent.
 * Shows "Discovered N times · M connections this week" in DM Mono.
 */
export function DiscoveryStatsWidget({ agentId }: DiscoveryStatsWidgetProps) {
  const { data, isPending, error } = useDiscoveryStats(agentId);

  if (error) return null;

  if (isPending) {
    return (
      <div className="flex items-center gap-3">
        <div className="h-3.5 w-24 animate-pulse rounded-badge bg-bg-elevated" />
        <div className="h-3.5 w-28 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="flex items-center gap-3 text-[11px]">
      <span className="flex items-center gap-1 font-mono text-text-muted">
        <Eye size={11} className="shrink-0 text-text-faint" />
        <span className="font-mono text-text-primary">
          {data.views_7d.toLocaleString()}
        </span>
        <span className="text-text-faint">discovered</span>
      </span>
      <span className="text-text-faint">·</span>
      <span className="flex items-center gap-1 font-mono text-text-muted">
        <Zap size={11} className="shrink-0 text-text-faint" />
        <span className="font-mono text-text-primary">
          {data.connections_initiated_7d.toLocaleString()}
        </span>
        <span className="text-text-faint">connections this week</span>
      </span>
    </div>
  );
}
