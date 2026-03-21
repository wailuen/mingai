"use client";

import type { TopHitPattern } from "@/lib/hooks/useCacheAnalytics";

interface TopHitPatternsProps {
  patterns: TopHitPattern[];
}

function truncate(str: string, max: number): string {
  if (str.length <= max) return str;
  return str.slice(0, max) + "\u2026";
}

export function TopHitPatterns({ patterns }: TopHitPatternsProps) {
  const top10 = patterns.slice(0, 10);
  const totalCount = patterns.reduce((sum, p) => sum + p.count, 0);

  if (top10.length === 0) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-8 text-center">
        <p className="text-body-default text-text-faint">
          No cached query patterns recorded yet. Patterns will appear here as
          the cache starts serving repeated queries.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-section-heading text-text-primary">
          Top Hit Patterns
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Pattern
              </th>
              <th className="px-3.5 py-2.5 text-right text-label-nav uppercase tracking-wider text-text-faint">
                Hit Count
              </th>
              <th className="px-3.5 py-2.5 text-right text-label-nav uppercase tracking-wider text-text-faint">
                % of Total
              </th>
            </tr>
          </thead>
          <tbody>
            {top10.map((p) => {
              const pct = totalCount > 0 ? (p.count / totalCount) * 100 : 0;
              return (
                <tr
                  key={p.pattern}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td
                    className="px-3.5 py-3 text-body-default text-text-primary"
                    title={p.pattern}
                  >
                    {truncate(p.pattern, 60)}
                  </td>
                  <td className="px-3.5 py-3 text-right font-mono text-data-value text-text-muted">
                    {p.count.toLocaleString()}
                  </td>
                  <td className="px-3.5 py-3 text-right font-mono text-data-value text-text-muted">
                    {pct.toFixed(1)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
