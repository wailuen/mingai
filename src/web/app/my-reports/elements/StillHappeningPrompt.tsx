"use client";

import { useState } from "react";
import { useReportRegression } from "@/hooks/useMyReports";

interface StillHappeningPromptProps {
  reportId: string;
}

export function StillHappeningPrompt({ reportId }: StillHappeningPromptProps) {
  const [expanded, setExpanded] = useState(false);
  const [comment, setComment] = useState("");
  const mutation = useReportRegression();

  if (mutation.isSuccess) {
    return (
      <div className="mt-4 rounded-control border border-accent-ring bg-accent-dim px-4 py-3">
        <p className="text-sm text-accent">
          Regression reported. The team will investigate.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-control border border-border bg-bg-surface px-4 py-3">
      {!expanded ? (
        <div className="flex items-center justify-between">
          <span className="text-body-default text-text-muted">
            Still happening?
          </span>
          <button
            onClick={() => setExpanded(true)}
            className="rounded-control border border-warn px-3 py-1 text-xs font-medium text-warn transition-colors hover:bg-warn-dim"
          >
            Yes, report regression
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <label className="block text-body-default text-text-muted">
            Optional comment
          </label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Describe what you're seeing..."
            rows={2}
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
          {mutation.isError && (
            <p className="text-xs text-alert">
              {mutation.error?.message || "Failed to submit. Please try again."}
            </p>
          )}
          <div className="flex items-center gap-2">
            <button
              onClick={() =>
                mutation.mutate({ id: reportId, comment: comment || undefined })
              }
              disabled={mutation.isPending}
              className="rounded-control border border-warn bg-warn-dim px-3 py-1 text-xs font-medium text-warn transition-colors hover:bg-warn disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {mutation.isPending ? "Submitting..." : "Confirm"}
            </button>
            <button
              onClick={() => {
                setExpanded(false);
                setComment("");
              }}
              className="rounded-control px-3 py-1 text-xs text-text-muted transition-colors hover:text-text-primary"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
