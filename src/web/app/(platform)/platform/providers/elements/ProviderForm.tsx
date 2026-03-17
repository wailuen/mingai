"use client";

import { useState, useEffect, useRef } from "react";
import { X, Loader2, Zap, CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCreateProvider,
  useUpdateProvider,
  useTestProvider,
  type Provider,
  type ProviderType,
  type CreateProviderPayload,
  type UpdateProviderPayload,
} from "@/lib/hooks/useLLMProviders";
import { SlotMappingGrid } from "./SlotMappingGrid";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROVIDER_TYPES: { value: ProviderType; label: string }[] = [
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "dashscope", label: "DashScope (Alibaba)" },
  { value: "doubao", label: "Doubao (ByteDance)" },
  { value: "gemini", label: "Gemini (Google)" },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProviderFormProps {
  /** null = create mode, Provider = edit mode */
  provider: Provider | null;
  /** Whether to show is_default toggle (only when no providers exist yet) */
  showDefaultToggle?: boolean;
  onClose: () => void;
  onSaved: () => void;
}

interface Step1State {
  display_name: string;
  provider_type: ProviderType;
  endpoint: string;
  api_version: string;
  api_key: string;
  description: string;
  is_default: boolean;
}

const EMPTY_STEP1: Step1State = {
  display_name: "",
  provider_type: "azure_openai",
  endpoint: "",
  api_version: "2024-02-01",
  api_key: "",
  description: "",
  is_default: false,
};

function step1FromProvider(p: Provider): Step1State {
  return {
    display_name: p.display_name,
    provider_type: p.provider_type,
    endpoint: p.endpoint ?? "",
    api_version: p.options?.api_version ?? "2024-02-01",
    api_key: "",
    description: p.description ?? "",
    is_default: p.is_default,
  };
}

// ---------------------------------------------------------------------------
// Test result chip
// ---------------------------------------------------------------------------

interface TestChipProps {
  success: boolean;
  latencyMs: number;
  errorMsg: string | null;
}

