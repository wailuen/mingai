"use client";

import {
  CheckCircle2,
  AlertCircle,
  Clock,
  XCircle,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useGoogleDriveConnections,
  useTriggerGoogleDriveSync,
  type GoogleDriveConnection,
  type GoogleDriveConnectionStatus,
} from "@/lib/hooks/useGoogleDrive";
import { Skeleton } from "@/components/shared/LoadingState";

// ---------------------------------------------------------------------------
// Status styling
// ---------------------------------------------------------------------------

function statusConfig(status: GoogleDriveConnectionStatus): {
  icon: typeof CheckCircle2;
  badgeClass: string;
  label: string;
} {
  switch (status) {
    case "active":
      return {
        icon: CheckCircle2,
        badgeClass: "border-accent/30 bg-accent/10 text-accent",
        label: "Active",
      };
    case "pending":
      return {
        icon: Clock,
        badgeClass: "border-warn/30 bg-warn/10 text-warn",
        label: "Pending",
      };
    case "error":
      return {
        icon: AlertCircle,
        badgeClass: "border-alert/30 bg-alert/10 text-alert",
        label: "Error",
      };
    case "disabled":
      return {
        icon: XCircle,
        badgeClass: "border-border bg-bg-elevated text-text-muted",
        label: "Disabled",
      };
  }
}

// ---------------------------------------------------------------------------
// ConnectionCard
// ---------------------------------------------------------------------------

function ConnectionCard({ connection }: { connection: GoogleDriveConnection }) {
  const syncMutation = useTriggerGoogleDriveSync();
  const config = statusConfig(connection.status);
  const StatusIcon = config.icon;

  function handleSync() {
    syncMutation.mutate(connection.id);
  }

  return (
    <div className="flex items-center justify-between rounded-card border border-border bg-bg-surface px-5 py-4">
      <div className="flex items-center gap-3">
        <StatusIcon
          size={18}
          className={cn(
            connection.status === "active"
              ? "text-accent"
              : connection.status === "error"
                ? "text-alert"
                : connection.status === "pending"
                  ? "text-warn"
                  : "text-text-faint",
          )}
        />
        <div>
          <span className="text-sm font-medium text-text-primary">
            {connection.name}
          </span>
          <div className="flex items-center gap-2 text-xs text-text-faint">
            <span className="font-mono">{connection.folder_id}</span>
            {connection.last_sync_at && (
              <>
                <span>·</span>
                <span>
                  Last sync:{" "}
                  <span className="font-mono text-text-muted">
                    {new Date(connection.last_sync_at).toLocaleString()}
                  </span>
                </span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <span
          className={cn(
            "rounded-sm border px-2 py-0.5 text-xs font-medium",
            config.badgeClass,
          )}
        >
          {syncMutation.isPending ? "Syncing" : config.label}
        </span>
        <button
          onClick={handleSync}
          disabled={
            syncMutation.isPending ||
            connection.status === "disabled" ||
            connection.status === "pending"
          }
          className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
        >
          <RefreshCw
            size={12}
            className={syncMutation.isPending ? "animate-spin" : ""}
          />
          Sync Now
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GoogleDriveConnectionList
// ---------------------------------------------------------------------------

export function GoogleDriveConnectionList() {
  const { data: connections, isPending, error } = useGoogleDriveConnections();

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load Google Drive connections: {error.message}
      </p>
    );
  }

  if (isPending) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <div
            key={i}
            className="rounded-card border border-border bg-bg-surface px-5 py-4"
          >
            <div className="flex items-center gap-3">
              <Skeleton className="h-5 w-5 rounded-full" />
              <div className="flex-1">
                <Skeleton className="mb-2 h-4 w-32" />
                <Skeleton className="h-3 w-48" />
              </div>
              <Skeleton className="h-6 w-20" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (!connections || connections.length === 0) {
    return (
      <div className="rounded-card border border-dashed border-border py-10 text-center">
        <p className="text-sm text-text-faint">
          No Google Drive connections yet.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {connections.map((conn) => (
        <ConnectionCard key={conn.id} connection={conn} />
      ))}
    </div>
  );
}
