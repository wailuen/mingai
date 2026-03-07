"use client";

import { Brain } from "lucide-react";

interface MemoryNotesPolicyProps {
  enabled: boolean;
  autoExtract: boolean;
  onToggle: (value: boolean) => void;
  onAutoExtractToggle: (value: boolean) => void;
  saving: boolean;
}

/**
 * FE-052: Memory notes policy card.
 * Controls whether memory notes are enabled and if auto-extraction is on.
 */
export function MemoryNotesPolicy({
  enabled,
  autoExtract,
  onToggle,
  onAutoExtractToggle,
  saving,
}: MemoryNotesPolicyProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 flex items-center gap-2">
        <Brain size={18} className="text-accent" />
        <h3 className="text-[15px] font-semibold text-text-primary">
          Memory Notes
        </h3>
      </div>

      <div className="space-y-4">
        {/* Main toggle */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-text-primary">
              Enable memory notes
            </p>
            <p className="mt-1 text-xs text-text-muted">
              Memory notes let users ask the AI to &quot;remember&quot; things
              explicitly for future conversations.
            </p>
          </div>
          <button
            onClick={() => onToggle(!enabled)}
            disabled={saving}
            className={`relative h-5 w-9 flex-shrink-0 rounded-full transition-colors ${
              enabled ? "bg-accent" : "bg-bg-elevated"
            } ${saving ? "opacity-50" : ""}`}
            role="switch"
            aria-checked={enabled}
            aria-label="Toggle memory notes"
          >
            <span
              className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        {/* Auto-extract sub-toggle */}
        <div
          style={{
            overflow: "hidden",
            maxHeight: enabled ? "80px" : "0",
            opacity: enabled ? 1 : 0,
            transition: "max-height 220ms ease, opacity 220ms ease",
          }}
        >
          <div className="ml-6 border-l border-border-faint pl-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-text-primary">
                  Auto-extract from conversations
                </p>
                <p className="mt-1 text-xs text-text-muted">
                  Automatically detect and save important facts from
                  conversations as memory notes.
                </p>
              </div>
              <button
                onClick={() => onAutoExtractToggle(!autoExtract)}
                disabled={saving || !enabled}
                className={`relative h-5 w-9 flex-shrink-0 rounded-full transition-colors ${
                  autoExtract ? "bg-accent" : "bg-bg-elevated"
                } ${saving || !enabled ? "opacity-50" : ""}`}
                role="switch"
                aria-checked={autoExtract}
                aria-label="Toggle auto-extract memory notes"
              >
                <span
                  className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                    autoExtract ? "translate-x-4" : "translate-x-0"
                  }`}
                />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
