"use client";

import { cn } from "@/lib/utils";
import type { CacheStats } from "@/lib/hooks/useCacheAnalytics";

interface CacheKPICardsProps {
  stats: CacheStats;
}

interface KPICardProps {
  label: string;
  value: string;
  suffix: string;
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
            colorClass ?? "text-text-primary",
          )}
        >
          {value}
        </span>
        <span className="font-mono text-xs text-text-muted">{suffix}</span>
      </p>
    </div>
  );
}

function getHitRateColor(pct: number): string {
  if (pct >= 80) return "text-accent";
  if (pct >= 50) return "text-warn";
  return "text-alert";
}

export function CacheKPICards({ stats }: CacheKPICardsProps) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KPICard
        label="Hit Rate"
        value={stats.hit_rate_pct.toFixed(1)}
        suffix="%"
        colorClass={getHitRateColor(stats.hit_rate_pct)}
      />
      <KPICard
        label="Miss Rate"
        value={stats.miss_rate_pct.toFixed(1)}
        suffix="%"
      />
      <KPICard
        label="Avg Hit Latency"
        value={stats.avg_hit_latency_ms.toFixed(1)}
        suffix="ms"
      />
      <KPICard
        label="Cache Size"
        value={stats.cache_size_mb.toFixed(1)}
        suffix="MB"
      />
    </div>
  );
}
