"use client";

import { useRef, useEffect, useState } from "react";
import { type ChatMessage } from "@/hooks/useChat";
import { ChatInput } from "./ChatInput";
import { FeedbackWidget } from "./FeedbackWidget";
import { ConfidenceBar } from "./ConfidenceBar";
import { GlossaryExpansionIndicator } from "./GlossaryExpansionIndicator";
import {
  TermsInterpreted,
  type GlossaryExpansionApplied,
} from "./TermsInterpreted";
import { ProfileIndicator } from "./ProfileIndicator";
import { TeamContextBadge } from "./TeamContextBadge";
import { CacheStateChip } from "./CacheStateChip";
import { Loader2, FileText } from "lucide-react";

interface ChatActiveStateProps {
  messages: ChatMessage[];
  streaming: boolean;
  statusMessage: string | null;
  retrievalConfidence: number | null;
  glossaryExpansions: string[];
  glossaryExpansionsApplied: GlossaryExpansionApplied[];
  profileContextUsed: boolean;
  layersActive: string[];
  error: string | null;
  onSend: (message: string, mode: string) => void;
  onViewSources?: () => void;
  currentMode?: string;
  /** FE-010: Team name for team context badge */
  teamName?: string | null;
  /** FE-014: Whether the last response was a cache hit */
  cacheHit?: boolean;
  /** FE-014: Age in seconds of the cached response */
  cacheAgeSeconds?: number | null;
}

/**
 * Active chat state: messages scroll area + input fixed at bottom.
 * Messages centered with max-width: 860px.
 */
export function ChatActiveState({
  messages,
  streaming,
  statusMessage,
  retrievalConfidence,
  glossaryExpansions,
  glossaryExpansionsApplied,
  profileContextUsed,
  layersActive,
  error,
  onSend,
  onViewSources,
  currentMode = "auto",
  teamName,
  cacheHit,
  cacheAgeSeconds,
}: ChatActiveStateProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Auto-scroll to bottom on new content
  useEffect(() => {
    if (autoScroll && messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, autoScroll]);

  // Detect if user has scrolled up
  function handleScroll() {
    const el = scrollContainerRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(isAtBottom);
  }

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-6"
      >
        <div className="mx-auto max-w-[860px] space-y-6">
          {messages.map((msg, idx) => (
            <div key={msg.id}>
              {msg.role === "user" ? (
                <UserMessage content={msg.content} />
              ) : (
                <AIMessage
                  message={msg}
                  isStreaming={streaming && idx === messages.length - 1}
                  statusMessage={
                    idx === messages.length - 1 ? statusMessage : null
                  }
                  retrievalConfidence={
                    idx === messages.length - 1 ? retrievalConfidence : null
                  }
                  glossaryExpansions={
                    idx === messages.length - 1 ? glossaryExpansions : []
                  }
                  glossaryExpansionsApplied={
                    idx === messages.length - 1
                      ? glossaryExpansionsApplied
                      : []
                  }
                  profileContextUsed={
                    idx === messages.length - 1 ? profileContextUsed : false
                  }
                  layersActive={idx === messages.length - 1 ? layersActive : []}
                  onViewSources={onViewSources}
                  currentMode={currentMode}
                  teamName={idx === messages.length - 1 ? teamName : null}
                  cacheHit={idx === messages.length - 1 ? cacheHit : undefined}
                  cacheAgeSeconds={
                    idx === messages.length - 1 ? cacheAgeSeconds : null
                  }
                />
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="mx-auto max-w-[860px] px-4 pb-2">
          <div className="rounded-control border border-alert-ring bg-alert-dim px-3 py-2 text-sm text-alert">
            {error}
          </div>
        </div>
      )}

      {/* Input bar - fixed at bottom */}
      <div className="border-t border-border-faint bg-bg-base px-4 pb-4 pt-3">
        <div className="mx-auto max-w-[860px]">
          <ChatInput
            onSend={onSend}
            disabled={streaming}
            placeholder="Ask follow-up..."
            showModeSelector={false}
          />
        </div>
      </div>
    </div>
  );
}

/** User message: right-aligned pill */
function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[68%] rounded-card border border-border bg-bg-elevated px-4 py-3 text-sm text-text-primary">
        {content}
      </div>
    </div>
  );
}

/**
 * AI message: NO card, NO bubble, NO border.
 * Text flows directly on --bg-base.
 * Anatomy: meta row -> response text -> footer -> feedback row
 */
function AIMessage({
  message,
  isStreaming,
  statusMessage,
  retrievalConfidence,
  glossaryExpansions,
  glossaryExpansionsApplied,
  profileContextUsed,
  layersActive,
  onViewSources,
  currentMode = "auto",
  teamName,
  cacheHit,
  cacheAgeSeconds,
}: {
  message: ChatMessage;
  isStreaming: boolean;
  statusMessage: string | null;
  retrievalConfidence: number | null;
  glossaryExpansions: string[];
  glossaryExpansionsApplied: GlossaryExpansionApplied[];
  profileContextUsed: boolean;
  layersActive: string[];
  onViewSources?: () => void;
  currentMode?: string;
  teamName?: string | null;
  cacheHit?: boolean;
  cacheAgeSeconds?: number | null;
}) {
  const hasSources = (message.sources?.length ?? 0) > 0;
  const modeLabel = currentMode === "auto" ? "AUTO" : currentMode.toUpperCase();

  return (
    <div className="space-y-2">
      {/* Meta row: AGENT . MODE + confidence pill */}
      <div className="flex items-center gap-2">
        <span className="text-label-nav uppercase tracking-wider text-accent">
          {modeLabel} · RESPONSE
        </span>
        {retrievalConfidence !== null && (
          <ConfidenceBar score={retrievalConfidence} />
        )}
      </div>

      {/* Profile indicator + team context badge */}
      {(profileContextUsed || teamName) && (
        <div className="flex flex-wrap items-center gap-2">
          {profileContextUsed && (
            <ProfileIndicator layersActive={layersActive} />
          )}
          <TeamContextBadge teamName={teamName ?? null} visible={!!teamName} />
        </div>
      )}

      {/* Status indicator (while streaming) */}
      {statusMessage && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 size={14} className="animate-spin" />
          <span>{statusMessage}</span>
        </div>
      )}

      {/* Response text - 14px/1.6, no card */}
      <div className="text-sm leading-relaxed text-text-primary">
        {message.content}
        {isStreaming && !statusMessage && (
          <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-accent" />
        )}
      </div>

      {/* Glossary expansion indicator (mandatory if expansions exist) */}
      {glossaryExpansions.length > 0 && (
        <GlossaryExpansionIndicator expansions={glossaryExpansions} />
      )}

      {/* AI-029: Structured terms interpreted indicator */}
      {glossaryExpansionsApplied.length > 0 && (
        <TermsInterpreted expansions={glossaryExpansionsApplied} />
      )}

      {/* Footer: sources count + cache state + latency */}
      {!isStreaming && message.content && (
        <div className="flex items-center gap-3 pt-1">
          {hasSources && (
            <button
              onClick={onViewSources}
              className="flex items-center gap-1 text-xs text-text-muted transition-colors hover:text-text-primary"
            >
              <FileText size={12} />
              <span className="font-mono">
                {message.sources?.length} sources
              </span>
            </button>
          )}
          {cacheHit != null && (
            <CacheStateChip
              cacheHit={cacheHit}
              cacheAgeSeconds={cacheAgeSeconds}
            />
          )}
        </div>
      )}

      {/* Feedback row */}
      {!isStreaming && message.content && (
        <FeedbackWidget messageId={message.id} />
      )}
    </div>
  );
}
