"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiDelete } from "@/lib/api";
import { X, AlertTriangle } from "lucide-react";
import type { LLMProfile } from "./ProfileList";

interface DeleteProfileDialogProps {
  profile: LLMProfile;
  onClose: () => void;
}

export function DeleteProfileDialog({
  profile,
  onClose,
}: DeleteProfileDialogProps) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await apiDelete(`/api/v1/platform/llm-profiles/${profile.id}`);
      queryClient.invalidateQueries({ queryKey: ["llm-profiles"] });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete profile");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-sm rounded-card border border-border bg-bg-surface">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-alert" />
            <h2 className="text-section-heading text-text-primary">
              Delete Profile
            </h2>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5">
          <p className="text-sm text-text-muted">
            Are you sure you want to delete{" "}
            <span className="font-medium text-text-primary">
              {profile.name}
            </span>
            ? This action cannot be undone.
          </p>
          {error && <p className="mt-3 text-sm text-alert">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="rounded-control border border-alert/30 bg-alert-dim px-4 py-1.5 text-sm font-semibold text-alert transition-opacity disabled:opacity-50"
          >
            {deleting ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
