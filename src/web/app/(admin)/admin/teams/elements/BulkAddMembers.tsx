"use client";

import { useState, useMemo } from "react";
import { Search, X, Loader2, Users } from "lucide-react";
import { Skeleton } from "@/components/shared/LoadingState";
import {
  useWorkspaceUsers,
  useBulkAddMembers,
  type WorkspaceUser,
} from "@/lib/hooks/useTeams";

interface BulkAddMembersProps {
  teamId: string;
  teamName: string;
  existingMemberIds?: string[];
  onClose: () => void;
}

/**
 * FE-039: Bulk add multiple users to a team from the user directory.
 *
 * Multi-select list with search. Shows selected users as chips.
 * Calls POST /api/v1/admin/teams/{id}/members with array of user_ids.
 */
export function BulkAddMembers({
  teamId,
  teamName,
  existingMemberIds = [],
  onClose,
}: BulkAddMembersProps) {
  const [search, setSearch] = useState("");
  const [selectedUsers, setSelectedUsers] = useState<WorkspaceUser[]>([]);
  const [error, setError] = useState("");
  const [successCount, setSuccessCount] = useState<number | null>(null);

  const { data, isLoading } = useWorkspaceUsers(search || undefined);
  const bulkAddMutation = useBulkAddMembers();

  const existingSet = useMemo(
    () => new Set(existingMemberIds),
    [existingMemberIds],
  );

  const selectedIds = useMemo(
    () => new Set(selectedUsers.map((u) => u.id)),
    [selectedUsers],
  );

  const availableUsers = useMemo(() => {
    const users = data?.items ?? [];
    return users.filter(
      (u) => !existingSet.has(u.id) && !selectedIds.has(u.id),
    );
  }, [data, existingSet, selectedIds]);

  function selectUser(user: WorkspaceUser) {
    setSelectedUsers([...selectedUsers, user]);
  }

  function removeUser(userId: string) {
    setSelectedUsers(selectedUsers.filter((u) => u.id !== userId));
  }

  async function handleSubmit() {
    if (selectedUsers.length === 0) return;
    setError("");

    try {
      const result = await bulkAddMutation.mutateAsync({
        teamId,
        userIds: selectedUsers.map((u) => u.id),
      });
      setSuccessCount(result.added);
      setSelectedUsers([]);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add members");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div
        className="flex w-full max-w-lg flex-col rounded-card border border-border bg-bg-surface"
        style={{ maxHeight: "80vh" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Add Members
            </h2>
            <p className="mt-0.5 text-xs text-text-muted">
              Add users to{" "}
              <span className="font-medium text-text-primary">{teamName}</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Success */}
        {successCount !== null && (
          <div className="mx-5 mt-4 rounded-control border border-accent/30 bg-accent-dim px-3 py-2 text-sm text-accent">
            {successCount} member{successCount !== 1 ? "s" : ""} added
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mx-5 mt-4 rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-sm text-alert">
            {error}
          </div>
        )}

        {/* Selected chips */}
        {selectedUsers.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-b border-border-faint px-5 py-3">
            {selectedUsers.map((user) => (
              <span
                key={user.id}
                className="inline-flex items-center gap-1 rounded-sm border border-accent/20 bg-accent-dim px-2 py-0.5 text-xs text-text-primary"
              >
                {user.name}
                <button
                  onClick={() => removeUser(user.id)}
                  className="ml-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-sm text-text-faint transition-colors hover:text-alert"
                >
                  <X size={10} />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Search */}
        <div className="border-b border-border-faint px-5 py-3">
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or email..."
              className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              autoFocus
            />
          </div>
        </div>

        {/* User list */}
        <div
          className="flex-1 overflow-y-auto px-5 py-2"
          style={{ minHeight: "160px", maxHeight: "320px" }}
        >
          {isLoading ? (
            <div className="space-y-2 py-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : availableUsers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Users size={24} className="mb-2 text-text-faint" />
              <p className="text-sm text-text-faint">
                {search
                  ? "No matching users found"
                  : "All workspace users are already in this team"}
              </p>
            </div>
          ) : (
            <div className="space-y-0.5">
              {availableUsers.map((user) => (
                <button
                  key={user.id}
                  onClick={() => selectUser(user)}
                  className="flex w-full items-center gap-3 rounded-control px-3 py-2 text-left transition-colors hover:bg-accent-dim"
                >
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-bg-elevated text-xs font-medium text-text-muted">
                    {user.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-text-primary">
                      {user.name}
                    </p>
                    <p className="truncate font-mono text-xs text-text-faint">
                      {user.email}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <span className="font-mono text-xs text-text-faint">
            {selectedUsers.length} selected
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={selectedUsers.length === 0 || bulkAddMutation.isPending}
              className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              {bulkAddMutation.isPending && (
                <Loader2 size={14} className="animate-spin" />
              )}
              Add {selectedUsers.length} member
              {selectedUsers.length !== 1 ? "s" : ""} to team
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
