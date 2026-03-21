"use client";

import { useState, useEffect } from "react";
import { X } from "lucide-react";
import {
  useCreateTeam,
  useUpdateTeam,
  type Team,
  type CreateTeamPayload,
  type UpdateTeamPayload,
} from "@/lib/hooks/useTeams";

interface TeamFormProps {
  team: Team | null;
  onClose: () => void;
}

const MAX_NAME_LENGTH = 200;
const MAX_DESCRIPTION_LENGTH = 1000;

export function TeamForm({ team, onClose }: TeamFormProps) {
  const isEdit = team !== null;

  const [name, setName] = useState(team?.name ?? "");
  const [description, setDescription] = useState(team?.description ?? "");
  const [error, setError] = useState("");

  const createMutation = useCreateTeam();
  const updateMutation = useUpdateTeam();
  const isPending = createMutation.isPending || updateMutation.isPending;

  useEffect(() => {
    if (team) {
      setName(team.name);
      setDescription(team.description ?? "");
    }
  }, [team]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!name.trim()) {
      setError("Team name is required");
      return;
    }

    try {
      if (isEdit && team) {
        const payload: UpdateTeamPayload = {
          name: name.trim(),
        };
        if (description.trim()) {
          payload.description = description.trim();
        }
        await updateMutation.mutateAsync({ id: team.id, payload });
      } else {
        const payload: CreateTeamPayload = {
          name: name.trim(),
        };
        if (description.trim()) {
          payload.description = description.trim();
        }
        await createMutation.mutateAsync(payload);
      }
      onClose();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to save team");
      }
    }
  }

  const canSubmit = name.trim().length > 0 && !isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-lg rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">
            {isEdit ? "Edit Team" : "New Team"}
          </h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          {error && (
            <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-body-default text-alert">
              {error}
            </div>
          )}

          {/* Name */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Name <span className="text-alert">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) =>
                setName(e.target.value.slice(0, MAX_NAME_LENGTH))
              }
              maxLength={MAX_NAME_LENGTH}
              placeholder="e.g. Finance Team"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Description */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) =>
                setDescription(e.target.value.slice(0, MAX_DESCRIPTION_LENGTH))
              }
              maxLength={MAX_DESCRIPTION_LENGTH}
              placeholder="Brief description of the team..."
              rows={3}
              className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
            <div className="mt-1 flex justify-end">
              <span className="font-mono text-xs text-text-faint">
                {description.length}/{MAX_DESCRIPTION_LENGTH}
              </span>
            </div>
          </div>
        </form>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
          >
            {isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
