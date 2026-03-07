"use client";

import { useRef, useEffect, useState } from "react";
import { type ChatMessage } from "@/hooks/useChat";
import { ChatInput } from "./ChatInput";
import { FeedbackWidget } from "./FeedbackWidget";
import { ConfidenceBar } from "./ConfidenceBar";
import { GlossaryExpansionIndicator } from "./GlossaryExpansionIndicator";
import { ProfileIndicator } from "./ProfileIndicator";
import { Loader2, FileText } from "lucide-react";

interface ChatActiveStateProps {
  messages: ChatMessage[];
  streaming: boolean;
  statusMessage: string | null;
  retrievalConfidence: number | null;
  glossaryExpansions: string[];
  profileContextUsed: boolean;
  layersActive: string[];
  error: string | null;
  onSend: (message: string) => void;
  onViewSources?: () => void;
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
  profileContextUsed,
  layersActive,
  error,
  onSend,
  onViewSources,
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
                  profileContextUsed={
                    idx === messages.length - 1 ? profileContextUsed : false
                  }
                  layersActive={idx === messages.length - 1 ? layersActive : []}
                  onViewSources={onViewSources}
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
  profileContextUsed,
  layersActive,
  onViewSources,
}: {
  message: ChatMessage;
  isStreaming: boolean;
  statusMessage: string | null;
  retrievalConfidence: number | null;
  glossaryExpansions: string[];
  profileContextUsed: boolean;
  layersActive: string[];
  onViewSources?: () => void;
}) {
  const hasSources = (message.sources?.length ?? 0) > 0;

  return (
    <div className="space-y-2">
      {/* Meta row: AGENT . MODE + confidence pill */}
      <div className="flex items-center gap-2">
        <span className="text-label-nav uppercase tracking-wider text-accent">
          AUTO · RESPONSE
        </span>
        {retrievalConfidence !== null && (
          <ConfidenceBar score={retrievalConfidence} />
        )}
      </div>

      {/* Profile indicator */}
      {profileContextUsed && <ProfileIndicator layersActive={layersActive} />}

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

      {/* Footer: sources count + latency */}
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
        </div>
      )}

      {/* Feedback row */}
      {!isStreaming && message.content && (
        <FeedbackWidget messageId={message.id} />
      )}
    </div>
  );
}
