"use client";

import { useState, useEffect, useCallback } from "react";
import { Brain, X } from "lucide-react";

/**
 * FE-012: "Memory saved" toast notification.
 * Listens for the custom mingai:memory_saved event dispatched by useChat
 * when a memory_saved SSE event is received.
 */
export function MemorySavedToast() {
  const [visible, setVisible] = useState(false);
  const [content, setContent] = useState("");

  const handleMemorySaved = useCallback((e: Event) => {
    const detail = (e as CustomEvent).detail as {
      note_id: string;
      content: string;
    };
    setContent(detail.content);
    setVisible(true);
  }, []);

  useEffect(() => {
    window.addEventListener("mingai:memory_saved", handleMemorySaved);
    return () => {
      window.removeEventListener("mingai:memory_saved", handleMemorySaved);
    };
  }, [handleMemorySaved]);

  // Auto-dismiss after 4 seconds
  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(() => setVisible(false), 4000);
    return () => clearTimeout(timer);
  }, [visible]);

  if (!visible) return null;

  return (
    <div className="fixed bottom-20 right-4 z-50 animate-fade-in">
      <div className="flex items-center gap-3 rounded-card border border-accent-ring bg-bg-surface px-4 py-3 shadow-lg">
        <Brain size={16} className="flex-shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-text-primary">Memory saved</p>
          {content && (
            <p className="mt-0.5 line-clamp-1 text-xs text-text-muted">
              {content}
            </p>
          )}
        </div>
        <button
          onClick={() => setVisible(false)}
          className="flex-shrink-0 text-text-faint transition-colors hover:text-text-muted"
          aria-label="Dismiss"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
