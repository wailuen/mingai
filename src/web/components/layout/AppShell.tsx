"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { useAuth } from "@/hooks/useAuth";
import { isPlatformAdmin, isTenantAdmin } from "@/lib/auth";
import { apiGet } from "@/lib/api";
import { cn } from "@/lib/utils";

interface AppShellProps {
  children: ReactNode;
  activeConversationId?: string | null;
  onSelectConversation?: (id: string) => void;
  onNewConversation?: () => void;
  /** Increment to force the conversation list sidebar to re-fetch. */
  conversationListRefreshTrigger?: number;
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
  conversationListRefreshTrigger,
}: AppShellProps) {
  const { claims, logout } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const isPA = claims ? isPlatformAdmin(claims) : false;

  const { data: workspaceData } = useQuery<{ tenant_name?: string }>({
    queryKey: ["workspace-name"],
    queryFn: () => apiGet<{ tenant_name?: string }>("/api/v1/admin/workspace"),
    enabled: !!claims && !isPA && isTenantAdmin(claims),
    staleTime: 5 * 60 * 1000,
  });

  const tenantName = isPA
    ? "Default"
    : (workspaceData?.tenant_name ?? undefined);

  return (
    <div className="flex h-screen flex-col bg-bg-base">
      <Topbar
        claims={claims}
        tenantName={tenantName}
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        onLogout={logout}
      />
      <div className="flex min-h-0 flex-1 pt-topbar-h">
        <div
          className={cn(
            "flex-shrink-0 overflow-hidden transition-all duration-200",
            sidebarOpen ? "w-sidebar-w" : "w-0",
          )}
        >
          <Sidebar
            claims={claims}
            activeConversationId={activeConversationId}
            onSelectConversation={onSelectConversation}
            onNewConversation={onNewConversation}
            conversationListRefreshTrigger={conversationListRefreshTrigger}
          />
        </div>
        <main className="min-h-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
