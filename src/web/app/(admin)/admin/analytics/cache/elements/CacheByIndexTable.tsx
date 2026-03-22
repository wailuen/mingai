"use client";

import {
  useCacheByIndex,
  type CachePeriod,
} from "@/lib/hooks/useCacheAnalytics";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";

interface CacheByIndexTableProps {
  period: CachePeriod;
}

function getHitRateColor(pct: number): string {
  if (pct >= 70) return "text-accent";
  if (pct >= 50) return "text-warn";
  return "text-alert";
}

function TableSkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <div className="h-4 w-40 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex gap-4 border-b border-border-faint px-3.5 py-3"
        >
          <div className="h-4 w-40 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="ml-auto h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

export function CacheByIndexTable({ period }: CacheByIndexTableProps) {
  const { data, isPending, error } = useCacheByIndex(period);

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load index breakdown: {error.message}
      </p>
    );
  }

  if (isPending) {
    return <TableSkeleton />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-8 text-center">
        <p className="text-body-default text-text-faint">
          No per-index cache data available for this period.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-section-heading text-text-primary">
          Cache Performance by Index
        </h2>
      </div>
      <ScrollableTableWrapper
        maxHeight="none"
        className="rounded-none border-0"
      >
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-bg-surface">
            <tr className="border-b border-border">
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Index
              </th>
              <th className="px-3.5 py-2.5 text-right text-label-nav uppercase tracking-wider text-text-faint">
                Hit Rate
              </th>
              <th className="px-3.5 py-2.5 text-right text-label-nav uppercase tracking-wider text-text-faint">
                Cost Saved
              </th>
              <th className="px-3.5 py-2.5 text-right text-label-nav uppercase tracking-wider text-text-faint">
                Requests
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => {
              const hitPct = (row.hit_rate * 100).toFixed(1);
              return (
                <tr
                  key={row.index_id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="px-3.5 py-3 font-mono text-data-value text-text-primary">
                    {row.index_id}
                  </td>
                  <td
                    className={`px-3.5 py-3 text-right font-mono text-data-value ${getHitRateColor(row.hit_rate * 100)}`}
                  >
                    {hitPct}%
                  </td>
                  <td className="px-3.5 py-3 text-right font-mono text-data-value text-accent">
                    ${row.cost_saved_usd.toFixed(2)}
                  </td>
                  <td className="px-3.5 py-3 text-right font-mono text-data-value text-text-muted">
                    {row.total_requests.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollableTableWrapper>
    </div>
  );
}
