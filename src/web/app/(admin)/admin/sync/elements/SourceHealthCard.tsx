"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { FreshnessIndicator } from "./FreshnessIndicator";
import { ScheduleConfigForm } from "./ScheduleConfigForm";
import { ReindexButton } from "./ReindexButton";
import { useTriggerSync } from "@/lib/hooks/useSyncHealth";
import type { Integration } from "@/lib/hooks/useSyncHealth";

interface SourceHealthCardProps {
  integration: Integration;
  isSelected: boolean;
  onSelect: (id: string) => void;
}

function formatSyncDate(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function SourceHealthCard({
  integration,
  isSelected,
  onSelect,
}: SourceHealthCardProps) {
  const triggerSync = useTriggerSync();
  const isSyncing =
    triggerSync.isPending && triggerSync.variables === integration.id;

  function handleSync(e: React.MouseEvent) {
    e.stopPropagation();
    triggerSync.mutate(integration.id);
  }

  return (
    <button
      type="button"
      onClick={() => onSelect(integration.id)}
      className={`w-full rounded-card border p-5 text-left transition-colors ${
        isSelected
          ? "border-accent bg-accent-dim"
          : "border-border bg-bg-surface hover:border-accent-ring"
      }`}
    >
      {/* Row 1: Name + Freshness + Sync button */}
      <div className="flex items-center justify-between gap-3">
        <h3 className="truncate text-[15px] font-semibold text-text-primary">
          {integration.name}
        </h3>
        <div className="flex items-center gap-3">
          <FreshnessIndicator lastSyncAt={integration.last_sync_at} />
          <button
            type="button"
            onClick={handleSync}
            disabled={isSyncing}
            className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-40"
          >
            {isSyncing ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <RefreshCw size={12} />
            )}
            Sync Now
          </button>
        </div>
      </div>

      {/* Row 2: Site URL */}
      <p className="mt-2 truncate font-mono text-body-default text-text-muted">
        {integration.site_url}
      </p>

      {/* Row 3: Library + Last synced */}
      <div className="mt-1 flex items-center gap-2 text-xs text-text-muted">
        <span className="font-mono">{integration.library_name}</span>
        <span className="text-text-faint">&middot;</span>
        <span>
          Last synced:{" "}
          <span className="font-mono">
            {formatSyncDate(integration.last_sync_at)}
          </span>
        </span>
      </div>

      {/* Row 4: Last status */}
      {integration.last_sync_status && (
        <p className="mt-1 text-xs text-text-faint">
          Last status:{" "}
          <span className="font-mono">{integration.last_sync_status}</span>
        </p>
      )}

      {/* Expanded controls when selected */}
      {isSelected && (
        <div
          className="mt-4 space-y-4 border-t border-border-faint pt-4"
          onClick={(e) => e.stopPropagation()}
        >
          <ScheduleConfigForm
            syncJobId={integration.id}
            currentFrequency="daily"
            onSave={() => {}}
          />
          <ReindexButton
            integrationId={integration.id}
            documentCount={0}
          />
        </div>
      )}
    </button>
  );
}
