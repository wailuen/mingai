"use client";

import { useRef, useEffect, useState } from "react";
import { type ChatMessage } from "@/hooks/useChat";
import { ChatInput } from "./ChatInput";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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
import { Loader2, FileText, RefreshCw } from "lucide-react";

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
  /** GAP-024: True while SSE stream is attempting reconnection */
  reconnecting?: boolean;
  /** GAP-024: Non-null when all reconnect attempts failed */
  reconnectFailed?: string | null;
  onSend: (message: string, mode: string) => void;
  /** GAP-024: Retry the last failed message */
  onRetry?: () => void;
  onViewSources?: () => void;
  currentMode?: string;
  /** FE-010: Team name for team context badge */
  teamName?: string | null;
  /** FE-014: Whether the last response was a cache hit */
  cacheHit?: boolean;
  /** FE-014: Age in seconds of the cached response */
  cacheAgeSeconds?: number | null;
  /** CACHE-018: Callback to re-send last message with X-Cache-Bypass */
  onBypassCache?: () => void;
  /** FE-2: Conversation ID for document upload */
  conversationId?: string | null;
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
  reconnecting,
  reconnectFailed,
  onSend,
  onRetry,
  onViewSources,
  currentMode = "auto",
  teamName,
  cacheHit,
  cacheAgeSeconds,
  onBypassCache,
  conversationId,
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
                    idx === messages.length - 1 ? glossaryExpansionsApplied : []
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
                  onBypassCache={
                    idx === messages.length - 1 ? onBypassCache : undefined
                  }
                />
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* GAP-024: Reconnecting indicator */}
      {reconnecting && (
        <div className="mx-auto max-w-[860px] px-4 pb-2">
          <div className="flex items-center gap-2 rounded-control border border-accent-ring bg-accent-dim px-3 py-2 text-sm text-accent">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
            <span>{statusMessage ?? "Reconnecting..."}</span>
          </div>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="mx-auto max-w-[860px] px-4 pb-2">
          <div className="flex items-center justify-between rounded-control border border-alert-ring bg-alert-dim px-3 py-2 text-sm text-alert">
            <span>{error}</span>
            {reconnectFailed && onRetry && (
              <button
                onClick={onRetry}
                className="ml-3 flex items-center gap-1 rounded-control border border-alert-ring px-2 py-1 text-xs text-alert transition-colors hover:bg-alert-dim"
              >
                <RefreshCw size={12} />
                Retry
              </button>
            )}
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
            conversationId={conversationId}
            isStreaming={streaming}
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
  onBypassCache,
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
  onBypassCache?: () => void;
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

      {/* Response text - 14px/1.6, no card. Markdown rendered. */}
      <div className="prose prose-invert prose-sm max-w-none text-sm leading-relaxed text-text-primary [&_code]:rounded [&_code]:bg-bg-elevated [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-accent [&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-text-primary [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-text-primary [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-text-muted [&_li]:text-text-primary [&_ol]:list-decimal [&_ol]:pl-4 [&_p]:text-text-primary [&_strong]:font-semibold [&_strong]:text-text-primary [&_ul]:list-disc [&_ul]:pl-4">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {message.content}
        </ReactMarkdown>
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
              onBypassCache={onBypassCache}
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
