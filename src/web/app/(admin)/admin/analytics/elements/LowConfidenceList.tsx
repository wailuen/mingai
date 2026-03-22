"use client";

import type { LowConfidenceItem } from "@/lib/hooks/useAnalytics";
import { ScrollableTableWrapper } from "@/components/shared/ScrollableTableWrapper";

interface LowConfidenceListProps {
  items: LowConfidenceItem[];
  isPending: boolean;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "...";
}

/**
 * FE-037: Table of low-confidence retrieval responses.
 *
 * Columns: Query text (truncated 80 chars), Confidence (mono, alert color), Date (mono, muted).
 * Admin table styling per design system.
 */
export function LowConfidenceList({
  items,
  isPending,
}: LowConfidenceListProps) {
  if (isPending) {
    return (
      <div className="rounded-card border border-border-faint bg-bg-surface p-6">
        <div className="h-8 w-64 animate-pulse rounded bg-bg-elevated" />
        <div className="mt-4 space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-10 animate-pulse rounded bg-bg-elevated"
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-card border border-border-faint bg-bg-surface p-6">
      <h2 className="mb-4 text-[15px] font-semibold text-text-primary">
        Low Confidence Responses
      </h2>

      {items.length === 0 ? (
        <p className="text-body-default text-text-muted">
          No low-confidence responses found. Your knowledge base is
          well-covered!
        </p>
      ) : (
        <ScrollableTableWrapper
          maxHeight="none"
          className="rounded-none border-0"
        >
          <table className="w-full text-left">
            <thead className="sticky top-0 z-10 bg-bg-surface">
              <tr className="border-b border-border">
                <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                  Query
                </th>
                <th className="pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint">
                  Confidence
                </th>
                <th className="hidden pb-2 text-[11px] font-medium uppercase tracking-[0.05em] text-text-faint sm:table-cell">
                  Date
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.message_id}
                  className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                >
                  <td className="py-3 pr-4 text-body-default font-medium text-text-primary">
                    {truncate(item.query_text, 80)}
                  </td>
                  <td className="py-3 pr-4 font-mono text-data-value text-alert">
                    {(item.retrieval_confidence * 100).toFixed(0)}%
                  </td>
                  <td className="hidden py-3 font-mono text-data-value text-text-muted sm:table-cell">
                    {formatDate(item.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollableTableWrapper>
      )}
    </div>
  );
}
