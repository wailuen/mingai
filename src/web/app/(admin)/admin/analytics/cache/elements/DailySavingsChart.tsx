"use client";

import {
  useDailyCostSavings,
  type CachePeriod,
} from "@/lib/hooks/useCacheAnalytics";
import { CHART_COLORS } from "@/lib/chartColors";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface DailySavingsChartProps {
  period: CachePeriod;
}

function ChartSkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 h-4 w-40 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="h-[260px] w-full animate-pulse rounded-control bg-bg-elevated" />
    </div>
  );
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

interface TooltipPayloadItem {
  value: number;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-control border border-border bg-bg-elevated px-3 py-2 text-xs">
      <p className="font-mono text-text-muted">{label}</p>
      <p className="mt-0.5 font-mono font-medium text-accent">
        ${payload[0].value.toFixed(2)}
      </p>
    </div>
  );
}

export function DailySavingsChart({ period }: DailySavingsChartProps) {
  const { data, isPending, error } = useDailyCostSavings(period);

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load daily savings: {error.message}
      </p>
    );
  }

  if (isPending) {
    return <ChartSkeleton />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-8 text-center">
        <p className="text-body-default text-text-faint">
          No daily savings data available for this period.
        </p>
      </div>
    );
  }

  const chartData = data.map((d) => ({
    date: formatDate(d.date),
    cost_saved_usd: d.cost_saved_usd,
  }));

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h2 className="mb-4 text-section-heading text-text-primary">
        Daily Cost Savings
      </h2>
      <div className="h-[260px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            margin={{ top: 4, right: 12, left: 4, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={CHART_COLORS.border}
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fill: CHART_COLORS.textFaint, fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: CHART_COLORS.border }}
            />
            <YAxis
              tick={{ fill: CHART_COLORS.textFaint, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `$${v}`}
            />
            <Tooltip content={<CustomTooltip />} />
            <Bar
              dataKey="cost_saved_usd"
              fill={CHART_COLORS.accent}
              radius={[3, 3, 0, 0]}
              maxBarSize={32}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
