"use client";

import { cn } from "@/lib/utils";
import { type RegistryStatus } from "@/lib/hooks/useTenantRegistry";

interface RegistryStatusBadgeProps {
  status: RegistryStatus;
}

const STATUS_STYLES: Record<RegistryStatus, string> = {
  published: "bg-accent-dim text-accent border-accent/30",
  pending_review: "bg-warn-dim text-warn border-warn/30",
  draft: "bg-bg-elevated text-text-muted border-border",
};

const STATUS_LABELS: Record<RegistryStatus, string> = {
  published: "Published",
  pending_review: "Pending Review",
  draft: "Draft",
};

/**
 * FE-050: Status badge for registry agent status.
 */
export function RegistryStatusBadge({ status }: RegistryStatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-block rounded-badge border px-2 py-0.5 font-mono text-[10px] uppercase",
        STATUS_STYLES[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}
