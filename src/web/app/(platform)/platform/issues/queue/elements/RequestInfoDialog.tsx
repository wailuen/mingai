"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useRequestInfo,
  type PlatformIssue,
} from "@/lib/hooks/useEngineeringIssues";

// ---------------------------------------------------------------------------
// RequestInfoDialog
// ---------------------------------------------------------------------------

interface RequestInfoDialogProps {
  issue: PlatformIssue;
  onClose: () => void;
}

export function RequestInfoDialog({ issue, onClose }: RequestInfoDialogProps) {
  const [message, setMessage] = useState("");
  const requestInfoMutation = useRequestInfo();

  const canSubmit = message.trim().length > 0 && !requestInfoMutation.isPending;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    requestInfoMutation.mutate(
      { id: issue.id, message: message.trim() },
      { onSuccess: () => onClose() },
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-[480px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h3 className="text-body-default font-semibold text-text-primary">
            Request Information
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
            Send a question to the reporter of:{" "}
            <span className="font-medium text-text-primary">{issue.title}</span>
          </p>

          <p className="mb-1 text-xs text-text-faint">
            Reporter:{" "}
            <span className="font-mono text-text-muted">
              {issue.reporter_email}
            </span>
          </p>

          {/* Message */}
          <label className="mb-1 mt-3 block text-[11px] font-medium uppercase tracking-wider text-text-faint">
            Message
          </label>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={4}
            placeholder="What additional information do you need from the reporter?"
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder-text-faint transition-colors focus:border-accent focus:outline-none"
          />

          {/* Error */}
          {requestInfoMutation.error && (
            <p className="mt-2 text-xs text-alert">
              {requestInfoMutation.error.message}
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
              {requestInfoMutation.isPending ? "Sending..." : "Send Request"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
