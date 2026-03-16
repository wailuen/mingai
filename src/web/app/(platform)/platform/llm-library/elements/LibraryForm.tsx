"use client";

import { useState, useEffect } from "react";
import { X, Loader2, Eye, EyeOff } from "lucide-react";
import {
  useCreateLLMLibraryEntry,
  useUpdateLLMLibraryEntry,
  type LLMLibraryEntry,
  type LLMLibraryProvider,
  type PlanTier,
  type CreateLLMLibraryPayload,
  type UpdateLLMLibraryPayload,
} from "@/lib/hooks/useLLMLibrary";
import { cn } from "@/lib/utils";

interface LibraryFormProps {
  entry: LLMLibraryEntry | null;
  onClose: () => void;
  onSaved: () => void;
}

interface FormState {
  provider: LLMLibraryProvider;
  model_name: string;
  display_name: string;
  plan_tier: PlanTier;
  is_recommended: boolean;
  pricing_per_1k_tokens_in: string;
  pricing_per_1k_tokens_out: string;
  best_practices_md: string;
}

const EMPTY_FORM: FormState = {
  provider: "azure_openai",
  model_name: "",
  display_name: "",
  plan_tier: "starter",
  is_recommended: false,
  pricing_per_1k_tokens_in: "",
  pricing_per_1k_tokens_out: "",
  best_practices_md: "",
};

const PROVIDERS: { value: LLMLibraryProvider; label: string }[] = [
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "openai_direct", label: "OpenAI Direct" },
  { value: "anthropic", label: "Anthropic" },
];

const PLAN_TIERS: { value: PlanTier; label: string }[] = [
  { value: "starter", label: "Starter" },
  { value: "professional", label: "Professional" },
  { value: "enterprise", label: "Enterprise" },
];

function formFromEntry(entry: LLMLibraryEntry): FormState {
  return {
    provider: entry.provider,
    model_name: entry.model_name,
    display_name: entry.display_name,
    plan_tier: entry.plan_tier,
    is_recommended: entry.is_recommended,
    pricing_per_1k_tokens_in: entry.pricing_per_1k_tokens_in.toString(),
    pricing_per_1k_tokens_out: entry.pricing_per_1k_tokens_out.toString(),
    best_practices_md: entry.best_practices_md ?? "",
  };
}

