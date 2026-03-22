"use client";

import { useState } from "react";
import {
  X,
  Star,
  Loader2,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  RotateCcw,
  History,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useProfileDetail,
  useProfileTenants,
  useUpdateProfile,
  useAssignSlot,
  useSetDefault,
  useTestProfile,
  useProfileHistory,
  useRollbackProfile,
  type PlatformProfile,
  type ProfileSlot,
  type AvailableModel,
  type SlotTestResult,
  type ProfileHistoryEntry,
} from "@/lib/hooks/usePlatformLLMProfiles";
import { SlotSelector } from "./SlotSelector";

const SLOT_LABELS: Record<ProfileSlot, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};

const SLOTS: ProfileSlot[] = ["chat", "intent", "vision", "agent"];
const REQUIRED_SLOTS: ProfileSlot[] = ["chat", "intent", "agent"];

function StatusBadge({ status }: { status: PlatformProfile["status"] }) {
  return (
    <span
      className={cn(
        "rounded-badge px-2 py-0.5 text-[10px] uppercase tracking-wider",
        status === "active" && "bg-accent-dim text-accent",
        status === "draft" && "bg-bg-elevated text-text-muted",
        status === "deprecated" && "bg-alert-dim text-alert",
      )}
    >
      {status}
    </span>
  );
}

function PlanChip({ tier }: { tier: string }) {
  return (
    <span
      className={cn(
        "rounded-badge px-1.5 py-0.5 text-[10px]",
        tier === "starter" && "bg-bg-elevated text-text-muted",
        tier === "professional" && "bg-warn-dim text-warn",
        tier === "enterprise" && "bg-accent-dim text-accent",
      )}
    >
      {tier}
    </span>
  );
}

function LatencyValue({ ms }: { ms: number }) {
  return (
    <span
      className={cn(
        "font-mono text-data-value",
        ms < 1000 && "text-accent",
        ms >= 1000 && ms <= 3000 && "text-warn",
        ms > 3000 && "text-alert",
      )}
    >
      {ms}ms
    </span>
  );
}

