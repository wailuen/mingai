"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCreateProfile,
  type PlanTier,
  type ProfileSlot,
} from "@/lib/hooks/usePlatformLLMProfiles";

interface CreateProfileModalProps {
  onClose: () => void;
  onCreated: (profileId: string) => void;
}

type Step = 1 | 2;

const PLAN_TIERS: PlanTier[] = ["starter", "professional", "enterprise"];
const SLOTS: ProfileSlot[] = ["chat", "intent", "vision", "agent"];
const SLOT_LABELS: Record<ProfileSlot, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};
const REQUIRED_SLOTS: ProfileSlot[] = ["chat", "intent", "agent"];

export function CreateProfileModal({
  onClose,
  onCreated,
}: CreateProfileModalProps) {
  const [step, setStep] = useState<Step>(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [planTiers, setPlanTiers] = useState<PlanTier[]>([
    "professional",
    "enterprise",
  ]);
  const [nameError, setNameError] = useState<string | null>(null);
  const createMutation = useCreateProfile();

  function togglePlanTier(tier: PlanTier) {
    setPlanTiers((prev) =>
      prev.includes(tier) ? prev.filter((t) => t !== tier) : [...prev, tier],
    );
  }

  function handleNext() {
    if (!name.trim()) {
      setNameError("Profile name is required.");
      return;
    }
    if (name.trim().length > 80) {
      setNameError("Name must be 80 characters or fewer.");
      return;
    }
    setNameError(null);
    setStep(2);
  }

  async function handleCreate() {
    const result = await createMutation.mutateAsync({
      name: name.trim(),
      description: description.trim() || undefined,
      plan_tiers: planTiers,
    });
    onCreated(result.id);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/60">
      <div className="relative w-full max-w-[560px] rounded-card border border-border bg-bg-surface shadow-md">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-section-heading text-text-primary">
            {step === 1
              ? "New Profile — Step 1 of 2"
              : "New Profile — Step 2 of 2"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1.5 text-text-faint hover:bg-bg-elevated"
          >
            <X size={16} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-1 bg-bg-elevated">
          <div
            className="h-full bg-accent transition-all duration-220"
            style={{ width: step === 1 ? "50%" : "100%" }}
          />
        </div>

        {/* Body */}
        <div className="px-6 py-5">
          {step === 1 ? (
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                  Profile Name <span className="text-alert">*</span>
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    if (nameError) setNameError(null);
                  }}
                  maxLength={80}
                  placeholder="e.g. Standard GPT-5 (Professional)"
                  className={cn(
                    "w-full rounded-control border bg-bg-elevated px-3 py-2 text-body-default text-text-primary outline-none focus:border-accent",
                    nameError ? "border-alert" : "border-border",
                  )}
                  autoFocus
                />
                {nameError && (
                  <p className="mt-1 text-[11px] text-alert">{nameError}</p>
                )}
              </div>

              <div>
                <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={300}
                  rows={3}
                  placeholder="Describe the intended use and audience for this profile..."
                  className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary outline-none focus:border-accent"
                />
                <p className="mt-1 text-right text-[11px] text-text-faint">
                  {description.length}/300
                </p>
              </div>

              <div>
                <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
                  Plan Tiers
                </label>
                <div className="flex gap-2">
                  {PLAN_TIERS.map((tier) => {
                    const active = planTiers.includes(tier);
                    return (
                      <button
                        key={tier}
                        type="button"
                        onClick={() => togglePlanTier(tier)}
                        className={cn(
                          "rounded-control border px-3 py-1.5 text-[11px] capitalize transition-colors",
                          active
                            ? "border-accent/40 bg-accent-dim text-accent"
                            : "border-border bg-bg-elevated text-text-muted hover:border-accent/30",
                        )}
                      >
                        {tier}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-body-default text-text-muted">
                Assign models to each slot. Chat and Intent are required to set
                this profile as the platform default.
              </p>
              <div className="rounded-card border border-border-faint bg-bg-elevated divide-y divide-border-faint">
                {SLOTS.map((slot) => {
                  const isRequired = REQUIRED_SLOTS.includes(slot);
                  return (
                    <div
                      key={slot}
                      className="flex items-center justify-between px-4 py-3"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-label-nav uppercase tracking-wider text-text-faint">
                          {SLOT_LABELS[slot]}
                        </span>
                        {isRequired && (
                          <span className="rounded-badge bg-bg-surface px-1.5 py-0.5 text-[10px] text-text-faint">
                            Required
                          </span>
                        )}
                      </div>
                      <span className="text-[11px] text-text-faint">
                        Assign after creation
                      </span>
                    </div>
                  );
                })}
              </div>
              <p className="text-[11px] text-text-faint">
                You can assign slots after creation — a profile can be saved
                without all slots filled.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          {step === 1 ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted hover:bg-bg-elevated"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleNext}
                className="rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base hover:opacity-90"
              >
                Next: Assign Slots →
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setStep(1)}
                className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted hover:bg-bg-elevated"
              >
                ← Back
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={createMutation.isPending}
                className="flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base disabled:opacity-50 hover:opacity-90"
              >
                {createMutation.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Create Profile
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
