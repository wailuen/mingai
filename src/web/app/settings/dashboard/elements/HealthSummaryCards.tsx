"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { isPlatformAdmin } from "@/lib/auth";
import { Skeleton } from "@/components/shared/LoadingState";
import {
  Users,
  FileText,
  MessageSquare,
  ThumbsUp,
  Building2,
  TrendingUp,
  TrendingDown,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface TenantDashboardMetrics {
  active_users: number;
  active_users_trend?: number;
  documents_indexed: number;
  documents_indexed_trend?: number;
  queries_today: number;
  queries_today_trend?: number;
  satisfaction_pct: number | null;
  satisfaction_score_trend?: number;
}

interface PlatformStatsMetrics {
  total_tenants: number;
  active_tenants: number;
  total_users: number;
  queries_today: number;
}

function KPICardsSkeleton() {
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

/**
 * KPI cards — role-aware.
 * Platform Admin: total tenants, active tenants, total users, queries today
 *   via GET /api/v1/platform/stats
 * Tenant Admin: active users, documents indexed, queries today, satisfaction
 *   via GET /api/v1/admin/dashboard
 * DM Mono font for all numeric values.
 * Cards use 10px border radius (rounded-card).
 * One API call per component rule — role determines which endpoint.
 */
export function HealthSummaryCards() {
  const { claims } = useAuth();
  const isPA = claims ? isPlatformAdmin(claims) : false;

  const { data: taMetrics, isLoading: taLoading } =
    useQuery<TenantDashboardMetrics>({
      queryKey: ["tenant-dashboard"],
      queryFn: () =>
        apiGet<TenantDashboardMetrics>("/api/v1/admin/dashboard"),
      enabled: !isPA,
    });

  const { data: paMetrics, isLoading: paLoading } =
    useQuery<PlatformStatsMetrics>({
      queryKey: ["platform-stats"],
      queryFn: () =>
        apiGet<PlatformStatsMetrics>("/api/v1/platform/stats"),
      enabled: isPA,
    });

  const isLoading = isPA ? paLoading : taLoading;

  if (isLoading) {
    return <KPICardsSkeleton />;
  }

  if (isPA) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          icon={Building2}
          label="Total Tenants"
          value={paMetrics?.total_tenants ?? 0}
          trend={0}
          color="accent"
        />
        <KPICard
          icon={Building2}
          label="Active Tenants"
          value={paMetrics?.active_tenants ?? 0}
          trend={0}
          color="accent"
        />
        <KPICard
          icon={Users}
          label="Total Users"
          value={paMetrics?.total_users ?? 0}
          trend={0}
          color="accent"
        />
        <KPICard
          icon={MessageSquare}
          label="Queries Today"
          value={paMetrics?.queries_today ?? 0}
          trend={0}
          color="accent"
        />
      </div>
    );
  }

  const satPct = taMetrics?.satisfaction_pct;
  const hasRealSatisfaction = satPct !== null && satPct !== undefined;
  const satisfactionColor: "accent" | "warn" | "alert" | "muted" =
    !hasRealSatisfaction
      ? "muted"
      : satPct >= 80
        ? "accent"
        : satPct >= 70
          ? "warn"
          : "alert";

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KPICard
        icon={Users}
        label="Active Users"
        value={taMetrics?.active_users ?? 0}
        trend={taMetrics?.active_users_trend ?? 0}
        color="accent"
      />
      <KPICard
        icon={FileText}
        label="Documents Indexed"
        value={taMetrics?.documents_indexed ?? 0}
        trend={taMetrics?.documents_indexed_trend ?? 0}
        color="accent"
      />
      <KPICard
        icon={MessageSquare}
        label="Queries Today"
        value={taMetrics?.queries_today ?? 0}
        trend={taMetrics?.queries_today_trend ?? 0}
        color="accent"
      />
      <KPICard
        icon={ThumbsUp}
        label="Satisfaction"
        value={hasRealSatisfaction ? satPct : null}
        trend={taMetrics?.satisfaction_score_trend ?? 0}
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
  value: number | null;
  trend: number;
  suffix?: string;
  color: "accent" | "warn" | "alert" | "muted";
}) {
  const colorMap = {
    accent: "text-accent",
    warn: "text-warn",
    alert: "text-alert",
    muted: "text-text-muted",
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
        {value !== null ? `${value.toLocaleString()}${suffix}` : "\u2014"}
      </span>
      {value !== null && (
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
      )}
    </div>
  );
}
