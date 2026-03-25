"use client";

import { useState } from "react";
import { X, Loader2, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCreateProfile,
  type PlanTier,
} from "@/lib/hooks/usePlatformLLMProfiles";

interface CreateProfileModalProps {
  onClose: () => void;
  onCreated: (profileId: string) => void;
}

const PLAN_TIERS: PlanTier[] = ["starter", "professional", "enterprise"];

export function CreateProfileModal({
  onClose,
  onCreated,
}: CreateProfileModalProps) {
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

  async function handleCreate() {
    if (!name.trim()) {
      setNameError("Profile name is required.");
      return;
    }
    if (name.trim().length > 80) {
      setNameError("Name must be 80 characters or fewer.");
      return;
    }
    setNameError(null);

    const result = await createMutation.mutateAsync({
      name: name.trim(),
      description: description.trim() || undefined,
      plan_tiers: planTiers,
    });
    onCreated(result.id);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/60">
      <div className="relative w-full max-w-[520px] rounded-card border border-border bg-bg-surface shadow-md">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-section-heading text-text-primary">
            New LLM Profile
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1.5 text-text-faint hover:bg-bg-elevated"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          {/* Name */}
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

          {/* Description */}
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

          {/* Plan tiers */}
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

          {/* Slot assignment hint */}
          <div className="flex items-start gap-2 rounded-control border border-border-faint bg-bg-elevated px-3 py-3">
            <Info size={13} className="mt-0.5 shrink-0 text-text-faint" />
            <p className="text-[11px] text-text-faint leading-relaxed">
              After creating the profile, open the detail panel to assign models
              to each slot (Chat, Intent, Vision, Agent).
            </p>
          </div>

          {/* Mutation error */}
          {createMutation.isError && (
            <p className="text-[11px] text-alert">
              Failed to create profile. Please try again.
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted hover:bg-bg-elevated"
          >
            Cancel
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
        </div>
      </div>
    </div>
  );
}
