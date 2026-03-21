"use client";

import { useState, useEffect, useCallback } from "react";
import { Shield, Check, Search, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { Skeleton } from "@/components/shared/LoadingState";
import {
  useKBAccessControl,
  useUpdateKBAccessControl,
  type KBVisibilityMode,
} from "@/lib/hooks/useKBAccessControl";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AccessControlPanelProps {
  kbId: string;
}

interface UserRecord {
  id: string;
  display_name: string;
  email: string;
}

interface UsersResponse {
  items: UserRecord[];
  total: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Roles must match backend _VALID_ROLES = {"viewer", "editor", "admin"}
const KB_ROLES = ["viewer", "editor", "admin"] as const;

const MODE_OPTIONS: {
  value: KBVisibilityMode;
  label: string;
  description: string;
}[] = [
  {
    value: "workspace_wide",
    label: "Workspace-wide",
    description: "All users in this workspace can access this knowledge base",
  },
  {
    value: "role_restricted",
    label: "Role-restricted",
    description: "Only users with specific roles can access",
  },
  {
    value: "user_specific",
    label: "User-specific",
    description: "Only named users can access this knowledge base",
  },
  {
    value: "agent_only",
    label: "Agent-only",
    description: "Only selected agents can access this KB",
  },
];

const ROLE_LABELS: Record<string, string> = {
  viewer: "Viewer",
  editor: "Editor",
  admin: "Admin",
};

// ---------------------------------------------------------------------------
// User search hook (debounced)
// ---------------------------------------------------------------------------

function useUserSearch(query: string) {
  return useQuery({
    queryKey: ["users-search", query],
    queryFn: () =>
      apiGet<UsersResponse>(
        `/api/v1/admin/users?search=${encodeURIComponent(query)}&page_size=10`,
      ),
    enabled: query.length >= 2,
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AccessControlPanel({ kbId }: AccessControlPanelProps) {
  const { data, isLoading, isError } = useKBAccessControl(kbId);
  const updateMutation = useUpdateKBAccessControl();

  const [mode, setMode] = useState<KBVisibilityMode>("workspace_wide");
  const [roles, setRoles] = useState<string[]>([]);
  const [userIds, setUserIds] = useState<string[]>([]);
  const [showSaved, setShowSaved] = useState(false);

  // User search state
  const [userSearch, setUserSearch] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [userRecords, setUserRecords] = useState<Record<string, UserRecord>>(
    {},
  );
  const { data: searchResults, isPending: isSearching } =
    useUserSearch(userSearch);

  // Sync local state when API data arrives
  useEffect(() => {
    if (data) {
      setMode(data.visibility_mode);
      setRoles(data.allowed_roles ?? []);
      setUserIds(data.allowed_user_ids ?? []);
    }
  }, [data]);

  // Resolve display names for pre-existing user IDs
  useEffect(() => {
    if (mode !== "user_specific") return;
    const unresolvedIds = userIds.filter((id) => !userRecords[id]);
    if (unresolvedIds.length === 0) return;

    Promise.all(
      unresolvedIds.map((id) =>
        apiGet<UserRecord>(`/api/v1/users/${encodeURIComponent(id)}`).catch(
          () => null,
        ),
      ),
    ).then((results) => {
      const resolved: Record<string, UserRecord> = {};
      results.forEach((rec, i) => {
        if (rec) resolved[unresolvedIds[i]] = rec;
      });
      if (Object.keys(resolved).length > 0) {
        setUserRecords((prev) => ({ ...prev, ...resolved }));
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, userIds.length]);

  const isDirty =
    !!data &&
    (mode !== data.visibility_mode ||
      JSON.stringify(roles.slice().sort()) !==
        JSON.stringify((data.allowed_roles ?? []).slice().sort()) ||
      JSON.stringify(userIds.slice().sort()) !==
        JSON.stringify((data.allowed_user_ids ?? []).slice().sort()));

  const handleSave = useCallback(async () => {
    const payload: {
      visibility_mode: KBVisibilityMode;
      allowed_roles?: string[];
      allowed_user_ids?: string[];
    } = { visibility_mode: mode };

    if (mode === "role_restricted") {
      payload.allowed_roles = roles;
    }
    if (mode === "user_specific") {
      payload.allowed_user_ids = userIds;
    }

    await updateMutation.mutateAsync({ kbId, payload });
    setShowSaved(true);
    setTimeout(() => setShowSaved(false), 2200);
  }, [kbId, mode, roles, userIds, updateMutation]);

  function toggleRole(role: string) {
    setRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  }

  function addUser(user: UserRecord) {
    if (!userIds.includes(user.id)) {
      setUserIds((prev) => [...prev, user.id]);
      setUserRecords((prev) => ({ ...prev, [user.id]: user }));
    }
    setUserSearch("");
    setShowDropdown(false);
  }

  function removeUser(userId: string) {
    setUserIds((prev) => prev.filter((id) => id !== userId));
    setUserRecords((prev) => {
      const next = { ...prev };
      delete next[userId];
      return next;
    });
  }

  // -----------------------------------------------------------------------
  // Loading skeleton
  // -----------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <div className="mb-4 flex items-center gap-2">
          <Skeleton className="h-4 w-4" />
          <Skeleton className="h-4 w-32" />
        </div>
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full rounded-control" />
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-card border border-alert/30 bg-alert-dim p-5">
        <p className="text-body-default text-alert">
          Failed to load access control settings.
        </p>
      </div>
    );
  }

  if (!data) return null;

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={16} className="text-text-faint" />
          <h3 className="text-section-heading text-text-primary">
            Access Control
          </h3>
        </div>
        {showSaved && (
          <span className="flex items-center gap-1 text-xs font-medium text-accent">
            <Check size={14} />
            Saved
          </span>
        )}
      </div>

      {/* Mode radio cards */}
      <div className="space-y-2">
        {MODE_OPTIONS.map((opt) => {
          const isActive = mode === opt.value;
          return (
            <div key={opt.value}>
              <button
                type="button"
                onClick={() => setMode(opt.value)}
                className={`w-full rounded-control border px-3 py-2.5 text-left transition-colors ${
                  isActive
                    ? "border-accent bg-accent-dim"
                    : "border-border bg-bg-elevated hover:border-accent-ring"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className={`flex h-4 w-4 items-center justify-center rounded-full border ${
                      isActive ? "border-accent" : "border-text-faint"
                    }`}
                  >
                    {isActive && (
                      <span className="h-2 w-2 rounded-full bg-accent" />
                    )}
                  </span>
                  <span
                    className={`text-body-default font-medium ${
                      isActive ? "text-text-primary" : "text-text-muted"
                    }`}
                  >
                    {opt.label}
                  </span>
                </div>
                <p className="mt-0.5 pl-[26px] text-xs text-text-faint">
                  {opt.description}
                </p>
              </button>

              {/* Role multi-select for role_restricted mode */}
              {isActive && opt.value === "role_restricted" && (
                <div className="mt-2 flex flex-wrap gap-2 pl-1">
                  {KB_ROLES.map((role) => {
                    const selected = roles.includes(role);
                    return (
                      <button
                        type="button"
                        key={role}
                        onClick={() => toggleRole(role)}
                        className={`rounded-badge px-2.5 py-1 text-xs font-medium transition-colors ${
                          selected
                            ? "bg-accent text-bg-base"
                            : "border border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary"
                        }`}
                      >
                        {ROLE_LABELS[role] ?? role}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* User search for user_specific mode */}
              {isActive && opt.value === "user_specific" && (
                <div className="relative mt-2 pl-1">
                  {/* Selected user chips */}
                  {userIds.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {userIds.map((uid) => {
                        const rec = userRecords[uid];
                        const label = rec
                          ? rec.display_name || rec.email
                          : uid.slice(0, 8);
                        return (
                          <span
                            key={uid}
                            className="flex items-center gap-1 rounded-badge bg-accent-dim px-2 py-0.5 text-xs text-text-primary"
                          >
                            <span className={rec ? "" : "font-mono italic"}>
                              {label}
                            </span>
                            <button
                              type="button"
                              onClick={() => removeUser(uid)}
                              className="text-text-faint hover:text-alert"
                            >
                              <X size={12} />
                            </button>
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {/* Search input */}
                  <div className="relative">
                    <Search
                      size={14}
                      className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-faint"
                    />
                    <input
                      type="text"
                      value={userSearch}
                      onChange={(e) => {
                        setUserSearch(e.target.value);
                        setShowDropdown(true);
                      }}
                      onFocus={() => setShowDropdown(true)}
                      onBlur={() =>
                        setTimeout(() => setShowDropdown(false), 150)
                      }
                      maxLength={100}
                      placeholder="Search users by name or email..."
                      className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                    />
                  </div>

                  {/* Search results dropdown */}
                  {showDropdown && userSearch.length >= 2 && (
                    <div className="absolute z-10 mt-1 w-full rounded-control border border-border bg-bg-surface">
                      {isSearching && (
                        <p className="px-3 py-2 text-xs text-text-faint">
                          Searching...
                        </p>
                      )}
                      {searchResults && searchResults.items.length === 0 && (
                        <p className="px-3 py-2 text-xs text-text-faint">
                          No users found
                        </p>
                      )}
                      {searchResults?.items.map((user) => {
                        const alreadyAdded = userIds.includes(user.id);
                        return (
                          <button
                            type="button"
                            key={user.id}
                            disabled={alreadyAdded}
                            onClick={() => addUser(user)}
                            className={`flex w-full items-center gap-2 px-3 py-2 text-left text-body-default transition-colors ${
                              alreadyAdded
                                ? "text-text-faint opacity-50"
                                : "text-text-primary hover:bg-bg-elevated"
                            }`}
                          >
                            <span className="font-medium">
                              {user.display_name}
                            </span>
                            <span className="text-xs text-text-faint">
                              {user.email}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Save button */}
      <div className="mt-5 flex items-center gap-3">
        <button
          type="button"
          disabled={!isDirty || updateMutation.isPending}
          onClick={handleSave}
          className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
        >
          {updateMutation.isPending ? "Saving..." : "Save Changes"}
        </button>
        {updateMutation.isError && (
          <span className="text-xs text-alert">
            Failed to save. Please try again.
          </span>
        )}
      </div>
    </div>
  );
}
