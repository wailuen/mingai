"use client";

import { cn } from "@/lib/utils";
import { useAgentTemplateInstances } from "@/lib/hooks/useAgentTemplatesAdmin";

interface InstancesTabProps {
  templateId: string;
  currentVersionLabel?: string | null;
}

function StatusBadge({ status }: { status: "Active" | "Paused" | "Outdated" }) {
  const styles =
    status === "Active"
      ? "bg-accent-dim text-accent"
      : status === "Outdated"
        ? "bg-warn-dim text-warn"
        : "bg-bg-elevated text-text-muted";

  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        styles,
      )}
    >
      {status}
    </span>
  );
}

function formatRelative(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

export function InstancesTab({
  templateId,
  currentVersionLabel,
}: InstancesTabProps) {
  const { data, isPending, error } = useAgentTemplateInstances(templateId);
  const instances = data?.instances ?? [];

  if (isPending) {
    return (
      <div className="space-y-2 p-5">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-10 w-full animate-pulse rounded-card bg-bg-elevated"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p className="p-5 text-body-default text-alert">
        Failed to load instances: {error.message}
      </p>
    );
  }

  if (instances.length === 0) {
    return (
      <p className="p-5 text-body-default text-text-faint">
        No tenant deployments yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border bg-bg-elevated">
            <th className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Tenant
            </th>
            <th className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Version
            </th>
            <th className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Status
            </th>
            <th className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Last Active
            </th>
          </tr>
        </thead>
        <tbody>
          {instances.map((inst, i) => {
            const isOutdated =
              inst.status === "Active" &&
              currentVersionLabel &&
              inst.pinned_version &&
              inst.pinned_version !== currentVersionLabel;

            return (
              <tr
                key={i}
                className="border-b border-border-faint last:border-0"
              >
                <td className="px-4 py-3 text-body-default font-medium text-text-primary">
                  {inst.tenant_name}
                </td>
                <td className="px-4 py-3">
                  <span className="font-mono text-data-value text-text-muted">
                    {inst.pinned_version ?? "latest"}
                  </span>
                  {isOutdated && currentVersionLabel && (
                    <span className="ml-2 text-[11px] text-warn">
                      v{currentVersionLabel} available
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge
                    status={isOutdated ? "Outdated" : inst.status}
                  />
                </td>
                <td className="px-4 py-3">
                  <span className="font-mono text-data-value text-text-faint">
                    {formatRelative(inst.last_active_at)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
