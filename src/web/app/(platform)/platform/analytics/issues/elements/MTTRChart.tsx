"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  useIssueMTTR,
  type AnalyticsPeriod,
} from "@/lib/hooks/useIssueAnalytics";
import { Skeleton } from "@/components/shared/LoadingState";
import { CHART_COLORS, severityColor } from "@/lib/chartColors";


// ---------------------------------------------------------------------------
// Custom tooltip
// ---------------------------------------------------------------------------

interface TooltipPayloadEntry {
  payload: {
    severity: string;
    avg_hours: number;
    median_hours: number;
    count: number;
  };
}

function MTTRTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-card border border-border bg-bg-surface px-3 py-2 text-xs shadow-md">
      <p className="font-mono font-medium text-text-primary">{d.severity}</p>
      <p className="mt-1 text-text-muted">
        Avg:{" "}
        <span className="font-mono text-text-primary">
          {d.avg_hours.toFixed(1)}h
        </span>
      </p>
      <p className="text-text-muted">
        Median:{" "}
        <span className="font-mono text-text-primary">
          {d.median_hours.toFixed(1)}h
        </span>
      </p>
      <p className="text-text-muted">
        Count: <span className="font-mono text-text-primary">{d.count}</span>
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MTTRChart
// ---------------------------------------------------------------------------

interface MTTRChartProps {
  period: AnalyticsPeriod;
}

export function MTTRChart({ period }: MTTRChartProps) {
  const { data, isPending, error } = useIssueMTTR(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load MTTR data: {error.message}
      </p>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-section-heading text-text-primary">
        Mean Time to Resolution
      </h2>

      {isPending ? (
        <div className="rounded-card border border-border bg-bg-surface p-5">
          <Skeleton className="h-[260px] w-full" />
        </div>
      ) : !data || data.length === 0 ? (
        <p className="text-sm text-text-faint">
          No MTTR data available for this period.
        </p>
      ) : (
        <div className="rounded-card border border-border bg-bg-surface p-5">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={data}
              margin={{ top: 8, right: 16, left: 0, bottom: 4 }}
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke={CHART_COLORS.border}
                vertical={false}
              />
              <XAxis
                dataKey="severity"
                tick={{
                  fill: CHART_COLORS.textMuted,
                  fontSize: 12,
                  fontFamily: "DM Mono, monospace",
                }}
                axisLine={{ stroke: CHART_COLORS.border }}
                tickLine={false}
              />
              <YAxis
                tick={{
                  fill: CHART_COLORS.textMuted,
                  fontSize: 12,
                  fontFamily: "DM Mono, monospace",
                }}
                axisLine={{ stroke: CHART_COLORS.border }}
                tickLine={false}
                label={{
                  value: "Hours",
                  angle: -90,
                  position: "insideLeft",
                  style: {
                    fill: CHART_COLORS.textFaint,
                    fontSize: 11,
                    fontFamily: "Plus Jakarta Sans, sans-serif",
                  },
                }}
              />
              <Tooltip
                content={<MTTRTooltip />}
                cursor={{ fill: "rgba(79, 255, 176, 0.04)" }}
              />
              <Bar dataKey="avg_hours" radius={[4, 4, 0, 0]} maxBarSize={48}>
                {data.map((entry) => (
                  <Cell
                    key={entry.severity}
                    fill={severityColor(entry.severity)}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
