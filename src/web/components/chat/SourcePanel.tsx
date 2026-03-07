"use client";

import { X, ExternalLink } from "lucide-react";
import type { Source } from "@/lib/sse";
import { cn } from "@/lib/utils";

interface SourcePanelProps {
  sources: Source[];
  onClose: () => void;
}

/**
 * Slide-out panel showing RAG source documents.
 * Slides from right edge. 400px on desktop, full-width on mobile.
 */
export function SourcePanel({ sources, onClose }: SourcePanelProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-bg-deep/50 md:hidden"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed bottom-0 right-0 top-topbar-h z-50 w-full animate-slide-in-right border-l border-border bg-bg-surface md:w-[400px]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">Sources</h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="Close sources"
          >
            <X size={16} />
          </button>
        </div>

        {/* Source list */}
        <div className="flex-1 overflow-y-auto p-5">
          {sources.length === 0 ? (
            <p className="text-sm text-text-faint">No sources available.</p>
          ) : (
            <div className="space-y-3">
              {sources.map((source) => (
                <SourceCard key={source.id} source={source} />
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function SourceCard({ source }: { source: Source }) {
  const pct = Math.round(source.score * 100);
  const colorClass =
    source.score >= 0.8
      ? "bg-accent"
      : source.score >= 0.6
        ? "bg-warn"
        : "bg-alert";

  return (
    <div className="rounded-control border border-border bg-bg-elevated p-3">
      <div className="flex items-center justify-between">
        <a
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-sm font-medium text-text-primary transition-colors hover:text-accent"
        >
          {source.title}
          <ExternalLink size={12} />
        </a>
        <span className="font-mono text-xs text-accent">{pct}%</span>
      </div>

      {/* Score bar */}
      <div className="mt-2 h-1 rounded-full bg-bg-deep">
        <div
          className={cn("h-full rounded-full", colorClass)}
          style={{ width: `${pct}%` }}
        />
      </div>

      {source.excerpt && (
        <p className="mt-2 line-clamp-2 text-xs text-text-muted">
          {source.excerpt}
        </p>
      )}
    </div>
  );
}
