"use client";

import { useState, useCallback } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";

type FeedbackRating = "up" | "down";

interface FeedbackWidgetProps {
  messageId: string;
}

interface FeedbackResponse {
  id: string;
  rating: string;
}

/**
 * Thumbs up/down feedback on AI responses.
 * Submits to POST /api/v1/chat/feedback with {message_id, rating: "up"|"down"}.
 * Can change selection (toggles to other option, re-submits).
 * Outlined neutral style until selected.
 */
export function FeedbackWidget({ messageId }: FeedbackWidgetProps) {
  const [selected, setSelected] = useState<FeedbackRating | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  const submit = useCallback(
    async (rating: FeedbackRating) => {
      if (selected === rating) return;

      setSelected(rating);
      setSubmitting(true);
      setError(false);

      try {
        await apiPost<FeedbackResponse>("/api/v1/chat/feedback", {
          message_id: messageId,
          rating,
        });
      } catch {
        setError(true);
        setTimeout(() => setError(false), 3000);
      } finally {
        setSubmitting(false);
      }
    },
    [messageId, selected],
  );

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => submit("up")}
        disabled={submitting}
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-control border transition-colors",
          selected === "up"
            ? "border-accent bg-accent-dim text-accent"
            : "border-transparent text-text-faint hover:border-border hover:text-text-muted",
        )}
        aria-label="Thumbs up"
      >
        <ThumbsUp size={14} />
      </button>
      <button
        onClick={() => submit("down")}
        disabled={submitting}
        className={cn(
          "flex h-7 w-7 items-center justify-center rounded-control border transition-colors",
          selected === "down"
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
