"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, Plus, X, FlaskConical } from "lucide-react";
import {
  useGroupSyncConfig,
  useUpdateGroupSyncConfig,
  type GroupRole,
  type GroupSyncConfig,
} from "@/lib/hooks/useSSO";
import { useUserProfile } from "@/lib/hooks/useUserProfile";

// TA-004: viewer | editor | admin only — "user" is excluded from mapping UI
const MAPPING_ROLE_OPTIONS: GroupRole[] = ["viewer", "editor", "admin"];

function isConfigEqual(a: GroupSyncConfig, b: GroupSyncConfig): boolean {
  const mappingMatch =
    JSON.stringify(
      Object.fromEntries(Object.entries(a.group_role_mapping).sort()),
    ) ===
    JSON.stringify(
      Object.fromEntries(Object.entries(b.group_role_mapping).sort()),
    );
  const groupsMatch =
    JSON.stringify(a.allowed_groups.slice().sort()) ===
    JSON.stringify(b.allowed_groups.slice().sort());
  return groupsMatch && mappingMatch;
}

/**
 * TA-004: Group-to-Role Mapping Table
 *
 * Standalone component that renders the current IdP group → mingai role
 * mappings with inline add/delete rows and a save action.
 *
 * The "Test My Groups" feature resolves the current user's groups from their
 * profile (if available) against the draft mapping state and shows the
 * resulting role. If the /me endpoint does not return groups, a "Coming soon"
 * state is shown instead.
 */
