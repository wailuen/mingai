"use client";

import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AppShell } from "@/components/layout/AppShell";
import { ChatInterface } from "@/components/chat/ChatInterface";

export default function ChatPage() {
  return (
    <AppShell>
      <ErrorBoundary
        fallback={
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-alert">
              Chat failed to load. Please refresh the page.
            </p>
          </div>
        }
      >
        <ChatInterface agentId="auto" />
      </ErrorBoundary>
    </AppShell>
  );
}