function TestChip({ success, latencyMs, errorMsg }: TestChipProps) {
  if (success) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-badge bg-accent-dim px-2.5 py-1 font-mono text-[11px] text-accent">
        <CheckCircle2 size={11} />
        OK · {latencyMs}ms
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-badge bg-alert-dim px-2.5 py-1 font-mono text-[11px] text-alert"
      title={errorMsg ?? undefined}
    >
      <AlertCircle size={11} />
      Failed
      {errorMsg && (
        <span className="max-w-[200px] truncate text-[10px]">{errorMsg}</span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function ProgressBar({ step, total }: { step: number; total: number }) {
  const pct = Math.round((step / total) * 100);
  return (
    <div className="h-0.5 w-full overflow-hidden rounded-full bg-bg-elevated">
      <div
        className="h-full rounded-full bg-accent transition-all duration-300"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ProviderForm({
  provider,
  showDefaultToggle = false,
  onClose,
  onSaved,
}: ProviderFormProps) {
  const isEditing = provider !== null;
  const totalSteps = isEditing ? 1 : 2;

  const [step, setStep] = useState(1);
  const [step1, setStep1] = useState<Step1State>(
    provider ? step1FromProvider(provider) : EMPTY_STEP1,
  );
  const [models, setModels] = useState<Record<string, string>>(
    provider?.models ?? {},
  );

  // Test connectivity state
  const testMutation = useTestProvider();
  const [testResult, setTestResult] = useState<{
    success: boolean;
    latencyMs: number;
    errorMsg: string | null;
  } | null>(null);
  const testTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const createMutation = useCreateProvider();
  const updateMutation = useUpdateProvider();
  const isPending = createMutation.isPending || updateMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error;

  useEffect(() => {
    return () => {
      if (testTimerRef.current) clearTimeout(testTimerRef.current);
    };
  }, []);

  function updateStep1<K extends keyof Step1State>(key: K, value: Step1State[K]) {
    setStep1((prev) => ({ ...prev, [key]: value }));
  }

  function handleTestConnectivity() {
    if (!provider) return;
    if (testTimerRef.current) clearTimeout(testTimerRef.current);
    testMutation.mutate(provider.id, {
      onSuccess: (data) => {
        setTestResult({
          success: data.success,
          latencyMs: data.latency_ms,
          errorMsg: data.error,
        });
        testTimerRef.current = setTimeout(() => setTestResult(null), 10000);
      },
      onError: (err) => {
        setTestResult({ success: false, latencyMs: 0, errorMsg: err.message });
        testTimerRef.current = setTimeout(() => setTestResult(null), 10000);
      },
    });
  }

  function handleNext() {
    if (step < totalSteps) setStep((s) => s + 1);
  }

  function handleBack() {
    if (step > 1) setStep((s) => s - 1);
  }

  function handleSubmit() {
    if (isEditing) {
      const payload: UpdateProviderPayload = {};

      if (step1.display_name !== provider.display_name)
        payload.display_name = step1.display_name;
      if (step1.description !== (provider.description ?? ""))
        payload.description = step1.description;
      if (step1.endpoint !== (provider.endpoint ?? ""))
        payload.endpoint = step1.endpoint;
      if (step1.is_default !== provider.is_default)
        payload.is_default = step1.is_default;
      if (step1.api_key.trim()) payload.api_key = step1.api_key;

      // Build merged options
      const newOptions: Record<string, string> = {
        ...(provider.options ?? {}),
      };
      if (step1.provider_type === "azure_openai") {
        newOptions.api_version = step1.api_version;
      }
      if (
        JSON.stringify(newOptions) !== JSON.stringify(provider.options ?? {})
      ) {
        payload.options = newOptions;
      }

      if (JSON.stringify(models) !== JSON.stringify(provider.models ?? {})) {
        payload.models = models;
      }

      if (Object.keys(payload).length === 0) {
        onClose();
        return;
      }

      updateMutation.mutate(
        { id: provider.id, payload },
        {
          onSuccess: () => {
            onSaved();
            onClose();
          },
        },
      );
    } else {
      const options: Record<string, string> = {};
      if (step1.provider_type === "azure_openai") {
        options.api_version = step1.api_version;
      }

      const payload: CreateProviderPayload = {
        provider_type: step1.provider_type,
        display_name: step1.display_name,
        api_key: step1.api_key,
      };
      if (step1.description.trim()) payload.description = step1.description;
      if (step1.endpoint.trim()) payload.endpoint = step1.endpoint;
      if (Object.keys(options).length) payload.options = options;
      if (Object.keys(models).length) payload.models = models;
      if (step1.is_default) payload.is_default = true;

      createMutation.mutate(payload, {
        onSuccess: () => {
          onSaved();
          onClose();
        },
      });
    }
  }

  const canAdvanceStep1 =
    step1.display_name.trim().length > 0 &&
    step1.display_name.length <= 200 &&
    step1.api_key.trim().length > 0 &&
    (step1.provider_type !== "azure_openai" || step1.endpoint.trim().length > 0);

  const canSubmitEdit =
    step1.display_name.trim().length > 0 &&
    step1.display_name.length <= 200 &&
    (step1.provider_type !== "azure_openai" || step1.endpoint.trim().length > 0);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="mx-4 w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Progress bar (create mode only) */}
        {!isEditing && (
          <div className="px-6 pt-4">
            <ProgressBar step={step} total={totalSteps} />
          </div>
        )}

        {/* Header */}
        <div className="flex items-start justify-between px-6 pb-4 pt-5">
          <div>
            <h2 className="text-section-heading text-text-primary">
              {isEditing
                ? `Edit: ${provider.display_name}`
                : "New Provider"}
            </h2>
            {!isEditing && (
              <p className="mt-0.5 text-[11px] text-text-faint">
                Step {step} of {totalSteps}
              </p>
            )}
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
        <div className="max-h-[60vh] overflow-y-auto px-6">
          {/* ---- Step 1 ---- */}
          {step === 1 && (
            <div className="space-y-4 pb-4">
              {/* Display name */}
              <div>
                <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                  Display Name *
                </label>
                <input
                  type="text"
                  value={step1.display_name}
                  onChange={(e) => updateStep1("display_name", e.target.value)}
                  required
                  maxLength={200}
                  placeholder="e.g. Azure Production"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>

              {/* Provider type */}
              <div>
                <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                  Provider Type *
                </label>
                <select
                  value={step1.provider_type}
                  onChange={(e) =>
                    updateStep1("provider_type", e.target.value as ProviderType)
                  }
                  disabled={isEditing}
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary transition-colors focus:border-accent focus:outline-none disabled:opacity-60"
                >
                  {PROVIDER_TYPES.map((pt) => (
                    <option key={pt.value} value={pt.value}>
                      {pt.label}
                    </option>
                  ))}
                </select>
                {isEditing && (
                  <p className="mt-1 text-[10px] text-text-faint">
                    Provider type cannot be changed after creation.
                  </p>
                )}
              </div>

              {/* Azure-specific: endpoint */}
              {step1.provider_type === "azure_openai" && (
                <div>
                  <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                    Endpoint URL *
                  </label>
                  <input
                    type="url"
                    value={step1.endpoint}
                    onChange={(e) => updateStep1("endpoint", e.target.value)}
                    required
                    placeholder="https://your-resource.openai.azure.com/"
                    className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                  />
                </div>
              )}

              {/* Azure-specific: api_version */}
              {step1.provider_type === "azure_openai" && (
                <div>
                  <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                    API Version
                  </label>
                  <input
                    type="text"
                    value={step1.api_version}
                    onChange={(e) => updateStep1("api_version", e.target.value)}
                    placeholder="2024-02-01"
                    className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                  />
                </div>
              )}

              {/* API Key */}
              <div>
                <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                  API Key {!isEditing && "*"}
                </label>
                <input
                  type="password"
                  value={step1.api_key}
                  onChange={(e) => updateStep1("api_key", e.target.value)}
                  required={!isEditing}
                  autoComplete="new-password"
                  placeholder={
                    isEditing
                      ? "Leave blank to keep existing key"
                      : "Enter API key"
                  }
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
                <p className="mt-1 text-[10px] text-text-faint">
                  Stored encrypted. Never returned in API responses.
                </p>
              </div>

              {/* Description */}
              <div>
                <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                  Description
                </label>
                <textarea
                  value={step1.description}
                  onChange={(e) => updateStep1("description", e.target.value)}
                  rows={2}
                  placeholder="Optional notes about this provider"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>

              {/* Default toggle — create mode only (or always in edit mode for changing) */}
              {(showDefaultToggle || isEditing) && (
                <label className="flex cursor-pointer items-center gap-2.5 rounded-control px-3 py-2 text-sm text-text-muted transition-colors hover:bg-bg-elevated">
                  <input
                    type="checkbox"
                    checked={step1.is_default}
                    onChange={(e) => updateStep1("is_default", e.target.checked)}
                    className="accent-accent"
                  />
                  Set as platform default provider
                </label>
              )}
            </div>
          )}

          {/* ---- Step 2 (create mode only) ---- */}
          {step === 2 && !isEditing && (
            <div className="pb-4">
              <SlotMappingGrid
                providerType={step1.provider_type}
                models={models}
                onChange={setModels}
              />
            </div>
          )}
        </div>

        {/* Error */}
        {mutationError && (
          <div className="mx-6 mt-2 rounded-control border border-alert-ring bg-alert-dim px-3 py-2">
            <p className="text-[12px] text-alert">{mutationError.message}</p>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-4">
          {/* Left side: test connectivity (step 2 in create, or always in edit) */}
          <div className="flex items-center gap-2">
            {step === 2 && !isEditing && provider && (
              <>
                <button
                  type="button"
                  onClick={handleTestConnectivity}
                  disabled={testMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-[12px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-40"
                >
                  {testMutation.isPending ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Zap size={12} />
                  )}
                  Test Connectivity
                </button>
                {testResult && <TestChip {...testResult} errorMsg={testResult.errorMsg} />}
              </>
            )}
          </div>

          {/* Right side: nav buttons */}
          <div className="flex items-center gap-2">
            {!isEditing && step > 1 && (
              <button
                type="button"
                onClick={handleBack}
                className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                Back
              </button>
            )}

            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              Cancel
            </button>

            {!isEditing && step < totalSteps ? (
              <button
                type="button"
                onClick={handleNext}
                disabled={!canAdvanceStep1}
                className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                Next
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={
                  isPending ||
                  (isEditing ? !canSubmitEdit : !canAdvanceStep1)
                }
                className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {isPending && <Loader2 size={14} className="animate-spin" />}
                {isEditing ? "Save Changes" : "Create Provider"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
