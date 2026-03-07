"use client";

const CATEGORIES = ["All", "HR", "IT", "Procurement", "Onboarding"] as const;

interface AgentFilterBarProps {
  selected: string;
  onSelect: (category: string) => void;
}

export function AgentFilterBar({ selected, onSelect }: AgentFilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {CATEGORIES.map((cat) => {
        const value = cat === "All" ? "" : cat;
        const isActive = selected === value;

        return (
          <button
            key={cat}
            onClick={() => onSelect(value)}
            className={`rounded-control px-3 py-1.5 text-sm transition-colors ${
              isActive
                ? "border border-accent-ring bg-accent-dim text-text-primary"
                : "border border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary"
            }`}
          >
            {cat}
          </button>
        );
      })}
    </div>
  );
}
