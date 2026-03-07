"use client";

import { useState } from "react";
import { ChatEmptyState } from "./ChatEmptyState";
import { ChatActiveState } from "./ChatActiveState";
import { SourcePanel } from "./SourcePanel";
import { useChat } from "@/hooks/useChat";
import { cn } from "@/lib/utils";

interface ChatInterfaceProps {
  agentId: string;
}

/**
 * Two-state chat layout:
 * - Empty: centered input + greeting (activateChatState on first send)
 * - Active: messages + bottom-fixed input (resetChatState on agent switch)
 */
export function ChatInterface({ agentId }: ChatInterfaceProps) {
  const chat = useChat(agentId);
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false);

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
            profileContextUsed={chat.profileContextUsed}
            layersActive={chat.layersActive}
            error={chat.error}
            onSend={chat.sendMessage}
            onViewSources={() => setSourcePanelOpen(true)}
          />
        ) : (
          <ChatEmptyState onSend={chat.sendMessage} agentId={agentId} />
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
