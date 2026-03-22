"use client";

import { useState } from "react";
import { X, Loader2, CheckCircle2, AlertCircle, KeyRound } from "lucide-react";
import {
  useRotateBYOLLMKey,
  type ProfileSlot,
} from "@/lib/hooks/useLLMProfileConfig";

const SLOT_LABELS: Record<ProfileSlot, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};

interface RotateKeyModalProps {
  slotName: ProfileSlot;
  entryId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export function RotateKeyModal({
  slotName,
  entryId,
  onClose,
  onSuccess,
}: RotateKeyModalProps) {
  const [newKey, setNewKey] = useState("");
  const [succeeded, setSucceeded] = useState(false);

  const rotateMutation = useRotateBYOLLMKey();

  const canSubmit =
    newKey.trim().length >= 8 && !rotateMutation.isPending && !succeeded;

  function handleRotate() {
    if (!canSubmit) return;

    rotateMutation.mutate(
      { id: entryId, payload: { api_key: newKey.trim() } },
      {
        onSuccess: () => {
          setSucceeded(true);
          // Brief success pause, then close
          setTimeout(() => {
            onSuccess();
          }, 1200);
        },
      },
    );
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") handleRotate();
    if (e.key === "Escape") onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/60">
      <div className="w-full max-w-md rounded-[10px] border border-border bg-bg-surface shadow-md">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div className="flex items-center gap-2">
            <KeyRound size={15} className="text-text-faint" />
            <h2 className="text-section-heading text-text-primary">
              Rotate API Key — {SLOT_LABELS[slotName]} Slot
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-[7px] p-1.5 text-text-faint transition-colors hover:bg-bg-elevated"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-5 px-6 py-5">
          {/* Warning notice */}
          <div className="flex items-start gap-2 rounded-[7px] border border-warn/20 bg-warn-dim px-4 py-3">
            <AlertCircle
              size={14}
              className="mt-0.5 flex-shrink-0 text-warn"
            />
            <p className="text-body-default text-warn">
              Enter your new API key. The old key will be immediately
              invalidated and cannot be recovered.
            </p>
          </div>

          {/* New API Key field */}
          <div>
            <label
              htmlFor="rotate-key-input"
              className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
            >
              New API Key
            </label>
            <input
              id="rotate-key-input"
              type="password"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="sk-..."
              autoComplete="new-password"
              disabled={rotateMutation.isPending || succeeded}
              minLength={8}
              className="w-full rounded-[7px] border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none disabled:opacity-60"
            />
            <p className="mt-1 text-[11px] text-text-faint">
              Minimum 8 characters. Never shared or displayed after saving.
            </p>
          </div>

          {/* Inline result messages */}
          {succeeded && (
            <div className="flex items-center gap-2">
              <CheckCircle2 size={13} className="flex-shrink-0 text-accent" />
              <span className="text-body-default text-accent">
                API key rotated successfully.
              </span>
            </div>
          )}

          {rotateMutation.isError && !succeeded && (
            <div className="flex items-center gap-2">
              <AlertCircle size={13} className="flex-shrink-0 text-alert" />
              <span className="text-body-default text-alert">
                {(rotateMutation.error as Error)?.message ??
                  "Key rotation failed. Please try again."}
              </span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={rotateMutation.isPending}
            className="rounded-[7px] border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleRotate}
            disabled={!canSubmit}
            className="flex items-center gap-1.5 rounded-[7px] bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {rotateMutation.isPending && (
              <Loader2 size={13} className="animate-spin" />
            )}
            Rotate Key
          </button>
        </div>
      </div>
    </div>
  );
}
