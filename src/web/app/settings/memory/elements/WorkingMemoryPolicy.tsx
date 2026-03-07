"use client";

import { Clock } from "lucide-react";

const TTL_OPTIONS = [
  { value: 1, label: "1 day" },
  { value: 3, label: "3 days" },
  { value: 7, label: "7 days" },
  { value: 14, label: "14 days" },
  { value: 30, label: "30 days" },
];

interface WorkingMemoryPolicyProps {
  enabled: boolean;
  ttlDays: number;
  onToggle: (value: boolean) => void;
  onTtlChange: (days: number) => void;
  saving: boolean;
}

/**
 * FE-052: Working memory policy card.
 * Controls whether working memory is enabled and the TTL window.
 */
export function WorkingMemoryPolicy({
  enabled,
  ttlDays,
  onToggle,
  onTtlChange,
  saving,
}: WorkingMemoryPolicyProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 flex items-center gap-2">
        <Clock size={18} className="text-accent" />
        <h3 className="text-[15px] font-semibold text-text-primary">
          Working Memory
        </h3>
      </div>

      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-text-primary">
              Enable working memory
            </p>
            <p className="mt-1 text-xs text-text-muted">
              Working memory helps the AI remember context across sessions
              within the TTL window.
            </p>
          </div>
          <button
            onClick={() => onToggle(!enabled)}
            disabled={saving}
            className={`relative h-5 w-9 flex-shrink-0 rounded-full transition-colors ${
              enabled ? "bg-accent" : "bg-bg-elevated"
            } ${saving ? "opacity-50" : ""}`}
            role="switch"
            aria-checked={enabled}
            aria-label="Toggle working memory"
          >
            <span
              className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        {/* TTL selector - visible when working memory is on */}
        <div
          style={{
            overflow: "hidden",
            maxHeight: enabled ? "60px" : "0",
            opacity: enabled ? 1 : 0,
            transition: "max-height 220ms ease, opacity 220ms ease",
          }}
        >
          <div className="flex items-center gap-3">
            <label htmlFor="ttl-select" className="text-sm text-text-muted">
              Retain for
            </label>
            <select
              id="ttl-select"
              value={ttlDays}
              onChange={(e) => onTtlChange(Number(e.target.value))}
              disabled={saving || !enabled}
              className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 font-mono text-sm text-text-primary transition-colors focus:border-accent focus:outline-none disabled:opacity-50"
            >
              {TTL_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}
