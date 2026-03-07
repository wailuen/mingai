"use client";

import {
  TenantStatusBadge,
  TenantPlanBadge,
} from "../../elements/TenantStatusBadge";

interface TenantHeaderProps {
  name: string;
  status: string;
  plan: string;
  primaryContactEmail: string;
  createdAt: string;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

export function TenantHeader({
  name,
  status,
  plan,
  primaryContactEmail,
  createdAt,
}: TenantHeaderProps) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[22px] font-bold text-text-primary">{name}</h1>
        <TenantStatusBadge status={status} />
        <TenantPlanBadge plan={plan} />
      </div>
      <p className="mt-1.5 text-sm text-text-muted">
        <span className="font-mono">{primaryContactEmail}</span>
        <span className="mx-2 text-text-faint">&middot;</span>
        <span className="font-mono">Created {formatDate(createdAt)}</span>
      </p>
    </div>
  );
}
