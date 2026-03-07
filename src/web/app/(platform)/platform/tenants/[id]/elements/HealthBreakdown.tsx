"use client";

import { cn } from "@/lib/utils";
import {
  useTenantHealth,
  type TenantHealthResponse,
} from "@/lib/hooks/usePlatformDashboard";

interface HealthBreakdownProps {
  tenantId: string;
}

function scoreColor(score: number): string {
  if (score >= 70) return "text-accent";
  if (score >= 50) return "text-warn";
  return "text-alert";
}

function scoreBgColor(score: number): string {
  if (score >= 70) return "bg-accent-dim";
  if (score >= 50) return "bg-warn-dim";
  return "bg-alert-dim";
}

function categoryLabel(category: string): string {
  switch (category) {
    case "healthy":
      return "Healthy";
    case "warning":
      return "At Risk";
    case "critical":
      return "Critical";
    default:
      return category;
  }
}

interface ComponentCardProps {
  label: string;
  weightPct: number;
  score: number;
  description: string;
}

function ComponentCard({
  label,
  weightPct,
  score,
  description,
}: ComponentCardProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-4">
      <div className="flex items-center justify-between">
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          {label}
        </span>
        <span className="font-mono text-[11px] text-text-faint">
          {weightPct}% weight
        </span>
      </div>
      <p
        className={cn("mt-2 font-mono text-xl font-medium", scoreColor(score))}
      >
        {Math.round(score)}
      </p>
      <p className="mt-1 text-[12px] text-text-muted">{description}</p>
    </div>
  );
}

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
            <div className="mt-2 h-3 w-full animate-pulse rounded-badge bg-bg-elevated" />
          </div>
        ))}
      </div>
    </div>
  );
}

function componentDescription(
  key: string,
  details: Record<string, number>,
): string {
  switch (key) {
    case "usage_trend":
      return `${details.recent_queries ?? 0} queries (last 30d) vs ${details.prior_queries ?? 0} prior`;
    case "feature_breadth":
      return `${details.features_active ?? 0} of ${details.features_total ?? 5} core features active`;
    case "satisfaction":
      return `${details.positive_feedback ?? 0} positive of ${details.total_feedback ?? 0} feedback`;
    case "error_rate":
      return `${details.open_issues ?? 0} open issues (last 30d)`;
    default:
      return "";
  }
}

function componentLabel(key: string): string {
  switch (key) {
    case "usage_trend":
      return "Usage Trend";
    case "feature_breadth":
      return "Feature Breadth";
    case "satisfaction":
      return "Satisfaction";
    case "error_rate":
      return "Error Rate";
    default:
      return key;
  }
}

export function HealthBreakdown({ tenantId }: HealthBreakdownProps) {
  const { data, isPending, error } = useTenantHealth(tenantId);

  if (isPending) return <SkeletonCards />;

  if (error) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <p className="text-sm text-alert">
          Failed to load health data: {error.message}
        </p>
      </div>
    );
  }

  if (!data) return null;

  const overall = data as TenantHealthResponse;

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      {/* Overall score header */}
      <div className="mb-4 flex items-center gap-3">
        <span
          className={cn(
            "font-mono text-2xl font-bold",
            scoreColor(overall.overall_score),
          )}
        >
          {Math.round(overall.overall_score)}
        </span>
        <span
          className={cn(
            "rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
            scoreBgColor(overall.overall_score),
            scoreColor(overall.overall_score),
          )}
        >
          {categoryLabel(overall.category)}
        </span>
      </div>

      {/* Component breakdown cards */}
      <div className="grid grid-cols-2 gap-3">
        {Object.entries(overall.components).map(([key, comp]) => (
          <ComponentCard
            key={key}
            label={componentLabel(key)}
            weightPct={Math.round(comp.weight * 100)}
            score={comp.score}
            description={componentDescription(key, comp.details)}
          />
        ))}
      </div>
    </div>
  );
}
