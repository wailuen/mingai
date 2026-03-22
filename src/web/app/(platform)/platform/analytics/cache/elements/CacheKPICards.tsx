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
  // API returns stats.overall.hit_rate (0–1 fraction) — convert to percentage for display.
  const overall = stats.overall ?? {
    hit_rate: 0,
    hits: 0,
    misses: 0,
    estimated_cost_saved_usd: 0,
  };
  const hitRatePct = (overall.hit_rate ?? 0) * 100;
  const total = (overall.hits ?? 0) + (overall.misses ?? 0);
  const missRatePct = total > 0 ? ((overall.misses ?? 0) / total) * 100 : 0;
  const costSaved = overall.estimated_cost_saved_usd ?? 0;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KPICard
        label="Hit Rate"
        value={hitRatePct.toFixed(1)}
        suffix="%"
        colorClass={getHitRateColor(hitRatePct)}
      />
      <KPICard label="Miss Rate" value={missRatePct.toFixed(1)} suffix="%" />
      <KPICard
        label="Total Hits"
        value={(overall.hits ?? 0).toLocaleString()}
        suffix="hits"
      />
      <KPICard
        label="Est. Cost Saved"
        value={`$${costSaved.toFixed(4)}`}
        suffix=""
      />
    </div>
  );
}
