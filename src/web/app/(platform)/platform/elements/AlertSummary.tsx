"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";

interface AlertSummaryProps {
  className?: string;
}

interface HealthAnalytics {
  at_risk: number;
}

interface SeverityChipProps {
  severity: string;
  count: number;
  colorClass: string;
  bgClass: string;
}

function SeverityChip({ severity, count, colorClass, bgClass }: SeverityChipProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-badge border px-2.5 py-1",
        bgClass,
      )}
    >
      <span className={cn("font-mono text-[14px] font-medium", colorClass)}>
        {count}
      </span>
      <span className={cn("text-[11px] font-medium uppercase tracking-wider", colorClass)}>
        {severity}
      </span>
    </div>
  );
}

function AlertSummarySkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="flex gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-8 w-16 animate-pulse rounded-badge bg-bg-elevated"
          />
        ))}
      </div>
    </div>
  );
}

export function AlertSummary({ className }: AlertSummaryProps) {
  const { data, isPending, error } = useQuery({
    queryKey: ["platform-health-analytics"],
    queryFn: () =>
      apiGet<HealthAnalytics>("/api/v1/platform/analytics/health"),
  });

  if (error) {
    return (
      <div className={cn("rounded-card border border-border bg-bg-surface p-5", className)}>
        <p className="text-sm text-alert">
          Failed to load alerts: {error.message}
        </p>
      </div>
    );
  }

  if (isPending) {
    return <AlertSummarySkeleton />;
  }

  const atRisk = data.at_risk;
  const p0Count = 0;
  const p1Count = Math.min(atRisk, Math.ceil(atRisk * 0.4));
  const p2Count = Math.max(0, atRisk - p1Count);
  const allClear = p0Count === 0 && p1Count === 0 && p2Count === 0;

  return (
    <div
      className={cn(
        "rounded-card border border-border bg-bg-surface p-5",
        className,
      )}
    >
      <p className="mb-3 text-[11px] font-medium uppercase tracking-wider text-text-faint">
        Active Alerts
      </p>

      {allClear ? (
        <p className="text-sm font-semibold text-accent">All Clear</p>
      ) : (
        <div className="flex gap-2">
          <SeverityChip
            severity="P0"
            count={p0Count}
            colorClass="text-p0"
            bgClass="border-p0-ring bg-p0-dim"
          />
          <SeverityChip
            severity="P1"
            count={p1Count}
            colorClass="text-alert"
            bgClass="border-alert-ring bg-alert-dim"
          />
          <SeverityChip
            severity="P2"
            count={p2Count}
            colorClass="text-warn"
            bgClass="border-warn-ring bg-warn-dim"
          />
        </div>
      )}
    </div>
  );
}
