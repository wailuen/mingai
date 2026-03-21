"use client";

import type { AnalyticsSatisfactionResponse } from "@/lib/hooks/useAnalytics";

interface SatisfactionGaugeProps {
  data: AnalyticsSatisfactionResponse | undefined;
  isPending: boolean;
}

/**
 * FE-037: Large KPI number showing 7-day rolling satisfaction %.
 *
 * Color logic:
 * - >= 80%: accent (green)
 * - 60-79%: warn (yellow)
 * - < 60%: alert (orange/red)
 *
 * Shows empty state when insufficient data (satisfaction_7d === 0 and no trend data).
 */
export function SatisfactionGauge({ data, isPending }: SatisfactionGaugeProps) {
  if (isPending) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <div className="h-16 w-32 animate-pulse rounded bg-bg-elevated" />
        <div className="mt-2 h-4 w-48 animate-pulse rounded bg-bg-elevated" />
      </div>
    );
  }

  // Backend signals explicitly that data volume is too low to be meaningful.
  if (data?.not_enough_data === true) {
    const count = data.total_ratings ?? 0;
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <p className="text-body-default font-medium text-text-muted">
          Collecting data…
        </p>
        <p className="mt-1 text-xs text-text-faint">
          {count} rating{count !== 1 ? "s" : ""} so far — 50+ needed for a
          reliable score.
        </p>
      </div>
    );
  }

  const satisfaction7d = data?.satisfaction_7d ?? 0;
  const hasData =
    data !== undefined &&
    (satisfaction7d > 0 || data.trend.some((t) => t.total > 0));

  if (!hasData) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <p className="text-body-default text-text-muted">
          Not enough data. Analytics available after 50 rated responses.
        </p>
      </div>
    );
  }

  const colorClass =
    satisfaction7d >= 80
      ? "text-accent"
      : satisfaction7d >= 60
        ? "text-warn"
        : "text-alert";

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-6">
      <p
        className={`font-mono text-[48px] font-semibold leading-none ${colorClass}`}
      >
        {satisfaction7d.toFixed(1)}%
      </p>
      <p className="mt-2 text-xs font-medium uppercase tracking-wider text-text-faint">
        7-day satisfaction rate
      </p>
    </div>
  );
}
