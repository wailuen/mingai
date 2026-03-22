"use client";

import { useState } from "react";
import { Plus, Star, Cpu } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { cn } from "@/lib/utils";
import {
  useProfileList,
  type PlatformProfile,
  type ProfileSlot,
  type ProfileStatus,
} from "@/lib/hooks/usePlatformLLMProfiles";
import { CreateProfileModal } from "./elements/CreateProfileModal";
import { ProfileDetailPanel } from "./elements/ProfileDetailPanel";

const SLOTS: ProfileSlot[] = ["chat", "intent", "vision", "agent"];
const SLOT_LABELS: Record<ProfileSlot, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};

function StatusBadge({ status }: { status: ProfileStatus }) {
  return (
    <span
      className={cn(
        "rounded-badge px-1.5 py-0.5 text-[10px] uppercase tracking-wider",
        status === "active" && "bg-accent-dim text-accent",
        status === "draft" && "bg-bg-elevated text-text-muted",
        status === "deprecated" && "bg-alert-dim text-alert",
      )}
    >
      {status}
    </span>
  );
}

function PlanChips({ tiers }: { tiers: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {tiers.map((tier) => (
        <span
          key={tier}
          className={cn(
            "rounded-badge px-1.5 py-0.5 text-[10px] capitalize",
            tier === "starter" && "bg-bg-elevated text-text-muted",
            tier === "professional" && "bg-warn-dim text-warn",
            tier === "enterprise" && "bg-accent-dim text-accent",
          )}
        >
          {tier}
        </span>
      ))}
    </div>
  );
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 8 }).map((_, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

interface ProfileTableProps {
  onRowClick: (profile: PlatformProfile) => void;
}

function ProfileTable({ onRowClick }: ProfileTableProps) {
  const { data, isPending, error } = useProfileList();

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load LLM profiles: {error.message}
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-card border border-border bg-bg-surface">
      <table className="min-w-full">
        <thead className="border-b border-border">
          <tr>
            <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Name
            </th>
            {SLOTS.map((slot) => (
              <th
                key={slot}
                className="hidden px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint md:table-cell"
              >
                {SLOT_LABELS[slot]}
              </th>
            ))}
            <th className="hidden px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint sm:table-cell">
              Plans
            </th>
            <th className="hidden px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint sm:table-cell">
              Tenants
            </th>
            <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {isPending && <SkeletonRows />}

          {!isPending && data && data.length === 0 && (
            <tr>
              <td colSpan={9} className="py-16 text-center">
                <div className="flex flex-col items-center gap-3">
                  <Cpu size={24} className="text-text-faint" />
                  <p className="text-body-default font-medium text-text-muted">
                    No LLM profiles yet
                  </p>
                  <p className="text-body-default text-text-faint">
                    Create a profile to configure AI models for your tenants.
                  </p>
                </div>
              </td>
            </tr>
          )}

          {(data ?? []).map((profile) => (
            <tr
              key={profile.id}
              onClick={() => onRowClick(profile)}
              className="cursor-pointer border-b border-border-faint transition-colors hover:bg-accent-dim"
            >
              {/* Name + default star */}
              <td className="px-3.5 py-3">
                <div className="flex items-center gap-2">
                  <span className="text-body-default font-medium text-text-primary">
                    {profile.name}
                  </span>
                  {profile.is_platform_default && (
                    <Star
                      size={12}
                      className="flex-shrink-0 text-accent fill-accent"
                    />
                  )}
                </div>
              </td>

              {/* Slot columns */}
              {SLOTS.map((slot) => (
                <td key={slot} className="hidden px-3.5 py-3 md:table-cell">
                  {profile.slots[slot] ? (
                    <span className="font-mono text-data-value text-text-muted truncate max-w-[120px] block">
                      {profile.slots[slot]!.model_name}
                    </span>
                  ) : (
                    <span className="text-[11px] text-text-faint">—</span>
                  )}
                </td>
              ))}

              {/* Plan tiers */}
              <td className="hidden px-3.5 py-3 sm:table-cell">
                <PlanChips tiers={profile.plan_tiers} />
              </td>

              {/* Tenant count */}
              <td className="hidden px-3.5 py-3 sm:table-cell">
                <span className="font-mono text-data-value text-text-muted">
                  {profile.tenants_count}
                </span>
              </td>

              {/* Status */}
              <td className="px-3.5 py-3">
                <StatusBadge status={profile.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {data && data.length > 0 && (
        <div className="border-t border-border-faint px-5 py-2.5">
          <p className="font-mono text-data-value text-text-faint">
            {data.length} profile{data.length !== 1 ? "s" : ""}
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * TODO-35: Platform Admin LLM Profiles page with slot-based design.
 * Lists all platform profiles with Chat/Intent/Vision/Agent slots.
 * Row click opens ProfileDetailPanel. New Profile button opens CreateProfileModal.
 */
export default function LLMProfilesPage() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(
    null,
  );

  return (
    <AppShell>
      <div className="p-7">
        {/* Mobile banner */}
        <div className="md:hidden mb-4 rounded-card border border-warn/30 bg-warn-dim p-4">
          <p className="text-body-default text-warn">
            Desktop recommended for managing LLM profiles.
          </p>
        </div>

        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">LLM Profiles</h1>
            <p className="mt-1 text-body-default text-text-muted">
              Configure AI model slot assignments for tenant workspaces
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Profile
          </button>
        </div>

        {/* Profile table */}
        <ErrorBoundary>
          <ProfileTable onRowClick={(p) => setSelectedProfileId(p.id)} />
        </ErrorBoundary>
      </div>

      {/* Create modal */}
      {showCreateModal && (
        <CreateProfileModal
          onClose={() => setShowCreateModal(false)}
          onCreated={(id) => {
            setShowCreateModal(false);
            setSelectedProfileId(id);
          }}
        />
      )}

      {/* Detail panel */}
      {selectedProfileId && (
        <ProfileDetailPanel
          profileId={selectedProfileId}
          onClose={() => setSelectedProfileId(null)}
        />
      )}
    </AppShell>
  );
}
