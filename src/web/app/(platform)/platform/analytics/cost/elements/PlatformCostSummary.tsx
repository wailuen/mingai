"use client";

import { DollarSign, Server, TrendingUp, Percent } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  usePlatformCostSummary,
  type CostPeriod,
} from "@/lib/hooks/useCostAnalytics";

interface CostKPICardProps {
  icon: React.ReactNode;
  value: string;
  label: string;
  sublabel?: string;
  valueClassName?: string;
}

function CostKPICard({
  icon,
  value,
  label,
  sublabel,
  valueClassName,
}: CostKPICardProps) {
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
      {sublabel && (
        <p className="mt-0.5 text-[10px] text-text-faint">{sublabel}</p>
      )}
    </div>
  );
}

function CostKPISkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-3 h-5 w-5 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="h-8 w-28 animate-pulse rounded-badge bg-bg-elevated" />
      <div className="mt-2 h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
    </div>
  );
}

function formatDollar(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function marginColorClass(pct: number): string {
  if (pct >= 50) return "text-accent";
  if (pct >= 20) return "text-warn";
  return "text-alert";
}

interface PlatformCostSummaryProps {
  period: CostPeriod;
}

export function PlatformCostSummary({ period }: PlatformCostSummaryProps) {
  const { data, isPending, error } = usePlatformCostSummary(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load cost summary: {error.message}
      </p>
    );
  }

  if (isPending) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <CostKPISkeleton key={i} />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <CostKPICard
        icon={<DollarSign size={20} />}
        value={formatDollar(data.total_llm_cost)}
        label="Total LLM Cost"
      />
      <CostKPICard
        icon={<Server size={20} />}
        value={formatDollar(data.total_infra_cost)}
        label="Total Infra Cost"
        sublabel="estimated"
      />
      <CostKPICard
        icon={<TrendingUp size={20} />}
        value={formatDollar(data.total_revenue)}
        label="Total Revenue"
      />
      <CostKPICard
        icon={<Percent size={20} />}
        value={`${data.gross_margin_pct.toFixed(1)}%`}
        label="Gross Margin"
        valueClassName={marginColorClass(data.gross_margin_pct)}
      />
    </div>
  );
}
