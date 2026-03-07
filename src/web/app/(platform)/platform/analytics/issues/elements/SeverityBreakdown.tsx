"use client";

import { cn } from "@/lib/utils";
import {
  useIssuesBySeverity,
  type AnalyticsPeriod,
} from "@/lib/hooks/useIssueAnalytics";
import { Skeleton } from "@/components/shared/LoadingState";

// ---------------------------------------------------------------------------
// Severity badge styling (matches design system severity rules)
// ---------------------------------------------------------------------------

function severityBadgeClass(severity: string): string {
  switch (severity) {
    case "P0":
      return "border-red-400/30 bg-red-400/10 text-red-400";
    case "P1":
      return "border-alert/30 bg-alert-dim text-alert";
    case "P2":
      return "border-warn/30 bg-warn-dim text-warn";
    case "P3":
      return "border-border bg-bg-elevated text-text-muted";
    case "P4":
      return "border-border bg-bg-elevated text-text-faint";
    default:
      return "border-border bg-bg-elevated text-text-muted";
  }
}

// ---------------------------------------------------------------------------
// SeverityBreakdown
// ---------------------------------------------------------------------------

interface SeverityBreakdownProps {
  period: AnalyticsPeriod;
}

export function SeverityBreakdown({ period }: SeverityBreakdownProps) {
  const { data: breakdown, isPending, error } = useIssuesBySeverity(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load severity breakdown: {error.message}
      </p>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-section-heading text-text-primary">
        Severity Breakdown
      </h2>

      {isPending ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-5 w-10" />
              <Skeleton className="h-4 w-12" />
              <Skeleton className="h-3 w-[100px]" />
            </div>
          ))}
        </div>
      ) : !breakdown || breakdown.length === 0 ? (
        <p className="text-sm text-text-faint">
          No severity data available for this period.
        </p>
      ) : (
        <div className="space-y-2.5">
          {breakdown.map((item) => (
            <div key={item.severity} className="flex items-center gap-3">
              <span
                className={cn(
                  "inline-block w-10 rounded-sm border px-1.5 py-0.5 text-center font-mono text-[11px] font-medium",
                  severityBadgeClass(item.severity),
                )}
              >
                {item.severity}
              </span>

              <span className="w-12 text-right font-mono text-sm text-text-primary">
                {item.count}
              </span>

              <div className="relative h-3 w-[100px] overflow-hidden rounded-sm bg-bg-elevated">
                <div
                  className="absolute inset-y-0 left-0 rounded-sm bg-accent transition-all duration-200"
                  style={{ width: `${Math.min(item.pct, 100)}%` }}
                />
              </div>

              <span className="font-mono text-xs text-text-faint">
                {item.pct.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
