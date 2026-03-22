"use client";

import { useState, useEffect, useCallback } from "react";
import { X } from "lucide-react";
import {
  useAgentTemplate,
  useDeployFromLibrary,
} from "@/lib/hooks/useAgentTemplates";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import { WizardStep1Template } from "./wizard/WizardStep1Template";
import { WizardStep2Knowledge } from "./wizard/WizardStep2Knowledge";
import { WizardStep3Access } from "./wizard/WizardStep3Access";
import { WizardStep4Credentials } from "./wizard/WizardStep4Credentials";
import { DeploySuccessOverlay } from "./DeploySuccessOverlay";

export interface WizardFormData {
  templateId: string;
  agentName: string;
  variableValues: Record<string, string>;
  kbIds: string[];
  kbSearchMode: "parallel" | "priority";
  accessMode: "workspace_wide" | "role_restricted" | "user_specific";
  allowedRoles: string[];
  allowedUserIds: string[];
  rateLimitPerMinute: number | null;
  credentials: Record<string, string>;
}

function buildInitialFormData(template: AgentTemplate | null): WizardFormData {
  return {
    templateId: template?.id ?? "",
    agentName: template?.name ?? "",
    variableValues: {},
    kbIds: [],
    kbSearchMode: "parallel",
    accessMode: "workspace_wide",
    allowedRoles: [],
    allowedUserIds: [],
    rateLimitPerMinute: null,
    credentials: {},
  };
}

const ACCESS_CONTROL_MAP: Record<
  WizardFormData["accessMode"],
  "workspace" | "role" | "user"
> = {
  workspace_wide: "workspace",
  role_restricted: "role",
  user_specific: "user",
};

function extractErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "Deployment failed. Please try again.";
}

export interface AgentDeployWizardProps {
  isOpen: boolean;
  onClose: () => void;
  templateId: string | null;
  template?: AgentTemplate | null;
}

