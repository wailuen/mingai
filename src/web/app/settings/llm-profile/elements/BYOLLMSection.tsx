"use client";

import { useState } from "react";
import {
  Loader2,
  Plus,
  RotateCcw,
  Pencil,
  Trash2,
  AlertCircle,
  KeyRound,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useBYOLLMEntries,
  useTestBYOLLMEntry,
  useActivateBYOLLMProfile,
  type ProfileSlot,
  type BYOLLMEntry,
} from "@/lib/hooks/useLLMProfileConfig";
import { AddEndpointModal } from "./AddEndpointModal";
import { RotateKeyModal } from "./RotateKeyModal";

const SLOT_LABELS: Record<ProfileSlot, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};

const ALL_SLOTS: ProfileSlot[] = ["chat", "intent", "vision", "agent"];
const REQUIRED_SLOTS: ProfileSlot[] = ["chat", "intent", "agent"];

function formatTestAge(testPassedAt: string | null): string {
  if (!testPassedAt) return "Not tested";
  const diff = Date.now() - new Date(testPassedAt).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `Tested ${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `Tested ${hrs}h ago`;
  return `Tested ${Math.floor(hrs / 24)}d ago`;
}

interface AcknowledgementGateProps {
  onCancel: () => void;
  onConfirm: () => void;
}

function AcknowledgementGate({
  onCancel,
  onConfirm,
}: AcknowledgementGateProps) {
  return (
    <div className="rounded-card border border-border bg-bg-surface p-6">
      <h3 className="text-section-heading text-text-primary">
        Bring Your Own LLM
      </h3>
      <ul className="mt-4 space-y-2">
        {[
          "You are responsible for the availability, cost, and performance of your custom models.",
          "Your API credentials are encrypted and stored securely. They are never visible after saving.",
          "Switching to a custom profile means your workspace will not automatically benefit from platform model upgrades.",
        ].map((point) => (
          <li key={point} className="flex items-start gap-2">
            <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-text-muted" />
            <span className="text-body-default text-text-muted">{point}</span>
          </li>
        ))}
      </ul>
      <div className="mt-6 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
        >
          I understand, configure my models
        </button>
      </div>
    </div>
  );
}

interface SlotCardProps {
  slot: ProfileSlot;
  entry: BYOLLMEntry | undefined;
  onAdd: () => void;
  onEdit: () => void;
  onRemove: () => void;
  onRetest: () => void;
  onRotateKey: () => void;
  isRetesting: boolean;
}

function SlotCard({
  slot,
  entry,
  onAdd,
  onEdit,
  onRemove,
  onRetest,
  onRotateKey,
  isRetesting,
}: SlotCardProps) {
  const isRequired = REQUIRED_SLOTS.includes(slot);
  const [confirmRemove, setConfirmRemove] = useState(false);

  return (
    <div className="rounded-card border border-border bg-bg-surface p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-label-nav uppercase tracking-wider text-text-faint">
            {SLOT_LABELS[slot]}
          </span>
          <span
            className={cn(
              "rounded-badge px-1.5 py-0.5 text-[10px]",
              isRequired
                ? "bg-warn-dim text-warn"
                : "bg-bg-elevated text-text-faint",
            )}
          >
            {isRequired ? "Required" : "Optional"}
          </span>
        </div>

        {entry ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onRetest}
              disabled={isRetesting}
              title="Re-test connection"
              className="rounded-control p-1.5 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-muted disabled:opacity-40"
            >
              {isRetesting ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RotateCcw size={13} />
              )}
            </button>
            <button
              type="button"
              onClick={onRotateKey}
              title="Rotate API key"
              className="rounded-control p-1.5 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-muted"
            >
              <KeyRound size={13} />
            </button>
            <button
              type="button"
              onClick={onEdit}
              title="Edit endpoint"
              className="rounded-control p-1.5 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-muted"
            >
              <Pencil size={13} />
            </button>
            <button
              type="button"
              onClick={() => setConfirmRemove(true)}
              title="Remove endpoint"
              className="rounded-control p-1.5 text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={onAdd}
            className="flex items-center gap-1 rounded-control border border-border px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-accent/40 hover:text-accent"
          >
            <Plus size={12} />
            Add Model Endpoint
          </button>
        )}
      </div>

      {entry ? (
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          <span className="font-mono text-data-value text-text-primary">
            {entry.model_name}
          </span>
          <span className="rounded-badge bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-muted">
            {entry.provider}
          </span>
          <span
            className={cn(
              "text-[11px]",
              !entry.test_passed_at ? "text-alert" : "text-text-faint",
            )}
          >
            {formatTestAge(entry.test_passed_at)}
          </span>
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-text-faint">No model configured</p>
      )}

      {confirmRemove && (
        <div className="mt-3 rounded-control border border-alert/20 bg-alert-dim p-3">
          <p className="text-body-default text-alert">
            Remove this endpoint? This cannot be undone.
          </p>
          <div className="mt-2 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirmRemove(false)}
              className="rounded-control border border-border px-2.5 py-1 text-[11px] text-text-muted hover:bg-bg-surface"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                onRemove();
                setConfirmRemove(false);
              }}
              className="rounded-control border border-alert/40 px-2.5 py-1 text-[11px] text-alert hover:bg-bg-surface"
            >
              Remove
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

interface BYOLLMSectionProps {
  /** Called when user clicks "Use Platform Profile instead" */
  onSwitchToPlatform: () => void;
}

export function BYOLLMSection({ onSwitchToPlatform }: BYOLLMSectionProps) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [showGate, setShowGate] = useState(true);
  const [addingSlot, setAddingSlot] = useState<ProfileSlot | null>(null);
  const [rotatingSlot, setRotatingSlot] = useState<ProfileSlot | null>(null);

  const { data: entries, isLoading, refetch } = useBYOLLMEntries();
  const testMutation = useTestBYOLLMEntry();
  const activateMutation = useActivateBYOLLMProfile();
  const [testingSlot, setTestingSlot] = useState<string | null>(null);

  const entryBySlot = (slot: ProfileSlot): BYOLLMEntry | undefined =>
    (entries ?? []).find((e) => e.slot === slot);

  // Activation gate: required slots must all have test_passed_at
  const requiredEntries = REQUIRED_SLOTS.map((s) => entryBySlot(s));
  const missingRequired = requiredEntries.filter(
    (e) => !e || !e.test_passed_at,
  ).length;
  const canActivate = missingRequired === 0;

  if (!acknowledged && showGate) {
    return (
      <AcknowledgementGate
        onCancel={() => setShowGate(false)}
        onConfirm={() => {
          setAcknowledged(true);
          setShowGate(false);
        }}
      />
    );
  }

  if (!acknowledged) {
    // User cancelled the gate — show nothing
    return null;
  }

  return (
    <div className="space-y-4">
      {/* Slot cards */}
      {isLoading ? (
        <div className="space-y-3">
          {ALL_SLOTS.map((s) => (
            <div
              key={s}
              className="h-20 animate-pulse rounded-card border border-border-faint bg-bg-elevated"
            />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {ALL_SLOTS.map((slot) => {
            const entry = entryBySlot(slot);
            return (
              <SlotCard
                key={slot}
                slot={slot}
                entry={entry}
                onAdd={() => setAddingSlot(slot)}
                onEdit={() => setAddingSlot(slot)}
                onRemove={() => {
                  // Entry removal is handled via AddEndpointModal in edit mode
                  // Placeholder — actual remove handled by edit flow
                }}
                onRotateKey={() => setRotatingSlot(slot)}
                onRetest={() => {
                  if (!entry) return;
                  setTestingSlot(entry.id);
                  testMutation.mutate(entry.id, {
                    onSettled: () => setTestingSlot(null),
                  });
                }}
                isRetesting={testingSlot === entry?.id}
              />
            );
          })}
        </div>
      )}

      {/* Activation footer */}
      <div className="space-y-2 pt-2">
        {!canActivate && (
          <div className="flex items-center gap-1.5">
            <AlertCircle size={13} className="flex-shrink-0 text-text-faint" />
            <span className="text-[11px] text-text-faint">
              Configure and test Chat, Intent, and Agent slots to activate.{" "}
              <span className="rounded-badge bg-bg-elevated px-1.5 py-0.5 font-mono text-data-value text-text-muted">
                {missingRequired} remaining
              </span>
            </span>
          </div>
        )}
        <button
          type="button"
          disabled={!canActivate || activateMutation.isPending}
          onClick={() => {
            // Use a synthetic byollm profile id — backend resolves from tenant context
            activateMutation.mutate("byollm");
          }}
          className="flex w-full items-center justify-center gap-1.5 rounded-control bg-accent py-2.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {activateMutation.isPending && (
            <Loader2 size={14} className="animate-spin" />
          )}
          Activate Custom Profile
        </button>
      </div>

      {/* Switch to platform profile */}
      <div className="border-t border-border-faint pt-3">
        <button
          type="button"
          onClick={onSwitchToPlatform}
          className="text-[11px] text-text-faint transition-colors hover:text-text-muted"
        >
          Use Platform Profile instead →
        </button>
      </div>

      {/* Add endpoint modal */}
      {addingSlot && (
        <AddEndpointModal
          slot={addingSlot}
          onClose={() => setAddingSlot(null)}
          onSaved={() => setAddingSlot(null)}
        />
      )}

      {/* Rotate key modal */}
      {rotatingSlot && (() => {
        const entry = entryBySlot(rotatingSlot);
        if (!entry) return null;
        return (
          <RotateKeyModal
            slotName={rotatingSlot}
            entryId={entry.id}
            onClose={() => setRotatingSlot(null)}
            onSuccess={() => {
              setRotatingSlot(null);
              refetch();
            }}
          />
        );
      })()}
    </div>
  );
}
