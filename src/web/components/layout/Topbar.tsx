"use client";

import { useState } from "react";
import { Moon, Sun, Menu, ChevronDown } from "lucide-react";
import type { JWTClaims } from "@/lib/auth";

interface TopbarProps {
  claims: JWTClaims | null;
  tenantName?: string;
  onToggleSidebar?: () => void;
  onLogout?: () => void;
}

type RoleView = "end_user" | "tenant_admin" | "platform";

const ROLE_LABELS: Record<RoleView, string> = {
  end_user: "End User",
  tenant_admin: "Tenant Admin",
  platform: "Platform Admin",
};

export function Topbar({
  claims,
  tenantName = "Acme Corp",
  onToggleSidebar,
  onLogout,
}: TopbarProps) {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [showUserMenu, setShowUserMenu] = useState(false);

  const currentRole: RoleView =
    claims?.scope === "platform"
      ? "platform"
      : claims?.roles?.includes("tenant_admin")
        ? "tenant_admin"
        : "end_user";

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
  }

  const userInitials = claims ? claims.sub.slice(0, 2).toUpperCase() : "??";

  return (
    <header className="fixed left-0 right-0 top-0 z-50 flex h-topbar-h items-center gap-2 border-b border-border bg-bg-surface px-3.5">
      {/* Hamburger */}
      <button
        onClick={onToggleSidebar}
        className="flex h-8 w-8 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        aria-label="Toggle sidebar"
      >
        <Menu size={16} />
      </button>

      {/* Logo + tenant */}
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-control bg-accent text-bg-base text-sm font-bold">
          m
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-semibold leading-tight text-text-primary">
            mingai
          </span>
          <span className="text-xs leading-tight text-text-muted">
            {tenantName}
          </span>
        </div>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Role indicator */}
      <div className="flex items-center gap-1 rounded-control border border-border px-2.5 py-1 text-xs text-text-muted">
        <span className="h-1.5 w-1.5 rounded-full bg-accent" />
        <span>{ROLE_LABELS[currentRole]}</span>
        <ChevronDown size={12} />
      </div>

      {/* Theme toggle */}
      <button
        onClick={toggleTheme}
        className="flex h-8 w-8 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        aria-label="Toggle theme"
      >
        {theme === "dark" ? <Moon size={16} /> : <Sun size={16} />}
      </button>

      {/* User avatar */}
      <div className="relative">
        <button
          onClick={() => setShowUserMenu(!showUserMenu)}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-xs font-semibold text-bg-base"
          aria-label="User menu"
        >
          {userInitials}
        </button>

        {showUserMenu && (
          <div className="absolute right-0 top-full mt-1 w-48 rounded-card border border-border bg-bg-surface p-1 shadow-lg">
            <div className="border-b border-border-faint px-3 py-2">
              <p className="text-sm font-medium text-text-primary">
                {claims?.sub ?? "Unknown"}
              </p>
              <p className="font-mono text-xs text-text-muted">
                {claims?.tenant_id?.slice(0, 8) ?? ""}
              </p>
            </div>
            <button
              onClick={() => {
                setShowUserMenu(false);
                onLogout?.();
              }}
              className="mt-1 w-full rounded-control px-3 py-2 text-left text-sm text-alert transition-colors hover:bg-alert-dim"
            >
              Log out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
