"use client";

import { useState } from "react";
import { Loader2, Eye, EyeOff, Trash2, ShieldCheck, Lock } from "lucide-react";
import {
  useUpdateBYOLLM,
  useDeleteBYOLLM,
  type LLMConfig,
} from "@/lib/hooks/useLLMConfig";

interface BYOLLMTabProps {
  config: LLMConfig;
  plan: string;
}

const PROVIDERS = [
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "openai_direct", label: "OpenAI Direct" },
  { value: "anthropic", label: "Anthropic" },
];

export function BYOLLMTab({ config, plan }: BYOLLMTabProps) {
  const updateBYOLLM = useUpdateBYOLLM();
  const deleteBYOLLM = useDeleteBYOLLM();

  const [provider, setProvider] = useState(
    config.byollm.provider ?? "azure_openai",
  );
  const [apiKey, setApiKey] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Enterprise gate
  if (plan !== "enterprise") {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-8 text-center">
        <Lock size={24} className="mx-auto mb-3 text-text-faint" />
        <h3 className="text-section-heading text-text-primary">
          Enterprise Feature
        </h3>
        <p className="mt-2 text-sm text-text-muted">
          BYOLLM (Bring Your Own LLM) is available on the Enterprise plan.
          Contact your platform administrator to upgrade.
        </p>
      </div>
    );
  }

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) return;

    updateBYOLLM.mutate({
      provider,
      api_key: apiKey,
      endpoint: endpoint.trim() || undefined,
    });
  }

  function handleDelete() {
    deleteBYOLLM.mutate(undefined, {
      onSuccess: () => setShowDeleteConfirm(false),
    });
  }

  return (
    <div>
      <p className="mb-4 text-sm text-text-muted">
        Use your own API key to connect directly to an LLM provider. Your key is
        encrypted and never displayed after saving.
      </p>

      {/* Key present indicator */}
      {config.byollm.key_present && (
        <div className="mb-4 flex items-center gap-2 rounded-card border border-accent bg-accent-dim p-3">
          <ShieldCheck size={16} className="text-accent" />
          <span className="text-sm text-text-primary">
            API key saved for{" "}
            <span className="font-mono text-data-value text-accent">
              {config.byollm.provider}
            </span>
          </span>
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-4">
        {/* Provider */}
        <div>
          <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
            Provider *
          </label>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent focus:outline-none"
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        {/* API Key */}
        <div>
          <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
            API Key *
          </label>
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              required
              placeholder={
                config.byollm.key_present
                  ? "Enter new key to replace existing"
                  : "sk-..."
              }
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 pr-10 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-faint transition-colors hover:text-text-primary"
            >
              {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        {/* Endpoint (optional) */}
        <div>
          <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
            Endpoint (Optional)
          </label>
          <input
            type="url"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="https://your-resource.openai.azure.com/"
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={!apiKey.trim() || updateBYOLLM.isPending}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {updateBYOLLM.isPending && (
              <Loader2 size={14} className="animate-spin" />
            )}
            Save Key
          </button>

          {config.byollm.key_present && (
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(true)}
              className="flex items-center gap-1 rounded-control border border-border px-3 py-2 text-sm text-alert transition-colors hover:bg-alert-dim"
            >
              <Trash2 size={14} />
              Remove Key
            </button>
          )}
        </div>
      </form>

      {updateBYOLLM.error && (
        <p className="mt-3 text-sm text-alert">{updateBYOLLM.error.message}</p>
      )}

      {/* Delete confirmation dialog */}
      {showDeleteConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowDeleteConfirm(false);
          }}
        >
          <div className="mx-4 w-full max-w-md rounded-card border border-border bg-bg-surface p-6">
            <h3 className="text-section-heading text-text-primary">
              Remove API Key
            </h3>
            <p className="mt-2 text-sm text-text-muted">
              This will remove your stored API key. Your workspace will fall
              back to the library profile if one is configured.
            </p>
            <div className="mt-5 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(false)}
                className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleteBYOLLM.isPending}
                className="flex items-center gap-1.5 rounded-control bg-alert px-4 py-1.5 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {deleteBYOLLM.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
