"use client";

import { useAgentTemplateVersions } from "@/lib/hooks/useAgentTemplatesAdmin";

interface VersionHistoryProps {
  templateId: string;
}

function formatDateTime(iso: string): string {
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

export function VersionHistory({ templateId }: VersionHistoryProps) {
  const {
    data: versions,
    isPending,
    error,
  } = useAgentTemplateVersions(templateId);

  if (isPending) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-14 animate-pulse rounded-control bg-bg-elevated"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load versions: {error.message}
      </p>
    );
  }

  if (!versions || versions.length === 0) {
    return (
      <p className="text-sm text-text-faint">No version history available.</p>
    );
  }

  return (
    <div>
      <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
        Version History
      </label>
      <div className="space-y-2">
        {versions.map((version) => (
          <div
            key={version.version}
            className="flex items-start gap-3 rounded-control border border-border bg-bg-elevated p-3"
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium text-text-primary">
                v{version.version}
              </span>
              {version.is_current && (
                <span className="rounded-badge bg-accent-dim px-1.5 py-0.5 font-mono text-[10px] uppercase text-accent">
                  Current
                </span>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-text-muted">{version.changelog}</p>
              <p className="mt-1 font-mono text-[11px] text-text-faint">
                {formatDateTime(version.published_at)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
