"use client";

import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { Skeleton } from "@/components/shared/LoadingState";
import {
  useTeamMemoryConfig,
  useUpdateMemoryConfig,
} from "@/lib/hooks/useTeams";

interface TeamMemoryControlsProps {
  teamId: string;
  memberCount: number;
}

const TTL_OPTIONS = [1, 3, 7, 14, 30] as const;

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(1)} ${units[i]}`;
}

/**
 * FE-039: Team working memory settings.
 *
 * Enable/disable toggle, TTL slider (discrete: 1,3,7,14,30 days),
 * current memory stats, and save button.
 */
export function TeamMemoryControls({
  teamId,
  memberCount,
}: TeamMemoryControlsProps) {
  const { data: config, isLoading } = useTeamMemoryConfig(teamId);
  const updateMutation = useUpdateMemoryConfig();

  const [enabled, setEnabled] = useState(false);
  const [ttlDays, setTtlDays] = useState(7);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (config) {
      setEnabled(config.enabled);
      setTtlDays(config.ttl_days);
    }
  }, [config]);

  async function handleSave() {
    setError("");
    setSaved(false);

    try {
      await updateMutation.mutateAsync({
        teamId,
        payload: { enabled, ttl_days: ttlDays },
      });
      setSaved(true);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to save memory config",
      );
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-4 w-32" />
      </div>
    );
  }

  const ttlIndex = TTL_OPTIONS.indexOf(ttlDays as (typeof TTL_OPTIONS)[number]);
  const sliderValue = ttlIndex >= 0 ? ttlIndex : 2;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[13px] font-semibold text-text-primary">
          Working Memory
        </h3>
        <p className="mt-0.5 text-xs text-text-muted">
          Shared context across team members between sessions
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-sm text-alert">
          {error}
        </div>
      )}

      {/* Success */}
      {saved && (
        <div className="rounded-control border border-accent/30 bg-accent-dim px-3 py-2 text-sm text-accent">
          Memory configuration saved
        </div>
      )}

      {/* Enable/disable toggle */}
      <div className="flex items-center justify-between rounded-control border border-border bg-bg-elevated px-3 py-2.5">
        <span className="text-sm text-text-primary">
          Enable team working memory
        </span>
        <button
          onClick={() => {
            setEnabled(!enabled);
            setSaved(false);
          }}
          className={`relative h-5 w-9 rounded-full transition-colors ${
            enabled ? "bg-accent" : "bg-border"
          }`}
          role="switch"
          aria-checked={enabled}
        >
          <span
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
              enabled ? "left-[18px]" : "left-0.5"
            }`}
          />
        </button>
      </div>

      {/* TTL slider */}
      {enabled && (
        <div>
          <label className="mb-2 block text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
            Retention Period
          </label>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={TTL_OPTIONS.length - 1}
              step={1}
              value={sliderValue}
              onChange={(e) => {
                const idx = Number(e.target.value);
                setTtlDays(TTL_OPTIONS[idx] ?? 7);
                setSaved(false);
              }}
              className="flex-1 accent-accent"
            />
            <span className="w-16 text-right font-mono text-sm text-text-primary">
              {ttlDays}d
            </span>
          </div>
          <div className="mt-1 flex justify-between px-0.5">
            {TTL_OPTIONS.map((opt) => (
              <span
                key={opt}
                className={`font-mono text-[10px] ${
                  opt === ttlDays ? "text-accent" : "text-text-faint"
                }`}
              >
                {opt}d
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Status message */}
      <div className="rounded-control border border-border-faint bg-bg-deep px-3 py-2.5">
        {enabled ? (
          <div className="space-y-1">
            <p className="text-sm text-text-muted">
              Team context shared across{" "}
              <span className="font-mono text-text-primary">{memberCount}</span>{" "}
              members, expires after{" "}
              <span className="font-mono text-text-primary">{ttlDays}</span>{" "}
              days
            </p>
            {config && config.entry_count > 0 && (
              <p className="font-mono text-xs text-text-faint">
                {config.entry_count} entries / {formatBytes(config.size_bytes)}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-text-faint">
            Team members&apos; shared context will not be preserved between
            sessions
          </p>
        )}
      </div>

      {/* Save button */}
      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={updateMutation.isPending}
          className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
        >
          {updateMutation.isPending && (
            <Loader2 size={14} className="animate-spin" />
          )}
          Save
        </button>
      </div>
    </div>
  );
}
