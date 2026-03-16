"use client";

import { X, Loader2, Plus } from "lucide-react";
import {
  useAgentTemplateVersions,
  useCreateTemplateVersion,
} from "@/lib/hooks/useAgentTemplatesAdmin";

interface VersionHistoryDrawerProps {
  templateId: string;
  onClose: () => void;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: string }) {
  const styles =
    status === "Published"
      ? "bg-accent-dim text-accent"
      : status === "Deprecated"
        ? "bg-alert-dim text-alert"
        : "bg-warn-dim text-warn";

  return (
    <span
      className={`inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase ${styles}`}
    >
      {status}
    </span>
  );
}

export function VersionHistoryDrawer({
  templateId,
  onClose,
}: VersionHistoryDrawerProps) {
  const {
    data: versions,
    isPending,
    error,
  } = useAgentTemplateVersions(templateId);

  const createVersionMutation = useCreateTemplateVersion();

  function handleCreateVersion() {
    createVersionMutation.mutate(templateId);
  }

  return (
    <div className="fixed inset-y-0 right-0 z-[60] flex w-[420px] flex-col border-l border-border bg-bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <h3 className="text-section-heading text-text-primary">
          Version History
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {/* Create new version button */}
        <button
          type="button"
          onClick={handleCreateVersion}
          disabled={createVersionMutation.isPending}
          className="flex w-full items-center justify-center gap-1.5 rounded-control border border-border px-4 py-2 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
        >
          {createVersionMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Plus size={14} />
          )}
          Create New Version
        </button>

        {createVersionMutation.error && (
          <p className="text-xs text-alert">
            {createVersionMutation.error instanceof Error
              ? createVersionMutation.error.message
              : "Failed to create version"}
          </p>
        )}

        {createVersionMutation.isSuccess && (
          <p className="text-xs text-accent">
            New draft version created successfully.
          </p>
        )}

        {/* Loading state */}
        {isPending && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-20 animate-pulse rounded-control bg-bg-elevated"
              />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && (
          <p className="text-sm text-alert">
            Failed to load versions: {error.message}
          </p>
        )}

        {/* Empty state */}
        {versions && versions.length === 0 && (
          <p className="text-sm text-text-faint">
            No version history available.
          </p>
        )}

        {/* Version list */}
        {versions && versions.length > 0 && (
          <div className="space-y-2">
            {versions.map((version) => (
              <div
                key={version.id}
                className="rounded-control border border-border bg-bg-elevated p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-medium text-text-primary">
                    v{version.version}
                  </span>
                  <StatusBadge status={version.status} />
                </div>

                {version.changelog && (
                  <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-text-muted">
                    {version.changelog}
                  </p>
                )}

                {version.system_prompt_preview && (
                  <p className="mt-1 line-clamp-1 font-mono text-[11px] text-text-faint">
                    {version.system_prompt_preview}
                  </p>
                )}

                <p className="mt-2 font-mono text-[11px] text-text-faint">
                  {formatDateTime(version.created_at)}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