export function AgentDeployWizard({
  isOpen,
  onClose,
  templateId,
  template: templateProp,
}: AgentDeployWizardProps) {
  const { data: fetchedTemplate } = useAgentTemplate(
    templateProp ? null : templateId,
  );

  const template = templateProp ?? fetchedTemplate ?? null;

  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
  const [formData, setFormData] = useState<WizardFormData>(() =>
    buildInitialFormData(template),
  );
  const [deployError, setDeployError] = useState<string | null>(null);
  const [deployed, setDeployed] = useState<{ name: string } | null>(null);

  // Reset when wizard opens or template changes
  useEffect(() => {
    if (isOpen) {
      setStep(1);
      setFormData(buildInitialFormData(template));
      setDeployError(null);
      setDeployed(null);
    }
  }, [isOpen, template?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update form data when template loads asynchronously
  useEffect(() => {
    if (template && !formData.templateId) {
      setFormData(buildInitialFormData(template));
    }
  }, [template]); // eslint-disable-line react-hooks/exhaustive-deps

  const { mutateAsync: deployFromLibrary, isPending: isDeploying } =
    useDeployFromLibrary();

  const needsCredentials = template?.auth_mode === "tenant_credentials";
  const totalSteps = needsCredentials ? 4 : 3;

  const handleChange = useCallback((data: Partial<WizardFormData>) => {
    setFormData((prev) => ({ ...prev, ...data }));
  }, []);

  function validateCurrentStep(): string | null {
    if (step === 2) {
      if (!formData.agentName.trim()) return "Agent name is required.";
    }
    if (step === 3) {
      if (
        formData.accessMode === "role_restricted" &&
        formData.allowedRoles.length === 0
      ) {
        return "Please enter at least one allowed role.";
      }
      if (
        formData.accessMode === "user_specific" &&
        formData.allowedUserIds.length === 0
      ) {
        return "Please enter at least one allowed user ID.";
      }
    }
    return null;
  }

  function handleNext() {
    const err = validateCurrentStep();
    if (err) {
      setDeployError(err);
      return;
    }
    setDeployError(null);
    setStep((s) => (s < 4 ? ((s + 1) as 1 | 2 | 3 | 4) : s));
  }

  function handleBack() {
    setDeployError(null);
    setStep((s) => (s > 1 ? ((s - 1) as 1 | 2 | 3 | 4) : s));
  }

  async function handleDeploy() {
    const err = validateCurrentStep();
    if (err) {
      setDeployError(err);
      return;
    }
    setDeployError(null);

    try {
      const payload = {
        template_id: template!.id,
        name: formData.agentName.trim(),
        variable_values:
          Object.keys(formData.variableValues).length > 0
            ? formData.variableValues
            : undefined,
        kb_ids: formData.kbIds.length > 0 ? formData.kbIds : undefined,
        access_control: ACCESS_CONTROL_MAP[formData.accessMode],
        allowed_roles:
          formData.accessMode === "role_restricted" &&
          formData.allowedRoles.length > 0
            ? formData.allowedRoles
            : undefined,
        allowed_user_ids:
          formData.accessMode === "user_specific" &&
          formData.allowedUserIds.length > 0
            ? formData.allowedUserIds
            : undefined,
      };

      const result = await deployFromLibrary(payload);
      setDeployed({ name: result.name || formData.agentName.trim() });
    } catch (err) {
      setDeployError(extractErrorMessage(err));
    }
  }

  const isFinalStep = step === totalSteps;

  function handleGoToAgents() {
    onClose();
    // Navigate to My Agents tab — page handles tab state
    window.location.href = "/settings/agents";
  }

  function handleDeployAnother() {
    setStep(1);
    setFormData(buildInitialFormData(null));
    setDeployed(null);
    setDeployError(null);
  }

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative flex w-full max-w-[640px] flex-col overflow-hidden rounded-card border border-border bg-bg-surface shadow-xl mx-4 max-h-[90vh]">
        {deployed ? (
          /* Success state */
          <DeploySuccessOverlay
            agentName={deployed.name}
            kbCount={formData.kbIds.length}
            accessMode={formData.accessMode}
            onGoToAgents={handleGoToAgents}
            onDeployAnother={handleDeployAnother}
          />
        ) : (
          <>
            {/* Top bar */}
            <div className="flex items-center justify-between border-b border-border px-6 py-4">
              <div className="flex flex-col gap-0.5">
                <p className="text-section-heading text-text-primary">
                  Deploy Agent
                </p>
                <p className="text-[11px] text-text-faint">
                  Step {step} of {totalSteps}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
                aria-label="Close wizard"
              >
                <X size={16} />
              </button>
            </div>

            {/* Progress bar */}
            <div className="h-1 bg-bg-elevated">
              <div
                className="h-full bg-accent transition-all duration-300"
                style={{ width: `${(step / totalSteps) * 100}%` }}
              />
            </div>

            {/* Step content */}
            <div className="overflow-y-auto p-6">
              {step === 1 && <WizardStep1Template template={template} />}
              {step === 2 && (
                <WizardStep2Knowledge
                  template={template}
                  formData={formData}
                  onChange={handleChange}
                />
              )}
              {step === 3 && (
                <WizardStep3Access
                  formData={formData}
                  onChange={handleChange}
                />
              )}
              {step === 4 && needsCredentials && (
                <WizardStep4Credentials
                  template={template}
                  formData={formData}
                  onChange={handleChange}
                />
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between border-t border-border px-6 py-4">
              <div className="flex-1">
                {deployError && (
                  <p className="text-[11px] text-alert">{deployError}</p>
                )}
              </div>
              <div className="flex items-center gap-3">
                {step > 1 && (
                  <button
                    type="button"
                    onClick={handleBack}
                    disabled={isDeploying}
                    className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Back
                  </button>
                )}

                {isFinalStep ? (
                  <button
                    type="button"
                    onClick={handleDeploy}
                    disabled={isDeploying}
                    className="flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isDeploying && (
                      <svg
                        className="h-3.5 w-3.5 animate-spin"
                        viewBox="0 0 24 24"
                        fill="none"
                        aria-hidden="true"
                      >
                        <circle
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="3"
                          strokeOpacity="0.3"
                        />
                        <path
                          d="M12 2a10 10 0 0 1 10 10"
                          stroke="currentColor"
                          strokeWidth="3"
                          strokeLinecap="round"
                        />
                      </svg>
                    )}
                    {isDeploying ? "Deploying…" : "Deploy"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleNext}
                    className="rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
                  >
                    Next
                  </button>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
