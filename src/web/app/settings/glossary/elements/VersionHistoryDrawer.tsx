"use client";

import { useState } from "react";
import { X, RotateCcw, Loader2 } from "lucide-react";
import { Skeleton } from "@/components/shared/LoadingState";
import {
  useVersionHistory,
  useRollbackTerm,
  type VersionEntry,
} from "@/lib/hooks/useGlossary";

interface VersionHistoryDrawerProps {
  termId: string | null;
  termName: string;
  isOpen: boolean;
  onClose: () => void;
}

function formatTimestamp(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * FE-033: Slide-in drawer showing per-term edit history with rollback.
 * Slides from right, full height, 420px wide.
 */
export function VersionHistoryDrawer({
  termId,
  termName,
  isOpen,
  onClose,
}: VersionHistoryDrawerProps) {
  const { data, isLoading } = useVersionHistory(termId);
  const rollbackMutation = useRollbackTerm();
  const [rollbackingVersionId, setRollbackingVersionId] = useState<
    string | null
  >(null);

  if (!isOpen) return null;

  const entries = data ?? [];

  function handleRollback(entry: VersionEntry) {
    if (!termId) return;
    setRollbackingVersionId(entry.version_id);
    rollbackMutation.mutate(
      { termId, versionId: entry.version_id },
      {
        onSuccess: () => setRollbackingVersionId(null),
        onError: () => setRollbackingVersionId(null),
      },
    );
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-[420px] animate-slide-in-right flex-col border-l border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-section-heading text-text-primary">
            History &mdash;{" "}
            <span className="font-semibold">{termName}</span>
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="Close history drawer"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <div className="space-y-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="space-y-2 rounded-card border border-border-faint p-4">
                  <Skeleton className="h-3 w-32" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-3 w-24" />
                </div>
              ))}
            </div>
          ) : entries.length === 0 ? (
            <div className="flex h-40 items-center justify-center">
              <p className="text-sm text-text-faint">No edit history yet</p>
            </div>
          ) : (
            <div className="space-y-3">
              {entries.map((entry, idx) => {
                const isCurrent = idx === 0;
                const isRollbacking =
                  rollbackingVersionId === entry.version_id;

                return (
                  <div
                    key={entry.version_id}
                    className={`rounded-card border p-4 ${
                      isCurrent
                        ? "border-accent bg-accent-dim"
                        : "border-border-faint bg-bg-base"
                    }`}
                  >
                    {/* Timestamp + Current badge */}
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs text-text-muted">
                        {formatTimestamp(entry.created_at)}
                      </span>
                      {isCurrent && (
                        <span className="rounded-badge border border-accent bg-accent-dim px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent">
                          Current
                        </span>
                      )}
                    </div>

                    {/* Editor */}
                    <p className="mt-1.5 text-xs text-text-faint">
                      by{" "}
                      <span className="font-mono text-text-muted">
                        {entry.editor_email}
                      </span>
                    </p>

                    {/* Change summary */}
                    <p className="mt-2 text-sm text-text-muted">
                      {entry.change_summary}
                    </p>

                    {/* Rollback button (not on current version) */}
                    {!isCurrent && (
                      <button
                        type="button"
                        onClick={() => handleRollback(entry)}
                        disabled={isRollbacking}
                        className="mt-3 flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
                      >
                        {isRollbacking ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <RotateCcw size={12} />
                        )}
                        Rollback to this version
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
