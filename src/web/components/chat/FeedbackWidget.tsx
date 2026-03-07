"use client";

import { useState, useCallback } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";

interface FeedbackWidgetProps {
  messageId: string;
}

/**
 * Thumbs up/down feedback on AI responses.
 * Submits to POST /api/v1/feedback.
 * Only one selection per message (toggle behavior).
 */
export function FeedbackWidget({ messageId }: FeedbackWidgetProps) {
  const [value, setValue] = useState<1 | -1 | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  const submit = useCallback(
    async (rating: 1 | -1) => {
      const newValue = value === rating ? null : rating;
      setValue(newValue);

      if (newValue === null) return;

      setSubmitting(true);
      setError(false);

      try {
        await apiPost("/api/v1/feedback", {
          message_id: messageId,
          value: newValue,
        });
      } catch {
        setError(true);
        setTimeout(() => setError(false), 3000);
      } finally {
        setSubmitting(false);
      }
    },
    [messageId, value],
  );

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => submit(1)}
        disabled={submitting}
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-control border transition-colors",
          value === 1
            ? "border-accent bg-accent-dim text-accent"
            : "border-transparent text-text-faint hover:border-border hover:text-text-muted",
        )}
        aria-label="Thumbs up"
      >
        <ThumbsUp size={14} />
      </button>
      <button
        onClick={() => submit(-1)}
        disabled={submitting}
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-control border transition-colors",
          value === -1
            ? "border-alert bg-alert-dim text-alert"
            : "border-transparent text-text-faint hover:border-border hover:text-text-muted",
        )}
        aria-label="Thumbs down"
      >
        <ThumbsDown size={14} />
      </button>
      {error && <span className="text-xs text-alert">Failed to submit</span>}
    </div>
  );
}
