"use client";

import { cn } from "@/lib/utils";
import { useAgentTemplateVersions } from "@/lib/hooks/useAgentTemplatesAdmin";

interface VersionHistoryTabProps {
  templateId: string;
}

type ChangeType = "Initial" | "Patch" | "Minor" | "Major";

function ChangeTypeBadge({ type }: { type: ChangeType }) {
  const styles: Record<ChangeType, string> = {
    Initial: "bg-bg-elevated text-text-muted",
    Patch: "bg-accent-dim text-accent",
    Minor: "bg-warn-dim text-warn",
    Major: "bg-alert-dim text-alert",
  };

  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        styles[type],
      )}
    >
      {type}
    </span>
  );
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function VersionHistoryTab({ templateId }: VersionHistoryTabProps) {
  const { data: versions, isPending, error } = useAgentTemplateVersions(templateId);

  if (isPending) {
    return (
      <div className="space-y-3 p-5">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-20 w-full animate-pulse rounded-card bg-bg-elevated"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p className="p-5 text-body-default text-alert">
        Failed to load version history: {error.message}
      </p>
    );
  }

  if (!versions || versions.length === 0) {
    return (
      <p className="p-5 text-body-default text-text-faint">
        No published versions yet.
      </p>
    );
  }

  return (
    <div className="p-5">
      <div className="relative">
        {/* Timeline line */}
        <div className="absolute left-[9px] top-2 bottom-2 w-px bg-border" />

        <ul className="space-y-5">
          {versions.map((v, i) => {
            const changeType: ChangeType =
              (v.change_type as ChangeType | undefined) ??
              (i === versions.length - 1 ? "Initial" : "Patch");

            return (
              <li key={v.id} className="flex gap-4">
                {/* Timeline dot */}
                <div className="relative mt-1 flex h-5 w-5 flex-shrink-0 items-center justify-center">
                  <div
                    className={cn(
                      "h-3 w-3 rounded-full border-2",
                      changeType === "Major"
                        ? "border-alert bg-alert-dim"
                        : changeType === "Minor"
                          ? "border-warn bg-warn-dim"
                          : changeType === "Initial"
                            ? "border-text-muted bg-bg-elevated"
                            : "border-accent bg-accent-dim",
                    )}
                  />
                </div>

                {/* Content */}
                <div className="flex-1 pb-1">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <span className="font-mono text-data-value text-accent">
                      v{v.version_label ?? v.version}
                    </span>
                    <ChangeTypeBadge type={changeType} />
                    <span className="font-mono text-[11px] text-text-faint">
                      {formatDate(v.created_at)}
                    </span>
                    {v.publisher && (
                      <span className="text-[11px] text-text-faint">
                        by {v.publisher}
                      </span>
                    )}
                  </div>

                  {v.changelog && (
                    <p className="text-body-default text-text-muted">
                      {v.changelog}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
