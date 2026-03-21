"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/lib/api";
import { X } from "lucide-react";

const MODEL_SLOTS = [
  { key: "primary", label: "Primary", required: true },
  { key: "intent", label: "Intent", required: false },
  { key: "embedding", label: "Embedding", required: false },
  { key: "vision", label: "Vision", required: false },
  { key: "router", label: "Router", required: false },
  { key: "worker", label: "Worker", required: false },
] as const;

interface NewProfileModalProps {
  onClose: () => void;
}

export function NewProfileModal({ onClose }: NewProfileModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [slots, setSlots] = useState<Record<string, string>>({
    primary: "",
    intent: "",
    embedding: "",
    vision: "",
    router: "",
    worker: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  function updateSlot(key: string, value: string) {
    setSlots((prev) => ({ ...prev, [key]: value }));
  }

  async function handleCreate() {
    setSubmitting(true);
    setError(null);
    try {
      // Build slots object, only include non-empty values
      const cleanSlots: Record<string, string> = {};
      for (const [key, value] of Object.entries(slots)) {
        if (value.trim()) {
          cleanSlots[key] = value.trim();
        }
      }

      await apiPost("/api/v1/platform/llm-profiles", {
        name: name.trim(),
        description: description.trim(),
        slots: cleanSlots,
      });
      queryClient.invalidateQueries({ queryKey: ["llm-profiles"] });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create profile");
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = name.trim().length > 0 && slots.primary.trim().length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">
            New LLM Profile
          </h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="max-h-[70vh] overflow-y-auto p-5">
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Profile Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Production Models"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe the purpose of this profile..."
                rows={2}
                className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>

            <div>
              <h3 className="mb-3 text-[11px] font-medium uppercase tracking-wider text-text-faint">
                Model Slots
              </h3>
              <div className="space-y-3">
                {MODEL_SLOTS.map((slot) => (
                  <div key={slot.key}>
                    <label className="mb-1 flex items-center gap-1.5 text-xs text-text-muted">
                      {slot.label}
                      {slot.required && <span className="text-accent">*</span>}
                    </label>
                    <input
                      type="text"
                      value={slots[slot.key]}
                      onChange={(e) => updateSlot(slot.key, e.target.value)}
                      placeholder={`e.g. gpt-4o, claude-sonnet-4-20250514`}
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-xs text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                    />
                  </div>
                ))}
              </div>
            </div>

            {error && <p className="text-body-default text-alert">{error}</p>}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!canSubmit || submitting}
            className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
          >
            {submitting ? "Creating..." : "Create Profile"}
          </button>
        </div>
      </div>
    </div>
  );
}
