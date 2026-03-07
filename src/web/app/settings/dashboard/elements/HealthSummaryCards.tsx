"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { Skeleton } from "@/components/shared/LoadingState";
import {
  Users,
  FileText,
  MessageSquare,
  ThumbsUp,
  TrendingUp,
  TrendingDown,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface DashboardMetrics {
  active_users: number;
  active_users_trend?: number;
  documents_indexed: number;
  documents_indexed_trend?: number;
  queries_today: number;
  queries_today_trend?: number;
  satisfaction_pct: number;
  satisfaction_score_trend?: number;
}

/**
 * KPI cards: active users, documents indexed, queries today, satisfaction.
 * Each card shows value + trend indicator (up/down arrow with percentage).
 * DM Mono font for all numeric values.
 * Cards use 10px border radius (rounded-card).
 * One API call per component rule.
 */
export function HealthSummaryCards() {
  const { data: metrics, isLoading } = useQuery<DashboardMetrics>({
    queryKey: ["tenant-dashboard"],
    queryFn: () => apiGet<DashboardMetrics>("/api/v1/admin/dashboard"),
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="rounded-card border border-border bg-bg-surface p-5"
          >
            <Skeleton className="mb-3 h-3 w-24" />
            <Skeleton className="mb-2 h-7 w-16" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>
    );
  }

  const satisfactionColor =
    (metrics?.satisfaction_pct ?? 0) >= 80
      ? "accent"
      : (metrics?.satisfaction_pct ?? 0) >= 70
        ? "warn"
        : "alert";

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KPICard
        icon={Users}
        label="Active Users"
        value={metrics?.active_users ?? 0}
        trend={metrics?.active_users_trend ?? 0}
        color="accent"
      />
      <KPICard
        icon={FileText}
        label="Documents Indexed"
        value={metrics?.documents_indexed ?? 0}
        trend={metrics?.documents_indexed_trend ?? 0}
        color="accent"
      />
      <KPICard
        icon={MessageSquare}
        label="Queries Today"
        value={metrics?.queries_today ?? 0}
        trend={metrics?.queries_today_trend ?? 0}
        color="accent"
      />
      <KPICard
        icon={ThumbsUp}
        label="Satisfaction"
        value={metrics?.satisfaction_pct ?? 0}
        trend={metrics?.satisfaction_score_trend ?? 0}
        suffix="%"
        color={satisfactionColor}
      />
    </div>
  );
}

function KPICard({
  icon: Icon,
  label,
  value,
  trend,
  suffix = "",
  color,
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  trend: number;
  suffix?: string;
  color: "accent" | "warn" | "alert";
}) {
  const colorMap = {
    accent: "text-accent",
    warn: "text-warn",
    alert: "text-alert",
  };

  const trendPositive = trend >= 0;
  const TrendIcon = trendPositive ? TrendingUp : TrendingDown;

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 flex items-center gap-2">
        <Icon size={16} className="text-text-faint" />
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          {label}
        </span>
      </div>
      <span className={cn("font-mono text-2xl font-semibold", colorMap[color])}>
        {value.toLocaleString()}
        {suffix}
      </span>
      <div className="mt-2 flex items-center gap-1">
        <TrendIcon
          size={12}
          className={trendPositive ? "text-accent" : "text-alert"}
        />
        <span
          className={cn(
            "font-mono text-xs",
            trendPositive ? "text-accent" : "text-alert",
          )}
        >
          {trendPositive ? "+" : ""}
          {trend}%
        </span>
        <span className="text-xs text-text-faint">vs last 7 days</span>
      </div>
    </div>
  );
}
