"use client";

import { cn } from "@/lib/utils";
import type { JobRunRow } from "@/lib/hooks/useJobHistory";

const STATUS_STYLES: Record<
  JobRunRow["status"],
  { label: string; className: string }
> = {
  completed: {
    label: "Completed",
    className: "bg-accent-dim text-accent",
  },
  running: {
    label: "Running",
    className: "bg-warn-dim text-warn",
  },
  failed: {
    label: "Failed",
    className: "bg-alert-dim text-alert",
  },
  abandoned: {
    label: "Abandoned",
    className: "bg-bg-elevated text-text-muted",
  },
  skipped: {
    label: "Skipped",
    className: "bg-bg-elevated text-text-faint",
  },
};

export function JobStatusBadge({ status }: { status: JobRunRow["status"] }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.skipped;
  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider",
        style.className,
      )}
    >
      {style.label}
    </span>
  );
}
