"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { useAddMember } from "@/lib/hooks/useTeams";

interface AddMemberDialogProps {
  teamId: string;
  teamName: string;
  onClose: () => void;
}

export function AddMemberDialog({
  teamId,
  teamName,
  onClose,
}: AddMemberDialogProps) {
  const [userId, setUserId] = useState("");
  const [error, setError] = useState("");
  const addMutation = useAddMember();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    const trimmed = userId.trim();
    if (!trimmed) {
      setError("User ID is required");
      return;
    }

    try {
      await addMutation.mutateAsync({ teamId, userId: trimmed });
      onClose();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to add member");
      }
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-md rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">Add Member</h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <p className="text-sm text-text-muted">
            Add a user to{" "}
            <span className="font-medium text-text-primary">{teamName}</span>
          </p>

          {error && (
            <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-sm text-alert">
              {error}
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              User ID <span className="text-alert">*</span>
            </label>
            <input
              type="text"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="Enter user ID or email"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              autoFocus
            />
            <p className="mt-1 text-xs text-text-faint">
              The user ID from the Users directory
            </p>
          </div>
        </form>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!userId.trim() || addMutation.isPending}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
          >
            {addMutation.isPending && (
              <Loader2 size={14} className="animate-spin" />
            )}
            Add Member
          </button>
        </div>
      </div>
    </div>
  );
}
