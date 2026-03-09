"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, Search } from "lucide-react";
import { apiGet } from "@/lib/api";

export interface AccessControlConfig {
  mode: "workspace" | "role" | "user";
  roles?: string[];
  userIds?: string[];
}

interface AccessControlSelectorProps {
  value: AccessControlConfig;
  onChange: (config: AccessControlConfig) => void;
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

const AVAILABLE_ROLES = ["admin", "user", "viewer"] as const;

const MODE_OPTIONS: {
  value: AccessControlConfig["mode"];
  label: string;
  description: string;
}[] = [
  {
    value: "workspace",
    label: "Workspace-wide",
    description: "All users in this workspace can access the agent",
  },
  {
    value: "role",
    label: "Role-restricted",
    description: "Only users with specific roles can access",
  },
  {
    value: "user",
    label: "User-specific",
    description: "Only named users can access the agent",
  },
];

function useUserSearch(query: string) {
  return useQuery({
    queryKey: ["users-search", query],
    queryFn: () =>
      apiGet<UsersResponse>(
        `/api/v1/users?search=${encodeURIComponent(query)}&page_size=10`,
      ),
    enabled: query.length >= 2,
  });
}

export function AccessControlSelector({
  value,
  onChange,
}: AccessControlSelectorProps) {
  const [userSearch, setUserSearch] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedUserRecords, setSelectedUserRecords] = useState<
    Record<string, UserRecord>
  >({});
  const { data: searchResults, isPending: isSearching } =
    useUserSearch(userSearch);

  function handleModeChange(mode: AccessControlConfig["mode"]) {
    onChange({
      mode,
      roles: mode === "role" ? (value.roles ?? []) : undefined,
      userIds: mode === "user" ? (value.userIds ?? []) : undefined,
    });
  }

  function toggleRole(role: string) {
    const current = value.roles ?? [];
    const next = current.includes(role)
      ? current.filter((r) => r !== role)
      : [...current, role];
    onChange({ ...value, roles: next });
  }

  function addUser(user: UserRecord) {
    const current = value.userIds ?? [];
    if (!current.includes(user.id)) {
      onChange({ ...value, userIds: [...current, user.id] });
      setSelectedUserRecords((prev) => ({ ...prev, [user.id]: user }));
    }
    setUserSearch("");
    setShowDropdown(false);
  }

  function removeUser(userId: string) {
    onChange({
      ...value,
      userIds: (value.userIds ?? []).filter((id) => id !== userId),
    });
    setSelectedUserRecords((prev) => {
      const next = { ...prev };
      delete next[userId];
      return next;
    });
  }

  function handleSearchBlur() {
    // Small delay so click-on-dropdown-item fires before hiding
    setTimeout(() => setShowDropdown(false), 150);
  }

  return (
    <div className="space-y-2">
      {/* Mode radio cards */}
      {MODE_OPTIONS.map((opt) => {
        const isActive = value.mode === opt.value;
        return (
          <div key={opt.value}>
            <button
              type="button"
              onClick={() => handleModeChange(opt.value)}
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
                  className={`text-sm font-medium ${
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

            {/* Role multi-select */}
            {isActive && opt.value === "role" && (
              <div className="mt-2 flex flex-wrap gap-2 pl-1">
                {AVAILABLE_ROLES.map((role) => {
                  const selected = (value.roles ?? []).includes(role);
                  return (
                    <button
                      type="button"
                      key={role}
                      onClick={() => toggleRole(role)}
                      className={`rounded-badge px-2.5 py-1 text-xs font-medium capitalize transition-colors ${
                        selected
                          ? "bg-accent text-bg-base"
                          : "border border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary"
                      }`}
                    >
                      {role}
                    </button>
                  );
                })}
              </div>
            )}

            {/* User-specific search */}
            {isActive && opt.value === "user" && (
              <div className="relative mt-2 pl-1">
                {/* Selected users as chips */}
                {(value.userIds ?? []).length > 0 && (
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    {(value.userIds ?? []).map((uid) => {
                      const rec = selectedUserRecords[uid];
                      const label = rec
                        ? rec.display_name || rec.email
                        : uid.slice(0, 8);
                      return (
                        <span
                          key={uid}
                          className="flex items-center gap-1 rounded-badge bg-accent-dim px-2 py-0.5 text-xs text-text-primary"
                        >
                          <span className={rec ? "" : "font-mono"}>
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
                    onBlur={handleSearchBlur}
                    maxLength={100}
                    placeholder="Search users by name or email..."
                    className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                  />
                </div>

                {/* Search results dropdown */}
                {showDropdown && userSearch.length >= 2 && (
                  <div className="absolute z-10 mt-1 w-full rounded-control border border-border bg-bg-surface shadow-lg">
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
                      const alreadyAdded = (value.userIds ?? []).includes(
                        user.id,
                      );
                      return (
                        <button
                          type="button"
                          key={user.id}
                          disabled={alreadyAdded}
                          onClick={() => addUser(user)}
                          className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
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
  );
}
