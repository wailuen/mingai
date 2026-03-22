"use client";

import { cn } from "@/lib/utils";

interface TenantStatusBadgeProps {
  status: string;
}

const STATUS_STYLES: Record<string, string> = {
  active: "bg-accent-dim text-accent",
  suspended: "bg-alert-dim text-alert",
  provisioning: "bg-warn-dim text-warn",
};

export function TenantStatusBadge({ status }: TenantStatusBadgeProps) {
  const key = status.toLowerCase();
  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        STATUS_STYLES[key] ?? "bg-bg-elevated text-text-faint",
      )}
    >
      {status}
    </span>
  );
}

interface TenantPlanBadgeProps {
  plan: string;
}

const PLAN_STYLES: Record<string, string> = {
  starter: "bg-bg-elevated text-text-faint",
  professional: "bg-warn-dim text-warn",
  enterprise: "bg-accent-dim text-accent",
};

export function TenantPlanBadge({ plan }: TenantPlanBadgeProps) {
  const key = plan.toLowerCase();
  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        PLAN_STYLES[key] ?? "bg-bg-elevated text-text-faint",
      )}
    >
      {plan}
    </span>
  );
}
