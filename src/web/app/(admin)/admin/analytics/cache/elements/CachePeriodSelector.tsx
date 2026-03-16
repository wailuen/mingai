"use client";

import { cn } from "@/lib/utils";
import type { CachePeriod } from "@/lib/hooks/useCacheAnalytics";

interface CachePeriodSelectorProps {
  value: CachePeriod;
  onChange: (period: CachePeriod) => void;
}

const PERIODS: { value: CachePeriod; label: string }[] = [
  { value: "7d", label: "7 Days" },
  { value: "30d", label: "30 Days" },
  { value: "90d", label: "90 Days" },
];

export function CachePeriodSelector({
  value,
  onChange,
}: CachePeriodSelectorProps) {
  return (
    <div className="flex items-center border-b border-border">
      {PERIODS.map((period) => (
        <button
          key={period.value}
          type="button"
          onClick={() => onChange(period.value)}
          className={cn(
            "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
            value === period.value
              ? "border-b-accent text-text-primary"
              : "border-b-transparent text-text-faint hover:text-accent"
          )}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}
