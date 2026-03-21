"use client";

import { Users, FileText, MessageSquare, ThumbsUp } from "lucide-react";
import { useDashboardStats } from "@/lib/hooks/usePlatformDashboard";

interface KPICardProps {
  icon: React.ReactNode;
  value: string;
  label: string;
}

function KPICard({ icon, value, label }: KPICardProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 text-text-faint">{icon}</div>
      <p className="font-mono text-[28px] font-semibold text-text-primary">
        {value}
      </p>
      <p className="mt-1 text-[11px] uppercase tracking-wider text-text-faint">
        {label}
      </p>
    </div>
  );
}

function KPICardSkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 h-5 w-5 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="h-8 w-24 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="mt-2 h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
    </div>
  );
}

function formatNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function PlatformKPICards() {
  const { data, isPending, error } = useDashboardStats();

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load dashboard stats: {error.message}
      </p>
    );
  }

  if (isPending) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <KPICardSkeleton key={i} />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <KPICard
        icon={<Users size={20} />}
        value={formatNumber(data.active_users)}
        label="Active Users"
      />
      <KPICard
        icon={<FileText size={20} />}
        value={formatNumber(data.documents_indexed)}
        label="Documents Indexed"
      />
      <KPICard
        icon={<MessageSquare size={20} />}
        value={formatNumber(data.queries_today)}
        label="Queries Today"
      />
      <KPICard
        icon={<ThumbsUp size={20} />}
        value={`${data.satisfaction_pct.toFixed(1)}%`}
        label="Satisfaction"
      />
    </div>
  );
}
