"use client";

import { cn } from "@/lib/utils";
import type { CostPeriod } from "@/lib/hooks/useCostAnalytics";

interface PeriodSelectorProps {
  value: CostPeriod;
  onChange: (period: CostPeriod) => void;
}

const PERIODS: { value: CostPeriod; label: string }[] = [
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
  { value: "90d", label: "90 Days" },
];

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
  return (
    <div className="flex items-center border-b border-border">
      {PERIODS.map((period) => (
        <button
          key={period.value}
          type="button"
          onClick={() => onChange(period.value)}
          className={cn(
            "px-3.5 py-2 text-xs font-medium transition-colors border-b-2",
            value === period.value
              ? "border-b-accent text-text-primary"
              : "border-b-transparent text-text-faint hover:text-accent",
          )}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}
