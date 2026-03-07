"use client";

import { cn } from "@/lib/utils";
import type { SafetyClass } from "@/lib/hooks/useToolCatalog";

interface SafetyClassificationBadgeProps {
  safetyClass: SafetyClass;
}

const SAFETY_STYLES: Record<SafetyClass, { className: string; label: string }> =
  {
    read_only: { className: "bg-accent-dim text-accent", label: "Read-Only" },
    write: { className: "bg-warn-dim text-warn", label: "Write" },
    destructive: {
      className: "bg-alert-dim text-alert",
      label: "Destructive",
    },
  };

export function SafetyClassificationBadge({
  safetyClass,
}: SafetyClassificationBadgeProps) {
  const style = SAFETY_STYLES[safetyClass];

  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        style.className,
      )}
    >
      {style.label}
    </span>
  );
}
