"use client";

import { useState } from "react";
import {
  X,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCreatePlatformSkill,
  useUpdatePlatformSkill,
  usePublishPlatformSkill,
  usePlatformSkillAdmin,
  type PlatformSkillAdmin,
  type CreatePlatformSkillPayload,
  type UpdatePlatformSkillPayload,
} from "@/lib/hooks/usePlatformSkillsAdmin";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHAR_WARN = 2400;
const CHAR_ALERT = 2800;
const CHAR_MAX = 3000;

type ExecutionPattern = "prompt" | "tool_composing" | "sequential_pipeline";
type PlanRequired = "starter" | "professional" | "enterprise" | null;

type AccordionSection =
  | "identity"
  | "execution"
  | "prompt"
  | "publishing"
  | "governance";

const EXECUTION_PATTERNS: {
  value: ExecutionPattern;
  label: string;
  description: string;
}[] = [
  {
    value: "prompt",
    label: "Prompt",
    description: "LLM processes input via a prompt template",
  },
  {
    value: "tool_composing",
    label: "Tool-Composing",
    description: "LLM orchestrates external tools to fulfil the request",
  },
  {
    value: "sequential_pipeline",
    label: "Sequential Pipeline",
    description: "Multi-step pipeline with deterministic execution order",
  },
];

const PLAN_OPTIONS: { value: PlanRequired; label: string }[] = [
  { value: null, label: "All Plans" },
  { value: "starter", label: "Starter+" },
  { value: "professional", label: "Professional+" },
  { value: "enterprise", label: "Enterprise" },
];

// ---------------------------------------------------------------------------
// Accordion sub-component
// ---------------------------------------------------------------------------

