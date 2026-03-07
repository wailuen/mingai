"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { UserTable } from "./elements/UserTable";
import { UserInviteModal } from "./elements/UserInviteModal";
import { UserPlus, Search } from "lucide-react";

/**
 * FE-027: User directory with invite + role management.
 * Orchestrator only -- business logic in elements/.
 * Search, filter by role/status, server-side pagination.
 */
export default function UsersPage() {
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 20 });

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-page-title text-text-primary">Users</h1>
          <button
            onClick={() => setShowInviteModal(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <UserPlus size={14} />
            Invite User
          </button>
        </div>

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
                setPagination((prev) => ({ ...prev, pageIndex: 0 }));
              }}
              className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPagination((prev) => ({ ...prev, pageIndex: 0 }));
            }}
            className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-muted transition-colors focus:border-accent focus:outline-none"
          >
            <option value="">All Roles</option>
            <option value="tenant_admin">Admin</option>
            <option value="user">User</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPagination((prev) => ({ ...prev, pageIndex: 0 }));
            }}
            className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-muted transition-colors focus:border-accent focus:outline-none"
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
          </select>
        </div>

        <ErrorBoundary>
          <UserTable
            searchQuery={searchQuery}
            roleFilter={roleFilter}
            statusFilter={statusFilter}
            pagination={pagination}
            onPaginationChange={setPagination}
          />
        </ErrorBoundary>

        {showInviteModal && (
          <UserInviteModal onClose={() => setShowInviteModal(false)} />
        )}
      </div>
    </AppShell>
  );
}
