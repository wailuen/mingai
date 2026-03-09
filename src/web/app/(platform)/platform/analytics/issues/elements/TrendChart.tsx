"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  useIssueTrend,
  type AnalyticsPeriod,
} from "@/lib/hooks/useIssueAnalytics";
import { Skeleton } from "@/components/shared/LoadingState";

// ---------------------------------------------------------------------------
// Severity line colors
// ---------------------------------------------------------------------------

const SEVERITY_LINE_COLORS: Record<string, string> = {
  p0: "#FF3547",
  p1: "#ff6b35",
  p2: "#f5c518",
  p3: "#4a5568",
  p4: "#2a3042",
};

// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

interface TrendTooltipEntry {
  name: string;
  value: number;
  color: string;
}

function TrendTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TrendTooltipEntry[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-card border border-border bg-bg-surface px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-mono text-text-primary">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="flex items-center gap-2 text-text-muted">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          {entry.name.toUpperCase()}:{" "}
          <span className="font-mono text-text-primary">{entry.value}</span>
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TrendChart
// ---------------------------------------------------------------------------

interface TrendChartProps {
  period: AnalyticsPeriod;
}

export function TrendChart({ period }: TrendChartProps) {
  const { data, isPending, error } = useIssueTrend(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load trend data: {error.message}
      </p>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-section-heading text-text-primary">
        Issue Trends
      </h2>

      {isPending ? (
        <div className="rounded-card border border-border bg-bg-surface p-5">
          <Skeleton className="h-[280px] w-full" />
        </div>
      ) : !data || data.length === 0 ? (
        <p className="text-sm text-text-faint">
          No trend data available for this period.
        </p>
      ) : (
        <div className="rounded-card border border-border bg-bg-surface p-5">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart
              data={data}
              margin={{ top: 8, right: 16, left: 0, bottom: 4 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#2a3042"
                vertical={false}
              />
              <XAxis
                dataKey="week"
                tick={{
                  fill: "#8892a4",
                  fontSize: 11,
                  fontFamily: "DM Mono, monospace",
                }}
                axisLine={{ stroke: "#2a3042" }}
                tickLine={false}
              />
              <YAxis
                tick={{
                  fill: "#8892a4",
                  fontSize: 12,
                  fontFamily: "DM Mono, monospace",
                }}
                axisLine={{ stroke: "#2a3042" }}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip content={<TrendTooltip />} />
              <Legend
                wrapperStyle={{
                  fontSize: 11,
                  fontFamily: "DM Mono, monospace",
                  color: "#8892a4",
                }}
              />
              {Object.entries(SEVERITY_LINE_COLORS).map(([key, color]) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  name={key.toUpperCase()}
                  stroke={color}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, stroke: color, fill: "#0c0e14" }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
