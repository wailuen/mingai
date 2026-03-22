"use client";

import { ArrowUpRight } from "lucide-react";
import type { EffectiveProfile } from "@/lib/hooks/useLLMProfileConfig";

interface StarterProfileViewProps {
  profile: EffectiveProfile;
}

const SLOT_LABELS: Record<string, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};

const ENTERPRISE_SLOTS = ["vision", "agent"];

export function StarterProfileView({ profile }: StarterProfileViewProps) {
  const availableCount = profile.available_profiles_count;

  return (
    <div className="space-y-6">
      {/* Profile identity */}
      <div>
        <p className="text-body-default font-medium text-text-primary">
          {profile.profile_name}
        </p>
        {profile.description && (
          <p className="mt-0.5 text-body-default text-text-muted">
            {profile.description}
          </p>
        )}
        <p className="mt-1 text-[11px] text-text-faint">
          Managed by platform — no configuration required
        </p>
      </div>

      {/* Slot table */}
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
              const isEnterprise = ENTERPRISE_SLOTS.includes(slot);
              return (
                <tr key={slot} className="border-b border-border-faint">
                  <td className="px-4 py-3">
                    <span className="text-body-default font-medium text-text-muted">
                      {SLOT_LABELS[slot]}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {isEnterprise ? (
                      <span className="rounded-badge bg-bg-elevated px-2 py-0.5 text-[10px] text-text-faint">
                        Enterprise
                      </span>
                    ) : info.model_name ? (
                      <span className="font-mono text-data-value text-text-primary">
                        {info.model_name}
                      </span>
                    ) : (
                      <span className="text-[11px] text-text-faint">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {!isEnterprise && info.provider ? (
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

      {/* Plan gate card */}
      <div className="rounded-card border border-border bg-bg-elevated pl-4 overflow-hidden relative">
        <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent" />
        <div className="py-4 pr-4">
          <p className="text-body-default font-medium text-text-primary">
            Want to choose from additional AI profiles?
          </p>
          <p className="mt-1 text-body-default text-text-muted">
            Upgrade to Professional to select from{" "}
            {availableCount > 0 ? (
              <span className="font-mono text-data-value text-text-primary">
                {availableCount}
              </span>
            ) : (
              "more"
            )}{" "}
            available profiles.
          </p>
          <button
            type="button"
            className="mt-3 inline-flex items-center gap-1.5 rounded-control border border-accent px-3 py-1.5 text-body-default font-medium text-accent transition-colors hover:bg-accent-dim"
          >
            Explore Professional features
            <ArrowUpRight size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
