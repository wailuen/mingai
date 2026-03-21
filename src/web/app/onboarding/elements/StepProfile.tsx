"use client";

import { useState } from "react";
import { TimezoneSelector } from "@/app/settings/workspace/elements/TimezoneSelector";

interface StepProfileProps {
  onNext: () => void;
  onBack: () => void;
}

export function StepProfile({ onNext, onBack }: StepProfileProps) {
  const [displayName, setDisplayName] = useState("");
  const [timezone, setTimezone] = useState("UTC");

  const canProceed = displayName.trim().length > 0;

  return (
    <div className="space-y-6 py-4">
      <div>
        <h2 className="text-section-heading text-text-primary">
          Set Up Your Profile
        </h2>
        <p className="mt-1 text-body-default text-text-muted">
          Tell us a bit about yourself so we can personalize your experience.
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
            Display Name
          </label>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Your name"
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
          />
        </div>

        <div>
          <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
            Timezone
          </label>
          <TimezoneSelector value={timezone} onChange={setTimezone} />
        </div>
      </div>

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
        >
          Back
        </button>
        <button
          onClick={onNext}
          disabled={!canProceed}
          className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
        >
          Next
        </button>
      </div>
    </div>
  );
}
