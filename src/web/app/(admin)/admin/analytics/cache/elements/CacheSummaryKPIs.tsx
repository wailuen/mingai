"use client";

import { cn } from "@/lib/utils";
import type { CacheSummary } from "@/lib/hooks/useCacheAnalytics";

interface CacheSummaryKPIsProps {
  data: CacheSummary;
}

interface KPICardProps {
  label: string;
  value: string;
  suffix?: string;
  colorClass?: string;
}

function KPICard({ label, value, suffix, colorClass }: KPICardProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <p className="text-label-nav uppercase tracking-wider text-text-faint">
        {label}
      </p>
      <p className="mt-2 flex items-baseline gap-1">
        <span
          className={cn(
            "font-mono text-[22px] font-bold",
            colorClass ?? "text-text-primary"
          )}
        >
          {value}
        </span>
        {suffix && (
          <span className="font-mono text-xs text-text-muted">{suffix}</span>
        )}
      </p>
    </div>
  );
}

function getHitRateColor(pct: number): string {
  if (pct >= 70) return "text-accent";
  if (pct >= 50) return "text-warn";
  return "text-alert";
}

export function CacheSummaryKPIs({ data }: CacheSummaryKPIsProps) {
  const hitRatePct = (data.hit_rate * 100).toFixed(1);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KPICard
        label="Hit Rate"
        value={hitRatePct}
        suffix="%"
        colorClass={getHitRateColor(data.hit_rate * 100)}
      />
      <KPICard
        label="Total Requests"
        value={data.total_requests.toLocaleString()}
      />
      <KPICard
        label="Cost Saved"
        value={`$${data.cost_saved_usd.toFixed(2)}`}
        colorClass="text-accent"
      />
      <KPICard
        label="Hits / Misses"
        value={`${data.cache_hits.toLocaleString()} / ${data.cache_misses.toLocaleString()}`}
      />
    </div>
  );
}

export function CacheSummaryKPIsSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="rounded-card border border-border bg-bg-surface p-5"
        >
          <div className="h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="mt-3 h-7 w-24 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}
