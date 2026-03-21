"use client";

import { useState, useEffect } from "react";
import {
  X,
  Loader2,
  Eye,
  EyeOff,
  CheckCircle2,
  Archive,
  KeyRound,
  FlaskConical,
} from "lucide-react";
import { ApiException } from "@/lib/api";
import {
  useCreateLLMLibraryEntry,
  useUpdateLLMLibraryEntry,
  usePublishLLMLibraryEntry,
  useDeprecateLLMLibraryEntry,
  useTestProfile,
  useTenantAssignments,
  type LLMLibraryEntry,
  type LLMLibraryProvider,
  type PlanTier,
  type CreateLLMLibraryPayload,
  type UpdateLLMLibraryPayload,
  type TestPromptResult,
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

interface FormState {
  provider: LLMLibraryProvider;
  model_name: string;
  display_name: string;
  plan_tier: PlanTier;
  is_recommended: boolean;
  pricing_per_1k_tokens_in: string;
  pricing_per_1k_tokens_out: string;
  best_practices_md: string;
  endpoint_url: string;
  api_key: string;
  api_version: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EMPTY_FORM: FormState = {
  provider: "azure_openai",
  model_name: "",
  display_name: "",
  plan_tier: "starter",
  is_recommended: false,
  pricing_per_1k_tokens_in: "",
  pricing_per_1k_tokens_out: "",
  best_practices_md: "",
  endpoint_url: "",
  api_key: "",
  api_version: "2024-12-01-preview",
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

function formFromEntry(entry: LLMLibraryEntry): FormState {
  return {
    provider: entry.provider,
    model_name: entry.model_name,
    display_name: entry.display_name,
    plan_tier: entry.plan_tier,
    is_recommended: entry.is_recommended,
    pricing_per_1k_tokens_in:
      entry.pricing_per_1k_tokens_in != null
        ? entry.pricing_per_1k_tokens_in.toString()
        : "",
    pricing_per_1k_tokens_out:
      entry.pricing_per_1k_tokens_out != null
        ? entry.pricing_per_1k_tokens_out.toString()
        : "",
    best_practices_md: entry.best_practices_md ?? "",
    endpoint_url: entry.endpoint_url ?? "",
    api_key: "", // never pre-filled from entry
    api_version: entry.api_version ?? "2024-12-01-preview",
  };
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// TestResultsPanel sub-component
// ---------------------------------------------------------------------------

interface TestResultsPanelProps {
  results: TestPromptResult[];
}

function TestResultsPanel({ results }: TestResultsPanelProps) {
  return (
    <div className="mt-4 rounded-card border border-border bg-bg-base p-4 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <CheckCircle2 size={14} className="text-accent" />
        <span className="text-[13px] font-semibold text-text-primary">
          Test Results ({results.length} prompt{results.length !== 1 ? "s" : ""}
          )
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-border">
              <th className="py-1.5 pr-3 text-left text-label-nav uppercase text-text-faint font-medium">
                Prompt
              </th>
              <th className="py-1.5 pr-3 text-right text-label-nav uppercase text-text-faint font-medium whitespace-nowrap">
                Latency
              </th>
              <th className="py-1.5 pr-3 text-right text-label-nav uppercase text-text-faint font-medium">
                Tokens In/Out
              </th>
              <th className="py-1.5 text-right text-label-nav uppercase text-text-faint font-medium whitespace-nowrap">
                Est. Cost
              </th>
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={i} className="border-b border-border-faint">
                <td className="py-2 pr-3 text-text-muted max-w-[200px] truncate">
                  {r.prompt}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-text-muted whitespace-nowrap">
                  {r.latency_ms}ms
                </td>
                <td className="py-2 pr-3 text-right font-mono text-text-muted whitespace-nowrap">
                  {r.tokens_in}/{r.tokens_out}
                </td>
                <td className="py-2 text-right font-mono text-text-muted whitespace-nowrap">
                  {r.estimated_cost_usd != null
                    ? `$${r.estimated_cost_usd.toFixed(8)}`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[12px] text-accent font-medium pt-1">
        All {results.length} test{results.length !== 1 ? "s" : ""} passed —
        entry is ready to publish
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LibraryForm({ entry, onClose, onSaved }: LibraryFormProps) {
  const isEditing = entry !== null;
  const createMutation = useCreateLLMLibraryEntry();
  const updateMutation = useUpdateLLMLibraryEntry();
  const publishMutation = usePublishLLMLibraryEntry();
  const deprecateMutation = useDeprecateLLMLibraryEntry();
  const testMutation = useTestProfile();

  const isPending =
    createMutation.isPending ||
    updateMutation.isPending ||
    publishMutation.isPending ||
    deprecateMutation.isPending;

  const mutationError =
    createMutation.error ??
    updateMutation.error ??
    publishMutation.error ??
    deprecateMutation.error;

  const [form, setForm] = useState<FormState>(
    entry ? formFromEntry(entry) : EMPTY_FORM,
  );
  const [showPreview, setShowPreview] = useState(false);
  const [showDeprecateConfirm, setShowDeprecateConfirm] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [testResults, setTestResults] = useState<TestPromptResult[] | null>(
    null,
  );
  const [testError, setTestError] = useState<string | null>(null);

  // Fetch tenant assignments only when deprecate dialog is open
  const { data: tenantAssignments } = useTenantAssignments(
    showDeprecateConfirm && isEditing ? entry.id : null,
  );
  const tenantCount = tenantAssignments?.length ?? 0;

  // Reset test results only when switching to a different entry (or closing the form)
  useEffect(() => {
    setTestResults(null);
    setTestError(null);
  }, [entry?.id]);

  // Always sync form state when entry data updates (picks up last_test_passed_at, key_present, etc.)
  useEffect(() => {
    setForm(entry ? formFromEntry(entry) : EMPTY_FORM);
  }, [entry]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  // Pricing validation — optional for Draft, only needed for publish
  const pricingInValid =
    form.pricing_per_1k_tokens_in === "" ||
    (!isNaN(Number(form.pricing_per_1k_tokens_in)) &&
      Number(form.pricing_per_1k_tokens_in) >= 0);
  const pricingOutValid =
    form.pricing_per_1k_tokens_out === "" ||
    (!isNaN(Number(form.pricing_per_1k_tokens_out)) &&
      Number(form.pricing_per_1k_tokens_out) >= 0);

  const canSave =
    !!form.model_name.trim() &&
    !!form.display_name.trim() &&
    !!form.provider &&
    pricingInValid &&
    pricingOutValid;

  const canPublish =
    canSave &&
    isEditing &&
    entry.status === "Draft" &&
    !!entry.last_test_passed_at;

  // Test button: enabled once entry is saved and key is present
  const canTest = isEditing && !!entry.key_present;

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

      const newPriceIn =
        form.pricing_per_1k_tokens_in !== ""
          ? Number(form.pricing_per_1k_tokens_in)
          : null;
      if (newPriceIn !== entry.pricing_per_1k_tokens_in)
        payload.pricing_per_1k_tokens_in = newPriceIn ?? undefined;

      const newPriceOut =
        form.pricing_per_1k_tokens_out !== ""
          ? Number(form.pricing_per_1k_tokens_out)
          : null;
      if (newPriceOut !== entry.pricing_per_1k_tokens_out)
        payload.pricing_per_1k_tokens_out = newPriceOut ?? undefined;

      if (form.endpoint_url !== (entry.endpoint_url ?? ""))
        payload.endpoint_url = form.endpoint_url || undefined;

      if (form.api_version !== (entry.api_version ?? ""))
        payload.api_version = form.api_version || undefined;

      // Only send api_key if user typed something — empty means "keep existing"
      if (form.api_key) payload.api_key = form.api_key;

      updateMutation.mutate(
        { id: entry.id, payload },
        {
          onSuccess: () => onSaved(),
          onError: (err) => {
            if (err instanceof ApiException && err.status === 401) {
              setSessionExpired(true);
            }
          },
        },
      );
    } else {
      const payload: CreateLLMLibraryPayload = {
        provider: form.provider,
        model_name: form.model_name,
        display_name: form.display_name,
        plan_tier: form.plan_tier,
        is_recommended: form.is_recommended,
        pricing_per_1k_tokens_in: form.pricing_per_1k_tokens_in
          ? Number(form.pricing_per_1k_tokens_in)
          : 0,
        pricing_per_1k_tokens_out: form.pricing_per_1k_tokens_out
          ? Number(form.pricing_per_1k_tokens_out)
          : 0,
        best_practices_md: form.best_practices_md || undefined,
        endpoint_url: form.endpoint_url || undefined,
        api_key: form.api_key || undefined,
        api_version: form.api_version || undefined,
      };

      createMutation.mutate(payload, {
        onSuccess: () => onSaved(),
        onError: (err) => {
          if (err instanceof ApiException && err.status === 401) {
            setSessionExpired(true);
          }
        },
      });
    }
  }

  function handlePublish() {
    if (!isEditing || !canPublish) return;
    // Save non-credential metadata before publishing.
    // api_key is already stored in DB — re-sending it would clear last_test_passed_at
    // and cause the subsequent publish call to fail 422.
    const payload: UpdateLLMLibraryPayload = {
      best_practices_md: form.best_practices_md,
    };

    updateMutation.mutate(
      { id: entry.id, payload },
      {
        onSuccess: () => {
          publishMutation.mutate(entry.id, {
            onSuccess: () => {
              onSaved();
            },
            onError: (err) => {
              if (err instanceof ApiException && err.status === 401) {
                setSessionExpired(true);
              }
            },
          });
        },
        onError: (err) => {
          if (err instanceof ApiException && err.status === 401) {
            setSessionExpired(true);
          }
        },
      },
    );
  }

  function handleDeprecate() {
    if (!isEditing) return;
    deprecateMutation.mutate(entry.id, {
      onSuccess: () => {
        setShowDeprecateConfirm(false);
        onSaved();
      },
    });
  }

  function handleTest() {
    if (!isEditing || !canTest) return;
    setTestError(null);
    setTestResults(null);
    testMutation.mutate(entry.id, {
      onSuccess: (data) => setTestResults(data.tests),
      onError: (err) => {
        setTestResults(null);
        if (err instanceof ApiException) {
          setTestError(
            `Test failed: ${err.message ?? "Connection error. Check credentials."}`,
          );
        } else {
          setTestError("Test failed. Check credentials and try again.");
        }
      },
    });
  }

  const isDeprecated = isEditing && entry.status === "Deprecated";
  const isPublished = isEditing && entry.status === "Published";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={handleSaveDraft}
        className="relative mx-4 w-full max-w-[640px] rounded-card border border-border bg-bg-surface p-6"
      >
        {/* Header */}
        <div className="mb-5 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-section-heading text-text-primary">
              {isEditing ? `Edit: ${entry.display_name}` : "New Library Entry"}
            </h2>
            {isDeprecated && (
              <span className="inline-flex items-center gap-1 rounded-badge border border-border px-2 py-0.5 font-mono text-[10px] uppercase text-text-faint">
                <Archive size={10} />
                Deprecated
              </span>
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

        {/* Deprecated notice — read-only banner */}
        {isDeprecated && (
          <div className="mb-4 rounded-control border border-border bg-bg-elevated px-3 py-2.5">
            <p className="text-[12px] text-text-faint">
              This profile is deprecated. Fields are shown in read-only mode. No
              status changes are possible.
            </p>
          </div>
        )}

        <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
          {/* ---------------------------------------------------------------- */}
          {/* Section 1 — Identity                                             */}
          {/* ---------------------------------------------------------------- */}

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

          {/* Deployment Name */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Deployment Name *
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

          {/* Plan Tier — segmented single-select */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
              Plan Tier *
            </label>
            <div
              role="radiogroup"
              aria-label="Plan tier"
              className="inline-flex rounded-control border border-border bg-bg-base"
            >
              {PLAN_TIERS.map((tier, idx) => {
                const isSelected = form.plan_tier === tier.value;
                return (
                  <button
                    key={tier.value}
                    type="button"
                    role="radio"
                    aria-checked={isSelected}
                    onClick={() => updateField("plan_tier", tier.value)}
                    className={cn(
                      "px-4 py-1.5 text-[12px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                      idx === 0 && "rounded-l-control",
                      idx === PLAN_TIERS.length - 1 && "rounded-r-control",
                      idx > 0 && "border-l border-border",
                      isSelected
                        ? "bg-accent-dim text-accent"
                        : "bg-transparent text-text-faint hover:text-text-muted",
                    )}
                  >
                    {tier.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Pricing */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                Price / 1K Tokens In
              </label>
              <div className="flex items-stretch rounded-control border border-border bg-bg-elevated transition-colors focus-within:border-accent">
                <span className="flex items-center rounded-l-control border-r border-border bg-bg-base px-2.5 font-mono text-sm text-text-faint select-none">
                  $
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.pricing_per_1k_tokens_in}
                  onChange={(e) =>
                    updateField("pricing_per_1k_tokens_in", e.target.value)
                  }
                  placeholder="0.000150"
                  className="min-w-0 flex-1 rounded-r-control bg-transparent px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint focus:outline-none"
                />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                Price / 1K Tokens Out
              </label>
              <div className="flex items-stretch rounded-control border border-border bg-bg-elevated transition-colors focus-within:border-accent">
                <span className="flex items-center rounded-l-control border-r border-border bg-bg-base px-2.5 font-mono text-sm text-text-faint select-none">
                  $
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.pricing_per_1k_tokens_out}
                  onChange={(e) =>
                    updateField("pricing_per_1k_tokens_out", e.target.value)
                  }
                  placeholder="0.000600"
                  className="min-w-0 flex-1 rounded-r-control bg-transparent px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint focus:outline-none"
                />
              </div>
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
          {/* Section 2 — Connection Credentials                               */}
          {/* ---------------------------------------------------------------- */}
          <div className="rounded-card border border-border bg-bg-base p-4 space-y-4">
            <div className="flex items-center gap-2">
              <KeyRound size={14} className="text-text-faint" />
              <h3 className="text-label-nav uppercase text-text-faint tracking-wider">
                Connection Credentials
              </h3>
            </div>

            {/* Endpoint URL — Azure only */}
            {form.provider === "azure_openai" && (
              <div>
                <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                  Endpoint URL
                </label>
                <input
                  type="text"
                  value={form.endpoint_url}
                  onChange={(e) => updateField("endpoint_url", e.target.value)}
                  maxLength={512}
                  placeholder="https://ai-xxx.cognitiveservices.azure.com/"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
            )}

            {/* API Key — all providers */}
            <div>
              <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                API Key
              </label>
              <div className="flex items-stretch rounded-control border border-border bg-bg-elevated transition-colors focus-within:border-accent">
                <input
                  type={showApiKey ? "text" : "password"}
                  value={form.api_key}
                  onChange={(e) => updateField("api_key", e.target.value)}
                  placeholder={
                    isEditing && entry.key_present
                      ? `••••••••${entry.api_key_last4 ?? "****"}`
                      : "Enter API key"
                  }
                  autoComplete="new-password"
                  className="min-w-0 flex-1 rounded-l-control bg-transparent px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey((v) => !v)}
                  className="flex items-center px-2.5 text-text-faint transition-colors hover:text-text-muted"
                  tabIndex={-1}
                  aria-label={showApiKey ? "Hide API key" : "Show API key"}
                >
                  {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              {isEditing && entry.key_present && (
                <p className="mt-1 text-[10px] text-text-faint">
                  Leave blank to keep the existing key
                </p>
              )}
            </div>

            {/* API Version — Azure only */}
            {form.provider === "azure_openai" && (
              <div>
                <label className="mb-1.5 block text-label-nav uppercase text-text-faint">
                  API Version
                </label>
                <input
                  type="text"
                  value={form.api_version}
                  onChange={(e) => updateField("api_version", e.target.value)}
                  maxLength={64}
                  placeholder="2024-12-01-preview"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
            )}
          </div>

          {/* ---------------------------------------------------------------- */}
          {/* Section 3 — Catalog                                              */}
          {/* ---------------------------------------------------------------- */}

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

          {/* Test results inline */}
          {testResults && <TestResultsPanel results={testResults} />}

          {/* Test error */}
          {testError && (
            <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2.5">
              <p className="text-[12px] text-alert">{testError}</p>
            </div>
          )}
        </div>

        {/* Session-expired warning */}
        {sessionExpired && (
          <div className="mt-3 rounded-control border border-warn/40 bg-warn-dim px-3 py-2.5">
            <p className="text-[12px] text-warn">
              Your session expired. Please copy your form data, log in again,
              and re-enter it.
            </p>
          </div>
        )}

        {/* Mutation error (not shown when session-expired banner is active) */}
        {mutationError && !sessionExpired && (
          <p className="mt-4 text-sm text-alert">
            {mutationError.message ?? "Operation failed."}
          </p>
        )}

        {/* Footer */}
        <div className="mt-5 flex items-center justify-between gap-3">
          {/* Left side: Deprecate (Published only) */}
          <div>
            {isPublished && (
              <button
                type="button"
                onClick={() => setShowDeprecateConfirm(true)}
                disabled={isPending}
                className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:border-alert/40 hover:bg-alert-dim hover:text-alert disabled:opacity-40"
              >
                <Archive size={14} />
                Deprecate
              </button>
            )}
          </div>

          {/* Right side: Cancel / Test / Save Draft / Publish */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              {isDeprecated ? "Close" : "Cancel"}
            </button>

            {!isDeprecated && (
              <>
                {/* Test button — only shown when editing a saved entry */}
                {isEditing && (
                  <button
                    type="button"
                    onClick={handleTest}
                    disabled={!canTest || testMutation.isPending}
                    title={
                      !isEditing
                        ? "Save the entry first to enable testing"
                        : !entry.key_present
                          ? "Add an API key to enable testing"
                          : entry.last_test_passed_at
                            ? `Last tested ${formatDate(entry.last_test_passed_at)}`
                            : "Run connectivity test"
                    }
                    className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
                  >
                    {testMutation.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <FlaskConical size={14} />
                    )}
                    Test
                  </button>
                )}

                {/* Publish — only for Draft entries that have passed a test */}
                {isEditing && entry.status === "Draft" && (
                  <button
                    type="button"
                    onClick={handlePublish}
                    disabled={isPending || !canPublish}
                    title={
                      !canPublish
                        ? "Run the connectivity test before publishing"
                        : undefined
                    }
                    className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
                  >
                    {publishMutation.isPending || updateMutation.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <CheckCircle2 size={14} />
                    )}
                    Publish
                  </button>
                )}

                <button
                  type="submit"
                  disabled={!canSave || isPending}
                  className="flex items-center gap-1.5 rounded-control border border-accent px-4 py-1.5 text-sm font-semibold text-accent transition-opacity hover:bg-accent-dim disabled:opacity-40"
                >
                  {(updateMutation.isPending && !publishMutation.isPending) ||
                  createMutation.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : null}
                  {isEditing ? "Save Draft" : "Save Draft"}
                </button>
              </>
            )}
          </div>
        </div>

        {/* Deprecate confirmation overlay */}
        {showDeprecateConfirm && (
          <div className="absolute inset-0 flex items-center justify-center rounded-card bg-bg-surface/95">
            <div className="mx-6 w-full max-w-sm rounded-card border border-border bg-bg-elevated p-5">
              <div className="mb-3 flex items-center gap-2">
                <Archive size={16} className="text-text-muted" />
                <h3 className="text-[14px] font-semibold text-text-primary">
                  Deprecate profile?
                </h3>
              </div>
              <p className="mb-1 text-[13px] text-text-muted">
                {tenantCount > 0 ? (
                  <>
                    <span className="font-mono text-text-primary">
                      {tenantCount}
                    </span>{" "}
                    tenant{tenantCount !== 1 ? "s are" : " is"} currently using
                    this profile.
                  </>
                ) : (
                  "No tenants are currently using this profile."
                )}
              </p>
              {tenantCount > 0 && tenantAssignments && (
                <ul className="mb-3 mt-2 max-h-[120px] overflow-y-auto space-y-1">
                  {tenantAssignments.map((t) => (
                    <li
                      key={t.tenant_id}
                      className="font-mono text-[11px] text-text-faint"
                    >
                      {t.tenant_name}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mb-4 text-[12px] text-text-faint">
                Existing assignments are preserved. No new tenants can be
                assigned to a deprecated profile.
              </p>
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowDeprecateConfirm(false)}
                  disabled={deprecateMutation.isPending}
                  className="rounded-control border border-border px-3 py-1.5 text-[12px] text-text-muted transition-colors hover:bg-bg-surface hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleDeprecate}
                  disabled={deprecateMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-[12px] text-text-muted transition-colors hover:border-alert/40 hover:bg-alert-dim hover:text-alert disabled:opacity-40"
                >
                  {deprecateMutation.isPending ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Archive size={12} />
                  )}
                  Confirm Deprecation
                </button>
              </div>
            </div>
          </div>
        )}
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Simple markdown preview (renders basic markdown without external dep)
// ---------------------------------------------------------------------------

function MarkdownPreview({ content }: { content: string }) {
  const lines = content.split("\n");
  return (
    <div className="space-y-1 text-[13px] leading-relaxed text-text-primary">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("### ")) {
          return (
            <p
              key={i}
              className="mt-2 text-[13px] font-semibold text-text-primary"
            >
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
