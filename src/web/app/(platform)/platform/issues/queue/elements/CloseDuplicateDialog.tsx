"use client";

import { useState, useRef, useEffect } from "react";
import { X, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCloseDuplicate,
  type PlatformIssue,
} from "@/lib/hooks/useEngineeringIssues";

// ---------------------------------------------------------------------------
// CloseDuplicateDialog
// ---------------------------------------------------------------------------

interface CloseDuplicateDialogProps {
  issue: PlatformIssue;
  onClose: () => void;
}

export function CloseDuplicateDialog({
  issue,
  onClose,
}: CloseDuplicateDialogProps) {
  const [duplicateOf, setDuplicateOf] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const closeDuplicateMutation = useCloseDuplicate();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const _UUID_RE =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const trimmed = duplicateOf.trim().toLowerCase();
  const isValidUuid = _UUID_RE.test(trimmed);
  const canSubmit =
    trimmed.length > 0 &&
    isValidUuid &&
    trimmed !== issue.id &&
    !closeDuplicateMutation.isPending;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    closeDuplicateMutation.mutate(
      { id: issue.id, duplicate_of: trimmed },
      { onSuccess: () => onClose() },
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-[480px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Copy size={15} className="text-text-muted" />
            <h3 className="text-sm font-semibold text-text-primary">
              Close as Duplicate
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-faint transition-colors hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="px-5 py-4">
          <p className="mb-4 text-xs text-text-muted">
            Closing:{" "}
            <span className="font-medium text-text-primary">{issue.title}</span>
          </p>

          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wider text-text-faint">
            Original Issue ID
          </label>
          <input
            ref={inputRef}
            type="text"
            value={duplicateOf}
            onChange={(e) => setDuplicateOf(e.target.value)}
            placeholder="Paste the original issue ID here"
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm font-mono text-text-primary placeholder-text-faint transition-colors focus:border-accent focus:outline-none"
          />
          {trimmed.length > 0 && !isValidUuid && (
            <p className="mt-1 text-xs text-alert">
              Enter a valid issue ID (UUID format).
            </p>
          )}
          {trimmed === issue.id && (
            <p className="mt-1 text-xs text-alert">
              Cannot mark an issue as a duplicate of itself.
            </p>
          )}

          {closeDuplicateMutation.isError && (
            <p className="mt-2 text-xs text-alert">
              Failed to close issue. Please try again.
            </p>
          )}

          <div className="mt-5 flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-4 py-2 text-xs font-medium text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className={cn(
                "rounded-control px-4 py-2 text-xs font-semibold transition-colors",
                canSubmit
                  ? "border border-alert/30 text-alert hover:bg-alert-dim"
                  : "cursor-not-allowed bg-bg-elevated text-text-faint",
              )}
            >
              {closeDuplicateMutation.isPending
                ? "Closing..."
                : "Close as Duplicate"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
