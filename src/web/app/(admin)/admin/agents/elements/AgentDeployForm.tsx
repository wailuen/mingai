"use client";

import { useState } from "react";
import { X, Loader2, ArrowLeft, ArrowRight, Check } from "lucide-react";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import { useDeployFromLibrary } from "@/lib/hooks/useAgentTemplates";
import { KBSelector } from "./KBSelector";
import type { KBSelection } from "./KBSelector";

interface AgentDeployFormProps {
  template: AgentTemplate;
  onClose: () => void;
  onDeployed: () => void;
}

/**
 * Two-step deployment wizard (Obsidian Intelligence modal spec):
 * Step 1: Agent name + variable values
 * Step 2: KB selector + confirm deploy
 */
export function AgentDeployForm({
  template,
  onClose,
  onDeployed,
}: AgentDeployFormProps) {
  const [step, setStep] = useState(1);
  const totalSteps = 2;
  const [name, setName] = useState(template.name);
  const [variableValues, setVariableValues] = useState<
    Record<string, string>
  >({});
  const [kbSelections, setKbSelections] = useState<KBSelection[]>([]);
  const deployMutation = useDeployFromLibrary();

  const varDefs = template.variable_definitions ?? [];

  // Check all required variables are filled
  const allRequiredFilled = varDefs
    .filter((v) => v.required)
    .every((v) => (variableValues[v.name] ?? "").trim().length > 0);

  const canProceedStep1 = name.trim().length > 0 && allRequiredFilled;

  function handleDeploy() {
    deployMutation.mutate(
      {
        template_id: template.id,
        name: name.trim(),
        variable_values:
          Object.keys(variableValues).length > 0 ? variableValues : undefined,
        kb_ids: kbSelections.map((kb) => kb.integrationId),
      },
      {
        onSuccess: () => {
          onDeployed();
          onClose();
        },
      },
    );
  }

  const progressPct = (step / totalSteps) * 100;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="mx-4 w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Progress bar */}
        <div className="h-1 w-full rounded-t-card bg-bg-elevated">
          <div
            className="h-full rounded-l-card bg-accent transition-all"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-text-faint">
              Step {step} of {totalSteps}
            </p>
            <h2 className="mt-1 text-section-heading text-text-primary">
              {step === 1 ? "Configure Agent" : "Select Knowledge Bases"}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 pb-4">
          {step === 1 && (
            <div className="space-y-5">
              {/* Agent Name */}
              <div>
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

              {/* Variable inputs */}
              {varDefs.length > 0 && (
                <div>
                  <label className="mb-2 block text-label-nav uppercase text-text-faint">
                    Template Variables
                  </label>
                  <div className="space-y-3">
                    {varDefs.map((v) => (
                      <div key={v.name}>
                        <label className="mb-1 block text-xs text-text-muted">
                          {v.label || v.name}
                          {v.required && (
                            <span className="ml-0.5 text-alert">*</span>
                          )}
                        </label>
                        {v.type === "select" && v.options ? (
                          <select
                            value={variableValues[v.name] ?? ""}
                            onChange={(e) =>
                              setVariableValues({
                                ...variableValues,
                                [v.name]: e.target.value,
                              })
                            }
                            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
                          >
                            <option value="">Select...</option>
                            {v.options.map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <input
                            type={v.type === "number" ? "number" : "text"}
                            value={variableValues[v.name] ?? ""}
                            onChange={(e) =>
                              setVariableValues({
                                ...variableValues,
                                [v.name]: e.target.value,
                              })
                            }
                            placeholder={`Enter ${v.label || v.name}`}
                            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {step === 2 && (
            <div>
              <label className="mb-2 block text-label-nav uppercase text-text-faint">
                Knowledge Bases
              </label>
              <p className="mb-3 text-xs text-text-faint">
                Select integrations to connect as knowledge sources for this
                agent.
              </p>
              <KBSelector value={kbSelections} onChange={setKbSelections} />
            </div>
          )}
        </div>

        {/* Error */}
        {deployMutation.isError && (
          <div className="px-6 pb-3">
            <p className="text-sm text-alert">
              {deployMutation.error?.message ?? "Deployment failed."}
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-6 py-4">
          <div>
            {step > 1 && (
              <button
                type="button"
                onClick={() => setStep(step - 1)}
                className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                <ArrowLeft size={14} />
                Back
              </button>
            )}
          </div>

          <div>
            {step < totalSteps ? (
              <button
                type="button"
                onClick={() => setStep(step + 1)}
                disabled={!canProceedStep1}
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
              >
                Next
                <ArrowRight size={14} />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleDeploy}
                disabled={deployMutation.isPending}
                className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {deployMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} />
                )}
                Deploy Agent
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
