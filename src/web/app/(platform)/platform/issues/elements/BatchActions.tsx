"use client";

import { useState } from "react";
import { X, UserCheck, CheckCircle, Download } from "lucide-react";
import { cn } from "@/lib/utils";

interface BatchActionsProps {
  selectedCount: number;
  onAssign: () => void;
  onResolve: () => void;
  onExport: () => void;
  onClear: () => void;
}

export function BatchActions({
  selectedCount,
  onAssign,
  onResolve,
  onExport,
  onClear,
}: BatchActionsProps) {
  const [showConfirm, setShowConfirm] = useState(false);

  if (selectedCount === 0) return null;

  function handleResolveClick() {
    setShowConfirm(true);
  }

  function handleConfirmResolve() {
    setShowConfirm(false);
    onResolve();
  }

  function handleCancelResolve() {
    setShowConfirm(false);
  }

  return (
    <div
      className={cn(
        "sticky bottom-0 z-10 flex items-center gap-3 rounded-card border border-border bg-bg-surface px-5 py-3",
        "animate-fade-in",
      )}
    >
      {/* Selected count */}
      <span className="font-mono text-data-value font-medium text-accent">
        {selectedCount}
      </span>
      <span className="text-body-default text-text-muted">selected</span>

      {/* Divider */}
      <div className="h-5 w-px bg-border" />

      {/* Actions */}
      <button
        type="button"
        onClick={onAssign}
        className="flex items-center gap-1.5 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
      >
        <UserCheck size={14} />
        Assign to me
      </button>

      {showConfirm ? (
        <div className="flex items-center gap-2">
          <span className="text-body-default text-warn">
            Resolve {selectedCount} issue{selectedCount !== 1 ? "s" : ""}?
          </span>
          <button
            type="button"
            onClick={handleConfirmResolve}
            className="rounded-control bg-accent px-3 py-1 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            Confirm
          </button>
          <button
            type="button"
            onClick={handleCancelResolve}
            className="rounded-control border border-border px-3 py-1 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={handleResolveClick}
          className="flex items-center gap-1.5 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
        >
          <CheckCircle size={14} />
          Mark Resolved
        </button>
      )}

      <button
        type="button"
        onClick={onExport}
        className="flex items-center gap-1.5 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
      >
        <Download size={14} />
        Export CSV
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Clear */}
      <button
        type="button"
        onClick={onClear}
        className="flex items-center gap-1 rounded-control px-2 py-1 text-body-default text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-muted"
      >
        <X size={12} />
        Clear
      </button>
    </div>
  );
}
