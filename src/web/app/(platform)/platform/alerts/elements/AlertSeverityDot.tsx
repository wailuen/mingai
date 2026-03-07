"use client";

import { cn } from "@/lib/utils";
import type { AlertSeverity } from "@/lib/hooks/usePlatformAlerts";

interface AlertSeverityDotProps {
  severity: AlertSeverity;
}

export function AlertSeverityDot({ severity }: AlertSeverityDotProps) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        (severity === "critical" || severity === "high") && "bg-alert",
        severity === "medium" && "bg-warn",
        severity === "low" && "border border-border bg-bg-elevated",
      )}
      title={severity}
    />
  );
}
