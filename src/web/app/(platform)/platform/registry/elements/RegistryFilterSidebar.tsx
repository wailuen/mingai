"use client";

import { cn } from "@/lib/utils";
import type { KYBLevel } from "@/lib/hooks/useRegistry";

// ---------------------------------------------------------------------------
// Static option lists — extend as needed
// ---------------------------------------------------------------------------

const INDUSTRIES = [
  "Finance",
  "Healthcare",
  "Legal",
  "HR",
  "Procurement",
  "Logistics",
  "Insurance",
  "Real Estate",
  "Retail",
  "Technology",
];

const TRANSACTION_TYPES = [
  "Invoice",
  "Contract",
  "Onboarding",
  "Compliance",
  "Payment",
  "Report",
  "Approval",
  "Audit",
];

const LANGUAGES = ["en", "zh", "ms", "ta", "id", "th", "vi", "ja", "ko"];

const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  zh: "Chinese",
  ms: "Malay",
  ta: "Tamil",
  id: "Indonesian",
  th: "Thai",
  vi: "Vietnamese",
  ja: "Japanese",
  ko: "Korean",
};

const KYB_LEVELS: { value: KYBLevel; label: string }[] = [
  { value: "none", label: "None" },
  { value: "basic", label: "Basic" },
  { value: "verified", label: "Verified" },
  { value: "enterprise", label: "Enterprise" },
];

export interface RegistryFilterState {
  industry: string;
  transaction_type: string;
  language: string;
  kyb_level: KYBLevel | "";
}

interface FilterChipProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

function FilterChip({ label, active, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-control border px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "border-accent bg-accent-dim text-accent"
          : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
      )}
    >
      {label}
    </button>
  );
}

interface FilterGroupProps {
  title: string;
  children: React.ReactNode;
}

function FilterGroup({ title, children }: FilterGroupProps) {
  return (
    <div className="mb-5">
      <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
        {title}
      </p>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

interface RegistryFilterSidebarProps {
  filters: RegistryFilterState;
  onChange: (filters: RegistryFilterState) => void;
  onClear: () => void;
}

export function RegistryFilterSidebar({
  filters,
  onChange,
  onClear,
}: RegistryFilterSidebarProps) {
  const hasActive =
    !!filters.industry ||
    !!filters.transaction_type ||
    !!filters.language ||
    !!filters.kyb_level;

  function toggle<K extends keyof RegistryFilterState>(
    key: K,
    value: RegistryFilterState[K],
  ) {
    onChange({
      ...filters,
      [key]: filters[key] === value ? "" : value,
    });
  }

  return (
    <div className="w-[216px] shrink-0">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-section-heading text-text-primary">Filters</p>
        {hasActive && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-text-faint hover:text-text-muted"
          >
            Clear all
          </button>
        )}
      </div>

      <FilterGroup title="Industry">
        {INDUSTRIES.map((ind) => (
          <FilterChip
            key={ind}
            label={ind}
            active={filters.industry === ind}
            onClick={() => toggle("industry", ind)}
          />
        ))}
      </FilterGroup>

      <FilterGroup title="Transaction Type">
        {TRANSACTION_TYPES.map((tt) => (
          <FilterChip
            key={tt}
            label={tt}
            active={filters.transaction_type === tt}
            onClick={() => toggle("transaction_type", tt)}
          />
        ))}
      </FilterGroup>

      <FilterGroup title="Language">
        {LANGUAGES.map((lang) => (
          <FilterChip
            key={lang}
            label={LANGUAGE_LABELS[lang] ?? lang.toUpperCase()}
            active={filters.language === lang}
            onClick={() => toggle("language", lang)}
          />
        ))}
      </FilterGroup>

      <FilterGroup title="KYB Level">
        {KYB_LEVELS.map(({ value, label }) => (
          <FilterChip
            key={value}
            label={label}
            active={filters.kyb_level === value}
            onClick={() => toggle("kyb_level", value)}
          />
        ))}
      </FilterGroup>
    </div>
  );
}
