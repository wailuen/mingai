"use client";

import { cn } from "@/lib/utils";
import { useTenants } from "@/lib/hooks/usePlatformDashboard";

function PlanBadge({ plan }: { plan: string }) {
  const styles: Record<string, string> = {
    starter: "bg-bg-elevated text-text-faint",
    professional: "bg-warn-dim text-warn",
    enterprise: "bg-accent-dim text-accent",
  };

  return (
    <span
      className={cn(
        "rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        styles[plan] ?? "bg-bg-elevated text-text-faint",
      )}
    >
      {plan}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const isActive = status === "active";
  return (
    <span
      className={cn(
        "rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        isActive ? "bg-accent-dim text-accent" : "bg-alert-dim text-alert",
      )}
    >
      {status}
    </span>
  );
}

function SkeletonRow() {
  return (
    <tr className="border-b border-border-faint">
      <td className="px-3.5 py-3">
        <div className="h-4 w-32 animate-pulse rounded-badge bg-bg-elevated" />
      </td>
      <td className="px-3.5 py-3">
        <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
      </td>
      <td className="px-3.5 py-3">
        <div className="h-4 w-14 animate-pulse rounded-badge bg-bg-elevated" />
      </td>
    </tr>
  );
}

export function TenantHealthTable() {
  const { data, isPending, error } = useTenants(1, 10);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load tenants: {error.message}
      </p>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-section-heading text-text-primary">
          Tenant Overview
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Tenant
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Plan
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending &&
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)}

            {data && data.items.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="px-3.5 py-8 text-center text-sm text-text-faint"
                >
                  No tenants found
                </td>
              </tr>
            )}

            {data &&
              data.items.map((tenant) => (
                <tr
                  key={tenant.id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="px-3.5 py-3 text-[13px] font-medium text-text-primary">
                    {tenant.name}
                  </td>
                  <td className="px-3.5 py-3">
                    <PlanBadge plan={tenant.plan} />
                  </td>
                  <td className="px-3.5 py-3">
                    <StatusBadge status={tenant.status} />
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
