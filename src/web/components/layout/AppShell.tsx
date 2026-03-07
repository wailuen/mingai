"use client";

import { useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

interface AppShellProps {
  children: ReactNode;
  activeConversationId?: string | null;
  onSelectConversation?: (id: string) => void;
  onNewConversation?: () => void;
}

/**
 * Main app shell: topbar + sidebar + content area.
 * Sidebar collapses on mobile.
 * Conversation props passed through to Sidebar for end-user history list.
 */
export function AppShell({
  children,
  activeConversationId,
  onSelectConversation,
  onNewConversation,
}: AppShellProps) {
  const { claims, logout } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex h-screen flex-col bg-bg-base">
      <Topbar
        claims={claims}
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        onLogout={logout}
      />
      <div className="flex flex-1 pt-topbar-h">
        <div
          className={cn(
            "flex-shrink-0 transition-all duration-200",
            sidebarOpen ? "w-sidebar-w" : "w-0 overflow-hidden",
          )}
        >
          <Sidebar
            claims={claims}
            activeConversationId={activeConversationId}
            onSelectConversation={onSelectConversation}
            onNewConversation={onNewConversation}
          />
        </div>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
