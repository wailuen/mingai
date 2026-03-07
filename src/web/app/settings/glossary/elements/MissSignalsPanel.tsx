"use client";

import { useMissSignals, type MissSignal } from "@/lib/hooks/useGlossary";
import { Loader2 } from "lucide-react";

interface MissSignalsPanelProps {
  onAddTerm: (term: string) => void;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function MissSignalRow({
  signal,
  onAdd,
}: {
  signal: MissSignal;
  onAdd: () => void;
}) {
  return (
    <tr className="border-b border-border-faint transition-colors hover:bg-accent-dim">
      <td className="px-3.5 py-3 font-mono text-sm text-text-primary">
        {signal.term}
      </td>
      <td className="px-3.5 py-3 font-mono text-sm text-accent">
        {signal.occurrence_count}
      </td>
      <td className="px-3.5 py-3 font-mono text-xs text-text-muted">
        {formatDate(signal.last_seen)}
      </td>
      <td className="px-3.5 py-3">
        <button
          onClick={onAdd}
          className="text-xs text-accent transition-colors hover:underline"
        >
          Add to Glossary
        </button>
      </td>
    </tr>
  );
}

export function MissSignalsPanel({ onAddTerm }: MissSignalsPanelProps) {
  const { data, isLoading } = useMissSignals();

  const items = data?.items ?? [];

  return (
    <div className="mt-6 rounded-card border border-border bg-bg-surface p-5">
      {/* Header */}
      <div className="mb-4">
        <h2 className="text-[15px] font-semibold text-text-primary">
          Miss Signals
        </h2>
        <p className="mt-0.5 text-[11px] uppercase tracking-wider text-text-muted">
          Terms appearing in queries but not covered by glossary
        </p>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-text-faint" />
        </div>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-faint">
          No miss signals yet. Come back after your first conversations.
        </p>
      ) : (
        <div className="overflow-hidden rounded-card border border-border">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3.5 py-3 text-left text-[11px] uppercase tracking-wider text-text-faint">
                  Term
                </th>
                <th className="px-3.5 py-3 text-left text-[11px] uppercase tracking-wider text-text-faint">
                  Occurrences
                </th>
                <th className="px-3.5 py-3 text-left text-[11px] uppercase tracking-wider text-text-faint">
                  Last Seen
                </th>
                <th className="px-3.5 py-3 text-left text-[11px] uppercase tracking-wider text-text-faint">
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((signal) => (
                <MissSignalRow
                  key={signal.term}
                  signal={signal}
                  onAdd={() => onAddTerm(signal.term)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
