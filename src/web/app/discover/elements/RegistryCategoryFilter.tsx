"use client";

import { cn } from "@/lib/utils";

const CATEGORIES = [
  "All",
  "HR",
  "IT",
  "Finance",
  "Legal",
  "Procurement",
  "Custom",
] as const;

export type RegistryCategory = (typeof CATEGORIES)[number];

interface RegistryCategoryFilterProps {
  selected: RegistryCategory;
  onSelect: (category: RegistryCategory) => void;
}

/**
 * FE-049: Horizontal chip strip for filtering public registry agents by category.
 */
export function RegistryCategoryFilter({
  selected,
  onSelect,
}: RegistryCategoryFilterProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {CATEGORIES.map((cat) => {
        const isActive = selected === cat;
        return (
          <button
            key={cat}
            type="button"
            onClick={() => onSelect(cat)}
            className={cn(
              "rounded-control border px-3 py-1.5 text-xs font-medium transition-[var(--t)]",
              isActive
                ? "border-accent bg-accent-dim text-accent"
                : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary",
            )}
          >
            {cat}
          </button>
        );
      })}
    </div>
  );
}
