"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPatch } from "@/lib/api";
import { Loader2, Check } from "lucide-react";

interface ScheduleConfigFormProps {
  syncJobId: string;
  currentFrequency: string;
  onSave: () => void;
}

const FREQUENCY_OPTIONS = [
  { value: "hourly", label: "Every hour" },
  { value: "every_6h", label: "Every 6 hours" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
] as const;

/**
 * FE-034: Frequency selector per sync source.
 * Radio group with save button. Calls PATCH /api/v1/sync/{syncJobId}/schedule.
 */
export function ScheduleConfigForm({
  syncJobId,
  currentFrequency,
  onSave,
}: ScheduleConfigFormProps) {
  const [selected, setSelected] = useState(currentFrequency);
  const [showSuccess, setShowSuccess] = useState(false);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () =>
      apiPatch<{ frequency: string }>(
        `/api/v1/sync/${syncJobId}/schedule`,
        { frequency: selected },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["sharepoint-integrations"],
      });
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 2000);
      onSave();
    },
  });

  const hasChanged = selected !== currentFrequency;

  return (
    <div className="space-y-3">
      <h4 className="text-label-nav uppercase tracking-wider text-text-faint">
        Sync Schedule
      </h4>

      <div className="space-y-2">
        {FREQUENCY_OPTIONS.map((opt) => (
          <label
            key={opt.value}
            className="flex cursor-pointer items-center gap-2.5 rounded-control border border-border-faint px-3 py-2 transition-colors hover:bg-bg-elevated"
          >
            <input
              type="radio"
              name={`freq-${syncJobId}`}
              value={opt.value}
              checked={selected === opt.value}
              onChange={() => setSelected(opt.value)}
              className="accent-[var(--accent)]"
            />
            <span className="text-sm text-text-primary">{opt.label}</span>
          </label>
        ))}
      </div>

      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={!hasChanged || mutation.isPending}
        className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
      >
        {mutation.isPending ? (
          <Loader2 size={14} className="animate-spin" />
        ) : showSuccess ? (
          <Check size={14} />
        ) : null}
        {showSuccess ? "Saved" : "Save Schedule"}
      </button>

      {mutation.isError && (
        <p className="text-xs text-alert">
          Failed to update schedule. Please try again.
        </p>
      )}
    </div>
  );
}
