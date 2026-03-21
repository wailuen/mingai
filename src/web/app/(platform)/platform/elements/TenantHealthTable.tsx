"use client";

import { cn } from "@/lib/utils";
import {
  useAtRiskTenants,
  useTenantHealthDrilldown,
  type AtRiskTenant,
} from "@/lib/hooks/useHealthScores";
import { healthScoreColor } from "@/lib/chartColors";
import { LineChart, Line } from "recharts";

// ---------------------------------------------------------------------------
// Health score badge — color-coded by threshold
// ---------------------------------------------------------------------------

function HealthScoreBadge({ score }: { score: number | null }) {
  if (score === null) {
    return <span className="font-mono text-data-value text-text-faint">--</span>;
  }

  const colorClass =
    score >= 70 ? "text-accent" : score >= 50 ? "text-warn" : "text-alert";

  return (
    <span className={cn("font-mono text-data-value font-medium", colorClass)}>
      {Math.round(score)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// At-risk reason badge
// ---------------------------------------------------------------------------

function ReasonBadge({ reason }: { reason: string | null }) {
  if (!reason) return null;

  const labels: Record<string, string> = {
    composite_low: "Low Score",
    satisfaction_declining: "Satisfaction Drop",
    usage_trending_down: "Usage Decline",
  };

  return (
    <span className="rounded-badge bg-alert-dim px-2 py-0.5 font-mono text-[10px] uppercase text-alert">
      {labels[reason] ?? reason}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Mini sparkline — 12-week composite trend per row
//
// NOTE: Each row fires one GET /platform/tenants/{id}/health request.
// This is intentional (React Query caches results for the detail panel)
// but produces N concurrent requests when the at-risk list is rendered.
// Acceptable because: (a) at-risk lists are expected to remain small
// (< 20 tenants), and (b) the same cached data is reused by HealthBreakdown.
// If the list grows large, consider embedding trend in the PA-008 response.
// ---------------------------------------------------------------------------

function TrendSparkline({ tenantId }: { tenantId: string }) {
  const { data } = useTenantHealthDrilldown(tenantId);

  if (!data || data.trend.length === 0) {
    return <div className="h-6 w-[60px]" />;
  }

  // Trend comes newest-first from backend; reverse for left-to-right display
  const points = [...data.trend].reverse();
  const lastValue = points[points.length - 1]?.composite;
  const lineColor = healthScoreColor(lastValue ?? null);

  return (
    <LineChart
      width={60}
      height={24}
      data={points}
      margin={{ top: 2, right: 2, bottom: 2, left: 2 }}
    >
      <Line
        type="monotone"
        dataKey="composite"
        stroke={lineColor}
        strokeWidth={1.5}
        dot={false}
        connectNulls
      />
    </LineChart>
  );
}

// ---------------------------------------------------------------------------
// Skeleton rows
// ---------------------------------------------------------------------------

function SkeletonRow() {
  return (
    <tr className="border-b border-border-faint">
      <td className="px-3.5 py-3">
        <div className="h-4 w-32 animate-pulse rounded-badge bg-bg-elevated" />
      </td>
      <td className="px-3.5 py-3">
        <div className="h-4 w-10 animate-pulse rounded-badge bg-bg-elevated" />
      </td>
      <td className="px-3.5 py-3">
        <div className="h-4 w-[60px] animate-pulse rounded-badge bg-bg-elevated" />
      </td>
      <td className="px-3.5 py-3">
        <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
      </td>
      <td className="px-3.5 py-3">
        <div className="h-4 w-14 animate-pulse rounded-badge bg-bg-elevated" />
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Table row
// ---------------------------------------------------------------------------

function TenantRow({ tenant }: { tenant: AtRiskTenant }) {
  return (
    <tr className="border-b border-border-faint transition-colors hover:bg-accent-dim">
      <td className="px-3.5 py-3 text-body-default font-medium text-text-primary">
        {tenant.name}
      </td>
      <td className="px-3.5 py-3">
        <HealthScoreBadge score={tenant.composite_score} />
      </td>
      <td className="px-3.5 py-3">
        <TrendSparkline tenantId={tenant.tenant_id} />
      </td>
      <td className="px-3.5 py-3">
        <span className="font-mono text-data-value text-text-muted">
          {tenant.weeks_at_risk} {tenant.weeks_at_risk === 1 ? "week" : "weeks"}
        </span>
      </td>
      <td className="px-3.5 py-3">
        <ReasonBadge reason={tenant.at_risk_reason} />
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// TenantHealthTable — wired to GET /api/v1/platform/tenants/at-risk
// ---------------------------------------------------------------------------

export function TenantHealthTable() {
  const { data, isPending, error } = useAtRiskTenants();

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load at-risk tenants: {error.message}
      </p>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-section-heading text-text-primary">
          At-Risk Tenants
        </h2>
        {/* at_risk_flag is set by 3 rules: composite < 40, OR satisfaction
            declining 2+ consecutive weeks, OR composite declining 3+ weeks.
            A tenant can appear here with composite 41-69 if rules 2 or 3 fired. */}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Tenant
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Score
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Trend
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Duration
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Reason
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending &&
              Array.from({ length: 3 }).map((_, i) => <SkeletonRow key={i} />)}

            {data && data.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="px-3.5 py-8 text-center text-body-default text-text-faint"
                >
                  No at-risk tenants
                </td>
              </tr>
            )}

            {data &&
              data.map((tenant) => (
                <TenantRow key={tenant.tenant_id} tenant={tenant} />
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