export function LibraryForm({ entry, onClose, onSaved }: LibraryFormProps) {
  const isEditing = entry !== null;
  const createMutation = useCreateLLMLibraryEntry();
  const updateMutation = useUpdateLLMLibraryEntry();
  const isPending = createMutation.isPending || updateMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error;

  const [form, setForm] = useState<FormState>(
    entry ? formFromEntry(entry) : EMPTY_FORM,
  );
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    setForm(entry ? formFromEntry(entry) : EMPTY_FORM);
  }, [entry]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const pricingInValid =
    form.pricing_per_1k_tokens_in !== "" &&
    !isNaN(Number(form.pricing_per_1k_tokens_in)) &&
    Number(form.pricing_per_1k_tokens_in) >= 0;
  const pricingOutValid =
    form.pricing_per_1k_tokens_out !== "" &&
    !isNaN(Number(form.pricing_per_1k_tokens_out)) &&
    Number(form.pricing_per_1k_tokens_out) >= 0;

  const canSave =
    form.model_name.trim() &&
    form.display_name.trim() &&
    form.provider &&
    pricingInValid &&
    pricingOutValid;

  function handleSaveDraft(e: React.FormEvent) {
    e.preventDefault();
    if (!canSave) return;

    if (isEditing) {
      const payload: UpdateLLMLibraryPayload = {};
      if (form.provider !== entry.provider) payload.provider = form.provider;
      if (form.model_name !== entry.model_name)
        payload.model_name = form.model_name;
      if (form.display_name !== entry.display_name)
        payload.display_name = form.display_name;
      if (form.plan_tier !== entry.plan_tier)
        payload.plan_tier = form.plan_tier;
      if (form.is_recommended !== entry.is_recommended)
        payload.is_recommended = form.is_recommended;
      if (form.best_practices_md !== (entry.best_practices_md ?? ""))
        payload.best_practices_md = form.best_practices_md;

      const newPriceIn = Number(form.pricing_per_1k_tokens_in);
      if (newPriceIn !== entry.pricing_per_1k_tokens_in)
        payload.pricing_per_1k_tokens_in = newPriceIn;
      const newPriceOut = Number(form.pricing_per_1k_tokens_out);
      if (newPriceOut !== entry.pricing_per_1k_tokens_out)
        payload.pricing_per_1k_tokens_out = newPriceOut;

      if (Object.keys(payload).length === 0) {
        onClose();
        return;
      }

      updateMutation.mutate(
        { id: entry.id, payload },
        { onSuccess: () => onSaved() },
      );
    } else {
      const payload: CreateLLMLibraryPayload = {
        provider: form.provider,
        model_name: form.model_name,
        display_name: form.display_name,
        plan_tier: form.plan_tier,
        is_recommended: form.is_recommended,
        pricing_per_1k_tokens_in: Number(form.pricing_per_1k_tokens_in),
        pricing_per_1k_tokens_out: Number(form.pricing_per_1k_tokens_out),
        best_practices_md: form.best_practices_md || undefined,
      };

      createMutation.mutate(payload, { onSuccess: () => onSaved() });
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={handleSaveDraft}
        className="mx-4 w-full max-w-xl rounded-card border border-border bg-bg-surface p-6"
      >
        {/* Header */}
        <div className="mb-5 flex items-start justify-between">
          <h2 className="text-section-heading text-text-primary">
            {isEditing ? `Edit: ${entry.display_name}` : "New Library Entry"}
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
          {/* Display Name */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Display Name *
            </label>
            <input
              type="text"
              value={form.display_name}
              onChange={(e) => updateField("display_name", e.target.value)}
              required
              maxLength={200}
              placeholder="e.g. GPT-4o Standard"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Provider */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Provider *
            </label>
            <select
              value={form.provider}
              onChange={(e) =>
                updateField("provider", e.target.value as LLMLibraryProvider)
              }
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent focus:outline-none"
            >
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>

          {/* Model Name */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Model Name *
            </label>
            <input
              type="text"
              value={form.model_name}
              onChange={(e) => updateField("model_name", e.target.value)}
              required
              maxLength={255}
              placeholder="e.g. agentic-worker"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
            <p className="mt-1 text-[10px] text-text-faint">
              Must match deployment name exactly
            </p>
          </div>

          {/* Plan Tier */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Plan Tier *
            </label>
            <div className="flex items-center gap-2">
              {PLAN_TIERS.map((tier) => (
                <button
                  key={tier.value}
                  type="button"
                  onClick={() => updateField("plan_tier", tier.value)}
                  className={cn(
                    "rounded-control border px-3 py-1.5 text-[12px] font-medium transition-colors",
                    form.plan_tier === tier.value
                      ? "border-accent bg-accent-dim text-accent"
                      : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
                  )}
                >
                  {tier.label}
                </button>
              ))}
            </div>
          </div>

          {/* Pricing */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                Price / 1K Tokens In *
              </label>
              <input
                type="text"
                inputMode="decimal"
                value={form.pricing_per_1k_tokens_in}
                onChange={(e) =>
                  updateField("pricing_per_1k_tokens_in", e.target.value)
                }
                required
                placeholder="0.000150"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                Price / 1K Tokens Out *
              </label>
              <input
                type="text"
                inputMode="decimal"
                value={form.pricing_per_1k_tokens_out}
                onChange={(e) =>
                  updateField("pricing_per_1k_tokens_out", e.target.value)
                }
                required
                placeholder="0.000600"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>
          </div>

          {/* Recommended toggle */}
          <label className="flex cursor-pointer items-center gap-2.5 rounded-control px-3 py-2 text-sm text-text-muted transition-colors hover:bg-bg-elevated">
            <input
              type="checkbox"
              checked={form.is_recommended}
              onChange={(e) => updateField("is_recommended", e.target.checked)}
              className="accent-accent"
            />
            Mark as recommended
          </label>

          {/* Best Practices */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-label-nav uppercase text-text-faint">
                Best Practices (Markdown)
              </label>
              <button
                type="button"
                onClick={() => setShowPreview(!showPreview)}
                className="flex items-center gap-1 text-[11px] text-text-muted transition-colors hover:text-text-primary"
              >
                {showPreview ? <EyeOff size={12} /> : <Eye size={12} />}
                {showPreview ? "Edit" : "Preview"}
              </button>
            </div>
            {showPreview ? (
              <div className="min-h-[120px] rounded-control border border-border bg-bg-elevated p-3 text-sm text-text-primary">
                {form.best_practices_md || (
                  <span className="text-text-faint">No content</span>
                )}
              </div>
            ) : (
              <textarea
                value={form.best_practices_md}
                onChange={(e) =>
                  updateField("best_practices_md", e.target.value)
                }
                rows={5}
                placeholder="Usage guidelines, recommended parameters, limitations..."
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            )}
          </div>
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
            disabled={!canSave || isPending}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {isPending && <Loader2 size={14} className="animate-spin" />}
            {isEditing ? "Save Changes" : "Save Draft"}
          </button>
        </div>
      </form>
    </div>
  );
}
