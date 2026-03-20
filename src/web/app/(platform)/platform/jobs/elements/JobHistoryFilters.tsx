"use client";

import { KNOWN_JOB_NAMES, type JobHistoryFilters } from "@/lib/hooks/useJobHistory";

interface JobHistoryFiltersProps {
  filters: JobHistoryFilters;
  onFiltersChange: (filters: JobHistoryFilters) => void;
  onApply: () => void;
  onClear: () => void;
}

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "completed", label: "Completed" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "abandoned", label: "Abandoned" },
  { value: "skipped", label: "Skipped" },
];

export function JobHistoryFiltersBar({
  filters,
  onFiltersChange,
  onApply,
  onClear,
}: JobHistoryFiltersProps) {
  const setField = (field: keyof JobHistoryFilters, value: string) => {
    onFiltersChange({ ...filters, [field]: value || undefined });
  };

  return (
    <div className="flex flex-wrap items-end gap-3">
      {/* Job name dropdown */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-wider text-text-faint">
          Job
        </label>
        <select
          value={filters.job_name ?? ""}
          onChange={(e) => setField("job_name", e.target.value)}
          className="h-8 min-w-[180px] rounded-control border border-border bg-bg-elevated px-2.5 text-[12px] text-text-primary focus:border-accent-ring focus:outline-none"
        >
          <option value="">All jobs</option>
          {KNOWN_JOB_NAMES.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      {/* Status filter chips */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-wider text-text-faint">
          Status
        </label>
        <div className="flex gap-1.5">
          {STATUS_OPTIONS.filter((s) => s.value !== "").map((opt) => (
            <button
              key={opt.value}
              onClick={() =>
                setField(
                  "status",
                  filters.status === opt.value ? "" : opt.value,
                )
              }
              className={`rounded-control border px-2.5 py-1 text-[11px] transition-colors ${
                filters.status === opt.value
                  ? "border-accent-ring bg-accent-dim text-accent"
                  : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Date range */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-wider text-text-faint">
          From
        </label>
        <input
          type="date"
          value={filters.from_date ?? ""}
          onChange={(e) => setField("from_date", e.target.value)}
          className="h-8 rounded-control border border-border bg-bg-elevated px-2.5 text-[12px] text-text-primary focus:border-accent-ring focus:outline-none"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase tracking-wider text-text-faint">
          To
        </label>
        <input
          type="date"
          value={filters.to_date ?? ""}
          onChange={(e) => setField("to_date", e.target.value)}
          className="h-8 rounded-control border border-border bg-bg-elevated px-2.5 text-[12px] text-text-primary focus:border-accent-ring focus:outline-none"
        />
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={onApply}
          className="h-8 rounded-control bg-accent px-4 text-[12px] font-medium text-bg-base transition-opacity hover:opacity-90"
        >
          Apply
        </button>
        <button
          onClick={onClear}
          className="h-8 rounded-control border border-border px-4 text-[12px] text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
        >
          Clear
        </button>
      </div>
    </div>
  );
}