export function GroupRoleMappingTable() {
  const { data, isPending, error } = useGroupSyncConfig();
  const updateMutation = useUpdateGroupSyncConfig();
  const { data: userProfile } = useUserProfile();

  const [groupRoleMapping, setGroupRoleMapping] = useState<
    Record<string, GroupRole>
  >({});
  const [allowedGroups, setAllowedGroups] = useState<string[]>([]);
  const [newGroup, setNewGroup] = useState("");
  const [newRole, setNewRole] = useState<GroupRole>("viewer");
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Test My Groups state
  const [testResult, setTestResult] = useState<{
    resolvedRole: GroupRole | null;
    matchedGroup: string | null;
    comingSoon: boolean;
  } | null>(null);

  // Sync local state from server data
  useEffect(() => {
    if (data) {
      setGroupRoleMapping(data.group_role_mapping);
      setAllowedGroups(data.allowed_groups);
    }
  }, [data]);

  const currentDraft: GroupSyncConfig = {
    allowed_groups: allowedGroups,
    group_role_mapping: groupRoleMapping,
  };

  const isDirty = data ? !isConfigEqual(currentDraft, data) : false;

  function handleAddRow() {
    const trimmed = newGroup.trim();
    if (!trimmed) return;
    setGroupRoleMapping((prev) => ({ ...prev, [trimmed]: newRole }));
    // Also add to allowed_groups if not already present
    setAllowedGroups((prev) =>
      prev.includes(trimmed) ? prev : [...prev, trimmed],
    );
    setNewGroup("");
    setNewRole("viewer");
  }

  function handleDeleteRow(group: string) {
    setGroupRoleMapping((prev) => {
      const next = { ...prev };
      delete next[group];
      return next;
    });
  }

  function handleRoleChange(group: string, role: GroupRole) {
    setGroupRoleMapping((prev) => ({ ...prev, [group]: role }));
  }

  async function handleSave() {
    setSaveSuccess(false);
    try {
      await updateMutation.mutateAsync(currentDraft);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch {
      // error surfaced via updateMutation.error
    }
  }

  const handleTestMyGroups = useCallback(() => {
    // The /me profile groups field is non-standard — check for its presence.
    // If the backend exposes groups in the profile, resolve against draft mapping.
    const profileGroups =
      userProfile && "groups" in userProfile
        ? (userProfile as { groups?: string[] }).groups
        : undefined;

    if (!profileGroups || profileGroups.length === 0) {
      setTestResult({
        resolvedRole: null,
        matchedGroup: null,
        comingSoon: true,
      });
      return;
    }

    // Find first group in the current draft mapping that matches a user group
    let matchedGroup: string | null = null;
    let resolvedRole: GroupRole | null = null;
    for (const group of profileGroups) {
      if (groupRoleMapping[group]) {
        matchedGroup = group;
        resolvedRole = groupRoleMapping[group];
        break;
      }
    }

    setTestResult({ resolvedRole, matchedGroup, comingSoon: false });
  }, [userProfile, groupRoleMapping]);

  if (isPending) {
    return (
      <div className="flex items-center gap-2 text-body-default text-text-muted">
        <Loader2 size={14} className="animate-spin" />
        Loading group mappings...
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load group mappings: {error.message}
      </p>
    );
  }

  const mappingEntries = Object.entries(groupRoleMapping);

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5 space-y-5">
      {/* Panel header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-section-heading text-text-primary">
            Group to Role Mapping
          </h2>
          <p className="mt-1 text-xs text-text-muted">
            Map IdP group names to mingai roles. Users inherit the role of their
            first matched group at login.
          </p>
        </div>
        {/* Test My Groups button */}
        <button
          type="button"
          onClick={handleTestMyGroups}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary"
        >
          <FlaskConical size={12} />
          Test My Groups
        </button>
      </div>

      {/* Test result banner */}
      {testResult && (
        <div
          className={`rounded-control border px-3 py-2.5 text-xs ${
            testResult.comingSoon
              ? "border-border-faint bg-bg-elevated text-text-muted"
              : testResult.resolvedRole
                ? "border-accent/30 bg-accent-dim text-accent"
                : "border-warn/30 bg-warn-dim text-warn"
          }`}
        >
          {testResult.comingSoon ? (
            "Coming soon — your IdP groups are not yet surfaced in the user profile."
          ) : testResult.resolvedRole ? (
            <>
              Your account matches group{" "}
              <span className="font-mono">{testResult.matchedGroup}</span> and
              would receive the{" "}
              <span className="font-semibold">{testResult.resolvedRole}</span>{" "}
              role.
            </>
          ) : (
            "No group match found for your account in the current draft mapping."
          )}
        </div>
      )}

      {/* Mapping table */}
      <div className="overflow-x-auto rounded-control border border-border">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-text-faint">
                IdP Group Name
              </th>
              <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-text-faint">
                mingai Role
              </th>
              <th className="w-8 px-3 py-2" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {mappingEntries.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="px-3 py-4 text-center text-xs italic text-text-faint"
                >
                  No mappings defined. Add a row below.
                </td>
              </tr>
            )}
            {mappingEntries.map(([group, role]) => (
              <tr
                key={group}
                className="border-b border-border-faint last:border-0 transition-colors hover:bg-accent-dim"
              >
                <td className="px-3 py-2.5 font-mono text-xs text-text-primary">
                  {group}
                </td>
                <td className="px-3 py-2.5">
                  <select
                    value={role}
                    onChange={(e) =>
                      handleRoleChange(group, e.target.value as GroupRole)
                    }
                    className="rounded-control border border-border bg-bg-elevated px-2 py-1 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-ring"
                  >
                    {MAPPING_ROLE_OPTIONS.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-3 py-2.5">
                  <button
                    type="button"
                    onClick={() => handleDeleteRow(group)}
                    className="text-text-faint transition-colors hover:text-alert"
                    aria-label={`Delete mapping for ${group}`}
                  >
                    <X size={12} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Add row */}
      <div className="flex gap-2">
        <input
          type="text"
          value={newGroup}
          onChange={(e) => setNewGroup(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAddRow();
            }
          }}
          placeholder="IdP group name (e.g. finance-team)"
          className="flex-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-accent-ring"
        />
        <select
          value={newRole}
          onChange={(e) => setNewRole(e.target.value as GroupRole)}
          className="rounded-control border border-border bg-bg-elevated px-2 py-1.5 text-body-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-ring"
        >
          {MAPPING_ROLE_OPTIONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleAddRow}
          disabled={!newGroup.trim()}
          className="inline-flex items-center gap-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-xs font-medium text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:opacity-40"
        >
          <Plus size={12} />
          Add Row
        </button>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between gap-4 border-t border-border-faint pt-3">
        <div className="text-xs">
          {saveSuccess && (
            <span className="text-accent">Mappings saved successfully.</span>
          )}
          {updateMutation.isError && (
            <span className="text-alert">
              Save failed:{" "}
              {updateMutation.error instanceof Error
                ? updateMutation.error.message
                : "Unknown error"}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={handleSave}
          disabled={!isDirty || updateMutation.isPending}
          className="inline-flex items-center gap-2 rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {updateMutation.isPending && (
            <Loader2 size={13} className="animate-spin" />
          )}
          Save
        </button>
      </div>
    </div>
  );
}
