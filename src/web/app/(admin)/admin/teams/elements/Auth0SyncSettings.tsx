"use client";

import { useState } from "react";
import { Plus, X, Loader2, AlertCircle } from "lucide-react";
import { useUpdateTeam } from "@/lib/hooks/useTeams";

interface Auth0SyncSettingsProps {
  teamId: string;
  initialPatterns?: string[];
}

/**
 * FE-039: Auth0 group sync allowlist configuration.
 *
 * Tag-style input for group name patterns with wildcard support.
 * Patterns like "Engineering*", "Procurement-*", "exact-group-name".
 * Saves via PUT /api/v1/admin/teams/{id}.
 */
export function Auth0SyncSettings({
  teamId,
  initialPatterns = [],
}: Auth0SyncSettingsProps) {
  const [patterns, setPatterns] = useState<string[]>(initialPatterns);
  const [inputValue, setInputValue] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const updateMutation = useUpdateTeam();

  function addPattern() {
    const trimmed = inputValue.trim();
    if (!trimmed) return;

    if (patterns.includes(trimmed)) {
      setError("Pattern already exists");
      return;
    }

    setPatterns([...patterns, trimmed]);
    setInputValue("");
    setError("");
    setSaved(false);
  }

  function removePattern(index: number) {
    setPatterns(patterns.filter((_, i) => i !== index));
    setSaved(false);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      addPattern();
    }
  }

  async function handleSave() {
    setError("");
    setSaved(false);

    try {
      await updateMutation.mutateAsync({
        id: teamId,
        payload: {
          auth0_sync_patterns: patterns,
        } as Record<string, unknown>,
      });
      setSaved(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save patterns");
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-body-default font-semibold text-text-primary">
          Auth0 Group Sync
        </h3>
        <p className="mt-0.5 text-xs text-text-muted">
          Configure which Auth0 groups auto-sync into this team
        </p>
      </div>

      {/* Warning note */}
      <div className="flex items-start gap-2 rounded-control border border-warn/20 bg-warn-dim px-3 py-2">
        <AlertCircle size={14} className="mt-0.5 flex-shrink-0 text-warn" />
        <p className="text-xs text-text-muted">
          Auto-sync only for groups matching these patterns. Members from
          non-matching groups will not be synced.
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-body-default text-alert">
          {error}
        </div>
      )}

      {/* Success */}
      {saved && (
        <div className="rounded-control border border-accent/30 bg-accent-dim px-3 py-2 text-body-default text-accent">
          Sync patterns saved
        </div>
      )}

      {/* Pattern list */}
      {patterns.length === 0 ? (
        <div className="rounded-control border border-border-faint bg-bg-deep px-4 py-6 text-center">
          <p className="text-body-default text-text-faint">
            No groups synced until configured
          </p>
          <p className="mt-1 text-xs text-text-faint">
            Add patterns below to start auto-syncing groups
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {patterns.map((pattern, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-xs text-text-muted"
            >
              {pattern}
              <button
                onClick={() => removePattern(i)}
                className="ml-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-badge text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
              >
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Add input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder='e.g. "Engineering*" or "Procurement-*"'
          className="flex-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
        <button
          onClick={addPattern}
          disabled={!inputValue.trim()}
          className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
        >
          <Plus size={12} />
          Add
        </button>
      </div>

      {/* Save button */}
      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={updateMutation.isPending}
          className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
        >
          {updateMutation.isPending && (
            <Loader2 size={14} className="animate-spin" />
          )}
          Save Patterns
        </button>
      </div>
    </div>
  );
}
