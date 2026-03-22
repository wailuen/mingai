"use client";

import { useState, useEffect } from "react";
import { ChevronDown, Check, Loader2, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  EffectiveProfile,
  AvailableProfile,
} from "@/lib/hooks/useLLMProfileConfig";
import {
  useAvailableProfiles,
  useSelectProfile,
} from "@/lib/hooks/useLLMProfileConfig";
import { BYOLLMSection } from "./BYOLLMSection";

interface EnterpriseProfileViewProps {
  profile: EffectiveProfile;
}

const SLOT_LABELS: Record<string, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};

function formatCost(cost: number | null | undefined): string {
  if (cost == null) return "—";
  return `$${cost.toFixed(4)}/1K queries`;
}

function PlanChip({ tier }: { tier: string }) {
  return (
    <span
      className={cn(
        "rounded-badge px-1.5 py-0.5 text-[10px] capitalize",
        tier === "starter" && "bg-bg-elevated text-text-muted",
        tier === "professional" && "bg-warn-dim text-warn",
        tier === "enterprise" && "bg-accent-dim text-accent",
      )}
    >
      {tier}
    </span>
  );
}

interface ProfilePickerProps {
  currentProfileId: string;
  onSelect: (profile: AvailableProfile) => void;
}

function ProfilePicker({ currentProfileId, onSelect }: ProfilePickerProps) {
  const [open, setOpen] = useState(false);
  const { data: profiles, isPending } = useAvailableProfiles();

  if (isPending) {
    return (
      <div className="flex items-center gap-2 py-1 text-body-default text-text-faint">
        <Loader2 size={13} className="animate-spin" />
        Loading profiles...
      </div>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent/40 hover:text-text-primary"
      >
        Change Profile
        <ChevronDown
          size={13}
          className={cn("transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-20 mt-1 w-72 rounded-card border border-border bg-bg-surface shadow-md">
          {(profiles ?? []).map((p) => {
            const isCurrent = p.id === currentProfileId;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  if (!isCurrent) {
                    onSelect(p);
                    setOpen(false);
                  }
                }}
                disabled={isCurrent}
                className={cn(
                  "flex w-full flex-col gap-1 px-3 py-2.5 text-left transition-colors",
                  isCurrent
                    ? "cursor-default opacity-60"
                    : "hover:bg-accent-dim",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-body-default font-medium text-text-primary">
                    {p.name}
                  </span>
                  {isCurrent && (
                    <Check size={12} className="flex-shrink-0 text-accent" />
                  )}
                </div>
                {p.description && (
                  <p className="text-[11px] text-text-faint">{p.description}</p>
                )}
                <div className="flex items-center gap-1.5">
                  {p.plan_tiers.map((t) => (
                    <PlanChip key={t} tier={t} />
                  ))}
                  <span className="ml-auto font-mono text-data-value text-text-faint">
                    {formatCost(p.estimated_cost_per_1k_queries)}
                  </span>
                </div>
              </button>
            );
          })}
          {(profiles ?? []).length === 0 && (
            <div className="px-3 py-4 text-center text-body-default text-text-faint">
              No available profiles
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ConfirmSwitchDialogProps {
  targetProfile: AvailableProfile;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}

function ConfirmSwitchDialog({
  targetProfile,
  onConfirm,
  onCancel,
  isPending,
}: ConfirmSwitchDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/60">
      <div className="w-full max-w-[420px] rounded-card border border-border bg-bg-surface p-6 shadow-md">
        <h3 className="text-section-heading text-text-primary">
          Switch to {targetProfile.name}?
        </h3>
        <p className="mt-2 text-body-default text-text-muted">
          Your AI responses will use the models in this profile.
        </p>
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {isPending && <Loader2 size={13} className="animate-spin" />}
            Confirm switch
          </button>
        </div>
      </div>
    </div>
  );
}

export function EnterpriseProfileView({ profile }: EnterpriseProfileViewProps) {
  const [pendingProfile, setPendingProfile] = useState<AvailableProfile | null>(
    null,
  );
  const [showBYOLLM, setShowBYOLLM] = useState(profile.is_byollm);
  const selectMutation = useSelectProfile();

  // Sync local view state when the server-side profile changes (e.g. another admin switches it)
  useEffect(() => {
    setShowBYOLLM(profile.is_byollm);
  }, [profile.is_byollm]);

  function handleConfirmSwitch() {
    if (!pendingProfile) return;
    selectMutation.mutate(pendingProfile.id, {
      onSuccess: () => setPendingProfile(null),
    });
  }

  // BYOLLM track — either the active profile is BYOLLM, or the user navigated here via "Configure custom models"
  // showBYOLLM is the sole gate: user can flip to platform view via "Use Platform Profile instead"
  if (showBYOLLM) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-2">
          <span className="rounded-badge bg-accent-dim px-2 py-0.5 text-[10px] text-accent">
            Custom AI Models
          </span>
          <span className="text-body-default font-medium text-text-primary">
            {profile.profile_name}
          </span>
        </div>

        <BYOLLMSection onSwitchToPlatform={() => setShowBYOLLM(false)} />
      </div>
    );
  }

  // Platform track
  return (
    <div className="space-y-6">
      {/* Active profile header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-text-faint">
            Active Profile
          </p>
          <p className="mt-0.5 text-body-default font-medium text-text-primary">
            {profile.profile_name}
          </p>
          {profile.description && (
            <p className="text-body-default text-text-muted">
              {profile.description}
            </p>
          )}
        </div>
        <ProfilePicker
          currentProfileId={profile.profile_id}
          onSelect={setPendingProfile}
        />
      </div>

      {/* All 4 slots — no lock badges */}
      <div className="overflow-x-auto rounded-card border border-border bg-bg-surface">
        <table className="min-w-full">
          <thead className="border-b border-border">
            <tr>
              <th className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Slot
              </th>
              <th className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Model
              </th>
              <th className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Provider
              </th>
            </tr>
          </thead>
          <tbody>
            {(["chat", "intent", "vision", "agent"] as const).map((slot) => {
              const info = profile.slots[slot];
              return (
                <tr key={slot} className="border-b border-border-faint">
                  <td className="px-4 py-3">
                    <span className="text-body-default font-medium text-text-muted">
                      {SLOT_LABELS[slot]}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {info.model_name ? (
                      <span className="font-mono text-data-value text-text-primary">
                        {info.model_name}
                      </span>
                    ) : (
                      <span className="text-[11px] text-text-faint">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {info.provider ? (
                      <span className="rounded-badge bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-muted">
                        {info.provider}
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* BYOLLM section link */}
      <div className="rounded-card border border-border-faint bg-bg-elevated px-4 py-3">
        <p className="text-body-default font-medium text-text-primary">
          Advanced: Bring Your Own LLM
        </p>
        <p className="mt-0.5 text-[11px] text-text-faint">
          Use your own model endpoints instead of the platform-managed profile.
        </p>
        <button
          type="button"
          onClick={() => setShowBYOLLM(true)}
          className="mt-2 flex items-center gap-1.5 text-[11px] text-accent transition-colors hover:opacity-80"
        >
          <Settings2 size={12} />
          Configure custom models
        </button>
      </div>

      {pendingProfile && (
        <ConfirmSwitchDialog
          targetProfile={pendingProfile}
          onConfirm={handleConfirmSwitch}
          onCancel={() => setPendingProfile(null)}
          isPending={selectMutation.isPending}
        />
      )}
    </div>
  );
}
