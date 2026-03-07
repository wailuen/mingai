"use client";

import { cn } from "@/lib/utils";
import { useTenantQuota } from "@/lib/hooks/usePlatformDashboard";

interface QuotaUsageBarProps {
  tenantId: string;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function usageColor(pct: number): string {
  if (pct >= 90) return "bg-alert";
  if (pct >= 70) return "bg-warn";
  return "bg-accent";
}

function usageTextColor(pct: number): string {
  if (pct >= 90) return "text-alert";
  if (pct >= 70) return "text-warn";
  return "text-accent";
}

function SkeletonBar() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="mt-3 h-5 w-32 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="mt-3 h-2 w-full animate-pulse rounded-full bg-bg-elevated" />
    </div>
  );
}

interface SingleBarProps {
  label: string;
  used: number;
  limit: number;
  formatFn?: (n: number) => string;
  suffix?: string;
}

function SingleBar({
  label,
  used,
  limit,
  formatFn = formatNumber,
  suffix = "",
}: SingleBarProps) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;

  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-label-nav uppercase tracking-wider text-text-faint">
          {label}
        </span>
        <span className={cn("font-mono text-sm", usageTextColor(pct))}>
          {pct.toFixed(1)}%
        </span>
      </div>
      <p className="mt-1 font-mono text-sm text-text-muted">
        {formatFn(used)}
        {suffix} / {formatFn(limit)}
        {suffix}
      </p>
      <div className="mt-2 h-2 w-full rounded-full bg-bg-elevated">
        <div
          className={cn("h-2 rounded-full transition-all", usageColor(pct))}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function QuotaUsageBar({ tenantId }: QuotaUsageBarProps) {
  const { data, isPending, error } = useTenantQuota(tenantId);

  if (isPending) return <SkeletonBar />;

  if (error) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <p className="text-sm text-alert">
          Failed to load quota data: {error.message}
        </p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h3 className="mb-4 text-section-heading font-semibold text-text-primary">
        Quota Usage
      </h3>
      <div className="space-y-5">
        <SingleBar
          label="Token Quota"
          used={data.tokens.used}
          limit={data.tokens.limit}
        />
        <SingleBar
          label="Users"
          used={data.users.used}
          limit={data.users.limit}
          formatFn={(n) => n.toString()}
        />
      </div>
    </div>
  );
}
