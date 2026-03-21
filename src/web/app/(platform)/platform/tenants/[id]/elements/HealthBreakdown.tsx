"use client";

import { cn } from "@/lib/utils";
import {
  useTenantHealthDrilldown,
  type HealthCurrent,
  type HealthTrendPoint,
} from "@/lib/hooks/useHealthScores";
import { CHART_COLORS, healthScoreColor } from "@/lib/chartColors";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface HealthBreakdownProps {
  tenantId: string;
}

// ---------------------------------------------------------------------------
// Color helpers (Tailwind classes for text)
// ---------------------------------------------------------------------------

function scoreColorClass(score: number | null): string {
  if (score === null) return "text-text-faint";
  if (score >= 70) return "text-accent";
  if (score >= 50) return "text-warn";
  return "text-alert";
}

function scoreBgClass(score: number | null): string {
  if (score === null) return "bg-bg-elevated";
  if (score >= 70) return "bg-accent-dim";
  if (score >= 50) return "bg-warn-dim";
  return "bg-alert-dim";
}

// ---------------------------------------------------------------------------
// Component KPI card
// ---------------------------------------------------------------------------

interface ComponentCardProps {
  label: string;
  score: number | null;
}

function ComponentCard({ label, score }: ComponentCardProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-4">
      <span className="text-label-nav uppercase tracking-wider text-text-faint">
        {label}
      </span>
      <p
        className={cn(
          "mt-2 font-mono text-xl font-medium",
          scoreColorClass(score),
        )}
      >
        {score !== null ? Math.round(score) : "--"}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trend chart — 12-week composite line (300px wide)
// ---------------------------------------------------------------------------

function TrendChart({ trend }: { trend: HealthTrendPoint[] }) {
  if (trend.length === 0) {
    return (
      <p className="py-4 text-center text-body-default text-text-faint">
        No trend data available
      </p>
    );
  }

  // Backend returns newest-first; reverse for chronological display
  const points = [...trend].reverse();
  const lastValue = points[points.length - 1]?.composite;
  const lineColor = healthScoreColor(lastValue ?? null);

  return (
    <div className="mt-4">
      <span className="text-label-nav uppercase tracking-wider text-text-faint">
        12-Week Trend
      </span>
      <div className="mt-2">
        <ResponsiveContainer width="100%" height={120}>
          <LineChart
            data={points}
            margin={{ top: 4, right: 8, bottom: 4, left: 8 }}
          >
            <XAxis
              dataKey="week"
              tick={{ fontSize: 10, fill: CHART_COLORS.textFaint }}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: CHART_COLORS.textFaint }}
              tickLine={false}
              axisLine={false}
              width={28}
            />
            <Tooltip
              contentStyle={{
                background: CHART_COLORS.bgSurface,
                border: `1px solid ${CHART_COLORS.border}`,
                borderRadius: 7,
                fontSize: 12,
                fontFamily: "DM Mono, monospace",
              }}
              labelStyle={{ color: CHART_COLORS.textMuted }}
            />
            <Line
              type="monotone"
              dataKey="composite"
              stroke={lineColor}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function SkeletonCards() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 flex items-center gap-3">
        <div className="h-6 w-24 animate-pulse rounded-badge bg-bg-elevated" />
        <div className="h-5 w-16 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="rounded-card border border-border-faint bg-bg-surface p-4"
          >
            <div className="h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
            <div className="mt-3 h-6 w-10 animate-pulse rounded-badge bg-bg-elevated" />
          </div>
        ))}
      </div>
      <div className="mt-4 h-[120px] animate-pulse rounded-badge bg-bg-elevated" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// HealthBreakdown — wired to PA-009 drilldown
// ---------------------------------------------------------------------------

export function HealthBreakdown({ tenantId }: HealthBreakdownProps) {
  const { data, isPending, error } = useTenantHealthDrilldown(tenantId);

  if (isPending) return <SkeletonCards />;

  if (error) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <p className="text-body-default text-alert">
          Failed to load health data: {error.message}
        </p>
      </div>
    );
  }

  if (!data) return null;

  const { current, trend } = data;

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      {/* Overall composite score header */}
      <div className="mb-4 flex items-center gap-3">
        <span
          className={cn(
            "font-mono text-2xl font-bold",
            scoreColorClass(current.composite),
          )}
        >
          {current.composite !== null ? Math.round(current.composite) : "--"}
        </span>

        {current.at_risk_flag && (
          <span className="rounded-badge bg-alert-dim px-2 py-0.5 font-mono text-[10px] uppercase text-alert">
            At Risk
          </span>
        )}

        {!current.at_risk_flag && current.composite !== null && (
          <span
            className={cn(
              "rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
              scoreBgClass(current.composite),
              scoreColorClass(current.composite),
            )}
          >
            {current.composite >= 70 ? "Healthy" : "Warning"}
          </span>
        )}
      </div>

      {/* Component breakdown: 4 mini KPI cards */}
      <div className="grid grid-cols-2 gap-3">
        <ComponentCard label="Usage Trend" score={current.usage_trend} />
        <ComponentCard
          label="Feature Breadth"
          score={current.feature_breadth}
        />
        <ComponentCard label="Satisfaction" score={current.satisfaction} />
        <ComponentCard label="Error Rate" score={current.error_rate} />
      </div>

      {/* 12-week trend chart */}
      <TrendChart trend={trend} />
    </div>
  );
}
