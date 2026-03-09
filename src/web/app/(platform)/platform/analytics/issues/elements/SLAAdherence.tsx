"use client";

import {
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  PolarAngleAxis,
} from "recharts";
import {
  useIssueSLA,
  type AnalyticsPeriod,
} from "@/lib/hooks/useIssueAnalytics";
import { Skeleton } from "@/components/shared/LoadingState";
import { CHART_COLORS, slaAdherenceColor } from "@/lib/chartColors";

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

function adherenceTextClass(pct: number): string {
  if (pct > 80) return "text-accent";
  if (pct >= 50) return "text-warn";
  return "text-alert";
}

// ---------------------------------------------------------------------------
// SLAAdherence
// ---------------------------------------------------------------------------

interface SLAAdherenceProps {
  period: AnalyticsPeriod;
}

export function SLAAdherence({ period }: SLAAdherenceProps) {
  const { data, isPending, error } = useIssueSLA(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load SLA data: {error.message}
      </p>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-section-heading text-text-primary">
        SLA Adherence
      </h2>

      {isPending ? (
        <div className="rounded-card border border-border bg-bg-surface p-5">
          <Skeleton className="mx-auto h-[220px] w-[220px] rounded-full" />
          <Skeleton className="mx-auto mt-4 h-4 w-32" />
        </div>
      ) : !data ? (
        <p className="text-sm text-text-faint">
          No SLA data available for this period.
        </p>
      ) : (
        <div className="rounded-card border border-border bg-bg-surface p-5">
          <div className="relative mx-auto w-fit">
            <ResponsiveContainer width={220} height={220}>
              <RadialBarChart
                cx="50%"
                cy="50%"
                innerRadius="70%"
                outerRadius="100%"
                startAngle={90}
                endAngle={-270}
                data={[
                  {
                    value: data.adherence_pct,
                    fill: slaAdherenceColor(data.adherence_pct),
                  },
                ]}
              >
                <PolarAngleAxis
                  type="number"
                  domain={[0, 100]}
                  angleAxisId={0}
                  tick={false}
                />
                <RadialBar
                  background={{ fill: CHART_COLORS.bgElevated }}
                  dataKey="value"
                  angleAxisId={0}
                  cornerRadius={8}
                />
              </RadialBarChart>
            </ResponsiveContainer>

            {/* Center label */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span
                className={`font-mono text-[32px] font-bold ${adherenceTextClass(data.adherence_pct)}`}
              >
                {data.adherence_pct.toFixed(1)}%
              </span>
              <span className="text-[11px] uppercase tracking-wider text-text-faint">
                In SLA
              </span>
            </div>
          </div>

          {/* Summary stats */}
          <div className="mt-5 grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="font-mono text-sm text-text-primary">
                {data.target_pct}%
              </p>
              <p className="mt-0.5 text-[11px] uppercase tracking-wider text-text-faint">
                Target
              </p>
            </div>
            <div>
              <p className="font-mono text-sm text-accent">
                {data.resolved_in_sla}
              </p>
              <p className="mt-0.5 text-[11px] uppercase tracking-wider text-text-faint">
                In SLA
              </p>
            </div>
            <div>
              <p className="font-mono text-sm text-alert">
                {data.resolved_out_sla}
              </p>
              <p className="mt-0.5 text-[11px] uppercase tracking-wider text-text-faint">
                Out of SLA
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
