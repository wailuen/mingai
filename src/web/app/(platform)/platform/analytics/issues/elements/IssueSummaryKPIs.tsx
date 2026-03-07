"use client";

import { AlertTriangle, Clock, CheckCircle2, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useIssueAnalyticsSummary,
  type AnalyticsPeriod,
} from "@/lib/hooks/useIssueAnalytics";

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------

interface KPICardProps {
  icon: React.ReactNode;
  value: string;
  label: string;
  valueClassName?: string;
  children?: React.ReactNode;
}

function KPICard({
  icon,
  value,
  label,
  valueClassName,
  children,
}: KPICardProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 text-text-faint">{icon}</div>
      <p
        className={cn(
          "font-mono text-[28px] font-semibold text-text-primary",
          valueClassName,
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-[11px] uppercase tracking-wider text-text-faint">
        {label}
      </p>
      {children}
    </div>
  );
}

function KPISkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 h-5 w-5 animate-pulse rounded-sm bg-bg-elevated" />
      <div className="h-8 w-28 animate-pulse rounded-sm bg-bg-elevated" />
      <div className="mt-2 h-3 w-20 animate-pulse rounded-sm bg-bg-elevated" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// SLA color logic
// ---------------------------------------------------------------------------

function slaColorClass(pct: number): string {
  if (pct >= 90) return "text-accent";
  if (pct >= 70) return "text-warn";
  return "text-alert";
}

// ---------------------------------------------------------------------------
// IssueSummaryKPIs
// ---------------------------------------------------------------------------

interface IssueSummaryKPIsProps {
  period: AnalyticsPeriod;
}

export function IssueSummaryKPIs({ period }: IssueSummaryKPIsProps) {
  const { data, isPending, error } = useIssueAnalyticsSummary(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load issue summary: {error.message}
      </p>
    );
  }

  if (isPending) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <KPISkeleton key={i} />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <KPICard
        icon={<BarChart3 size={20} />}
        value={data.total.toLocaleString()}
        label="Total Issues"
      >
        <div className="mt-2 flex items-center gap-2 text-xs">
          <span className="font-mono text-alert">{data.p0_count} P0</span>
          <span className="text-text-faint">/</span>
          <span className="font-mono text-warn">{data.p1_count} P1</span>
        </div>
      </KPICard>

      <KPICard
        icon={<AlertTriangle size={20} />}
        value={data.open.toLocaleString()}
        label="Open Issues"
        valueClassName={data.open > 0 ? "text-warn" : undefined}
      />

      <KPICard
        icon={<CheckCircle2 size={20} />}
        value={`${data.resolved_in_sla_pct.toFixed(1)}%`}
        label="SLA Resolution"
        valueClassName={slaColorClass(data.resolved_in_sla_pct)}
      />

      <KPICard
        icon={<Clock size={20} />}
        value={data.avg_resolution_hours.toFixed(1)}
        label="Avg Resolution (hrs)"
      />
    </div>
  );
}
