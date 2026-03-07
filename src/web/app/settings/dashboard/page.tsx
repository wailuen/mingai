"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import {
  Users,
  FileText,
  MessageSquare,
  ThumbsUp,
  type LucideIcon,
} from "lucide-react";
import { Skeleton } from "@/components/shared/LoadingState";

interface DashboardMetrics {
  active_users: number;
  documents_indexed: number;
  queries_today: number;
  satisfaction_score: number;
}

/**
 * FE-026: Tenant admin dashboard.
 * KPI cards: active users, documents indexed, queries today, satisfaction score.
 * Uses --accent for positive metrics, --warn for at-risk, --alert for errors.
 */
export default function TenantDashboardPage() {
  const { data: metrics, isLoading } = useQuery<DashboardMetrics>({
    queryKey: ["tenant-dashboard"],
    queryFn: () => apiRequest<DashboardMetrics>("/api/v1/admin/dashboard"),
  });

  return (
    <AppShell>
      <div className="p-7">
        <h1 className="mb-6 text-page-title text-text-primary">Dashboard</h1>

        <ErrorBoundary>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="rounded-card border border-border bg-bg-surface p-5"
                >
                  <Skeleton className="mb-3 h-3 w-24" />
                  <Skeleton className="h-7 w-16" />
                </div>
              ))
            ) : (
              <>
                <KPICard
                  icon={Users}
                  label="Active Users"
                  value={metrics?.active_users ?? 0}
                  color="accent"
                />
                <KPICard
                  icon={FileText}
                  label="Documents Indexed"
                  value={metrics?.documents_indexed ?? 0}
                  color="accent"
                />
                <KPICard
                  icon={MessageSquare}
                  label="Queries Today"
                  value={metrics?.queries_today ?? 0}
                  color="accent"
                />
                <KPICard
                  icon={ThumbsUp}
                  label="Satisfaction"
                  value={metrics?.satisfaction_score ?? 0}
                  suffix="%"
                  color={
                    (metrics?.satisfaction_score ?? 0) >= 80
                      ? "accent"
                      : (metrics?.satisfaction_score ?? 0) >= 70
                        ? "warn"
                        : "alert"
                  }
                />
              </>
            )}
          </div>
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}

function KPICard({
  icon: Icon,
  label,
  value,
  suffix = "",
  color,
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  suffix?: string;
  color: "accent" | "warn" | "alert";
}) {
  const colorMap = {
    accent: "text-accent",
    warn: "text-warn",
    alert: "text-alert",
  };

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 flex items-center gap-2">
        <Icon size={16} className="text-text-faint" />
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          {label}
        </span>
      </div>
      <span className={`font-mono text-2xl font-semibold ${colorMap[color]}`}>
        {value.toLocaleString()}
        {suffix}
      </span>
    </div>
  );
}
