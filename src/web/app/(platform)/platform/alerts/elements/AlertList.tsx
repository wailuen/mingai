"use client";

import { cn } from "@/lib/utils";
import type { PlatformAlert } from "@/lib/hooks/usePlatformAlerts";
import { useAcknowledgeAlert } from "@/lib/hooks/usePlatformAlerts";
import { AlertSeverityDot } from "./AlertSeverityDot";

interface AlertListProps {
  alerts: PlatformAlert[];
  onConfigureAlert: (alert: PlatformAlert) => void;
}

function formatTime(iso: string): string {
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

function AlertCard({
  alert,
  onConfigure,
}: {
  alert: PlatformAlert;
  onConfigure: () => void;
}) {
  const acknowledge = useAcknowledgeAlert();
  const isAcknowledged = alert.acknowledged_at !== null;

  return (
    <div
      className={cn(
        "rounded-card border border-border p-4 transition-colors",
        isAcknowledged ? "bg-bg-base opacity-50" : "bg-bg-elevated",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-1">
          <AlertSeverityDot severity={alert.severity} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-text-primary">
              {alert.type}
            </span>
            <span
              className={cn(
                "rounded-badge px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider",
                (alert.severity === "critical" || alert.severity === "high") &&
                  "bg-alert-dim text-alert",
                alert.severity === "medium" && "bg-warn-dim text-warn",
                alert.severity === "low" &&
                  "bg-bg-elevated text-text-muted border border-border",
              )}
            >
              {alert.severity}
            </span>
          </div>
          <p className="mt-1 text-[13px] text-text-muted">{alert.message}</p>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-text-faint">
            <span>{alert.tenant_name}</span>
            <span className="font-mono">{formatTime(alert.created_at)}</span>
            {alert.threshold > 0 && (
              <span className="font-mono">
                threshold: {alert.threshold} / current: {alert.current_value}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!isAcknowledged && (
            <button
              type="button"
              disabled={acknowledge.isPending}
              onClick={() => acknowledge.mutate(alert.id)}
              className="rounded-control border border-border px-3 py-1 text-[12px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-50"
            >
              {acknowledge.isPending ? "..." : "Acknowledge"}
            </button>
          )}
          <button
            type="button"
            onClick={onConfigure}
            className="rounded-control border border-border px-3 py-1 text-[12px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Configure
          </button>
        </div>
      </div>
    </div>
  );
}

export function AlertList({ alerts, onConfigureAlert }: AlertListProps) {
  const unacknowledged = alerts.filter((a) => a.acknowledged_at === null);
  const acknowledged = alerts.filter((a) => a.acknowledged_at !== null);

  if (alerts.length === 0) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-12 text-center">
        <p className="text-sm text-text-muted">
          No alerts at this time. The system will generate alerts when
          configured thresholds are breached.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {unacknowledged.map((alert) => (
        <AlertCard
          key={alert.id}
          alert={alert}
          onConfigure={() => onConfigureAlert(alert)}
        />
      ))}
      {acknowledged.map((alert) => (
        <AlertCard
          key={alert.id}
          alert={alert}
          onConfigure={() => onConfigureAlert(alert)}
        />
      ))}
    </div>
  );
}
