"use client";

import { cn } from "@/lib/utils";
import type { IssueSeverity } from "@/lib/hooks/usePlatformIssues";

interface IssueSeverityBadgeProps {
  severity: IssueSeverity;
}

const SEVERITY_STYLES: Record<IssueSeverity, string> = {
  P0: "bg-p0-dim text-p0 border-p0-ring",
  P1: "bg-alert-dim text-alert border-alert-ring",
  P2: "bg-warn-dim text-warn border-warn-ring",
  P3: "bg-bg-elevated text-text-muted border-border",
  P4: "bg-bg-elevated text-text-faint border-border-faint",
};

export function IssueSeverityBadge({ severity }: IssueSeverityBadgeProps) {
  return (
    <span
      className={cn(
        "inline-block rounded-control border px-2 py-0.5 font-mono text-data-value uppercase",
        SEVERITY_STYLES[severity],
      )}
    >
      {severity}
    </span>
  );
}
