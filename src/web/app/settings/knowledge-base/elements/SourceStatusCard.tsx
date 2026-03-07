"use client";

import { CheckCircle2, AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface Integration {
  id: string;
  type: "sharepoint" | "googledrive";
  status: "connected" | "disconnected" | "syncing" | "error";
  last_sync: string | null;
  document_count: number;
  error_count: number;
}

/**
 * Per-source status card with status badge, doc count, last sync, error count.
 * "Sync Now" button per card triggers sync and shows progress.
 */
export function SourceStatusCard({
  integration,
}: {
  integration: Integration;
}) {
  const [syncing, setSyncing] = useState(false);
  const queryClient = useQueryClient();

  async function handleSync() {
    setSyncing(true);
    try {
      await apiPost(`/api/v1/sync/trigger`, {
        integration_id: integration.id,
      });
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
    } catch {
      // Error surfaced by API layer
    } finally {
      setSyncing(false);
    }
  }

  const StatusIcon =
    integration.status === "connected"
      ? CheckCircle2
      : integration.status === "error"
        ? AlertCircle
        : integration.status === "syncing" || syncing
          ? Loader2
          : AlertCircle;

  const statusColor =
    integration.status === "connected"
      ? "text-accent"
      : integration.status === "error"
        ? "text-alert"
        : integration.status === "syncing"
          ? "text-warn"
          : "text-text-faint";

  const statusBadge =
    integration.status === "connected"
      ? "border-accent/30 bg-accent/10 text-accent"
      : integration.status === "error"
        ? "border-alert/30 bg-alert/10 text-alert"
        : integration.status === "syncing"
          ? "border-warn/30 bg-warn/10 text-warn"
          : "border-border bg-bg-elevated text-text-muted";

  const label =
    integration.type === "sharepoint" ? "SharePoint" : "Google Drive";

  return (
    <div className="flex items-center justify-between rounded-card border border-border bg-bg-surface px-5 py-4">
      <div className="flex items-center gap-3">
        <StatusIcon
          size={18}
          className={cn(
            statusColor,
            (integration.status === "syncing" || syncing) && "animate-spin",
          )}
        />
        <div>
          <span className="text-sm font-medium text-text-primary">{label}</span>
          <div className="flex items-center gap-2 text-xs text-text-faint">
            <span className="font-mono">
              {integration.document_count.toLocaleString()} documents
            </span>
            {integration.error_count > 0 && (
              <>
                <span>·</span>
                <span className="font-mono text-alert">
                  {integration.error_count} errors
                </span>
              </>
            )}
            {integration.last_sync && (
              <>
                <span>·</span>
                <span>
                  Last sync: {new Date(integration.last_sync).toLocaleString()}
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <span
          className={`rounded-badge border px-2 py-0.5 text-xs font-medium ${statusBadge}`}
        >
          {syncing ? "syncing" : integration.status}
        </span>
        <button
          onClick={handleSync}
          disabled={syncing || integration.status === "syncing"}
          className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
        >
          <RefreshCw size={12} className={syncing ? "animate-spin" : ""} />
          Sync Now
        </button>
      </div>
    </div>
  );
}
