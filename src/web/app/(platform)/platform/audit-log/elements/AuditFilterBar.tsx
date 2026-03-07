"use client";

import type { AuditLogFilters } from "@/lib/hooks/useAuditLog";

interface AuditFilterBarProps {
  filters: AuditLogFilters;
  onFiltersChange: (filters: AuditLogFilters) => void;
  onApply: () => void;
  onClear: () => void;
}

const ACTOR_TYPES = [
  { value: "", label: "All Actors" },
  { value: "platform_admin", label: "Platform Admin" },
  { value: "tenant_admin", label: "Tenant Admin" },
  { value: "system", label: "System" },
] as const;

const ACTION_CATEGORIES = [
  { value: "", label: "All Actions" },
  { value: "auth", label: "Authentication" },
  { value: "tenant", label: "Tenant Management" },
  { value: "user", label: "User Management" },
  { value: "config", label: "Configuration" },
  { value: "data", label: "Data Operations" },
] as const;

export function AuditFilterBar({
  filters,
  onFiltersChange,
  onApply,
  onClear,
}: AuditFilterBarProps) {
  function updateFilter(key: keyof AuditLogFilters, value: string) {
    onFiltersChange({ ...filters, [key]: value || undefined });
  }

  return (
    <div className="flex flex-wrap items-end gap-3">
      {/* Actor type */}
      <div className="flex flex-col gap-1">
        <label className="text-label-nav uppercase tracking-wider text-text-faint">
          Actor
        </label>
        <select
          value={filters.actor_type ?? ""}
          onChange={(e) =>
            updateFilter(
              "actor_type",
              e.target.value as AuditLogFilters["actor_type"] & string,
            )
          }
          className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-[13px] text-text-primary outline-none transition-colors focus:border-accent-ring"
        >
          {ACTOR_TYPES.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Action category */}
      <div className="flex flex-col gap-1">
        <label className="text-label-nav uppercase tracking-wider text-text-faint">
          Action
        </label>
        <select
          value={filters.action_category ?? ""}
          onChange={(e) => updateFilter("action_category", e.target.value)}
          className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-[13px] text-text-primary outline-none transition-colors focus:border-accent-ring"
        >
          {ACTION_CATEGORIES.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Tenant */}
      <div className="flex flex-col gap-1">
        <label className="text-label-nav uppercase tracking-wider text-text-faint">
          Tenant
        </label>
        <input
          type="text"
          placeholder="Tenant ID"
          value={filters.tenant_id ?? ""}
          onChange={(e) => updateFilter("tenant_id", e.target.value)}
          className="w-36 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-[13px] text-text-primary placeholder:text-text-faint outline-none transition-colors focus:border-accent-ring"
        />
      </div>

      {/* Date from */}
      <div className="flex flex-col gap-1">
        <label className="text-label-nav uppercase tracking-wider text-text-faint">
          From
        </label>
        <input
          type="date"
          value={filters.from ?? ""}
          onChange={(e) => updateFilter("from", e.target.value)}
          className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-[13px] text-text-primary outline-none transition-colors focus:border-accent-ring"
        />
      </div>

      {/* Date to */}
      <div className="flex flex-col gap-1">
        <label className="text-label-nav uppercase tracking-wider text-text-faint">
          To
        </label>
        <input
          type="date"
          value={filters.to ?? ""}
          onChange={(e) => updateFilter("to", e.target.value)}
          className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-[13px] text-text-primary outline-none transition-colors focus:border-accent-ring"
        />
      </div>

      {/* Actions */}
      <button
        type="button"
        onClick={onApply}
        className="rounded-control bg-accent px-4 py-1.5 text-[13px] font-semibold text-bg-base transition-opacity hover:opacity-90"
      >
        Apply Filters
      </button>
      <button
        type="button"
        onClick={onClear}
        className="px-2 py-1.5 text-[13px] text-text-muted transition-colors hover:text-text-primary"
      >
        Clear
      </button>
    </div>
  );
}
