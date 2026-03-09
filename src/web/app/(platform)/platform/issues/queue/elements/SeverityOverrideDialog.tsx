"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useOverrideSeverity,
  type TenantIssueSeverity,
  type PlatformIssue,
} from "@/lib/hooks/useEngineeringIssues";

// ---------------------------------------------------------------------------
// SeverityOverrideDialog
// ---------------------------------------------------------------------------

const SEVERITIES: TenantIssueSeverity[] = ["P0", "P1", "P2", "P3", "P4"];

interface SeverityOverrideDialogProps {
  issue: PlatformIssue;
  onClose: () => void;
}

export function SeverityOverrideDialog({
  issue,
  onClose,
}: SeverityOverrideDialogProps) {
  const [newSeverity, setNewSeverity] = useState<TenantIssueSeverity>(
    issue.severity,
  );
  const [reason, setReason] = useState("");
  const overrideMutation = useOverrideSeverity();

  const canSubmit =
    newSeverity !== issue.severity &&
    reason.trim().length > 0 &&
    !overrideMutation.isPending;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    overrideMutation.mutate(
      { id: issue.id, severity: newSeverity, reason: reason.trim() },
      { onSuccess: () => onClose() },
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-[480px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-sm font-semibold text-text-primary">
            Override Severity
          </h3>
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
            Changing severity for:{" "}
            <span className="font-medium text-text-primary">{issue.title}</span>
          </p>

          {/* Current severity */}
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-text-faint">
            Current Severity
          </p>
          <p className="mb-4 font-mono text-sm text-text-primary">
            {issue.severity}
          </p>

          {/* New severity selector */}
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wider text-text-faint">
            New Severity
          </label>
          <div className="mb-4 flex gap-2">
            {SEVERITIES.map((sev) => (
              <button
                key={sev}
                type="button"
                onClick={() => setNewSeverity(sev)}
                disabled={sev === issue.severity}
                className={cn(
                  "rounded-control border px-3 py-1.5 font-mono text-xs font-medium transition-colors",
                  sev === issue.severity
                    ? "cursor-not-allowed border-border bg-bg-elevated text-text-faint"
                    : sev === newSeverity
                      ? "border-accent-ring bg-accent-dim text-accent"
                      : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
                )}
              >
                {sev}
              </button>
            ))}
          </div>

          {/* Reason */}
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wider text-text-faint">
            Reason (required)
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            placeholder="Explain why this severity change is needed..."
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder-text-faint transition-colors focus:border-accent focus:outline-none"
          />

          {/* Error */}
          {overrideMutation.error && (
            <p className="mt-2 text-xs text-alert">
              {overrideMutation.error.message}
            </p>
          )}

          {/* Footer */}
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
                  ? "bg-accent text-bg-base hover:bg-accent/90"
                  : "cursor-not-allowed bg-bg-elevated text-text-faint",
              )}
            >
              {overrideMutation.isPending ? "Saving..." : "Override Severity"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
