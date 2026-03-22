"use client";

import { useState, useCallback, useEffect } from "react";
import { X, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useAgentTemplate,
  useCreateAgentTemplate,
  useUpdateAgentTemplate,
  useDeprecateAgentTemplate,
  type AgentTemplateAdmin,
  type AgentTemplateVariable,
  type GuardrailRule,
  type CredentialSchema,
  type LLMPolicy,
  type KBPolicy,
  type A2AInterface,
  type A2AOperation,
} from "@/lib/hooks/useAgentTemplatesAdmin";
import {
  SystemPromptEditor,
  extractVariableTokens,
} from "@/components/shared/SystemPromptEditor";
import { GuardrailsEditor } from "@/components/shared/GuardrailsEditor";
import { CredentialSchemaEditor } from "./CredentialSchemaEditor";
import { PublishFlow } from "./PublishFlow";
import { TestHarnessTab } from "./TestHarnessTab";
import { InstancesTab } from "./InstancesTab";
import { VersionHistoryTab } from "./VersionHistoryTab";
import { LifecycleActions } from "./LifecycleActions";
import { PerformanceTab } from "./PerformanceTab";

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

type StudioTab = "edit" | "test" | "instances" | "versions" | "performance";

const TABS: { value: StudioTab; label: string }[] = [
  { value: "edit", label: "Edit" },
  { value: "test", label: "Test" },
  { value: "instances", label: "Instances" },
  { value: "versions", label: "Version History" },
  { value: "performance", label: "Performance" },
];

const CATEGORY_OPTIONS = [
  "HR",
  "IT",
  "Finance",
  "Legal",
  "Procurement",
  "Onboarding",
  "Custom",
] as const;

const ICON_OPTIONS = [
  { value: "people", emoji: "👥", label: "HR" },
  { value: "money", emoji: "💰", label: "Finance" },
  { value: "scales", emoji: "⚖️", label: "Legal" },
  { value: "desktop", emoji: "🖥", label: "IT" },
  { value: "search", emoji: "🔍", label: "Search" },
  { value: "star", emoji: "⭐", label: "Custom" },
] as const;

type IconValue = (typeof ICON_OPTIONS)[number]["value"];

// ---------------------------------------------------------------------------
// Helper: build form state from existing template
// ---------------------------------------------------------------------------

interface FormState {
  name: string;
  description: string;
  category: string;
  icon: IconValue;
  tags: string[];
  systemPrompt: string;
  variables: AgentTemplateVariable[];
  guardrails: GuardrailRule[];
  confidenceThreshold: number;
  citationMode: "inline" | "footnote" | "none";
  maxResponseLength: number | null;
  piiMaskingEnabled: boolean;
  llmPolicy: LLMPolicy;
  kbPolicy: KBPolicy;
  authMode: "none" | "tenant_credentials" | "platform_credentials";
  credentialSchema: CredentialSchema[];
  attachedSkills: string[];
  attachedTools: string[];
  a2aInterface: A2AInterface;
}

function templateToForm(t: AgentTemplateAdmin): FormState {
  return {
    name: t.name,
    description: t.description ?? "",
    category: t.category ?? "Custom",
    icon: (t.icon as IconValue) ?? "star",
    tags: t.tags ?? [],
    systemPrompt: t.system_prompt,
    variables: t.variable_definitions ?? [],
    guardrails: t.guardrails ?? [],
    confidenceThreshold: t.confidence_threshold ?? 0.7,
    citationMode: t.citation_mode ?? "inline",
    maxResponseLength: t.max_response_length ?? null,
    piiMaskingEnabled: t.pii_masking_enabled ?? false,
    llmPolicy: t.llm_policy ?? { tenant_override_enabled: true },
    kbPolicy: t.kb_policy ?? { ownership_mode: "tenant_managed" },
    authMode: t.auth_mode ?? "none",
    credentialSchema: t.credential_schema ?? [],
    attachedSkills: t.attached_skills ?? [],
    attachedTools: t.attached_tools ?? [],
    a2aInterface: t.a2a_interface ?? { enabled: false },
  };
}

