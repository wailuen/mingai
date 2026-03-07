"use client";

import { useState, useEffect } from "react";
import { X, Loader2 } from "lucide-react";
import {
  useCreateLLMProfile,
  useUpdateLLMProfile,
  type LLMProfile,
  type CreateLLMProfilePayload,
  type UpdateLLMProfilePayload,
} from "@/lib/hooks/useLLMProfiles";

interface ProfileFormProps {
  profile: LLMProfile | null;
  onClose: () => void;
  onSaved: () => void;
}

interface FormState {
  tenant_id: string;
  name: string;
  provider: string;
  primary_model: string;
  intent_model: string;
  embedding_model: string;
  endpoint_url: string;
  api_key_ref: string;
  is_default: boolean;
}

const EMPTY_FORM: FormState = {
  tenant_id: "",
  name: "",
  provider: "",
  primary_model: "",
  intent_model: "",
  embedding_model: "",
  endpoint_url: "",
  api_key_ref: "",
  is_default: false,
};

function formFromProfile(profile: LLMProfile): FormState {
  return {
    tenant_id: profile.tenant_id,
    name: profile.name,
    provider: profile.provider,
    primary_model: profile.primary_model,
    intent_model: profile.intent_model,
    embedding_model: profile.embedding_model,
    endpoint_url: profile.endpoint_url ?? "",
    api_key_ref: "",
    is_default: profile.is_default,
  };
}

export function ProfileForm({ profile, onClose, onSaved }: ProfileFormProps) {
  const isEditing = profile !== null;
  const createMutation = useCreateLLMProfile();
  const updateMutation = useUpdateLLMProfile();
  const isPending = createMutation.isPending || updateMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error;

  const [form, setForm] = useState<FormState>(
    profile ? formFromProfile(profile) : EMPTY_FORM,
  );

  useEffect(() => {
    setForm(profile ? formFromProfile(profile) : EMPTY_FORM);
  }, [profile]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (isEditing) {
      const payload: UpdateLLMProfilePayload = {};
      if (form.name !== profile.name) payload.name = form.name;
      if (form.provider !== profile.provider) payload.provider = form.provider;
      if (form.primary_model !== profile.primary_model)
        payload.primary_model = form.primary_model;
      if (form.intent_model !== profile.intent_model)
        payload.intent_model = form.intent_model;
      if (form.embedding_model !== profile.embedding_model)
        payload.embedding_model = form.embedding_model;
      if (form.endpoint_url !== (profile.endpoint_url ?? ""))
        payload.endpoint_url = form.endpoint_url || undefined;
      if (form.api_key_ref) payload.api_key_ref = form.api_key_ref;
      if (form.is_default !== profile.is_default)
        payload.is_default = form.is_default;

      if (Object.keys(payload).length === 0) {
        onClose();
        return;
      }

      updateMutation.mutate(
        { id: profile.id, payload },
        {
          onSuccess: () => {
            onSaved();
            onClose();
          },
        },
      );
    } else {
      const payload: CreateLLMProfilePayload = {
        tenant_id: form.tenant_id,
        name: form.name,
        provider: form.provider,
        primary_model: form.primary_model,
        intent_model: form.intent_model,
        embedding_model: form.embedding_model,
      };
      if (form.endpoint_url) payload.endpoint_url = form.endpoint_url;
      if (form.api_key_ref) payload.api_key_ref = form.api_key_ref;
      if (form.is_default) payload.is_default = true;

      createMutation.mutate(payload, {
        onSuccess: () => {
          onSaved();
          onClose();
        },
      });
    }
  }

  const canSubmit =
    form.name.trim() &&
    form.provider.trim() &&
    form.primary_model.trim() &&
    form.intent_model.trim() &&
    form.embedding_model.trim() &&
    (isEditing || form.tenant_id.trim());

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="mx-4 w-full max-w-xl rounded-card border border-border bg-bg-surface p-6"
      >
        {/* Header */}
        <div className="mb-5 flex items-start justify-between">
          <h2 className="text-section-heading text-text-primary">
            {isEditing ? `Edit: ${profile.name}` : "New LLM Profile"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
          {/* Tenant ID — only for create */}
          {!isEditing && (
            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                Tenant ID *
              </label>
              <input
                type="text"
                value={form.tenant_id}
                onChange={(e) => updateField("tenant_id", e.target.value)}
                required
                placeholder="UUID of the tenant"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>
          )}

          {/* Name */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Profile Name *
            </label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => updateField("name", e.target.value)}
              required
              maxLength={200}
              placeholder="e.g. Standard, Premium, Enterprise"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Provider */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Provider *
            </label>
            <input
              type="text"
              value={form.provider}
              onChange={(e) => updateField("provider", e.target.value)}
              required
              maxLength={100}
              placeholder="e.g. azure_openai, openai, anthropic"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Model fields */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                Primary Model *
              </label>
              <input
                type="text"
                value={form.primary_model}
                onChange={(e) => updateField("primary_model", e.target.value)}
                required
                maxLength={255}
                placeholder="e.g. gpt-4o"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
              <p className="mt-1 text-[10px] text-text-faint">
                Must match deployment name exactly
              </p>
            </div>

            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                Intent Model *
              </label>
              <input
                type="text"
                value={form.intent_model}
                onChange={(e) => updateField("intent_model", e.target.value)}
                required
                maxLength={255}
                placeholder="e.g. gpt-4o-mini"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
              <p className="mt-1 text-[10px] text-text-faint">
                Must match deployment name exactly
              </p>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Embedding Model *
            </label>
            <input
              type="text"
              value={form.embedding_model}
              onChange={(e) => updateField("embedding_model", e.target.value)}
              required
              maxLength={255}
              placeholder="e.g. text-embedding-3-small"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
            <p className="mt-1 text-[10px] text-text-faint">
              Must match deployment name exactly
            </p>
          </div>

          {/* Optional fields */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Endpoint URL
            </label>
            <input
              type="url"
              value={form.endpoint_url}
              onChange={(e) => updateField("endpoint_url", e.target.value)}
              maxLength={500}
              placeholder="https://your-resource.openai.azure.com/"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              API Key Reference
            </label>
            <input
              type="text"
              value={form.api_key_ref}
              onChange={(e) => updateField("api_key_ref", e.target.value)}
              maxLength={500}
              placeholder="vault://secret/path or env var name"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
            <p className="mt-1 text-[10px] text-text-faint">
              Reference to secret store, never the raw key
            </p>
          </div>

          {/* Default toggle */}
          <label className="flex cursor-pointer items-center gap-2.5 rounded-control px-3 py-2 text-sm text-text-muted transition-colors hover:bg-bg-elevated">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(e) => updateField("is_default", e.target.checked)}
              className="accent-accent"
            />
            Set as default profile for this tenant
          </label>
        </div>

        {/* Error */}
        {mutationError && (
          <p className="mt-4 text-sm text-alert">
            {mutationError.message ?? "Operation failed."}
          </p>
        )}

        {/* Footer */}
        <div className="mt-5 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit || isPending}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {isPending && <Loader2 size={14} className="animate-spin" />}
            {isEditing ? "Save Changes" : "Create Profile"}
          </button>
        </div>
      </form>
    </div>
  );
}
