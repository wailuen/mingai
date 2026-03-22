"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { UserTable } from "./elements/UserTable";
import { UserInviteModal } from "./elements/UserInviteModal";
import { AccessRequestsTab } from "./elements/AccessRequestsTab";
import { UserPlus, Search } from "lucide-react";
import { cn } from "@/lib/utils";

type ActiveTab = "users" | "access_requests";

const TABS: { value: ActiveTab; label: string }[] = [
  { value: "users", label: "Users" },
  { value: "access_requests", label: "Access Requests" },
];

/**
 * FE-027: User directory with invite + role management.
 * Tabs: Users | Access Requests
 * Orchestrator only -- business logic in elements/.
 */
export default function UsersPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("users");
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  return (
    <AppShell>
      <div className="p-4 sm:p-7">
        {/* Page header */}
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="text-page-title text-text-primary">Users</h1>
          {activeTab === "users" && (
            <button
              type="button"
              onClick={() => setShowInviteModal(true)}
              className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
            >
              <UserPlus size={14} />
              Invite User
            </button>
          )}
        </div>

        {/* Tab nav */}
        <div className="mb-5 flex gap-0 border-b border-border">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setActiveTab(tab.value)}
              className={cn(
                "px-4 py-2 text-[12px] font-medium transition-colors",
                activeTab === tab.value
                  ? "border-b-2 border-accent text-text-primary"
                  : "border-b-2 border-transparent text-text-faint hover:text-text-muted",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "users" && (
          <>
            {/* Filters */}
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <div className="relative flex-1 sm:max-w-xs">
                <Search
                  size={14}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-faint"
                />
                <input
                  type="text"
                  placeholder="Search by name or email..."
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value);
                  }}
                  className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>

              <select
                value={roleFilter}
                onChange={(e) => {
                  setRoleFilter(e.target.value);
                }}
                className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-muted transition-colors focus:border-accent focus:outline-none"
              >
                <option value="">All Roles</option>
                <option value="tenant_admin">Admin</option>
                <option value="viewer">User</option>
              </select>

              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                }}
                className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-muted transition-colors focus:border-accent focus:outline-none"
              >
                <option value="">All Status</option>
                <option value="active">Active</option>
                <option value="invited">Invited</option>
                <option value="suspended">Suspended</option>
              </select>
            </div>

            <ErrorBoundary>
              <UserTable
                searchQuery={searchQuery}
                roleFilter={roleFilter}
                statusFilter={statusFilter}
              />
            </ErrorBoundary>
          </>
        )}

        {activeTab === "access_requests" && (
          <ErrorBoundary>
            <AccessRequestsTab />
          </ErrorBoundary>
        )}

        {showInviteModal && (
          <UserInviteModal onClose={() => setShowInviteModal(false)} />
        )}
      </div>
    </AppShell>
  );
}
