"use client";

import { useState, useCallback } from "react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AppShell } from "@/components/layout/AppShell";
import { ChatInterface } from "@/components/chat/ChatInterface";
import { useAuth } from "@/hooks/useAuth";

function deriveDisplayName(email?: string): string | undefined {
  if (!email) return undefined;
  const localPart = email.split("@")[0];
  if (!localPart) return undefined;
  return localPart.charAt(0).toUpperCase() + localPart.slice(1);
}

/**
 * Chat page: coordinates conversation selection between sidebar and chat.
 * - selectedConversationId: set by clicking a sidebar conversation
 * - activeConversationId: the conversation currently loaded in chat
 */
export default function ChatPage() {
  const { claims } = useAuth();
  const userName = deriveDisplayName(claims?.email);

  const [selectedConversationId, setSelectedConversationId] = useState<
    string | null
  >(null);
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null);

  const handleSelectConversation = useCallback((id: string) => {
    setSelectedConversationId(id);
    setActiveConversationId(id);
  }, []);

  const handleNewConversation = useCallback(() => {
    setSelectedConversationId(null);
    setActiveConversationId(null);
  }, []);

  const handleConversationChange = useCallback((id: string | null) => {
    setActiveConversationId(id);
  }, []);

  return (
    <AppShell
      activeConversationId={activeConversationId}
      onSelectConversation={handleSelectConversation}
      onNewConversation={handleNewConversation}
    >
      <ErrorBoundary
        fallback={
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-alert">
              Chat failed to load. Please refresh the page.
            </p>
          </div>
        }
      >
        <ChatInterface
          agentId="auto"
          userName={userName}
          selectedConversationId={selectedConversationId}
          onConversationChange={handleConversationChange}
        />
      </ErrorBoundary>
    </AppShell>
  );
}
