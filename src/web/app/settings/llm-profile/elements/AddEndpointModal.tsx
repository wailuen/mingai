"use client";

import { useState } from "react";
import { X, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCreateBYOLLMEntry,
  testConnection,
  type ProfileSlot,
  type CreateBYOLLMEntryPayload,
  type TestConnectionResult,
} from "@/lib/hooks/useLLMProfileConfig";

type BYOProvider = "azure_openai" | "openai" | "anthropic" | "google";

interface AddEndpointModalProps {
  slot: ProfileSlot;
  onClose: () => void;
  onSaved: () => void;
}

const SLOT_LABELS: Record<ProfileSlot, string> = {
  chat: "Chat",
  intent: "Intent",
  vision: "Vision",
  agent: "Agent",
};

const PROVIDERS: { value: BYOProvider; label: string }[] = [
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
];

const AZURE_API_VERSIONS = [
  "2024-12-01-preview",
  "2024-08-01-preview",
  "2024-05-01-preview",
];

function errorCodeToMessage(code: string | null, msg: string | null): string {
  switch (code) {
    case "auth_failed":
      return "Authentication failed — check your API key";
    case "ssrf_blocked":
    case "endpoint_not_permitted":
      return "Endpoint address is not permitted — use a supported provider URL";
    case "timeout":
      return "Connection timed out — check the endpoint URL";
    default:
      return msg ?? "Connection test failed — check your configuration";
  }
}

export function AddEndpointModal({
  slot,
  onClose,
  onSaved,
}: AddEndpointModalProps) {
  const [provider, setProvider] = useState<BYOProvider>("azure_openai");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiVersion, setApiVersion] = useState("2024-12-01-preview");
  const [modelName, setModelName] = useState("");

  const [testState, setTestState] = useState<
    "idle" | "testing" | "passed" | "failed"
  >("idle");
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(
    null,
  );

  const createMutation = useCreateBYOLLMEntry();

  const isAzure = provider === "azure_openai";
  const canTest =
    !!apiKey.trim() && !!modelName.trim() && (!isAzure || !!endpointUrl.trim());
  const canSave = testState === "passed" && !createMutation.isPending;

  async function handleTest() {
    if (!canTest) return;
    setTestState("testing");
    setTestResult(null);

    const result = await testConnection({
      provider,
      endpoint_url: isAzure ? endpointUrl || undefined : undefined,
      api_key: apiKey,
      api_version: isAzure ? apiVersion || undefined : undefined,
      model_name: modelName,
    });

    setTestResult(result);
    setTestState(result.passed ? "passed" : "failed");
  }

  function handleSave() {
    if (!canSave) return;

    const payload: CreateBYOLLMEntryPayload = {
      slot,
      provider,
      endpoint_url: isAzure ? endpointUrl || undefined : undefined,
      api_key: apiKey,
      api_version: isAzure ? apiVersion || undefined : undefined,
      model_name: modelName,
    };

    createMutation.mutate(payload, {
      onSuccess: () => onSaved(),
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-base/60">
      <div className="w-full max-w-[520px] rounded-card border border-border bg-bg-surface shadow-md">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-section-heading text-text-primary">
            Configure {SLOT_LABELS[slot]} Model
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1.5 text-text-faint hover:bg-bg-elevated"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 px-6 py-5">
          {/* Provider */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Provider
            </label>
            <div className="flex flex-wrap gap-2">
              {PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => {
                    setProvider(p.value);
                    setTestState("idle");
                    setTestResult(null);
                  }}
                  className={cn(
                    "rounded-control border px-3 py-1.5 text-body-default transition-colors",
                    provider === p.value
                      ? "border-accent/40 bg-accent-dim text-accent"
                      : "border-border bg-bg-elevated text-text-muted hover:border-accent/30",
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Endpoint URL — Azure only */}
          {isAzure && (
            <div>
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Endpoint URL
              </label>
              <input
                type="text"
                value={endpointUrl}
                onChange={(e) => {
                  setEndpointUrl(e.target.value);
                  setTestState("idle");
                }}
                placeholder="https://your-resource.openai.azure.com/"
                maxLength={512}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
              <p className="mt-1 text-[11px] text-text-faint">
                Your Azure OpenAI resource endpoint
              </p>
            </div>
          )}

          {/* API Key */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                setTestState("idle");
              }}
              placeholder="sk-..."
              autoComplete="new-password"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
            <p className="mt-1 text-[11px] text-text-faint">
              Never shared or displayed after saving
            </p>
          </div>

          {/* API Version — Azure only */}
          {isAzure && (
            <div>
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                API Version
              </label>
              <select
                value={apiVersion}
                onChange={(e) => setApiVersion(e.target.value)}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary transition-colors focus:border-accent focus:outline-none"
              >
                {AZURE_API_VERSIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Model / Deployment name */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              {isAzure ? "Deployment Name" : "Model Name"}
            </label>
            <input
              type="text"
              value={modelName}
              onChange={(e) => {
                setModelName(e.target.value);
                setTestState("idle");
              }}
              placeholder={isAzure ? "my-deployment" : "gpt-4o"}
              maxLength={255}
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Test button + inline result */}
          <div>
            <button
              type="button"
              onClick={handleTest}
              disabled={!canTest || testState === "testing"}
              className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
            >
              {testState === "testing" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : null}
              Test Connection
            </button>

            {testState === "passed" && testResult && (
              <div className="mt-2 flex items-center gap-2">
                <CheckCircle2 size={13} className="flex-shrink-0 text-accent" />
                <span className="text-body-default text-accent">
                  Connected successfully — model responded in{" "}
                  <span className="font-mono text-data-value">
                    {testResult.latency_ms}ms
                  </span>
                </span>
              </div>
            )}

            {testState === "failed" && testResult && (
              <div className="mt-2 flex items-center gap-2">
                <AlertCircle size={13} className="flex-shrink-0 text-alert" />
                <span className="text-body-default text-alert">
                  {errorCodeToMessage(
                    testResult.error_code,
                    testResult.error_message,
                  )}
                </span>
              </div>
            )}
          </div>

          {createMutation.error && (
            <p className="text-body-default text-alert">
              {createMutation.error.message ?? "Failed to save configuration."}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {createMutation.isPending && (
              <Loader2 size={13} className="animate-spin" />
            )}
            Save Configuration
          </button>
        </div>
      </div>
    </div>
  );
}