function AccordionSection({
  title,
  isOpen,
  onToggle,
  children,
}: {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-border">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-5 py-3.5 text-left transition-colors hover:bg-bg-elevated"
      >
        <span className="text-body-default font-medium text-text-primary">
          {title}
        </span>
        {isOpen ? (
          <ChevronUp size={15} className="text-text-faint" />
        ) : (
          <ChevronDown size={15} className="text-text-faint" />
        )}
      </button>
      {isOpen && <div className="px-5 pb-5 pt-2">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface PlatformSkillAuthoringPanelProps {
  /** null = create mode, string = edit mode */
  skillId: string | null;
  onClose: () => void;
  onSaved: (id: string) => void;
}

export function PlatformSkillAuthoringPanel({
  skillId,
  onClose,
  onSaved,
}: PlatformSkillAuthoringPanelProps) {
  const isEdit = !!skillId;
  const { data: existingSkill } = usePlatformSkillAdmin(skillId);

  // Form state — initialised from existing skill when editing
  const [name, setName] = useState(existingSkill?.name ?? "");
  const [description, setDescription] = useState(
    existingSkill?.description ?? "",
  );
  const [category, setCategory] = useState(existingSkill?.category ?? "");
  const [execPattern, setExecPattern] = useState<ExecutionPattern>(
    existingSkill?.execution_pattern ?? "prompt",
  );
  const [planRequired, setPlanRequired] = useState<PlanRequired>(
    existingSkill?.plan_required ?? null,
  );
  const [promptTemplate, setPromptTemplate] = useState("");

  // PA-specific publishing state
  const [versionLabel, setVersionLabel] = useState(
    existingSkill?.version_label ?? "",
  );
  const [changelog, setChangelog] = useState("");

  // PA-specific governance state
  const [mandatory, setMandatory] = useState(existingSkill?.mandatory ?? false);

  // Accordion state
  const [openSections, setOpenSections] = useState<Set<AccordionSection>>(
    () => new Set<AccordionSection>(["identity", "execution", "prompt"]),
  );

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [savedSkillId, setSavedSkillId] = useState<string | null>(skillId);

  const { mutate: createSkill, isPending: isCreating } =
    useCreatePlatformSkill();
  const { mutate: updateSkill, isPending: isUpdating } =
    useUpdatePlatformSkill();
  const { mutate: publishSkill, isPending: isPublishing } =
    usePublishPlatformSkill();

  const isPending = isCreating || isUpdating || isPublishing;
  const charCount = promptTemplate.length;

  function toggleSection(section: AccordionSection) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  }

  function buildCreatePayload(): CreatePlatformSkillPayload {
    return {
      name: name.trim(),
      description: description.trim() || undefined,
      category: category.trim() || undefined,
      execution_pattern: execPattern,
      prompt_template: promptTemplate || undefined,
      plan_required: planRequired,
      mandatory,
    };
  }

  function buildUpdatePayload(): UpdatePlatformSkillPayload {
    return {
      name: name.trim() || undefined,
      description: description.trim() || undefined,
      category: category.trim() || undefined,
      execution_pattern: execPattern,
      prompt_template: promptTemplate || undefined,
      plan_required: planRequired,
    };
  }

  function handleSaveDraft() {
    setSubmitError(null);
    if (!name.trim()) {
      setSubmitError("Name is required.");
      return;
    }

    if (isEdit && savedSkillId) {
      updateSkill(
        { id: savedSkillId, payload: buildUpdatePayload() },
        {
          onSuccess: (data) => {
            setSavedSkillId(data.id);
            onSaved(data.id);
          },
          onError: (err) =>
            setSubmitError(err instanceof Error ? err.message : "Save failed"),
        },
      );
    } else {
      createSkill(buildCreatePayload(), {
        onSuccess: (data) => {
          setSavedSkillId(data.id);
          onSaved(data.id);
        },
        onError: (err) =>
          setSubmitError(err instanceof Error ? err.message : "Create failed"),
      });
    }
  }

  function handlePublish() {
    setSubmitError(null);
    const targetId = savedSkillId;
    if (!targetId) {
      setSubmitError("Save as draft first before publishing.");
      return;
    }
    if (!changelog.trim()) {
      setSubmitError("Changelog is required before publishing.");
      return;
    }
    publishSkill(
      {
        id: targetId,
        payload: {
          version_label: versionLabel.trim() || undefined,
          changelog: changelog.trim(),
        },
      },
      {
        onSuccess: () => onSaved(targetId),
        onError: (err) =>
          setSubmitError(err instanceof Error ? err.message : "Publish failed"),
      },
    );
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div className="relative z-10 flex h-full w-[560px] flex-col border-l border-border bg-bg-surface shadow-xl">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-section-heading text-text-primary">
              {isEdit ? "Edit Skill" : "New Platform Skill"}
            </h2>
            <p className="mt-0.5 text-body-default text-text-muted">
              {isEdit
                ? (existingSkill?.name ?? "Loading…")
                : "Author a skill available to all tenants"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1.5 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          {/* Section: Identity */}
          <AccordionSection
            title="Identity"
            isOpen={openSections.has("identity")}
            onToggle={() => toggleSection("identity")}
          >
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-body-default font-medium text-text-primary">
                  Name <span className="text-alert">*</span>
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Compliance Checker"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </div>

              <div>
                <label className="mb-1 block text-body-default font-medium text-text-primary">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  placeholder="Describe what this skill does"
                  className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </div>

              <div>
                <label className="mb-1 block text-body-default font-medium text-text-primary">
                  Category
                </label>
                <input
                  type="text"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g. Compliance, Finance, HR"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </div>

              <div>
                <label className="mb-1 block text-body-default font-medium text-text-primary">
                  Plan Gate
                </label>
                <select
                  value={planRequired ?? ""}
                  onChange={(e) =>
                    setPlanRequired((e.target.value || null) as PlanRequired)
                  }
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary outline-none focus:border-accent-ring"
                >
                  {PLAN_OPTIONS.map((opt) => (
                    <option key={String(opt.value)} value={opt.value ?? ""}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </AccordionSection>

          {/* Section: Execution */}
          <AccordionSection
            title="Execution"
            isOpen={openSections.has("execution")}
            onToggle={() => toggleSection("execution")}
          >
            <div className="space-y-2">
              {EXECUTION_PATTERNS.map((pattern) => (
                <label
                  key={pattern.value}
                  className="flex cursor-pointer items-center gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5 transition-colors hover:border-accent-ring"
                >
                  <input
                    type="radio"
                    name="exec_pattern"
                    value={pattern.value}
                    checked={execPattern === pattern.value}
                    onChange={() => setExecPattern(pattern.value)}
                    className="accent-accent"
                  />
                  <div>
                    <p className="text-body-default font-medium text-text-primary">
                      {pattern.label}
                    </p>
                    <p className="text-body-default text-text-muted">
                      {pattern.description}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          </AccordionSection>

          {/* Section: Prompt Template */}
          <AccordionSection
            title="Prompt Template"
            isOpen={openSections.has("prompt")}
            onToggle={() => toggleSection("prompt")}
          >
            <div className="space-y-3">
              <div className="relative">
                <textarea
                  value={promptTemplate}
                  onChange={(e) =>
                    setPromptTemplate(e.target.value.slice(0, CHAR_MAX))
                  }
                  rows={10}
                  placeholder="Enter prompt template. Use {{input.field_name}} to reference input fields."
                  className={cn(
                    "w-full resize-none rounded-control border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:font-sans placeholder:text-body-default placeholder:text-text-faint outline-none",
                    charCount >= CHAR_ALERT
                      ? "border-alert focus:border-alert"
                      : charCount >= CHAR_WARN
                        ? "border-warn focus:border-warn"
                        : "border-border focus:border-accent-ring",
                  )}
                />
                <div
                  className={cn(
                    "absolute bottom-2 right-3 font-mono text-data-value",
                    charCount >= CHAR_ALERT
                      ? "text-alert"
                      : charCount >= CHAR_WARN
                        ? "text-warn"
                        : "text-text-faint",
                  )}
                >
                  {charCount}/{CHAR_MAX}
                </div>
              </div>
            </div>
          </AccordionSection>

          {/* Section: Publishing (PA-specific) */}
          <AccordionSection
            title="Publishing"
            isOpen={openSections.has("publishing")}
            onToggle={() => toggleSection("publishing")}
          >
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-body-default font-medium text-text-primary">
                  Version Label
                </label>
                <input
                  type="text"
                  value={versionLabel}
                  onChange={(e) => setVersionLabel(e.target.value)}
                  placeholder="1.0.0"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:font-sans placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </div>

              <div>
                <label className="mb-1 block text-body-default font-medium text-text-primary">
                  Changelog{" "}
                  <span className="text-text-faint">(required to publish)</span>
                </label>
                <textarea
                  value={changelog}
                  onChange={(e) => setChangelog(e.target.value)}
                  rows={4}
                  placeholder="Describe what changed in this version"
                  className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </div>

              <button
                type="button"
                onClick={handlePublish}
                disabled={isPending || !savedSkillId}
                className="flex w-full items-center justify-center gap-2 rounded-control bg-accent px-4 py-2.5 text-body-default font-medium text-bg-base transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isPublishing && <Loader2 size={13} className="animate-spin" />}
                Publish
              </button>

              {!savedSkillId && (
                <p className="text-body-default text-text-faint">
                  Save as draft first to enable publishing.
                </p>
              )}
            </div>
          </AccordionSection>

          {/* Section: Governance (PA-specific) */}
          <AccordionSection
            title="Governance"
            isOpen={openSections.has("governance")}
            onToggle={() => toggleSection("governance")}
          >
            <div className="space-y-4">
              <label className="flex cursor-pointer items-start gap-3 rounded-control border border-border bg-bg-elevated px-3 py-3 transition-colors hover:border-accent-ring">
                <input
                  type="checkbox"
                  checked={mandatory}
                  onChange={(e) => setMandatory(e.target.checked)}
                  className="mt-0.5 accent-accent"
                />
                <div>
                  <p className="text-body-default font-medium text-text-primary">
                    Mandatory Skill
                  </p>
                  <p className="mt-0.5 text-body-default text-text-muted">
                    This skill will run on all tenant agents and cannot be
                    removed by tenant admins.
                  </p>
                </div>
              </label>

              {mandatory && (
                <div className="flex items-start gap-2.5 rounded-control border border-alert/30 bg-alert-dim px-3 py-2.5">
                  <AlertTriangle
                    size={14}
                    className="mt-0.5 shrink-0 text-alert"
                  />
                  <p className="text-body-default text-alert">
                    Mandatory skills affect all tenants. Enable only for
                    platform-wide compliance requirements.
                  </p>
                </div>
              )}
            </div>
          </AccordionSection>
        </div>

        {/* Footer */}
        <div className="shrink-0 space-y-2 border-t border-border px-5 py-4">
          {submitError && (
            <p className="text-body-default text-alert">{submitError}</p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleSaveDraft}
              disabled={isPending}
              className="flex flex-1 items-center justify-center gap-2 rounded-control border border-border px-4 py-2.5 text-body-default font-medium text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {(isCreating || isUpdating) && (
                <Loader2 size={13} className="animate-spin" />
              )}
              Save Draft
            </button>

            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-4 py-2.5 text-body-default text-text-muted transition-colors hover:border-border hover:text-text-primary"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
