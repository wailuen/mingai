"use client";

import { cn } from "@/lib/utils";
import {
  useIssuesByTenant,
  type AnalyticsPeriod,
} from "@/lib/hooks/useIssueAnalytics";
import { TableRowSkeleton } from "@/components/shared/LoadingState";

interface IssuesByTenantTableProps {
  period: AnalyticsPeriod;
}

export function IssuesByTenantTable({ period }: IssuesByTenantTableProps) {
  const { data: stats, isPending, error } = useIssuesByTenant(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load tenant issue stats: {error.message}
      </p>
    );
  }

  const sorted = stats ? [...stats].sort((a, b) => b.total - a.total) : [];

  return (
    <div>
      <h2 className="mb-3 text-section-heading text-text-primary">
        Issues by Tenant
      </h2>
      <div className="overflow-hidden rounded-card border border-border">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-bg-surface">
              <th className="px-3.5 py-3 text-left text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Tenant
              </th>
              <th className="px-3.5 py-3 text-right text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Total
              </th>
              <th className="px-3.5 py-3 text-right text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Open
              </th>
              <th className="px-3.5 py-3 text-right text-[11px] font-medium uppercase tracking-wider text-text-faint">
                P0 Count
              </th>
            </tr>
          </thead>
          <tbody>
            {isPending ? (
              Array.from({ length: 4 }).map((_, i) => (
                <TableRowSkeleton key={i} columns={4} />
              ))
            ) : sorted.length === 0 ? (
              <tr>
                <td
                  colSpan={4}
                  className="px-3.5 py-12 text-center text-sm text-text-faint"
                >
                  No tenant issue data available for this period.
                </td>
              </tr>
            ) : (
              sorted.map((stat) => (
                <tr
                  key={stat.tenant_name}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="px-3.5 py-3 text-sm font-medium text-text-primary">
                    {stat.tenant_name}
                  </td>
                  <td className="px-3.5 py-3 text-right font-mono text-sm text-text-primary">
                    {stat.total}
                  </td>
                  <td
                    className={cn(
                      "px-3.5 py-3 text-right font-mono text-sm",
                      stat.open > 0 ? "text-warn" : "text-text-muted",
                    )}
                  >
                    {stat.open}
                  </td>
                  <td
                    className={cn(
                      "px-3.5 py-3 text-right font-mono text-sm",
                      stat.p0_count > 0 ? "text-alert" : "text-text-muted",
                    )}
                  >
                    {stat.p0_count}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