function formatTestAge(iso: string | null): string {
  if (!iso) return "Not tested";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `Tested ${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `Tested ${hrs}h ago`;
  return `Tested ${Math.floor(hrs / 24)}d ago`;
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

interface SlotRowProps {
  slot: ProfileSlot;
  profile: PlatformProfile;
  onAssignRequested: (slot: ProfileSlot) => void;
}

function SlotRow({ slot, profile, onAssignRequested }: SlotRowProps) {
  const assignment = profile.slots[slot];
  const isRequired = REQUIRED_SLOTS.includes(slot);

  return (
    <div className="flex items-center justify-between gap-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="w-14 text-label-nav uppercase tracking-wider text-text-faint">
          {SLOT_LABELS[slot]}
        </span>
        {isRequired && (
          <span className="rounded-badge bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-faint">
            Required
          </span>
        )}
      </div>

      {assignment ? (
        <div className="flex flex-1 items-center justify-between gap-2">
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "h-2 w-2 flex-shrink-0 rounded-full",
                  assignment.health_status === "healthy" && "bg-accent",
                  assignment.health_status === "unknown" && "bg-warn",
                  assignment.health_status === "degraded" && "bg-alert",
                )}
              />
              <span className="font-mono text-data-value text-text-primary truncate">
                {assignment.model_name}
              </span>
              <span className="text-[11px] text-text-faint flex-shrink-0">
                {formatTestAge(assignment.test_passed_at)}
              </span>
            </div>
            {(assignment.pricing_per_1k_tokens_in !== null ||
              assignment.pricing_per_1k_tokens_out !== null) && (
              <span className="ml-4 font-mono text-[10px] text-text-faint">
                {assignment.pricing_per_1k_tokens_in !== null &&
                  `$${assignment.pricing_per_1k_tokens_in}/1k in`}
                {assignment.pricing_per_1k_tokens_in !== null &&
                  assignment.pricing_per_1k_tokens_out !== null &&
                  " · "}
                {assignment.pricing_per_1k_tokens_out !== null &&
                  `$${assignment.pricing_per_1k_tokens_out}/1k out`}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => onAssignRequested(slot)}
            className="flex-shrink-0 rounded-control border border-border px-2.5 py-1 text-[11px] text-text-muted hover:bg-bg-elevated"
          >
            Change
          </button>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-between gap-2">
          <span className="text-[11px] text-text-faint">Not assigned</span>
          <button
            type="button"
            onClick={() => onAssignRequested(slot)}
            className="flex-shrink-0 rounded-control border border-accent/40 px-2.5 py-1 text-[11px] text-accent hover:bg-accent-dim"
          >
            Assign
          </button>
        </div>
      )}
    </div>
  );
}

interface ProfileDetailPanelProps {
  profileId: string;
  onClose: () => void;
}

export function ProfileDetailPanel({
  profileId,
  onClose,
}: ProfileDetailPanelProps) {
  const {
    data: profile,
    isPending,
    error,
    refetch,
  } = useProfileDetail(profileId);
  const { data: tenants } = useProfileTenants(profileId);
  const updateMutation = useUpdateProfile();
  const assignSlotMutation = useAssignSlot();
  const setDefaultMutation = useSetDefault();
  const testMutation = useTestProfile();

  const { data: history } = useProfileHistory(profileId);
  const rollbackMutation = useRollbackProfile();

  const [assigningSlot, setAssigningSlot] = useState<ProfileSlot | null>(null);
  const [editName, setEditName] = useState<string | null>(null);
  const [editDesc, setEditDesc] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<SlotTestResult[] | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [showTenants, setShowTenants] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [rollbackConfirmId, setRollbackConfirmId] = useState<string | null>(null);

  const isDirtyName = editName !== null && editName !== (profile?.name ?? "");
  const isDirtyDesc =
    editDesc !== null && editDesc !== (profile?.description ?? "");
  const isDirty = isDirtyName || isDirtyDesc;

  if (isPending) {
    return (
      <aside className="fixed right-0 top-0 z-40 flex h-full w-[480px] flex-col border-l border-border bg-bg-surface">
        <div className="flex h-full items-center justify-center">
          <Loader2 size={24} className="animate-spin text-text-faint" />
        </div>
      </aside>
    );
  }

  if (error || !profile) {
    return (
      <aside className="fixed right-0 top-0 z-40 flex h-full w-[480px] flex-col border-l border-border bg-bg-surface">
        <div className="flex h-full flex-col items-center justify-center gap-3 p-6">
          <AlertTriangle size={24} className="text-alert" />
          <p className="text-body-default text-text-muted">
            Failed to load profile.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-control border border-border px-3 py-1.5 text-[11px] text-text-muted hover:bg-bg-elevated"
          >
            Retry
          </button>
        </div>
      </aside>
    );
  }

  const hasRequiredSlots = REQUIRED_SLOTS.every(
    (s) => profile.slots[s] !== null,
  );
  const tenantsCount = tenants?.length ?? profile.tenants_count;
  const canDeprecate = tenantsCount === 0 && profile.status === "active";

  async function handleSave() {
    const payload: Record<string, string> = {};
    if (isDirtyName && editName !== null) payload.name = editName;
    if (isDirtyDesc && editDesc !== null) payload.description = editDesc;
    await updateMutation.mutateAsync({ id: profileId, payload });
    setEditName(null);
    setEditDesc(null);
  }

  async function handleSlotSelect(slot: ProfileSlot, model: AvailableModel) {
    await assignSlotMutation.mutateAsync({
      profileId,
      slot,
      payload: { library_entry_id: model.library_entry_id },
    });
    setAssigningSlot(null);
  }

  async function handleSetDefault() {
    await setDefaultMutation.mutateAsync(profileId);
  }

  async function handleDeprecate() {
    // profile is guaranteed non-null here — early return guard at line 201 handles !profile
    if (!window.confirm(`Deprecate profile "${profile!.name}"?`)) return;
    await updateMutation.mutateAsync({
      id: profileId,
      payload: { status: "deprecated" },
    });
  }

  async function handleTestAll() {
    setTestResults(null);
    setTestError(null);
    testMutation.mutate(profileId, {
      onSuccess: (data) => setTestResults(data.results),
      onError: () =>
        setTestError("Test failed. Check your slot assignments and try again."),
    });
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-30 bg-bg-base/40" onClick={onClose} />

      {/* Panel */}
      <aside className="fixed right-0 top-0 z-40 flex h-full w-[480px] flex-col border-l border-border bg-bg-surface animate-slide-in-right">
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-border px-5 py-3.5">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-section-heading text-text-primary truncate">
              {editName !== null ? editName : profile.name}
            </span>
            <StatusBadge status={profile.status} />
            {profile.is_platform_default && (
              <Star
                size={14}
                className="flex-shrink-0 text-accent fill-accent"
              />
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-2 flex-shrink-0 rounded-control p-1.5 text-text-faint hover:bg-bg-elevated"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body (scrollable) */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Identity section */}
          <section>
            <p className="mb-3 text-label-nav uppercase tracking-wider text-text-faint">
              Profile Details
            </p>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-[11px] text-text-faint">
                  Name
                </label>
                <input
                  type="text"
                  value={editName !== null ? editName : profile.name}
                  onChange={(e) => setEditName(e.target.value)}
                  onFocus={() => {
                    if (editName === null) setEditName(profile.name);
                  }}
                  maxLength={80}
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-primary outline-none focus:border-accent"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-text-faint">
                  Description
                </label>
                <textarea
                  value={
                    editDesc !== null ? editDesc : (profile.description ?? "")
                  }
                  onChange={(e) => setEditDesc(e.target.value)}
                  onFocus={() => {
                    if (editDesc === null)
                      setEditDesc(profile.description ?? "");
                  }}
                  maxLength={300}
                  rows={2}
                  className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-body-default text-text-primary outline-none focus:border-accent"
                />
              </div>
              {isDirty && (
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={updateMutation.isPending}
                  className="rounded-control bg-accent px-3 py-1.5 text-[11px] font-semibold text-bg-base disabled:opacity-50"
                >
                  {updateMutation.isPending ? "Saving..." : "Save changes"}
                </button>
              )}
            </div>
          </section>

          {/* Slot assignments */}
          <section>
            <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
              Slot Assignments
            </p>
            <div className="divide-y divide-border-faint rounded-card border border-border bg-bg-elevated px-4">
              {SLOTS.map((slot) => (
                <div key={slot} className="relative">
                  <SlotRow
                    slot={slot}
                    profile={profile}
                    onAssignRequested={(s) => setAssigningSlot(s)}
                  />
                  {assigningSlot === slot && (
                    <div className="absolute right-0 top-full z-50 mt-1">
                      <SlotSelector
                        slot={slot}
                        currentEntryId={
                          profile.slots[slot]?.library_entry_id ?? null
                        }
                        onSelect={(model) => handleSlotSelect(slot, model)}
                        onCancel={() => setAssigningSlot(null)}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Plan availability */}
          <section>
            <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
              Plan Availability
            </p>
            <div className="flex flex-wrap gap-2">
              {(["starter", "professional", "enterprise"] as const).map(
                (tier) => {
                  const active = profile.plan_tiers.includes(tier);
                  return (
                    <button
                      key={tier}
                      type="button"
                      onClick={() => {
                        const tiers = active
                          ? profile.plan_tiers.filter((t) => t !== tier)
                          : [...profile.plan_tiers, tier];
                        updateMutation.mutate({
                          id: profileId,
                          payload: { plan_tiers: tiers },
                        });
                      }}
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
                },
              )}
            </div>
            <p className="mt-2 text-[11px] text-text-faint">
              This profile will appear in the selector for tenants on these
              plans.
            </p>
          </section>

          {/* Tenant usage */}
          <section>
            <button
              type="button"
              onClick={() => setShowTenants((v) => !v)}
              className="flex w-full items-center justify-between text-label-nav uppercase tracking-wider text-text-faint"
            >
              <span>Tenant Usage</span>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-data-value text-text-muted">
                  {tenantsCount}
                </span>
                {showTenants ? (
                  <ChevronDown size={12} />
                ) : (
                  <ChevronRight size={12} />
                )}
              </div>
            </button>
            {showTenants && (
              <div className="mt-2">
                {tenantsCount === 0 ? (
                  <p className="text-body-default text-text-faint">
                    No tenants are using this profile yet.
                  </p>
                ) : (
                  <div className="max-h-40 overflow-y-auto space-y-1">
                    {(tenants ?? []).map((t) => (
                      <div
                        key={t.tenant_id}
                        className="flex items-center justify-between rounded-control bg-bg-elevated px-3 py-2"
                      >
                        <span className="text-body-default text-text-primary">
                          {t.tenant_name}
                        </span>
                        <PlanChip tier={t.plan_tier} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Version History section */}
          <section>
            <button
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              className="flex w-full items-center justify-between border-b border-border-faint pb-1 text-label-nav uppercase tracking-wider text-text-faint"
            >
              <span className="flex items-center gap-1.5">
                <History size={11} />
                Version History
              </span>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-data-value text-text-muted">
                  {history?.length ?? 0}
                </span>
                {showHistory ? (
                  <ChevronDown size={12} />
                ) : (
                  <ChevronRight size={12} />
                )}
              </div>
            </button>

            {showHistory && (
              <div className="mt-2 space-y-1.5">
                {!history || history.length === 0 ? (
                  <p className="text-[11px] text-text-faint">
                    No history entries yet.
                  </p>
                ) : (
                  <div className="max-h-56 overflow-y-auto space-y-1">
                    {history.map((entry) => {
                      const hasSlotBefore =
                        entry.diff.before &&
                        Object.keys(entry.diff.before).some((k) =>
                          k.endsWith("_library_id"),
                        );
                      const isConfirming = rollbackConfirmId === entry.id;

                      return (
                        <div
                          key={entry.id}
                          className="rounded-control border border-border-faint bg-bg-elevated px-3 py-2"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="flex-shrink-0 rounded-badge bg-bg-base px-1.5 py-0.5 font-mono text-[10px] text-text-muted">
                                {entry.action}
                              </span>
                              <span className="truncate text-[11px] text-text-faint">
                                {entry.created_at
                                  ? formatRelativeTime(entry.created_at)
                                  : "—"}
                              </span>
                            </div>
                            {hasSlotBefore && entry.action !== "rollback" && (
                              <button
                                type="button"
                                onClick={() =>
                                  isConfirming
                                    ? setRollbackConfirmId(null)
                                    : setRollbackConfirmId(entry.id)
                                }
                                className="flex-shrink-0 flex items-center gap-1 rounded-control border border-border px-2 py-0.5 text-[10px] text-text-muted hover:bg-bg-base"
                              >
                                <RotateCcw size={10} />
                                Rollback
                              </button>
                            )}
                          </div>

                          {isConfirming && (
                            <div className="mt-2 rounded-control border border-warn/30 bg-warn-dim p-2">
                              <p className="text-[11px] text-text-primary">
                                Restore slot assignments from{" "}
                                <span className="font-mono">
                                  {entry.created_at
                                    ? formatRelativeTime(entry.created_at)
                                    : "this entry"}
                                </span>
                                ? Current slot assignments will be overwritten.
                              </p>
                              <div className="mt-2 flex gap-2">
                                <button
                                  type="button"
                                  onClick={() => setRollbackConfirmId(null)}
                                  className="rounded-control border border-border px-2.5 py-1 text-[11px] text-text-muted hover:bg-bg-elevated"
                                >
                                  Cancel
                                </button>
                                <button
                                  type="button"
                                  disabled={rollbackMutation.isPending}
                                  onClick={async () => {
                                    await rollbackMutation.mutateAsync({
                                      profileId,
                                      historyId: entry.id,
                                    });
                                    setRollbackConfirmId(null);
                                  }}
                                  className="rounded-control border border-warn/40 bg-warn-dim px-2.5 py-1 text-[11px] text-warn disabled:opacity-50"
                                >
                                  {rollbackMutation.isPending
                                    ? "Restoring..."
                                    : "Restore"}
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Test section */}
          <section>
            <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
              Connection Test
            </p>
            <button
              type="button"
              onClick={handleTestAll}
              disabled={testMutation.isPending}
              className="flex items-center gap-2 rounded-control border border-border px-4 py-2 text-body-default text-text-primary hover:bg-bg-elevated disabled:opacity-50"
            >
              {testMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <FlaskConical size={14} />
              )}
              {testMutation.isPending ? "Testing..." : "Test All Slots"}
            </button>

            {testError && (
              <p className="mt-2 text-[11px] text-alert">{testError}</p>
            )}

            {testResults && (
              <div className="mt-3 space-y-2">
                {testResults.map((r) => (
                  <div
                    key={r.slot}
                    className="rounded-card border border-border-faint bg-bg-elevated p-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-label-nav uppercase tracking-wider text-text-faint">
                        {SLOT_LABELS[r.slot as ProfileSlot]}
                      </span>
                      {r.latency_ms !== null && (
                        <LatencyValue ms={r.latency_ms} />
                      )}
                    </div>
                    <p className="mt-0.5 font-mono text-data-value text-text-muted">
                      {r.model_name}
                    </p>
                    {r.error ? (
                      <p className="mt-1 text-[11px] text-alert">{r.error}</p>
                    ) : (
                      <>
                        {r.tokens_used !== null && (
                          <p className="mt-0.5 font-mono text-[11px] text-text-faint">
                            {r.tokens_used} tokens
                          </p>
                        )}
                        {r.response_snippet && (
                          <p className="mt-1 line-clamp-2 text-[11px] text-text-muted">
                            {r.response_snippet}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Footer actions */}
        <div className="flex-shrink-0 space-y-2 border-t border-border px-5 py-4">
          {/* Set as default */}
          <div className="relative">
            <button
              type="button"
              onClick={handleSetDefault}
              disabled={
                !hasRequiredSlots ||
                profile.is_platform_default ||
                setDefaultMutation.isPending
              }
              title={
                !hasRequiredSlots
                  ? "Assign Chat and Intent slots first"
                  : profile.is_platform_default
                    ? "Already the platform default"
                    : ""
              }
              className={cn(
                "w-full rounded-control border px-4 py-2.5 text-body-default font-medium transition-colors disabled:opacity-50",
                profile.is_platform_default
                  ? "border-accent/40 bg-accent-dim text-accent"
                  : "border-accent/40 text-accent hover:bg-accent-dim",
              )}
            >
              {profile.is_platform_default ? (
                <span className="flex items-center justify-center gap-2">
                  <Star size={14} className="fill-accent" />
                  Platform Default
                </span>
              ) : (
                "Set as Platform Default"
              )}
            </button>
          </div>

          {/* Deprecate */}
          <button
            type="button"
            onClick={handleDeprecate}
            disabled={!canDeprecate || updateMutation.isPending}
            title={
              !canDeprecate && tenantsCount > 0
                ? `Used by ${tenantsCount} tenant${tenantsCount !== 1 ? "s" : ""}`
                : profile.status === "deprecated"
                  ? "Already deprecated"
                  : ""
            }
            className="flex w-full items-center justify-center gap-2 rounded-control border border-alert/30 px-4 py-2 text-body-default text-alert hover:bg-alert-dim disabled:opacity-40"
          >
            Deprecate Profile
            {tenantsCount > 0 && (
              <span className="rounded-badge bg-alert-dim px-1.5 py-0.5 text-[10px]">
                {tenantsCount} tenant{tenantsCount !== 1 ? "s" : ""}
              </span>
            )}
          </button>
        </div>
      </aside>
    </>
  );
}
