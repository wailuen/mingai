"use client";

import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, X } from "lucide-react";

interface ErrorDetectionPromptProps {
  onOpenReporter: () => void;
}

/**
 * FE-023: Error detection auto-prompt.
 * Detects JS errors and surfaces issue reporter prompt.
 * Shows a non-intrusive banner when errors are detected.
 */
export function ErrorDetectionPrompt({
  onOpenReporter,
}: ErrorDetectionPromptProps) {
  const [errorDetected, setErrorDetected] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const handleError = useCallback(() => {
    setErrorDetected(true);
    setDismissed(false);
  }, []);

  useEffect(() => {
    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleError);

    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleError);
    };
  }, [handleError]);

  if (!errorDetected || dismissed) return null;

  return (
    <div className="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 animate-fade-in">
      <div className="flex items-center gap-3 rounded-card border border-warn-dim bg-bg-surface px-4 py-3 shadow-lg">
        <AlertTriangle size={16} className="flex-shrink-0 text-warn" />
        <p className="text-sm text-text-primary">
          Something went wrong.{" "}
          <button
            onClick={() => {
              onOpenReporter();
              setDismissed(true);
            }}
            className="text-accent underline transition-colors hover:text-accent"
          >
            Report this issue
          </button>
        </p>
        <button
          onClick={() => setDismissed(true)}
          className="flex-shrink-0 text-text-faint transition-colors hover:text-text-muted"
          aria-label="Dismiss"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
