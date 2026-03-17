"use client";

import { useState, useCallback } from "react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AppShell } from "@/components/layout/AppShell";
import { ChatInterface } from "@/components/chat/ChatInterface";
import { useAuth } from "@/hooks/useAuth";
import { useUserProfile } from "@/lib/hooks/useUserProfile";

/**
 * Derive a human-readable display name.
 * Priority: profile.name > email local part (cleaned up).
 */
function deriveDisplayName(
  profileName?: string | null,
  email?: string,
): string | undefined {
  if (profileName) return profileName;
  if (!email) return undefined;
  const localPart = email.split("@")[0];
  if (!localPart) return undefined;
  // Replace underscores/dots with spaces, then title-case each word
  return localPart
    .replace(/[._-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Chat page: coordinates conversation selection between sidebar and chat.
 * - selectedConversationId: set by clicking a sidebar conversation
 * - activeConversationId: the conversation currently loaded in chat
 */
export default function ChatPage() {
  const { claims } = useAuth();
  const { data: profile } = useUserProfile();
  const userName = deriveDisplayName(profile?.name, claims?.email);

  const [selectedConversationId, setSelectedConversationId] = useState<
    string | null
  >(null);
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null);
  // Incremented each time "New conversation" is clicked so ChatInterface
  // can detect the reset request even when selectedConversationId was already null.
  const [resetKey, setResetKey] = useState(0);
  // Incremented when a new conversation is created so ConversationList re-fetches.
  const [conversationListRefreshTrigger, setConversationListRefreshTrigger] =
    useState(0);

  const handleSelectConversation = useCallback((id: string) => {
    setSelectedConversationId(id);
    setActiveConversationId(id);
  }, []);

  const handleNewConversation = useCallback(() => {
    setSelectedConversationId(null);
    setActiveConversationId(null);
    setResetKey((k) => k + 1);
  }, []);

  const handleConversationChange = useCallback((id: string | null) => {
    setActiveConversationId(id);
    // When a conversation is newly created (id goes null → UUID), bump the
    // refresh trigger so ConversationList immediately re-fetches the sidebar.
    if (id !== null) {
      setConversationListRefreshTrigger((n) => n + 1);
    }
  }, []);

  return (
    <AppShell
      activeConversationId={activeConversationId}
      onSelectConversation={handleSelectConversation}
      onNewConversation={handleNewConversation}
      conversationListRefreshTrigger={conversationListRefreshTrigger}
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
          resetKey={resetKey}
          onConversationChange={handleConversationChange}
        />
      </ErrorBoundary>
    </AppShell>
  );
}
