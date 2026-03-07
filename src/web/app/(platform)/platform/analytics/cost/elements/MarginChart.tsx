"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  useMarginTrend,
  type CostPeriod,
  type MarginPoint,
} from "@/lib/hooks/useCostAnalytics";

function formatDateLabel(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ value: number; payload: MarginPoint }>;
  label?: string;
}

function ChartTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div className="rounded-card border border-border bg-bg-surface px-3 py-2 shadow-md">
      <p className="text-[11px] text-text-faint">
        {label ? formatDateLabel(label) : ""}
      </p>
      <p className="font-mono text-sm font-medium text-text-primary">
        {payload[0].value.toFixed(1)}%
      </p>
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="flex h-[300px] items-center justify-center rounded-card border border-border bg-bg-surface">
      <div className="h-48 w-full mx-6 animate-pulse rounded-card bg-bg-elevated" />
    </div>
  );
}

interface MarginChartProps {
  period: CostPeriod;
}

export function MarginChart({ period }: MarginChartProps) {
  const { data, isPending, error } = useMarginTrend(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load margin trend: {error.message}
      </p>
    );
  }

  if (isPending) {
    return <ChartSkeleton />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center rounded-card border border-border bg-bg-surface">
        <p className="text-sm text-text-faint">
          No margin data available for this period
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h3 className="mb-4 text-section-heading text-text-primary">
        Margin Trend
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={data}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border)"
            vertical={false}
          />
          <XAxis
            dataKey="date"
            tickFormatter={formatDateLabel}
            tick={{ fill: "var(--text-faint)", fontSize: 11 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
          />
          <YAxis
            tickFormatter={(v: number) => `${v}%`}
            tick={{ fill: "var(--text-faint)", fontSize: 11 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
            domain={[0, 100]}
          />
          <Tooltip content={<ChartTooltip />} />
          <Area
            type="monotone"
            dataKey="margin_pct"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="var(--accent-dim)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
