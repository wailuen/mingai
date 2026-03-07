"use client";

import { useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

interface AppShellProps {
  children: ReactNode;
}

/**
 * Main app shell: topbar + sidebar + content area.
 * Sidebar collapses on mobile.
 */
export function AppShell({ children }: AppShellProps) {
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
          <Sidebar claims={claims} />
        </div>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
