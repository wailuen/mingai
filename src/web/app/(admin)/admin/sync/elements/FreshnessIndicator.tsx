"use client";

import { cn } from "@/lib/utils";

interface FreshnessIndicatorProps {
  lastSyncAt: string | null;
  className?: string;
}

function getFreshness(lastSyncAt: string | null): {
  label: string;
  colorClass: string;
} {
  if (lastSyncAt === null) {
    return { label: "Never synced", colorClass: "text-alert" };
  }

  const now = Date.now();
  const syncTime = new Date(lastSyncAt).getTime();
  const hoursAgo = (now - syncTime) / (1000 * 60 * 60);

  if (hoursAgo < 24) {
    return { label: "Fresh", colorClass: "text-accent" };
  }
  if (hoursAgo < 72) {
    return { label: "Stale", colorClass: "text-warn" };
  }
  return { label: "Outdated", colorClass: "text-alert" };
}

export function FreshnessIndicator({
  lastSyncAt,
  className,
}: FreshnessIndicatorProps) {
  const { label, colorClass } = getFreshness(lastSyncAt);

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn(
          "inline-block h-2 w-2 rounded-full bg-current",
          colorClass,
        )}
        aria-hidden="true"
      />
      <span className={cn("text-xs font-medium", colorClass)}>{label}</span>
    </span>
  );
}
