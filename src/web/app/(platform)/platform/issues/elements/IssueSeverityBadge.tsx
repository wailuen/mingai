"use client";

import { cn } from "@/lib/utils";
import type { IssueSeverity } from "@/lib/hooks/usePlatformIssues";

interface IssueSeverityBadgeProps {
  severity: IssueSeverity;
}

const SEVERITY_STYLES: Record<IssueSeverity, string> = {
  P0: "bg-[rgb(255,53,71,0.1)] text-[#FF3547] border-[rgb(255,53,71,0.3)]",
  P1: "bg-alert-dim text-alert border-alert-ring",
  P2: "bg-warn-dim text-warn border-warn-ring",
  P3: "bg-bg-elevated text-text-muted border-border",
  P4: "bg-bg-elevated text-text-faint border-border-faint",
};

export function IssueSeverityBadge({ severity }: IssueSeverityBadgeProps) {
  return (
    <span
      className={cn(
        "inline-block rounded-control border px-2 py-0.5 font-mono text-[11px] uppercase",
        SEVERITY_STYLES[severity],
      )}
    >
      {severity}
    </span>
  );
}