function emptyForm(): FormState {
  return {
    name: "",
    description: "",
    category: "Custom",
    icon: "star",
    tags: [],
    systemPrompt: "",
    variables: [],
    guardrails: [],
    confidenceThreshold: 0.7,
    citationMode: "inline",
    maxResponseLength: null,
    piiMaskingEnabled: false,
    llmPolicy: { tenant_override_enabled: true },
    kbPolicy: { ownership_mode: "tenant_managed" },
    authMode: "none",
    credentialSchema: [],
    attachedSkills: [],
    attachedTools: [],
    a2aInterface: { enabled: false },
  };
}

// ---------------------------------------------------------------------------
// Section collapse wrapper
// ---------------------------------------------------------------------------

interface CollapsibleSectionProps {
  title: string;
  summary?: string;
  defaultOpen?: boolean;
  forceOpen?: boolean;
  children: React.ReactNode;
}

function CollapsibleSection({
  title,
  summary,
  defaultOpen = false,
  forceOpen = false,
  children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const isOpen = forceOpen || open;

  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <button
        type="button"
        onClick={() => !forceOpen && setOpen(!open)}
        className={cn(
          "flex w-full items-center justify-between px-4 py-3",
          !forceOpen && "cursor-pointer hover:bg-bg-elevated",
        )}
      >
        <div className="text-left">
          <p className="text-section-heading text-text-primary">{title}</p>
          {!isOpen && summary && (
            <p className="mt-0.5 text-body-default text-text-faint">
              {summary}
            </p>
          )}
        </div>
        {!forceOpen &&
          (isOpen ? (
            <ChevronDown size={15} className="flex-shrink-0 text-text-muted" />
          ) : (
            <ChevronRight size={15} className="flex-shrink-0 text-text-muted" />
          ))}
      </button>
      {isOpen && (
        <div className="border-t border-border px-4 pb-4 pt-3">{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tag chip input
// ---------------------------------------------------------------------------

function TagInput({
  tags,
  onChange,
  placeholder = "Add tag, press Enter",
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && draft.trim()) {
      e.preventDefault();
      if (!tags.includes(draft.trim())) {
        onChange([...tags, draft.trim()]);
      }
      setDraft("");
    } else if (e.key === "Backspace" && !draft && tags.length > 0) {
      onChange(tags.slice(0, -1));
    }
  }

  return (
    <div className="flex flex-wrap gap-1.5 rounded-control border border-border bg-bg-elevated px-2 py-1.5 focus-within:border-accent">
      {tags.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 rounded-badge bg-bg-base px-2 py-0.5 text-body-default text-text-muted"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(tags.filter((t) => t !== tag))}
            className="text-text-faint hover:text-alert"
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={tags.length === 0 ? placeholder : ""}
        className="min-w-[120px] flex-1 bg-transparent text-body-default text-text-primary placeholder:text-text-faint focus:outline-none"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface TemplateStudioPanelProps {
  templateId: string | null;
  onClose: () => void;
  onCreated?: (id: string) => void;
}

export function TemplateStudioPanel({
  templateId,
  onClose,
  onCreated,
}: TemplateStudioPanelProps) {
  const isCreate = templateId === null;

  const { data: serverTemplate, isPending: loadingTemplate } =
    useAgentTemplate(templateId);

  const [activeTab, setActiveTab] = useState<StudioTab>("edit");
  const [form, setForm] = useState<FormState>(emptyForm);
  const [isDirty, setIsDirty] = useState(false);
  const [showPublishFlow, setShowPublishFlow] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [tagDraft, setTagDraft] = useState("");

  // Reset form when template loads
  useEffect(() => {
    if (serverTemplate) {
      setForm(templateToForm(serverTemplate));
      setIsDirty(false);
      setValidationError(null);
    } else if (isCreate) {
      setForm(emptyForm());
      setIsDirty(false);
    }
  }, [serverTemplate, isCreate]);

  const createMutation = useCreateAgentTemplate();
  const updateMutation = useUpdateAgentTemplate();
  const deprecateMutation = useDeprecateAgentTemplate();

  const isSaving = createMutation.isPending || updateMutation.isPending;

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setIsDirty(true);
  }

  // Auto-sync variables from prompt tokens
  function handlePromptChange(value: string) {
    setField("systemPrompt", value);
    const tokenNames = extractVariableTokens(value);
    const existingNames = form.variables.map((v) => v.name);
    const newVars: AgentTemplateVariable[] = tokenNames
      .filter((n) => !existingNames.includes(n))
      .map((n) => ({ name: n, type: "string", required: false }));
    if (newVars.length > 0) {
      setField("variables", [...form.variables, ...newVars]);
    }
    // Remove variables that no longer appear in prompt
    const pruned = form.variables.filter((v) => tokenNames.includes(v.name));
    if (pruned.length !== form.variables.length) {
      setField("variables", pruned);
    }
  }

  const handleSaveDraft = useCallback(async () => {
    if (!form.name.trim()) return;

    const payload = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      category: form.category,
      icon: form.icon,
      tags: form.tags,
      system_prompt: form.systemPrompt,
      variable_definitions: form.variables,
      guardrails: form.guardrails,
      confidence_threshold: form.confidenceThreshold,
      citation_mode: form.citationMode,
      max_response_length: form.maxResponseLength ?? undefined,
      pii_masking_enabled: form.piiMaskingEnabled,
      llm_policy: form.llmPolicy,
      kb_policy: form.kbPolicy,
      auth_mode: form.authMode,
      credential_schema: form.credentialSchema,
      attached_skills: form.attachedSkills,
      attached_tools: form.attachedTools,
      a2a_interface: form.a2aInterface,
    };

    try {
      setValidationError(null);
      if (isCreate) {
        const created = await createMutation.mutateAsync(payload);
        setIsDirty(false);
        onCreated?.(created.id);
      } else if (serverTemplate) {
        await updateMutation.mutateAsync({
          id: serverTemplate.id,
          payload,
          etag: serverTemplate.etag,
        });
        setIsDirty(false);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Save failed";
      setValidationError(msg);
    }
  }, [
    form,
    isCreate,
    serverTemplate,
    createMutation,
    updateMutation,
    onCreated,
  ]);

  const saveError = createMutation.error || updateMutation.error;

  // Progressive disclosure: expand sections 3 & 5 when auth_mode !== none
  const authActive = form.authMode !== "none";

  // Summary strings for collapsed sections
  const llmSummary = [
    form.llmPolicy.required_model
      ? `Model: ${form.llmPolicy.required_model}`
      : "Any model",
    form.llmPolicy.tenant_override_enabled
      ? "tenant override enabled"
      : "tenant override disabled",
  ].join(" · ");

  const kbSummary = `${(form.kbPolicy.ownership_mode ?? "tenant_managed").replace(/_/g, " ")} · ${(form.kbPolicy.recommended_categories ?? []).length} categories`;

  const capsSummary = [
    form.attachedSkills.length > 0
      ? `${form.attachedSkills.length} skill${form.attachedSkills.length !== 1 ? "s" : ""}`
      : "No skills",
    form.attachedTools.length > 0
      ? `${form.attachedTools.length} tool${form.attachedTools.length !== 1 ? "s" : ""}`
      : "No tools",
  ].join(" · ");

  const template = serverTemplate as AgentTemplateAdmin | undefined;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-bg-deep/60"
        onClick={onClose}
        role="presentation"
      />

      {/* Panel — 800px wide */}
      <div className="relative flex w-full max-w-[800px] flex-col border-l border-border bg-bg-surface">
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-border px-5 py-3">
          <div className="flex flex-1 items-center gap-3 min-w-0">
            {/* Inline editable name */}
            {activeTab === "edit" ? (
              <input
                type="text"
                value={form.name}
                onChange={(e) => setField("name", e.target.value)}
                placeholder="Template name"
                className="flex-1 min-w-0 bg-transparent text-section-heading text-text-primary placeholder:text-text-faint focus:outline-none"
              />
            ) : (
              <h2 className="truncate text-section-heading text-text-primary">
                {form.name || "New Template"}
              </h2>
            )}

            {template && <StatusBadge status={template.status} />}
          </div>

          <div className="ml-3 flex flex-shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex flex-shrink-0 border-b border-border">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setActiveTab(tab.value)}
              disabled={isCreate && tab.value !== "edit"}
              className={cn(
                "border-b-2 px-4 py-2 text-[12px] font-medium transition-colors",
                activeTab === tab.value
                  ? "border-accent text-text-primary"
                  : "border-transparent text-text-faint hover:text-text-muted",
                isCreate &&
                  tab.value !== "edit" &&
                  "cursor-not-allowed opacity-40",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto">
          {/* ── EDIT TAB ── */}
          {activeTab === "edit" && (
            <div className="space-y-3 p-5">
              {loadingTemplate && !isCreate && (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={24} className="animate-spin text-text-faint" />
                </div>
              )}

              {(!loadingTemplate || isCreate) && (
                <>
                  {/* Section 1 — Identity */}
                  <CollapsibleSection title="Identity" defaultOpen>
                    {/* Icon picker */}
                    <div className="mb-4">
                      <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
                        Icon
                      </label>
                      <div className="flex flex-wrap gap-2">
                        {ICON_OPTIONS.map((opt) => (
                          <button
                            key={opt.value}
                            type="button"
                            onClick={() => setField("icon", opt.value)}
                            title={opt.label}
                            className={cn(
                              "flex h-10 w-10 items-center justify-center rounded-control border text-xl transition-colors",
                              form.icon === opt.value
                                ? "border-accent bg-accent-dim"
                                : "border-border bg-bg-elevated hover:border-accent/50",
                            )}
                          >
                            {opt.emoji}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="sm:col-span-2">
                        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                          Description
                        </label>
                        <textarea
                          value={form.description}
                          onChange={(e) =>
                            setField("description", e.target.value)
                          }
                          placeholder="Brief description of what this template does"
                          rows={2}
                          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                        />
                      </div>

                      <div>
                        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                          Category
                        </label>
                        <select
                          value={form.category}
                          onChange={(e) => setField("category", e.target.value)}
                          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary focus:border-accent focus:outline-none"
                        >
                          {CATEGORY_OPTIONS.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                          Tags
                        </label>
                        <TagInput
                          tags={form.tags}
                          onChange={(tags) => setField("tags", tags)}
                        />
                      </div>
                    </div>
                  </CollapsibleSection>

                  {/* Section 2 — System Prompt + Variables */}
                  <CollapsibleSection
                    title="System Prompt & Variables"
                    defaultOpen
                  >
                    <SystemPromptEditor
                      value={form.systemPrompt}
                      onChange={handlePromptChange}
                      validationError={validationError}
                    />

                    {/* Variable schema table */}
                    {form.variables.length > 0 && (
                      <div className="mt-4">
                        <p className="mb-2 text-[11px] uppercase tracking-wider text-text-faint">
                          Variable Schema
                        </p>
                        <div className="overflow-x-auto rounded-card border border-border">
                          <table className="w-full">
                            <thead>
                              <tr className="border-b border-border bg-bg-elevated">
                                <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                                  Variable
                                </th>
                                <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                                  Type
                                </th>
                                <th className="px-3 py-2 text-center text-label-nav uppercase tracking-wider text-text-faint">
                                  Required
                                </th>
                                <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                                  Description
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {form.variables.map((v, i) => (
                                <tr
                                  key={v.name}
                                  className="border-b border-border-faint last:border-0"
                                >
                                  <td className="px-3 py-2">
                                    <span className="font-mono text-data-value text-accent">
                                      {`{{${v.name}}}`}
                                    </span>
                                  </td>
                                  <td className="px-3 py-2">
                                    <select
                                      value={v.type}
                                      onChange={(e) => {
                                        const updated = form.variables.map(
                                          (vv, ii) =>
                                            ii === i
                                              ? {
                                                  ...vv,
                                                  type: e.target.value as
                                                    | "string"
                                                    | "number"
                                                    | "boolean",
                                                }
                                              : vv,
                                        );
                                        setField("variables", updated);
                                      }}
                                      className="rounded-control border border-border bg-bg-elevated px-2 py-1 text-body-default text-text-primary focus:border-accent focus:outline-none"
                                    >
                                      <option value="string">String</option>
                                      <option value="number">Number</option>
                                      <option value="boolean">Boolean</option>
                                    </select>
                                  </td>
                                  <td className="px-3 py-2 text-center">
                                    <input
                                      type="checkbox"
                                      checked={v.required}
                                      onChange={(e) => {
                                        const updated = form.variables.map(
                                          (vv, ii) =>
                                            ii === i
                                              ? {
                                                  ...vv,
                                                  required: e.target.checked,
                                                }
                                              : vv,
                                        );
                                        setField("variables", updated);
                                      }}
                                      className="accent-accent"
                                    />
                                  </td>
                                  <td className="px-3 py-2">
                                    <input
                                      type="text"
                                      value={v.description ?? ""}
                                      onChange={(e) => {
                                        const updated = form.variables.map(
                                          (vv, ii) =>
                                            ii === i
                                              ? {
                                                  ...vv,
                                                  description: e.target.value,
                                                }
                                              : vv,
                                        );
                                        setField("variables", updated);
                                      }}
                                      placeholder="Optional description"
                                      className="w-full rounded-control border border-border bg-bg-elevated px-2 py-1 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </CollapsibleSection>

                  {/* Section 3 — LLM Policy (collapsed, expands when auth active) */}
                  <CollapsibleSection
                    title="LLM Policy"
                    summary={llmSummary}
                    defaultOpen={false}
                    forceOpen={authActive}
                  >
                    <div className="space-y-4">
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <div>
                          <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                            Required Model
                          </label>
                          <input
                            type="text"
                            value={form.llmPolicy.required_model ?? ""}
                            onChange={(e) =>
                              setField("llmPolicy", {
                                ...form.llmPolicy,
                                required_model: e.target.value || null,
                              })
                            }
                            placeholder="None (any model)"
                            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                          />
                        </div>

                        <div>
                          <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                            Temperature (0.0–2.0)
                          </label>
                          <div className="flex items-center gap-2">
                            <input
                              type="range"
                              min={0}
                              max={2}
                              step={0.1}
                              value={form.llmPolicy.temperature ?? 1.0}
                              onChange={(e) =>
                                setField("llmPolicy", {
                                  ...form.llmPolicy,
                                  temperature: parseFloat(e.target.value),
                                })
                              }
                              className="flex-1 accent-accent"
                            />
                            <span className="w-8 text-right font-mono text-data-value text-text-primary">
                              {(form.llmPolicy.temperature ?? 1.0).toFixed(1)}
                            </span>
                          </div>
                        </div>

                        <div>
                          <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                            Max Tokens
                          </label>
                          <input
                            type="number"
                            value={form.llmPolicy.max_tokens ?? ""}
                            onChange={(e) =>
                              setField("llmPolicy", {
                                ...form.llmPolicy,
                                max_tokens: e.target.value
                                  ? parseInt(e.target.value, 10)
                                  : undefined,
                              })
                            }
                            placeholder="Model default"
                            min={100}
                            max={32000}
                            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:font-sans placeholder:text-text-faint focus:border-accent focus:outline-none"
                          />
                        </div>

                        <div className="flex items-center gap-3">
                          <span className="text-body-default text-text-muted">
                            Tenant Override
                          </span>
                          <ToggleSwitch
                            checked={
                              form.llmPolicy.tenant_override_enabled ?? true
                            }
                            onChange={(v) =>
                              setField("llmPolicy", {
                                ...form.llmPolicy,
                                tenant_override_enabled: v,
                              })
                            }
                          />
                          <span className="text-body-default text-text-faint">
                            {form.llmPolicy.tenant_override_enabled
                              ? "Tenants can change model"
                              : "Locked to required model"}
                          </span>
                        </div>
                      </div>
                    </div>
                  </CollapsibleSection>

                  {/* Section 4 — Knowledge */}
                  <CollapsibleSection
                    title="Knowledge"
                    summary={kbSummary}
                    defaultOpen={false}
                  >
                    <div className="space-y-4">
                      <div>
                        <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
                          KB Ownership
                        </label>
                        <div className="flex flex-col gap-2">
                          {[
                            {
                              value: "tenant_managed" as const,
                              label: "Tenant-managed",
                              desc: "Each tenant connects their own knowledge base",
                            },
                            {
                              value: "platform_managed" as const,
                              label: "Platform-managed",
                              desc: "Platform admin controls which KBs are used",
                            },
                            {
                              value: "dedicated" as const,
                              label: "Dedicated",
                              desc: "Agent has its own dedicated knowledge base",
                            },
                          ].map((opt) => (
                            <label
                              key={opt.value}
                              className="flex cursor-pointer items-start gap-2"
                            >
                              <input
                                type="radio"
                                name="kb-ownership"
                                value={opt.value}
                                checked={
                                  (form.kbPolicy.ownership_mode ??
                                    "tenant_managed") === opt.value
                                }
                                onChange={() =>
                                  setField("kbPolicy", {
                                    ...form.kbPolicy,
                                    ownership_mode: opt.value,
                                  })
                                }
                                className="mt-0.5 accent-accent"
                              />
                              <div>
                                <p className="text-body-default font-medium text-text-primary">
                                  {opt.label}
                                </p>
                                <p className="text-body-default text-text-faint">
                                  {opt.desc}
                                </p>
                              </div>
                            </label>
                          ))}
                        </div>
                      </div>

                      <div>
                        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                          Recommended Categories
                        </label>
                        <TagInput
                          tags={form.kbPolicy.recommended_categories ?? []}
                          onChange={(cats) =>
                            setField("kbPolicy", {
                              ...form.kbPolicy,
                              recommended_categories: cats,
                            })
                          }
                          placeholder="Add category, press Enter"
                        />
                      </div>

                      {form.kbPolicy.ownership_mode === "platform_managed" && (
                        <div>
                          <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                            Required KB IDs
                          </label>
                          <TagInput
                            tags={form.kbPolicy.required_kb_ids ?? []}
                            onChange={(ids) =>
                              setField("kbPolicy", {
                                ...form.kbPolicy,
                                required_kb_ids: ids,
                              })
                            }
                            placeholder="Add KB ID, press Enter"
                          />
                        </div>
                      )}
                    </div>
                  </CollapsibleSection>

                  {/* Section 5 — Capabilities (collapsed, expands when auth active) */}
                  <CollapsibleSection
                    title="Capabilities"
                    summary={capsSummary}
                    defaultOpen={false}
                    forceOpen={authActive}
                  >
                    <div className="space-y-4">
                      {/* Auth mode */}
                      <div>
                        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                          Auth Mode
                        </label>
                        <select
                          value={form.authMode}
                          onChange={(e) =>
                            setField(
                              "authMode",
                              e.target.value as FormState["authMode"],
                            )
                          }
                          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary focus:border-accent focus:outline-none"
                        >
                          <option value="none">None (RAG only)</option>
                          <option value="tenant_credentials">
                            Tenant Credentials
                          </option>
                          <option value="platform_credentials">
                            Platform Credentials
                          </option>
                        </select>
                      </div>

                      {/* Credential schema (shown when auth active) */}
                      {form.authMode !== "none" && (
                        <div>
                          <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
                            Credential Schema
                          </label>
                          <CredentialSchemaEditor
                            rows={form.credentialSchema}
                            onChange={(rows) =>
                              setField("credentialSchema", rows)
                            }
                          />
                        </div>
                      )}
                    </div>
                  </CollapsibleSection>

                  {/* Section 6 — A2A Interface */}
                  <CollapsibleSection title="A2A Interface" defaultOpen>
                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        <span className="text-body-default text-text-muted">
                          A2A Enabled
                        </span>
                        <ToggleSwitch
                          checked={form.a2aInterface.enabled}
                          onChange={(v) =>
                            setField("a2aInterface", {
                              ...form.a2aInterface,
                              enabled: v,
                            })
                          }
                        />
                      </div>

                      {form.a2aInterface.enabled && (
                        <div className="space-y-3">
                          <div className="flex items-center gap-3">
                            <span className="text-body-default text-text-muted">
                              Auth Required
                            </span>
                            <ToggleSwitch
                              checked={form.a2aInterface.auth_required ?? false}
                              onChange={(v) =>
                                setField("a2aInterface", {
                                  ...form.a2aInterface,
                                  auth_required: v,
                                })
                              }
                            />
                          </div>

                          <div>
                            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                              Caller Requires Plan
                            </label>
                            <select
                              value={
                                form.a2aInterface.caller_requires_plan ?? ""
                              }
                              onChange={(e) =>
                                setField("a2aInterface", {
                                  ...form.a2aInterface,
                                  caller_requires_plan: e.target.value || null,
                                })
                              }
                              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary focus:border-accent focus:outline-none"
                            >
                              <option value="">None</option>
                              <option value="starter">Starter</option>
                              <option value="professional">Professional</option>
                              <option value="enterprise">Enterprise</option>
                            </select>
                          </div>

                          {/* Operations */}
                          <A2AOperationsEditor
                            operations={form.a2aInterface.operations ?? []}
                            onChange={(ops) =>
                              setField("a2aInterface", {
                                ...form.a2aInterface,
                                operations: ops,
                              })
                            }
                          />
                        </div>
                      )}
                    </div>
                  </CollapsibleSection>

                  {/* Section 7 — Guardrails */}
                  <CollapsibleSection title="Guardrails" defaultOpen>
                    <GuardrailsEditor
                      rules={form.guardrails}
                      onChange={(rules) => setField("guardrails", rules)}
                      confidenceThreshold={form.confidenceThreshold}
                      onConfidenceChange={(v) =>
                        setField("confidenceThreshold", v)
                      }
                      citationMode={form.citationMode}
                      onCitationModeChange={(v) => setField("citationMode", v)}
                      maxResponseLength={form.maxResponseLength}
                      onMaxResponseLengthChange={(v) =>
                        setField("maxResponseLength", v)
                      }
                      piiMaskingEnabled={form.piiMaskingEnabled}
                      onPiiMaskingChange={(v) =>
                        setField("piiMaskingEnabled", v)
                      }
                    />
                  </CollapsibleSection>

                  {/* Lifecycle actions (existing published template) */}
                  {template && template.status !== "Draft" && (
                    <div className="rounded-card border border-border bg-bg-surface p-4">
                      <LifecycleActions template={template} onClose={onClose} />
                    </div>
                  )}

                  {/* Publish flow */}
                  {!showPublishFlow &&
                    template &&
                    template.status === "Draft" && (
                      <div /> /* Placeholder — publish button is in footer */
                    )}
                  {showPublishFlow && template && (
                    <PublishFlow
                      template={{ ...template, ...formToTemplatePreview(form) }}
                      onClose={() => setShowPublishFlow(false)}
                      onPublished={() => {
                        setShowPublishFlow(false);
                        onClose();
                      }}
                    />
                  )}

                  {/* Error */}
                  {saveError && (
                    <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2">
                      <p className="text-body-default text-alert">
                        {saveError instanceof Error
                          ? saveError.message
                          : "Save failed"}
                      </p>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* ── TEST TAB ── */}
          {activeTab === "test" && template && (
            <TestHarnessTab template={template} />
          )}

          {/* ── INSTANCES TAB ── */}
          {activeTab === "instances" && template && (
            <InstancesTab
              templateId={template.id}
              currentVersionLabel={
                template.version_label ?? String(template.version)
              }
            />
          )}

          {/* ── VERSION HISTORY TAB ── */}
          {activeTab === "versions" && template && (
            <VersionHistoryTab templateId={template.id} />
          )}

          {/* ── PERFORMANCE TAB ── */}
          {activeTab === "performance" && template && (
            <PerformanceTab templateId={template.id} />
          )}
        </div>

        {/* Footer — Edit tab only */}
        {activeTab === "edit" && (
          <div className="flex flex-shrink-0 items-center justify-between border-t border-border px-5 py-3">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSaveDraft}
                disabled={!isDirty || !form.name.trim() || isSaving}
                className="flex items-center gap-1.5 rounded-control border border-border px-4 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
              >
                {isSaving && <Loader2 size={13} className="animate-spin" />}
                {isSaving ? "Saving..." : "Save Draft"}
              </button>

              {template && template.status === "Draft" && (
                <button
                  type="button"
                  onClick={() => setShowPublishFlow(!showPublishFlow)}
                  className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
                >
                  Publish →
                </button>
              )}
            </div>

            <p className="text-[11px] text-text-faint">
              {isDirty
                ? "Unsaved changes"
                : template
                  ? "Saved"
                  : "New template"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helper: merge form state back onto a template for PublishFlow preview
// ---------------------------------------------------------------------------

function formToTemplatePreview(form: FormState): Partial<AgentTemplateAdmin> {
  return {
    name: form.name,
    description: form.description || null,
    category: form.category,
    system_prompt: form.systemPrompt,
    guardrails: form.guardrails,
    auth_mode: form.authMode,
    required_credentials: form.credentialSchema.map((c) => c.key),
    attached_tools: form.attachedTools,
    variable_definitions: form.variables,
  };
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({
  status,
}: {
  status: "Draft" | "Published" | "Deprecated";
}) {
  const styles =
    status === "Published"
      ? "bg-accent-dim text-accent"
      : status === "Deprecated"
        ? "bg-alert-dim text-alert"
        : "bg-warn-dim text-warn";

  return (
    <span
      className={cn(
        "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
        styles,
      )}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Toggle switch
// ---------------------------------------------------------------------------

function ToggleSwitch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
        checked ? "bg-accent" : "bg-bg-elevated border-border",
      )}
    >
      <span
        className={cn(
          "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition-transform",
          checked ? "translate-x-4" : "translate-x-0",
        )}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// A2A operations editor
// ---------------------------------------------------------------------------

function A2AOperationsEditor({
  operations,
  onChange,
}: {
  operations: A2AOperation[];
  onChange: (ops: A2AOperation[]) => void;
}) {
  function handleAdd() {
    onChange([
      ...operations,
      { name: "", description: "", input_schema: "", output_schema: "" },
    ]);
  }

  function handleRemove(i: number) {
    onChange(operations.filter((_, idx) => idx !== i));
  }

  function handleUpdate<K extends keyof A2AOperation>(
    i: number,
    field: K,
    value: A2AOperation[K],
  ) {
    onChange(
      operations.map((op, idx) => (idx === i ? { ...op, [field]: value } : op)),
    );
  }

  return (
    <div className="space-y-3">
      <label className="block text-[11px] uppercase tracking-wider text-text-faint">
        Operations
      </label>

      {operations.map((op, i) => (
        <div
          key={i}
          className="rounded-card border border-border bg-bg-elevated p-3 space-y-2"
        >
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={op.name}
              onChange={(e) => handleUpdate(i, "name", e.target.value)}
              placeholder="Operation name"
              className="flex-1 rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
            <button
              type="button"
              onClick={() => handleRemove(i)}
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint hover:bg-alert-dim hover:text-alert"
            >
              <X size={12} />
            </button>
          </div>
          <input
            type="text"
            value={op.description ?? ""}
            onChange={(e) => handleUpdate(i, "description", e.target.value)}
            placeholder="Description"
            className="w-full rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
          />
          <div className="grid grid-cols-2 gap-2">
            <textarea
              value={op.input_schema ?? ""}
              onChange={(e) => handleUpdate(i, "input_schema", e.target.value)}
              placeholder="Input schema (JSON)"
              rows={2}
              className="rounded-control border border-border bg-bg-base px-2 py-1.5 font-mono text-body-default text-text-primary placeholder:font-sans placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
            <textarea
              value={op.output_schema ?? ""}
              onChange={(e) => handleUpdate(i, "output_schema", e.target.value)}
              placeholder="Output schema (JSON)"
              rows={2}
              className="rounded-control border border-border bg-bg-base px-2 py-1.5 font-mono text-body-default text-text-primary placeholder:font-sans placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      ))}

      <button
        type="button"
        onClick={handleAdd}
        className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
      >
        <X size={13} className="rotate-45" />
        Add Operation
      </button>
    </div>
  );
}
