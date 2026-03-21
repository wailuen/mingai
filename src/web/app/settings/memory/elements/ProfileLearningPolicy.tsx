"use client";

import { useState } from "react";
import { User } from "lucide-react";

interface ProfileLearningPolicyProps {
  enabled: boolean;
  onToggle: (value: boolean) => void;
  saving: boolean;
}

/**
 * FE-052: Profile learning policy toggle card.
 * Controls whether AI learns from each user's communication style and preferences.
 */
export function ProfileLearningPolicy({
  enabled,
  onToggle,
  saving,
}: ProfileLearningPolicyProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 flex items-center gap-2">
        <User size={18} className="text-accent" />
        <h3 className="text-[15px] font-semibold text-text-primary">
          Profile Learning
        </h3>
      </div>

      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-body-default font-medium text-text-primary">
            Enable profile learning workspace-wide
          </p>
          <p className="mt-1 text-xs text-text-muted">
            When enabled, the AI learns from each user&apos;s communication
            style and preferences to provide more personalized responses.
          </p>
          <span className="mt-2 inline-block text-[11px] text-text-faint">
            Default: On
          </span>
        </div>
        <button
          onClick={() => onToggle(!enabled)}
          disabled={saving}
          className={`relative h-5 w-9 flex-shrink-0 rounded-full transition-colors ${
            enabled ? "bg-accent" : "bg-bg-elevated"
          } ${saving ? "opacity-50" : ""}`}
          role="switch"
          aria-checked={enabled}
          aria-label="Toggle profile learning"
        >
          <span
            className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
              enabled ? "translate-x-4" : "translate-x-0"
            }`}
          />
        </button>
      </div>
    </div>
  );
}
