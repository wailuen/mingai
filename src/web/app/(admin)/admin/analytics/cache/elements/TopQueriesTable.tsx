"use client";

import {
  useTopCachedQueries,
  type CachePeriod,
} from "@/lib/hooks/useCacheAnalytics";

interface TopQueriesTableProps {
  period: CachePeriod;
}

function TableSkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <div className="h-4 w-36 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex gap-4 border-b border-border-faint px-3.5 py-3"
        >
          <div className="h-4 w-48 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="ml-auto h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

export function TopQueriesTable({ period }: TopQueriesTableProps) {
  const { data, isPending, error } = useTopCachedQueries(period);

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load top queries: {error.message}
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
          No cached query patterns recorded yet.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-section-heading text-text-primary">
          Top Cached Queries
        </h2>
        <p className="mt-0.5 text-xs text-text-faint">
          Query hashes shown for privacy. Full queries are not stored.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Query Hash
              </th>
              <th className="px-3.5 py-2.5 text-right text-label-nav uppercase tracking-wider text-text-faint">
                Hit Count
              </th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr
                key={row.query_hash_prefix}
                className="border-b border-border-faint transition-colors hover:bg-accent-dim"
              >
                <td className="px-3.5 py-3 font-mono text-data-value text-text-primary">
                  {row.query_hash_prefix}
                </td>
                <td className="px-3.5 py-3 text-right font-mono text-data-value text-text-muted">
                  {row.hit_count.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
