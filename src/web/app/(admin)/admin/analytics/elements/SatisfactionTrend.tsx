"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { SatisfactionTrendPoint } from "@/lib/hooks/useAnalytics";

interface SatisfactionTrendProps {
  trend: SatisfactionTrendPoint[];
  isPending: boolean;
}

interface CustomTooltipPayloadEntry {
  payload: SatisfactionTrendPoint;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: CustomTooltipPayloadEntry[];
  label?: string;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const entry = payload[0]?.payload;
  if (!entry) return null;

  return (
    <div className="rounded-control border border-border bg-bg-surface px-3 py-2 shadow-lg">
      <p className="text-xs font-medium text-text-primary">
        {formatDate(String(label))}
      </p>
      <p className="font-mono text-sm text-accent">
        {entry.satisfaction_pct.toFixed(1)}%
      </p>
      <p className="text-xs text-text-faint">
        {entry.total} rating{entry.total !== 1 ? "s" : ""}
      </p>
    </div>
  );
}

/**
 * FE-037: 30-day area chart for satisfaction trend.
 *
 * Uses Recharts AreaChart with dark-theme-compatible styling.
 * Accent green (#4FFFB0) for stroke and dim fill.
 */
export function SatisfactionTrend({
  trend,
  isPending,
}: SatisfactionTrendProps) {
  if (isPending) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <div className="h-[280px] animate-pulse rounded bg-bg-elevated" />
      </div>
    );
  }

  if (trend.length === 0) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <h2 className="mb-3 text-[15px] font-semibold text-text-primary">
          Satisfaction Trend
        </h2>
        <p className="text-sm text-text-muted">No feedback data yet</p>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-6">
      <h2 className="mb-4 text-[15px] font-semibold text-text-primary">
        Satisfaction Trend (30 days)
      </h2>
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={trend}>
          <defs>
            <linearGradient id="satFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4FFFB0" stopOpacity={0.15} />
              <stop offset="100%" stopColor="#4FFFB0" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            tick={{ fill: "var(--text-faint)", fontSize: 11 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: "var(--text-faint)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${v}%`}
            width={42}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="satisfaction_pct"
            stroke="#4FFFB0"
            strokeWidth={2}
            fill="url(#satFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
