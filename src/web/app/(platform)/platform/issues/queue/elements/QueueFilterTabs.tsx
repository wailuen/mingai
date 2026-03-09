"use client";

import { cn } from "@/lib/utils";
import type { QueueFilter } from "@/lib/hooks/useEngineeringIssues";

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

interface TabDef {
  value: QueueFilter;
  label: string;
  showBadge?: boolean;
}

const TABS: TabDef[] = [
  { value: "incoming", label: "Incoming" },
  { value: "triaged", label: "Triaged" },
  { value: "in_progress", label: "In Progress" },
  { value: "sla_at_risk", label: "SLA At-Risk", showBadge: true },
  { value: "resolved", label: "Resolved" },
];

// ---------------------------------------------------------------------------
// QueueFilterTabs
// ---------------------------------------------------------------------------

interface QueueFilterTabsProps {
  activeFilter: QueueFilter;
  onFilterChange: (filter: QueueFilter) => void;
  counts: Record<QueueFilter, number> | undefined;
}

export function QueueFilterTabs({
  activeFilter,
  onFilterChange,
  counts,
}: QueueFilterTabsProps) {
  return (
    <div className="flex items-center border-b border-border">
      {TABS.map((tab) => {
        const isActive = activeFilter === tab.value;
        const count = counts?.[tab.value] ?? 0;

        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => onFilterChange(tab.value)}
            className={cn(
              "relative border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
              isActive
                ? "border-b-accent text-text-primary"
                : "border-b-transparent text-text-faint hover:text-accent",
            )}
          >
            {tab.label}

            {/* Count badge */}
            {count > 0 && (
              <span
                className={cn(
                  "ml-1.5 inline-flex min-w-[18px] items-center justify-center rounded-full px-1 py-0.5 font-mono text-[10px] font-semibold leading-none",
                  tab.showBadge
                    ? "bg-alert/15 text-alert"
                    : "bg-bg-elevated text-text-muted",
                )}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
