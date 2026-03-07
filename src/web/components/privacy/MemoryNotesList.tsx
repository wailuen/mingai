"use client";

import { useState, useCallback } from "react";
import { Brain, Trash2, AlertTriangle } from "lucide-react";
import { apiDelete, apiRequest } from "@/lib/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";

interface MemoryNote {
  id: string;
  content: string;
  source: "user-directed" | "auto-extracted";
  agent_id: string | null;
  created_at: string;
}

/**
 * FE-019: Memory notes list with CRUD.
 * Shows source badge: user-directed | auto-extracted.
 * Delete individual notes + "Clear all" with confirmation.
 */
export function MemoryNotesList() {
  const queryClient = useQueryClient();
  const [confirmClearAll, setConfirmClearAll] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const { data: notes = [], isLoading } = useQuery<MemoryNote[]>({
    queryKey: ["memory-notes"],
    queryFn: () => apiRequest<MemoryNote[]>("/api/v1/me/memory"),
  });

  const handleDeleteNote = useCallback(
    async (noteId: string) => {
      setDeleting(noteId);
      try {
        await apiDelete(`/api/v1/me/memory/${noteId}`);
        queryClient.invalidateQueries({ queryKey: ["memory-notes"] });
      } catch {
        // Error handled silently - note stays visible
      } finally {
        setDeleting(null);
      }
    },
    [queryClient],
  );

  const handleClearAll = useCallback(async () => {
    try {
      await apiDelete("/api/v1/me/memory");
      queryClient.invalidateQueries({ queryKey: ["memory-notes"] });
      setConfirmClearAll(false);
    } catch {
      // Error handled silently
    }
  }, [queryClient]);

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain size={18} className="text-accent" />
          <h3 className="text-section-heading text-text-primary">
            Memory Notes
          </h3>
          <span className="font-mono text-xs text-text-faint">
            {notes.length}/15
          </span>
        </div>

        {notes.length > 0 && (
          <button
            onClick={() => setConfirmClearAll(true)}
            className="text-xs text-alert transition-colors hover:underline"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Clear all confirmation */}
      {confirmClearAll && (
        <div className="mb-4 flex items-center gap-3 rounded-control border border-alert-ring bg-alert-dim px-3 py-2">
          <AlertTriangle size={14} className="flex-shrink-0 text-alert" />
          <span className="flex-1 text-xs text-alert">
            This will permanently delete all memory notes.
          </span>
          <button
            onClick={handleClearAll}
            className="rounded-control bg-alert px-2.5 py-1 text-xs font-medium text-white"
          >
            Confirm
          </button>
          <button
            onClick={() => setConfirmClearAll(false)}
            className="text-xs text-text-muted"
          >
            Cancel
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-control bg-bg-elevated"
            />
          ))}
        </div>
      ) : notes.length === 0 ? (
        <p className="text-sm text-text-faint">
          No memory notes yet. Notes are created as you interact with mingai.
        </p>
      ) : (
        <div className="space-y-2">
          {notes.map((note) => (
            <div
              key={note.id}
              className="flex items-start justify-between gap-3 rounded-control border border-border-faint bg-bg-elevated px-3 py-2.5"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm text-text-primary">{note.content}</p>
                <div className="mt-1 flex items-center gap-2">
                  <SourceBadge source={note.source} />
                  <span className="font-mono text-xs text-text-faint">
                    {new Date(note.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
              <button
                onClick={() => handleDeleteNote(note.id)}
                disabled={deleting === note.id}
                className="flex-shrink-0 p-1 text-text-faint transition-colors hover:text-alert"
                aria-label={`Delete note: ${note.content}`}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SourceBadge({
  source,
}: {
  source: "user-directed" | "auto-extracted";
}) {
  return (
    <span className="rounded-badge border border-border px-2 py-0.5 text-xs text-text-faint">
      {source}
    </span>
  );
}
