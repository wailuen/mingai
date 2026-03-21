"use client";

import { useState, useEffect } from "react";
import { Loader2, X, Plus } from "lucide-react";
import {
  useGroupSyncConfig,
  useUpdateGroupSyncConfig,
  type GroupRole,
  type GroupSyncConfig,
} from "@/lib/hooks/useSSO";

const ROLE_OPTIONS: GroupRole[] = ["admin", "editor", "viewer", "user"];

function isConfigEqual(a: GroupSyncConfig, b: GroupSyncConfig): boolean {
  const groupsMatch =
    JSON.stringify(a.allowed_groups.slice().sort()) ===
    JSON.stringify(b.allowed_groups.slice().sort());
  const mappingMatch =
    JSON.stringify(
      Object.fromEntries(Object.entries(a.group_role_mapping).sort()),
    ) ===
    JSON.stringify(
      Object.fromEntries(Object.entries(b.group_role_mapping).sort()),
    );
  return groupsMatch && mappingMatch;
}

export function GroupSyncConfigPanel() {
  const { data, isPending, error } = useGroupSyncConfig();
  const updateMutation = useUpdateGroupSyncConfig();

  const [allowedGroups, setAllowedGroups] = useState<string[]>([]);
  const [groupRoleMapping, setGroupRoleMapping] = useState<
    Record<string, GroupRole>
  >({});
  const [newGroupInput, setNewGroupInput] = useState("");
  const [newMappingGroup, setNewMappingGroup] = useState("");
  const [newMappingRole, setNewMappingRole] = useState<GroupRole>("viewer");
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Sync local state from fetched data
  useEffect(() => {
    if (data) {
      setAllowedGroups(data.allowed_groups);
      setGroupRoleMapping(data.group_role_mapping);
    }
  }, [data]);

  const currentDraft: GroupSyncConfig = {
    allowed_groups: allowedGroups,
    group_role_mapping: groupRoleMapping,
  };

  const isDirty = data ? !isConfigEqual(currentDraft, data) : false;

  function handleAddGroup() {
    const trimmed = newGroupInput.trim();
    if (!trimmed || allowedGroups.includes(trimmed)) return;
    setAllowedGroups((prev) => [...prev, trimmed]);
    setNewGroupInput("");
  }

  function handleRemoveGroup(group: string) {
    setAllowedGroups((prev) => prev.filter((g) => g !== group));
  }

  function handleAddMapping() {
    const trimmed = newMappingGroup.trim();
    if (!trimmed) return;
    setGroupRoleMapping((prev) => ({ ...prev, [trimmed]: newMappingRole }));
    setNewMappingGroup("");
    setNewMappingRole("viewer");
  }

  function handleRemoveMapping(group: string) {
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

  if (isPending) {
    return (
      <div className="flex items-center gap-2 text-body-default text-text-muted">
        <Loader2 size={14} className="animate-spin" />
        Loading group sync configuration...
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load group sync config: {error.message}
      </p>
    );
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5 space-y-6">
      {/* Panel header */}
      <div>
        <h2 className="text-section-heading text-text-primary">
          Group Sync Configuration
        </h2>
        <p className="mt-1 text-xs text-text-muted">
          Map IdP groups to workspace roles. Changes apply at next login.
        </p>
      </div>

      {/* Allowed Groups */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-faint">
          Allowed Groups
        </h3>

        {/* Tag list */}
        <div className="flex flex-wrap gap-2 min-h-[32px]">
          {allowedGroups.length === 0 && (
            <span className="text-xs text-text-faint italic">
              No groups added
            </span>
          )}
          {allowedGroups.map((g) => (
            <span
              key={g}
              className="inline-flex items-center gap-1 rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-xs font-medium text-text-primary"
            >
              {g}
              <button
                type="button"
                onClick={() => handleRemoveGroup(g)}
                className="text-text-faint hover:text-alert transition-colors"
                aria-label={`Remove group ${g}`}
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>

        {/* Add group input */}
        <div className="flex gap-2">
          <input
            type="text"
            value={newGroupInput}
            onChange={(e) => setNewGroupInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleAddGroup();
              }
            }}
            placeholder="Group name (e.g. finance-team)"
            className="flex-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-accent-ring"
          />
          <button
            type="button"
            onClick={handleAddGroup}
            disabled={!newGroupInput.trim()}
            className="inline-flex items-center gap-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-xs font-medium text-text-muted hover:border-accent-ring hover:text-text-primary disabled:opacity-40 transition-colors"
          >
            <Plus size={12} />
            Add
          </button>
        </div>
      </section>

      {/* Group → Role Mapping */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-text-faint">
          Group to Role Mapping
        </h3>

        {Object.keys(groupRoleMapping).length > 0 && (
          <div className="overflow-x-auto rounded-control border border-border">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-border">
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-text-faint">
                    Group
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-text-faint">
                    Role
                  </th>
                  <th className="w-8 px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {Object.entries(groupRoleMapping).map(([group, role]) => (
                  <tr
                    key={group}
                    className="border-b border-border-faint last:border-0 hover:bg-accent-dim transition-colors"
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
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2.5">
                      <button
                        type="button"
                        onClick={() => handleRemoveMapping(group)}
                        className="text-text-faint hover:text-alert transition-colors"
                        aria-label={`Remove mapping for ${group}`}
                      >
                        <X size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {Object.keys(groupRoleMapping).length === 0 && (
          <p className="text-xs text-text-faint italic">No mappings defined</p>
        )}

        {/* Add mapping row */}
        <div className="flex gap-2">
          <input
            type="text"
            value={newMappingGroup}
            onChange={(e) => setNewMappingGroup(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleAddMapping();
              }
            }}
            placeholder="Group name"
            className="flex-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-accent-ring"
          />
          <select
            value={newMappingRole}
            onChange={(e) => setNewMappingRole(e.target.value as GroupRole)}
            className="rounded-control border border-border bg-bg-elevated px-2 py-1.5 text-body-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent-ring"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleAddMapping}
            disabled={!newMappingGroup.trim()}
            className="inline-flex items-center gap-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-xs font-medium text-text-muted hover:border-accent-ring hover:text-text-primary disabled:opacity-40 transition-colors"
          >
            <Plus size={12} />
            Add
          </button>
        </div>
      </section>

      {/* Footer: save + feedback */}
      <div className="flex items-center justify-between gap-4 pt-2 border-t border-border-faint">
        <div className="text-xs">
          {saveSuccess && (
            <span className="text-accent">
              Configuration saved successfully.
            </span>
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
