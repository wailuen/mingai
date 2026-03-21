"use client";

import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { Skeleton } from "@/components/shared/LoadingState";
import { useSatisfactionData, useSyncStatus } from "@/lib/hooks/useAnalytics";
import type {
  SatisfactionTrendPoint,
  SyncStatusEntry,
} from "@/lib/hooks/useAnalytics";

interface MergedDataPoint {
  date: string;
  satisfaction_pct: number;
  max_staleness: number;
}

interface CorrelationEvent {
  source_name: string;
  freshness_days: number;
  satisfaction_at_time: number;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function buildMergedData(
  trend: SatisfactionTrendPoint[],
  syncItems: SyncStatusEntry[],
): MergedDataPoint[] {
  const maxStaleness =
    syncItems.length > 0
      ? Math.max(...syncItems.map((s) => s.freshness_days))
      : 0;

  return trend.map((point) => ({
    date: point.date,
    satisfaction_pct: point.satisfaction_pct,
    max_staleness: maxStaleness,
  }));
}

function findCorrelations(
  trend: SatisfactionTrendPoint[],
  syncItems: SyncStatusEntry[],
): CorrelationEvent[] {
  const events: CorrelationEvent[] = [];

  const staleThreshold = 3;
  const satDropThreshold = 70;

  const latestSatisfaction =
    trend.length > 0 ? (trend[trend.length - 1]?.satisfaction_pct ?? 0) : 0;

  for (const source of syncItems) {
    if (
      source.freshness_days >= staleThreshold &&
      latestSatisfaction < satDropThreshold
    ) {
      events.push({
        source_name: source.source_name,
        freshness_days: source.freshness_days,
        satisfaction_at_time: latestSatisfaction,
      });
    }
  }

  return events;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}

function ChartTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div className="rounded-control border border-border bg-bg-surface px-3 py-2">
      <p className="text-xs font-medium text-text-primary">
        {formatDate(String(label))}
      </p>
      {payload.map((entry) => (
        <p
          key={entry.name}
          className="font-mono text-xs"
          style={{ color: entry.color }}
        >
          {entry.name}: {entry.value.toFixed(1)}
          {entry.name === "Satisfaction" ? "%" : " days"}
        </p>
      ))}
    </div>
  );
}

/**
 * FE-037: Root cause panel correlating sync freshness with satisfaction drops.
 *
 * Shows dual-axis chart (satisfaction % vs staleness days) and
 * lists correlated events where stale sync sources coincide with satisfaction drops.
 */
export function RootCausePanel() {
  const satisfaction = useSatisfactionData();
  const syncStatus = useSyncStatus();

  const isPending = satisfaction.isPending || syncStatus.isPending;
  const hasError = satisfaction.error ?? syncStatus.error;

  if (isPending) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <Skeleton className="mb-4 h-5 w-56" />
        <Skeleton className="h-[240px] w-full" />
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <h2 className="mb-2 text-[15px] font-semibold text-text-primary">
          Root Cause Analysis
        </h2>
        <p className="text-body-default text-alert">
          Failed to load correlation data
        </p>
      </div>
    );
  }

  const trend = satisfaction.data?.trend ?? [];
  const syncItems = syncStatus.data?.items ?? [];
  const mergedData = buildMergedData(trend, syncItems);
  const correlations = findCorrelations(trend, syncItems);

  const avgStaleness =
    syncItems.length > 0
      ? syncItems.reduce((sum, s) => sum + s.freshness_days, 0) /
        syncItems.length
      : 0;

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-6">
      <h2 className="mb-4 text-[15px] font-semibold text-text-primary">
        Root Cause Analysis
      </h2>

      {trend.length === 0 ? (
        <p className="text-body-default text-text-muted">
          Not enough data for correlation analysis
        </p>
      ) : (
        <>
          {/* Dual-axis chart */}
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={mergedData}>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--border-faint)"
                vertical={false}
              />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                tick={{ fill: "var(--text-faint)", fontSize: 11 }}
                axisLine={{ stroke: "var(--border)" }}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                yAxisId="left"
                domain={[0, 100]}
                tick={{ fill: "var(--text-faint)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => `${v}%`}
                width={42}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fill: "var(--text-faint)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => `${v}d`}
                width={36}
              />
              <Tooltip content={<ChartTooltip />} />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="satisfaction_pct"
                name="Satisfaction"
                stroke="#4FFFB0"
                strokeWidth={2}
                dot={false}
              />
              <Bar
                yAxisId="right"
                dataKey="max_staleness"
                name="Staleness"
                fill="rgba(255, 107, 53, 0.3)"
                barSize={6}
                radius={[2, 2, 0, 0]}
              />
            </ComposedChart>
          </ResponsiveContainer>

          {/* Correlation insight */}
          {avgStaleness > 0 && (
            <p className="mt-4 text-body-default text-text-muted">
              Documents become stale after{" "}
              <span className="font-mono text-text-primary">
                {avgStaleness.toFixed(1)}
              </span>{" "}
              days on average, which may cause satisfaction drops.
            </p>
          )}

          {/* Correlated events */}
          {correlations.length > 0 && (
            <div className="mt-4 space-y-2">
              <h3 className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
                Correlated Events
              </h3>
              {correlations.map((evt, i) => (
                <div
                  key={i}
                  className="rounded-control border border-alert/20 bg-alert-dim px-3 py-2 text-body-default text-text-muted"
                >
                  Sync for{" "}
                  <span className="font-medium text-text-primary">
                    {evt.source_name}
                  </span>{" "}
                  was{" "}
                  <span className="font-mono text-alert">
                    {evt.freshness_days}d stale
                  </span>{" "}
                  when satisfaction dropped to{" "}
                  <span className="font-mono text-warn">
                    {evt.satisfaction_at_time.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
