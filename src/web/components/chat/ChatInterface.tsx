"use client";

import { useState, useEffect, useRef } from "react";
import { ChatEmptyState } from "./ChatEmptyState";
import { ChatActiveState } from "./ChatActiveState";
import { SourcePanel } from "./SourcePanel";
import { useChat } from "@/hooks/useChat";
import { cn } from "@/lib/utils";

interface ChatInterfaceProps {
  agentId: string;
  userName?: string;
  /** Externally-selected conversation ID (from sidebar). */
  selectedConversationId?: string | null;
  /** Incremented each time "New conversation" is requested; triggers chat reset. */
  resetKey?: number;
  /** Called when the active conversation changes (for sidebar sync). */
  onConversationChange?: (id: string | null) => void;
}

/**
 * Two-state chat layout:
 * - Empty: centered input + greeting (activateChatState on first send)
 * - Active: messages + bottom-fixed input (resetChatState on agent switch)
 *
 * Supports loading an existing conversation via selectedConversationId prop.
 */
export function ChatInterface({
  agentId,
  userName,
  selectedConversationId,
  resetKey,
  onConversationChange,
}: ChatInterfaceProps) {
  const chat = useChat(agentId);
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false);

  // Reset chat when "New conversation" is requested (resetKey increments).
  // Skip the initial render (resetKey === 0 or undefined).
  const prevResetKey = useRef(resetKey ?? 0);
  useEffect(() => {
    const current = resetKey ?? 0;
    if (current !== prevResetKey.current) {
      prevResetKey.current = current;
      chat.resetChat();
      setSourcePanelOpen(false);
      onConversationChange?.(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  // Load conversation when selectedConversationId changes externally.
  useEffect(() => {
    if (
      selectedConversationId &&
      selectedConversationId !== chat.conversationId
    ) {
      chat.loadConversation(selectedConversationId);
    }
    // Only react to external selection changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedConversationId]);

  // Notify parent when conversation ID changes (after first message creates one)
  useEffect(() => {
    onConversationChange?.(chat.conversationId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.conversationId]);

  function handleNewConversation() {
    chat.resetChat();
    onConversationChange?.(null);
  }

  return (
    <div className="relative flex h-full bg-bg-base">
      <div
        className={cn("flex flex-1 flex-col", sourcePanelOpen && "mr-[400px]")}
      >
        {chat.hasMessages ? (
          <ChatActiveState
            messages={chat.messages}
            streaming={chat.streaming}
            statusMessage={chat.statusMessage}
            retrievalConfidence={chat.retrievalConfidence}
            glossaryExpansions={chat.glossaryExpansions}
            glossaryExpansionsApplied={chat.glossaryExpansionsApplied}
            profileContextUsed={chat.profileContextUsed}
            layersActive={chat.layersActive}
            error={chat.error}
            reconnecting={chat.reconnecting}
            reconnectFailed={chat.reconnectFailed}
            onSend={(message, mode) => chat.sendMessage(message, mode)}
            onRetry={() => chat.retryLastMessage()}
            onViewSources={() => setSourcePanelOpen(true)}
            currentMode={chat.currentMode}
            cacheHit={chat.cacheHit ?? undefined}
            cacheAgeSeconds={chat.cacheAgeSeconds}
            onBypassCache={() => chat.bypassCacheAndResend()}
          />
        ) : (
          <ChatEmptyState
            onSend={(message, mode) => chat.sendMessage(message, mode)}
            agentId={agentId}
            userName={userName}
          />
        )}
      </div>

      {sourcePanelOpen && (
        <SourcePanel
          sources={chat.sources}
          onClose={() => setSourcePanelOpen(false)}
        />
      )}
    </div>
  );
}
