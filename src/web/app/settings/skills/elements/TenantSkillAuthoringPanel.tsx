"use client";

import { useState } from "react";
import {
  X,
  ChevronDown,
  ChevronUp,
  Plus,
  Trash2,
  Loader2,
  FlaskConical,
} from "lucide-react";
import {
  useCreateSkill,
  useUpdateSkill,
  usePublishSkill,
} from "@/lib/hooks/useSkills";
import type { TenantSkill, CreateSkillPayload } from "@/lib/hooks/useSkills";
import { useTools } from "@/lib/hooks/useToolCatalog";
import { SkillTestDrawer } from "./SkillTestDrawer";
import { cn } from "@/lib/utils";

interface TenantSkillAuthoringPanelProps {
  skill: TenantSkill | null; // null = create mode
  onClose: () => void;
  onSaved: () => void;
}

type FieldType = "string" | "number" | "boolean" | "object" | "array";

interface SchemaRow {
  id: string;
  name: string;
  type: FieldType;
  required: boolean;
  description: string;
}

const FIELD_TYPES: FieldType[] = [
  "string",
  "number",
  "boolean",
  "object",
  "array",
];

function buildSchema(rows: SchemaRow[]): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];
  for (const row of rows) {
    if (!row.name.trim()) continue;
    properties[row.name] = {
      type: row.type,
      description: row.description || undefined,
    };
    if (row.required) required.push(row.name);
  }
  return { type: "object", properties, required };
}

function parseSchema(schema: Record<string, unknown>): SchemaRow[] {
  if (!schema || typeof schema !== "object") return [];
  const properties = schema.properties as
    | Record<string, { type?: string; description?: string }>
    | undefined;
  const required = (schema.required as string[]) ?? [];
  if (!properties) return [];

  return Object.entries(properties).map(([name, def], i) => ({
    id: String(i),
    name,
    type: (def?.type as FieldType) ?? "string",
    required: required.includes(name),
    description: def?.description ?? "",
  }));
}

function newRow(): SchemaRow {
  return {
    id: String(Math.random()),
    name: "",
    type: "string",
    required: false,
    description: "",
  };
}

function detectTemplateTokens(template: string): string[] {
  const matches = template.match(/\{\{input\.(\w+)\}\}/g) ?? [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const m of matches) {
    const token = m.replace(/\{\{input\.(\w+)\}\}/, "$1");
    if (!seen.has(token)) {
      seen.add(token);
      result.push(token);
    }
  }
  return result;
}

const CHAR_WARN = 2400;
const CHAR_ALERT = 2800;
const CHAR_MAX = 3000;

type AccordionSection =
  | "identity"
  | "execution"
  | "prompt"
  | "schema"
  | "tools";

