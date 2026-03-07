"use client";

import { Diamond } from "lucide-react";
import { ChatInput } from "./ChatInput";

interface ChatEmptyStateProps {
  onSend: (message: string, mode: string) => void;
  agentId: string;
  userName?: string;
}

const SUGGESTIONS = [
  "Outstanding invoices",
  "Salary band L5",
  "Annual leave policy",
  "Contract clause 8.2b",
];

/**
 * Chat empty state: centered layout matching proto UI.
 * - Agent icon (44x44px diamond)
 * - Greeting + subtitle
 * - Input bar embedded (NOT bottom-fixed)
 * - KB hint below input
 * - Suggestion chips
 */
function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function ChatEmptyState({ onSend, userName }: ChatEmptyStateProps) {
  const displayName = userName ?? "there";

  return (
    <div className="flex h-full flex-col items-center justify-center px-4">
      <div className="w-full max-w-[600px]">
        {/* Agent icon */}
        <div className="mb-4 flex justify-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-card bg-accent/10 text-accent">
            <Diamond size={22} />
          </div>
        </div>

        {/* Greeting */}
        <h1 className="mb-1.5 text-center text-2xl font-bold text-text-muted">
          {getGreeting()}, {displayName}.
        </h1>
        <p className="mb-8 text-center text-sm text-text-faint">
          What would you like to know today?
        </p>

        {/* Input bar - embedded, not bottom-fixed */}
        <ChatInput onSend={onSend} showModeSelector />

        {/* KB hint - never expose "RAG" or technical terms */}
        <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-text-faint">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          <span>SharePoint · Google Drive · 2,081 documents indexed</span>
        </div>

        {/* Suggestion chips */}
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              onClick={() => onSend(suggestion, "auto")}
              className="rounded-control border border-border px-3.5 py-2 text-sm text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
