"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import { useDeployAgent } from "@/lib/hooks/useAgentTemplates";

type AccessControl = "workspace" | "role" | "user";

const ACCESS_OPTIONS: { value: AccessControl; label: string }[] = [
  { value: "workspace", label: "Workspace-wide (all users)" },
  { value: "role", label: "Role-restricted" },
  { value: "user", label: "User-specific" },
];

interface AgentDeployFormProps {
  template: AgentTemplate;
  onClose: () => void;
  onDeployed: () => void;
}

export function AgentDeployForm({
  template,
  onClose,
  onDeployed,
}: AgentDeployFormProps) {
  const [name, setName] = useState(template.name);
  const [accessControl, setAccessControl] =
    useState<AccessControl>("workspace");
  const deployMutation = useDeployAgent();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    deployMutation.mutate(
      {
        templateId: template.id,
        payload: {
          name: name.trim(),
          access_control: accessControl,
          kb_ids: [],
        },
      },
      {
        onSuccess: () => {
          onDeployed();
          onClose();
        },
      },
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="mx-4 w-full max-w-lg rounded-card border border-border bg-bg-surface p-6"
      >
        {/* Header */}
        <div className="mb-5 flex items-start justify-between">
          <h2 className="text-section-heading text-text-primary">
            Deploy: {template.name}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        {/* Agent Name */}
        <div className="mb-5">
          <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
            Agent Name *
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
        </div>

        {/* Access Control */}
        <div className="mb-6">
          <label className="mb-2 block text-label-nav uppercase text-text-faint">
            Access Control
          </label>
          <div className="space-y-2">
            {ACCESS_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="flex cursor-pointer items-center gap-2.5 rounded-control px-3 py-2 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
              >
                <input
                  type="radio"
                  name="access_control"
                  value={opt.value}
                  checked={accessControl === opt.value}
                  onChange={() => setAccessControl(opt.value)}
                  className="accent-accent"
                />
                {opt.label}
              </label>
            ))}
          </div>
        </div>

        {/* Error */}
        {deployMutation.isError && (
          <p className="mb-4 text-sm text-alert">
            {deployMutation.error?.message ?? "Deployment failed."}
          </p>
        )}

        {/* Footer */}
        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!name.trim() || deployMutation.isPending}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {deployMutation.isPending && (
              <Loader2 size={14} className="animate-spin" />
            )}
            Deploy Agent
          </button>
        </div>
      </form>
    </div>
  );
}
