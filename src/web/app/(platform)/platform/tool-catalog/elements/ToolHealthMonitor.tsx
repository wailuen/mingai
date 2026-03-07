"use client";

import { cn } from "@/lib/utils";
import {
  useToolHealthHistory,
  type HealthStatus,
} from "@/lib/hooks/useToolCatalog";

interface ToolHealthMonitorProps {
  toolId: string;
  currentStatus: HealthStatus;
}

const STATUS_DOT_COLOR: Record<HealthStatus, string> = {
  healthy: "bg-accent",
  degraded: "bg-warn",
  unavailable: "bg-alert",
};

const STATUS_LABEL: Record<HealthStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  unavailable: "Unavailable",
};

export function ToolHealthMonitor({
  toolId,
  currentStatus,
}: ToolHealthMonitorProps) {
  const { data: history, isPending } = useToolHealthHistory(toolId);

  return (
    <div className="flex items-center gap-3">
      {/* Current status */}
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            "inline-block h-2 w-2 rounded-full",
            STATUS_DOT_COLOR[currentStatus],
          )}
        />
        <span className="text-xs text-text-muted">
          {STATUS_LABEL[currentStatus]}
        </span>
      </div>

      {/* Last 24 check dots */}
      {isPending ? (
        <div className="flex gap-0.5">
          {Array.from({ length: 12 }).map((_, i) => (
            <div
              key={i}
              className="h-2 w-2 animate-pulse rounded-full bg-bg-elevated"
            />
          ))}
        </div>
      ) : (
        history &&
        history.length > 0 && (
          <div className="flex gap-0.5">
            {history.slice(-24).map((check, i) => (
              <div
                key={i}
                title={`${check.status} - ${new Date(check.timestamp).toLocaleTimeString()}`}
                className={cn(
                  "h-2 w-2 rounded-full",
                  STATUS_DOT_COLOR[check.status],
                )}
              />
            ))}
          </div>
        )
      )}
    </div>
  );
}