export function TenantSkillAuthoringPanel({
  skill,
  onClose,
  onSaved,
}: TenantSkillAuthoringPanelProps) {
  const isEdit = !!skill;

  // Form state
  const [name, setName] = useState(skill?.name ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [category, setCategory] = useState(skill?.category ?? "");
  const [execPattern, setExecPattern] = useState<"prompt" | "tool_composing">(
    (skill?.execution_pattern as "prompt" | "tool_composing") ?? "prompt",
  );
  const [invocationMode, setInvocationMode] = useState<
    "llm_invoked" | "pipeline"
  >(skill?.invocation_mode ?? "llm_invoked");
  const [pipelineTrigger, setPipelineTrigger] = useState(
    skill?.pipeline_trigger ?? "",
  );
  const [promptTemplate, setPromptTemplate] = useState(
    skill?.prompt_template ?? "",
  );
  const [inputRows, setInputRows] = useState<SchemaRow[]>(() =>
    skill?.input_schema ? parseSchema(skill.input_schema) : [],
  );
  const [outputRows, setOutputRows] = useState<SchemaRow[]>(() =>
    skill?.output_schema ? parseSchema(skill.output_schema) : [],
  );
  const [selectedTools, setSelectedTools] = useState<string[]>(
    skill?.tool_dependencies ?? [],
  );

  // Accordion state
  const [openSections, setOpenSections] = useState<Set<AccordionSection>>(
    () => {
      const s = new Set<AccordionSection>();
      s.add("identity");
      s.add("execution");
      s.add("prompt");
      return s;
    },
  );

  // Test drawer
  const [showTest, setShowTest] = useState(false);
  const [savedSkill, setSavedSkill] = useState<TenantSkill | null>(skill);

  // Error
  const [submitError, setSubmitError] = useState<string | null>(null);

  const { mutate: createSkill, isPending: isCreating } = useCreateSkill();
  const { mutate: updateSkill, isPending: isUpdating } = useUpdateSkill();
  const { mutate: publishSkill, isPending: isPublishing } = usePublishSkill();

  // Tools from catalog
  const { data: toolsData } = useTools();
  const availableTools = toolsData ?? [];

  const isPending = isCreating || isUpdating || isPublishing;
  const charCount = promptTemplate.length;
  const detectedTokens = detectTemplateTokens(promptTemplate);

  function toggleSection(section: AccordionSection) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  }

  function buildPayload(): CreateSkillPayload {
    return {
      name: name.trim(),
      description: description.trim() || undefined,
      category: category.trim() || undefined,
      execution_pattern: execPattern,
      invocation_mode: invocationMode,
      pipeline_trigger:
        invocationMode === "pipeline" ? pipelineTrigger.trim() || null : null,
      prompt_template: promptTemplate,
      input_schema: buildSchema(inputRows),
      output_schema: buildSchema(outputRows),
      tool_dependencies: execPattern === "tool_composing" ? selectedTools : [],
    };
  }

  function handleSaveDraft() {
    setSubmitError(null);
    const payload = buildPayload();
    if (!payload.name) {
      setSubmitError("Name is required.");
      return;
    }
    if (isEdit && skill) {
      updateSkill(
        { skillId: skill.id, payload },
        {
          onSuccess: (data) => {
            setSavedSkill(data);
            onSaved();
          },
          onError: (err) =>
            setSubmitError(err instanceof Error ? err.message : "Save failed"),
        },
      );
    } else {
      createSkill(payload, {
        onSuccess: (data) => {
          setSavedSkill(data);
          onSaved();
        },
        onError: (err) =>
          setSubmitError(err instanceof Error ? err.message : "Create failed"),
      });
    }
  }

  function handlePublish() {
    setSubmitError(null);
    const targetId = savedSkill?.id ?? skill?.id;
    if (!targetId) {
      setSubmitError("Save as draft first before publishing.");
      return;
    }
    publishSkill(targetId, {
      onSuccess: () => onSaved(),
      onError: (err) =>
        setSubmitError(err instanceof Error ? err.message : "Publish failed"),
    });
  }

  function addInputRow() {
    setInputRows((prev) => [...prev, newRow()]);
  }

  function updateInputRow(id: string, update: Partial<SchemaRow>) {
    setInputRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, ...update } : r)),
    );
  }

  function removeInputRow(id: string) {
    setInputRows((prev) => prev.filter((r) => r.id !== id));
  }

  function addOutputRow() {
    setOutputRows((prev) => [...prev, newRow()]);
  }

  function updateOutputRow(id: string, update: Partial<SchemaRow>) {
    setOutputRows((prev) =>
      prev.map((r) => (r.id === id ? { ...r, ...update } : r)),
    );
  }

  function removeOutputRow(id: string) {
    setOutputRows((prev) => prev.filter((r) => r.id !== id));
  }

  function toggleTool(toolId: string) {
    setSelectedTools((prev) =>
      prev.includes(toolId)
        ? prev.filter((t) => t !== toolId)
        : [...prev, toolId],
    );
  }

  const testTarget = savedSkill ?? skill;

  return (
    <>
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
                {isEdit ? "Edit Skill" : "New Skill"}
              </h2>
              <p className="mt-0.5 text-body-default text-text-muted">
                {isEdit ? skill?.name : "Author a tenant-specific skill"}
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
                    placeholder="e.g. Sentiment Analyzer"
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
                    placeholder="e.g. NLP, Finance, HR"
                    className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                  />
                </div>
              </div>
            </AccordionSection>

            {/* Section: Execution */}
            <AccordionSection
              title="Execution"
              isOpen={openSections.has("execution")}
              onToggle={() => toggleSection("execution")}
            >
              <div className="space-y-4">
                <div>
                  <p className="mb-2 text-body-default font-medium text-text-primary">
                    Execution Pattern
                  </p>
                  <div className="space-y-2">
                    {(["prompt", "tool_composing"] as const).map((pattern) => (
                      <label
                        key={pattern}
                        className="flex cursor-pointer items-center gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5 transition-colors hover:border-accent-ring"
                      >
                        <input
                          type="radio"
                          name="exec_pattern"
                          value={pattern}
                          checked={execPattern === pattern}
                          onChange={() => setExecPattern(pattern)}
                          className="accent-accent"
                        />
                        <div>
                          <p className="text-body-default font-medium text-text-primary">
                            {pattern === "prompt" ? "Prompt" : "Tool-Composing"}
                          </p>
                          <p className="text-body-default text-text-muted">
                            {pattern === "prompt"
                              ? "LLM processes input via a prompt template"
                              : "LLM orchestrates external tools to fulfill the request"}
                          </p>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-body-default font-medium text-text-primary">
                    Invocation Mode
                  </p>
                  <div className="space-y-2">
                    {(["llm_invoked", "pipeline"] as const).map((mode) => (
                      <label
                        key={mode}
                        className="flex cursor-pointer items-center gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5 transition-colors hover:border-accent-ring"
                      >
                        <input
                          type="radio"
                          name="invocation_mode"
                          value={mode}
                          checked={invocationMode === mode}
                          onChange={() => setInvocationMode(mode)}
                          className="accent-accent"
                        />
                        <div>
                          <p className="text-body-default font-medium text-text-primary">
                            {mode === "llm_invoked"
                              ? "LLM Decides"
                              : "Auto-Trigger"}
                          </p>
                          <p className="text-body-default text-text-muted">
                            {mode === "llm_invoked"
                              ? "The LLM determines when to invoke this skill"
                              : "Skill is triggered automatically based on a pipeline condition"}
                          </p>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                {invocationMode === "pipeline" && (
                  <div>
                    <label className="mb-1 block text-body-default font-medium text-text-primary">
                      Pipeline Trigger
                    </label>
                    <input
                      type="text"
                      value={pipelineTrigger}
                      onChange={(e) => setPipelineTrigger(e.target.value)}
                      placeholder="e.g. on_document_upload"
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                    />
                  </div>
                )}
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

                {detectedTokens.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-label-nav uppercase tracking-wider text-text-faint">
                      Detected Input Tokens
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {detectedTokens.map((token) => (
                        <span
                          key={token}
                          className="rounded-badge border border-accent/30 bg-accent-dim px-2 py-0.5 font-mono text-data-value text-accent"
                        >
                          {`{{input.${token}}}`}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </AccordionSection>

            {/* Section: Input/Output Schema */}
            <AccordionSection
              title="Input / Output Schema"
              isOpen={openSections.has("schema")}
              onToggle={() => toggleSection("schema")}
            >
              <div className="space-y-5">
                {/* Input schema */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-body-default font-medium text-text-primary">
                      Input Schema
                    </p>
                    <button
                      type="button"
                      onClick={addInputRow}
                      className="flex items-center gap-1 rounded-control border border-border px-2 py-1 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-accent"
                    >
                      <Plus size={12} />
                      Add Field
                    </button>
                  </div>
                  {inputRows.length === 0 ? (
                    <p className="text-body-default text-text-faint">
                      No input fields defined.
                    </p>
                  ) : (
                    <SchemaTable
                      rows={inputRows}
                      onUpdate={updateInputRow}
                      onRemove={removeInputRow}
                    />
                  )}
                </div>

                {/* Output schema */}
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-body-default font-medium text-text-primary">
                      Output Schema
                    </p>
                    <button
                      type="button"
                      onClick={addOutputRow}
                      className="flex items-center gap-1 rounded-control border border-border px-2 py-1 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-accent"
                    >
                      <Plus size={12} />
                      Add Field
                    </button>
                  </div>
                  {outputRows.length === 0 ? (
                    <p className="text-body-default text-text-faint">
                      No output fields defined.
                    </p>
                  ) : (
                    <SchemaTable
                      rows={outputRows}
                      onUpdate={updateOutputRow}
                      onRemove={removeOutputRow}
                    />
                  )}
                </div>
              </div>
            </AccordionSection>

            {/* Section: Tools (only for tool_composing) */}
            {execPattern === "tool_composing" && (
              <AccordionSection
                title="Tools"
                isOpen={openSections.has("tools")}
                onToggle={() => toggleSection("tools")}
              >
                {availableTools.length === 0 ? (
                  <p className="text-body-default text-text-faint">
                    No tools available in the catalog.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {availableTools.map((tool) => (
                      <label
                        key={tool.id}
                        className="flex cursor-pointer items-start gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5 transition-colors hover:border-accent-ring"
                      >
                        <input
                          type="checkbox"
                          checked={selectedTools.includes(tool.id)}
                          onChange={() => toggleTool(tool.id)}
                          className="mt-0.5 accent-accent"
                        />
                        <div>
                          <p className="text-body-default font-medium text-text-primary">
                            {tool.name}
                          </p>
                          <p className="font-mono text-data-value text-text-faint">
                            {tool.provider}
                          </p>
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </AccordionSection>
            )}
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

              {testTarget && (
                <button
                  type="button"
                  onClick={() => setShowTest(true)}
                  className="flex items-center gap-2 rounded-control border border-border px-3 py-2.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
                >
                  <FlaskConical size={13} />
                  Test
                </button>
              )}

              <button
                type="button"
                onClick={handlePublish}
                disabled={isPending}
                className="flex flex-1 items-center justify-center gap-2 rounded-control bg-accent px-4 py-2.5 text-body-default font-medium text-bg-base transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isPublishing && <Loader2 size={13} className="animate-spin" />}
                Publish
              </button>
            </div>
          </div>
        </div>
      </div>

      {showTest && testTarget && (
        <SkillTestDrawer
          skill={testTarget}
          onClose={() => setShowTest(false)}
        />
      )}
    </>
  );
}

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
// Schema table sub-component
// ---------------------------------------------------------------------------

function SchemaTable({
  rows,
  onUpdate,
  onRemove,
}: {
  rows: SchemaRow[];
  onUpdate: (id: string, update: Partial<SchemaRow>) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-card border border-border">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border bg-bg-elevated">
            <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Field Name
            </th>
            <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Type
            </th>
            <th className="px-3 py-2 text-center text-label-nav uppercase tracking-wider text-text-faint">
              Req
            </th>
            <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
              Description
            </th>
            <th className="w-8 px-2 py-2" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className="border-b border-border-faint last:border-0"
            >
              <td className="px-3 py-2">
                <input
                  type="text"
                  value={row.name}
                  onChange={(e) => onUpdate(row.id, { name: e.target.value })}
                  placeholder="field_name"
                  className="w-full rounded border border-border bg-bg-deep px-2 py-1 font-mono text-data-value text-text-primary placeholder:font-sans placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </td>
              <td className="px-3 py-2">
                <select
                  value={row.type}
                  onChange={(e) =>
                    onUpdate(row.id, { type: e.target.value as FieldType })
                  }
                  className="rounded border border-border bg-bg-deep px-2 py-1 font-mono text-data-value text-text-primary outline-none focus:border-accent-ring"
                >
                  {FIELD_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-3 py-2 text-center">
                <input
                  type="checkbox"
                  checked={row.required}
                  onChange={(e) =>
                    onUpdate(row.id, { required: e.target.checked })
                  }
                  className="accent-accent"
                />
              </td>
              <td className="px-3 py-2">
                <input
                  type="text"
                  value={row.description}
                  onChange={(e) =>
                    onUpdate(row.id, { description: e.target.value })
                  }
                  placeholder="Optional description"
                  className="w-full rounded border border-border bg-bg-deep px-2 py-1 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </td>
              <td className="px-2 py-2">
                <button
                  type="button"
                  onClick={() => onRemove(row.id)}
                  className="rounded p-1 text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
                >
                  <Trash2 size={13} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
