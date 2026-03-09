"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import { useDeployAgent } from "@/lib/hooks/useAgentTemplates";
import { KBSelector } from "./KBSelector";
import type { KBSelection } from "./KBSelector";
import { AccessControlSelector } from "./AccessControlSelector";
import type { AccessControlConfig } from "./AccessControlSelector";

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
  const [kbSelections, setKbSelections] = useState<KBSelection[]>([]);
  const [accessControl, setAccessControl] = useState<AccessControlConfig>({
    mode: "workspace",
  });
  const deployMutation = useDeployAgent();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    deployMutation.mutate(
      {
        templateId: template.id,
        payload: {
          name: name.trim(),
          access_control: accessControl.mode,
          kb_ids: kbSelections.map((kb) => kb.integrationId),
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

        {/* Knowledge Bases */}
        <div className="mb-5">
          <label className="mb-2 block text-label-nav uppercase text-text-faint">
            Knowledge Bases
          </label>
          <KBSelector value={kbSelections} onChange={setKbSelections} />
        </div>

        {/* Access Control */}
        <div className="mb-6">
          <label className="mb-2 block text-label-nav uppercase text-text-faint">
            Access Control
          </label>
          <AccessControlSelector
            value={accessControl}
            onChange={setAccessControl}
          />
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
