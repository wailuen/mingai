"use client";

import { useState, useEffect } from "react";
import { X, Loader2, Eye, EyeOff, Plus, CheckCircle2 } from "lucide-react";
import {
  useCreateLLMLibraryEntry,
  useUpdateLLMLibraryEntry,
  usePublishLLMLibraryEntry,
  type LLMLibraryEntry,
  type LLMLibraryProvider,
  type PlanTier,
  type ModelSlotKey,
  type ModelSlot,
  type CreateLLMLibraryPayload,
  type UpdateLLMLibraryPayload,
} from "@/lib/hooks/useLLMLibrary";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Props & Types
// ---------------------------------------------------------------------------

interface LibraryFormProps {
  entry: LLMLibraryEntry | null;
  onClose: () => void;
  onSaved: () => void;
}

interface SlotFormState {
  provider: LLMLibraryProvider;
  deployment_name: string;
  override: boolean;
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
  slots: Record<ModelSlotKey, SlotFormState>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SLOT_KEYS: { key: ModelSlotKey; label: string }[] = [
  { key: "intent_model", label: "Intent Model" },
  { key: "primary_model", label: "Primary Model" },
  { key: "vision_model", label: "Vision Model" },
  { key: "embedding_model", label: "Embedding Model" },
];

const EMPTY_SLOT: SlotFormState = {
  provider: "azure_openai",
  deployment_name: "",
  override: false,
};

const EMPTY_FORM: FormState = {
  provider: "azure_openai",
  model_name: "",
  display_name: "",
  plan_tier: "starter",
  is_recommended: false,
  pricing_per_1k_tokens_in: "",
  pricing_per_1k_tokens_out: "",
  best_practices_md: "",
  slots: {
    intent_model: { ...EMPTY_SLOT },
    primary_model: { ...EMPTY_SLOT },
    vision_model: { ...EMPTY_SLOT },
    embedding_model: { ...EMPTY_SLOT },
  },
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function slotFromEntry(slot: ModelSlot | undefined): SlotFormState {
  if (!slot) return { ...EMPTY_SLOT };
  return {
    provider: slot.provider,
    deployment_name: slot.deployment_name,
    override: slot.override,
  };
}

function formFromEntry(entry: LLMLibraryEntry): FormState {
  const slots = entry.model_slots;
  return {
    provider: entry.provider,
    model_name: entry.model_name,
    display_name: entry.display_name,
    plan_tier: entry.plan_tier,
    is_recommended: entry.is_recommended,
    pricing_per_1k_tokens_in: entry.pricing_per_1k_tokens_in.toString(),
    pricing_per_1k_tokens_out: entry.pricing_per_1k_tokens_out.toString(),
    best_practices_md: entry.best_practices_md ?? "",
    slots: {
      intent_model: slotFromEntry(slots?.intent_model),
      primary_model: slotFromEntry(slots?.primary_model),
      vision_model: slotFromEntry(slots?.vision_model),
      embedding_model: slotFromEntry(slots?.embedding_model),
    },
  };
}

function allSlotsHaveDeployment(slots: Record<ModelSlotKey, SlotFormState>): boolean {
  return SLOT_KEYS.every((s) => slots[s.key].deployment_name.trim().length > 0);
}

function buildModelSlots(
  slots: Record<ModelSlotKey, SlotFormState>,
): Record<ModelSlotKey, ModelSlot> {
  const result: Partial<Record<ModelSlotKey, ModelSlot>> = {};
  for (const { key } of SLOT_KEYS) {
    result[key] = {
      provider: slots[key].provider,
      deployment_name: slots[key].deployment_name.trim(),
      override: slots[key].override,
    };
  }
  return result as Record<ModelSlotKey, ModelSlot>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LibraryForm({ entry, onClose, onSaved }: LibraryFormProps) {
  const isEditing = entry !== null;
  const createMutation = useCreateLLMLibraryEntry();
  const updateMutation = useUpdateLLMLibraryEntry();
  const publishMutation = usePublishLLMLibraryEntry();
  const isPending =
    createMutation.isPending || updateMutation.isPending || publishMutation.isPending;
  const mutationError =
    createMutation.error ?? updateMutation.error ?? publishMutation.error;

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

  function updateSlot(slotKey: ModelSlotKey, field: keyof SlotFormState, value: string | boolean) {
    setForm((prev) => ({
      ...prev,
      slots: {
        ...prev.slots,
        [slotKey]: {
          ...prev.slots[slotKey],
          [field]: value,
        },
      },
    }));
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

  const canPublish =
    canSave &&
    allSlotsHaveDeployment(form.slots) &&
    isEditing &&
    entry.status === "Draft";

  function handleSaveDraft(e: React.FormEvent) {
    e.preventDefault();
    if (!canSave) return;

    const modelSlots = buildModelSlots(form.slots);

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

      payload.model_slots = modelSlots;

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
        model_slots: modelSlots,
      };

      createMutation.mutate(payload, { onSuccess: () => onSaved() });
    }
  }

  function handlePublish() {
    if (!isEditing || !canPublish) return;
    // Save + Publish in sequence: update first, then publish
    const modelSlots = buildModelSlots(form.slots);
    const payload: UpdateLLMLibraryPayload = {
      model_slots: modelSlots,
      best_practices_md: form.best_practices_md,
    };

    updateMutation.mutate(
      { id: entry.id, payload },
      {
        onSuccess: () => {
          publishMutation.mutate(entry.id, {
            onSuccess: () => onSaved(),
          });
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
        onSubmit={handleSaveDraft}
        className="mx-4 w-full max-w-[640px] rounded-card border border-border bg-bg-surface p-6"
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

          {/* ---------------------------------------------------------------- */}
          {/* Model Slots (4 slots)                                            */}
          {/* ---------------------------------------------------------------- */}
          <div className="rounded-card border border-border bg-bg-base p-4">
            <div className="mb-3 flex items-center gap-2">
              <Plus size={14} className="text-accent" />
              <h3 className="text-[13px] font-semibold text-text-primary">
                Model Slots
              </h3>
            </div>
            <p className="mb-4 text-[11px] text-text-faint">
              Configure deployment names for each model slot. All 4 slots must have a deployment name to publish.
            </p>

            <div className="space-y-4">
              {SLOT_KEYS.map(({ key, label }) => (
                <ModelSlotField
                  key={key}
                  label={label}
                  slot={form.slots[key]}
                  onUpdate={(field, value) => updateSlot(key, field, value)}
                />
              ))}
            </div>
          </div>

          {/* Best Practices (Markdown) */}
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
              <div className="prose-invert min-h-[120px] rounded-control border border-border bg-bg-elevated p-3 text-sm text-text-primary">
                {form.best_practices_md ? (
                  <MarkdownPreview content={form.best_practices_md} />
                ) : (
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

          {/* Draft -> Publish (only for Draft entries with all slots filled) */}
          {canPublish && (
            <button
              type="button"
              onClick={handlePublish}
              disabled={isPending}
              className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {isPending && <Loader2 size={14} className="animate-spin" />}
              <CheckCircle2 size={14} />
              Save &amp; Publish
            </button>
          )}

          <button
            type="submit"
            disabled={!canSave || isPending}
            className="flex items-center gap-1.5 rounded-control border border-accent px-4 py-1.5 text-sm font-semibold text-accent transition-opacity hover:bg-accent-dim disabled:opacity-40"
          >
            {isPending && !publishMutation.isPending && (
              <Loader2 size={14} className="animate-spin" />
            )}
            {isEditing ? "Save Draft" : "Save Draft"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ModelSlotField sub-component
// ---------------------------------------------------------------------------

interface ModelSlotFieldProps {
  label: string;
  slot: SlotFormState;
  onUpdate: (field: keyof SlotFormState, value: string | boolean) => void;
}

function ModelSlotField({ label, slot, onUpdate }: ModelSlotFieldProps) {
  return (
    <div className="rounded-control border border-border-faint bg-bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[12px] font-medium text-text-primary">
          {label}
        </span>
        <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-text-faint">
          <input
            type="checkbox"
            checked={slot.override}
            onChange={(e) => onUpdate("override", e.target.checked)}
            className="accent-accent"
          />
          Override
        </label>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <select
          value={slot.provider}
          onChange={(e) => onUpdate("provider", e.target.value)}
          className="rounded-control border border-border bg-bg-elevated px-2.5 py-1.5 text-[12px] text-text-primary transition-colors focus:border-accent focus:outline-none"
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={slot.deployment_name}
          onChange={(e) => onUpdate("deployment_name", e.target.value)}
          maxLength={255}
          placeholder="deployment-name"
          className="rounded-control border border-border bg-bg-elevated px-2.5 py-1.5 font-mono text-[12px] text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Simple markdown preview (renders basic markdown without external dep)
// ---------------------------------------------------------------------------

function MarkdownPreview({ content }: { content: string }) {
  // Simple line-by-line rendering: headings, bold, lists, paragraphs
  const lines = content.split("\n");
  return (
    <div className="space-y-1 text-[13px] leading-relaxed text-text-primary">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("### ")) {
          return (
            <p key={i} className="mt-2 text-[13px] font-semibold text-text-primary">
              {trimmed.slice(4)}
            </p>
          );
        }
        if (trimmed.startsWith("## ")) {
          return (
            <p key={i} className="mt-2 text-[14px] font-bold text-text-primary">
              {trimmed.slice(3)}
            </p>
          );
        }
        if (trimmed.startsWith("# ")) {
          return (
            <p key={i} className="mt-2 text-[15px] font-bold text-text-primary">
              {trimmed.slice(2)}
            </p>
          );
        }
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          return (
            <p key={i} className="pl-3 text-text-muted">
              <span className="mr-1 text-accent">&bull;</span>
              {trimmed.slice(2)}
            </p>
          );
        }
        if (trimmed === "") return <div key={i} className="h-2" />;
        return (
          <p key={i} className="text-text-muted">
            {trimmed}
          </p>
        );
      })}
    </div>
  );
}
