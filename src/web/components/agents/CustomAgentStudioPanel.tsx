"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { X, ChevronDown, ChevronRight, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { IconPicker } from "@/components/shared/IconPicker";
import { SkillPickerPanel } from "@/components/shared/SkillPickerPanel";
import { usePlatformTools, useTenantTools } from "@/lib/hooks/useTools";
import {
  useCreateCustomAgent,
  useUpdateCustomAgent,
  useTestCustomAgent,
  usePublishCustomAgent,
  type CustomAgentFormData,
  type SkillAttachment,
  type GuardrailsSchema,
  type AccessRules,
  type AgentIconType,
} from "@/lib/hooks/useCustomAgentStudio";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CustomAgentStudioPanelProps {
  agentId?: string | null;
  onClose: () => void;
  onPublished?: (agentId: string) => void;
}

type SaveState = "idle" | "saving" | "saved";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EMPTY_FORM: CustomAgentFormData = {
  name: "",
  description: "",
  category: "",
  icon: "custom",
  system_prompt: "",
  kb_ids: [],
  attached_skills: [],
  attached_tools: [],
  guardrails: {
    blocked_topics: [],
    confidence_threshold: null,
    max_response_length: null,
  },
  access_rules: {
    access_control: "workspace",
    allowed_roles: [],
    allowed_user_ids: [],
  },
};

function SectionHeader({
  title,
  isOpen,
  onToggle,
}: {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="flex w-full items-center justify-between py-3 text-left"
    >
      <span className="text-section-heading text-text-primary">{title}</span>
      {isOpen ? (
        <ChevronDown size={15} className="text-text-faint" />
      ) : (
        <ChevronRight size={15} className="text-text-faint" />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CustomAgentStudioPanel({
  agentId: initialAgentId,
  onClose,
  onPublished,
}: CustomAgentStudioPanelProps) {
  const [agentId, setAgentId] = useState<string | null>(initialAgentId ?? null);
  const [form, setForm] = useState<CustomAgentFormData>(EMPTY_FORM);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  // Section open states
  const [openSections, setOpenSections] = useState({
    identity: true,
    systemPrompt: true,
    skills: false,
    capabilities: false,
    access: false,
    guardrails: false,
  });

  // Inline test pane
  const [testPaneOpen, setTestPaneOpen] = useState(false);
  const [testQuery, setTestQuery] = useState("");
  const [testResult, setTestResult] = useState<{
    response?: string;
    confidence?: number;
    sources_count?: number;
    latency_ms?: number;
    error?: string;
  } | null>(null);

  // Blocked topics chip input
  const [topicInput, setTopicInput] = useState("");

  // Access control textareas (one-per-line editing)
  const [rolesText, setRolesText] = useState("");
  const [usersText, setUsersText] = useState("");

  // Debounce timer ref for auto-save
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const createMutation = useCreateCustomAgent();
  const updateMutation = useUpdateCustomAgent();
  const testMutation = useTestCustomAgent();
  const publishMutation = usePublishCustomAgent();

  const { data: platformToolsData } = usePlatformTools();
  const { data: tenantToolsData } = useTenantTools();

  const platformTools = platformToolsData?.items ?? [];
  const tenantTools = tenantToolsData?.items ?? [];

  // Sync roles/users text when access_rules mode changes
  useEffect(() => {
    setRolesText((form.access_rules?.allowed_roles ?? []).join("\n"));
    setUsersText((form.access_rules?.allowed_user_ids ?? []).join("\n"));
  }, [form.access_rules?.access_control]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleSection(key: keyof typeof openSections) {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function updateForm(patch: Partial<CustomAgentFormData>) {
    setForm((prev) => ({ ...prev, ...patch }));
  }

  function updateGuardrails(patch: Partial<GuardrailsSchema>) {
    setForm((prev) => ({
      ...prev,
      guardrails: { ...prev.guardrails, ...patch },
    }));
  }

  function updateAccessRules(patch: Partial<AccessRules>) {
    setForm((prev) => ({
      ...prev,
      access_rules: {
        ...(prev.access_rules ?? { access_control: "workspace" }),
        ...patch,
      },
    }));
  }

  // ---------------------------------------------------------------------------
  // Auto-save on blur
  // ---------------------------------------------------------------------------

  const triggerAutoSave = useCallback(() => {
    if (!agentId) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      setSaveState("saving");
      try {
        await updateMutation.mutateAsync({ agentId, payload: form });
        setSaveState("saved");
        setTimeout(() => setSaveState("idle"), 2000);
      } catch {
        setSaveState("idle");
      }
    }, 2000);
  }, [agentId, form, updateMutation]);

  // ---------------------------------------------------------------------------
  // Save Draft
  // ---------------------------------------------------------------------------

  async function handleSaveDraft() {
    if (agentId) {
      setSaveState("saving");
      try {
        await updateMutation.mutateAsync({ agentId, payload: form });
        setSaveState("saved");
        setTimeout(() => setSaveState("idle"), 2000);
      } catch {
        setSaveState("idle");
      }
    } else {
      setSaveState("saving");
      try {
        const created = await createMutation.mutateAsync(form);
        setAgentId(created.id);
        setSaveState("saved");
        setTimeout(() => setSaveState("idle"), 2000);
      } catch {
        setSaveState("idle");
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Publish
  // ---------------------------------------------------------------------------

  async function handlePublish() {
    if (!agentId) {
      // Create first, then publish
      const created = await createMutation.mutateAsync(form);
      const id = created.id;
      setAgentId(id);
      await publishMutation.mutateAsync({
        agentId: id,
        payload: { access_rules: form.access_rules },
      });
      onPublished?.(id);
    } else {
      await publishMutation.mutateAsync({
        agentId,
        payload: { access_rules: form.access_rules },
      });
      onPublished?.(agentId);
    }
  }

  // ---------------------------------------------------------------------------
  // Test
  // ---------------------------------------------------------------------------

  async function handleTest() {
    if (!agentId || !testQuery.trim()) return;
    const result = await testMutation.mutateAsync({
      agentId,
      payload: { query: testQuery },
    });
    setTestResult(result);
  }

  // ---------------------------------------------------------------------------
  // Skills
  // ---------------------------------------------------------------------------

  function handleSkillsChange(
    selectedIds: string[],
    overrides: Record<string, string>,
  ) {
    const attachments: SkillAttachment[] = selectedIds.map((id) => ({
      skill_id: id,
      invocation_override: overrides[id] ?? null,
    }));
    updateForm({ attached_skills: attachments });
  }

  const selectedSkillIds = form.attached_skills.map((a) => a.skill_id);
  const invocationOverrides = Object.fromEntries(
    form.attached_skills
      .filter((a) => a.invocation_override)
      .map((a) => [a.skill_id, a.invocation_override as string]),
  );

  // ---------------------------------------------------------------------------
  // Tools
  // ---------------------------------------------------------------------------

  function toggleTool(toolId: string) {
    const current = form.attached_tools;
    if (current.includes(toolId)) {
      updateForm({ attached_tools: current.filter((id) => id !== toolId) });
    } else {
      updateForm({ attached_tools: [...current, toolId] });
    }
  }

  // ---------------------------------------------------------------------------
  // Blocked topics chip input
  // ---------------------------------------------------------------------------

  function handleTopicKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if ((e.key === "Enter" || e.key === ",") && topicInput.trim()) {
      e.preventDefault();
      const topic = topicInput.trim().replace(/,$/, "");
      if (topic && !(form.guardrails.blocked_topics ?? []).includes(topic)) {
        updateGuardrails({
          blocked_topics: [...(form.guardrails.blocked_topics ?? []), topic],
        });
      }
      setTopicInput("");
    }
  }

  function removeTopic(topic: string) {
    updateGuardrails({
      blocked_topics: (form.guardrails.blocked_topics ?? []).filter(
        (t) => t !== topic,
      ),
    });
  }

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const charCount = form.system_prompt.length;
  const charCountColor =
    charCount >= 2800
      ? "text-alert"
      : charCount >= 2400
        ? "text-warn"
        : "text-text-faint";

  const isPublishing = publishMutation.isPending;
  const canPublish = form.name.trim().length > 0;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-bg-base/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-bg-surface shadow-xl sm:w-[560px]">
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-3">
            <h2 className="text-section-heading text-text-primary">
              {agentId ? form.name || "Custom Agent" : "New Agent"}
            </h2>
            {agentId && (
              <span className="rounded-badge border border-border px-2 py-0.5 text-[11px] text-text-faint">
                Draft
              </span>
            )}
          </div>
          <div className="flex items-center gap-4">
            {saveState === "saving" && (
              <span className="text-label-nav text-text-faint">Saving...</span>
            )}
            {saveState === "saved" && (
              <span className="text-label-nav text-accent">Saved</span>
            )}
            <button
              type="button"
              onClick={onClose}
              className="text-text-faint transition-colors hover:text-text-primary"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-0 divide-y divide-border">
            {/* ── Section 1: Identity ── */}
            <div>
              <SectionHeader
                title="Identity"
                isOpen={openSections.identity}
                onToggle={() => toggleSection("identity")}
              />
              {openSections.identity && (
                <div className="space-y-4 pb-5">
                  {/* Icon picker */}
                  <div>
                    <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
                      Icon
                    </label>
                    <IconPicker
                      value={form.icon}
                      onChange={(icon) => updateForm({ icon })}
                    />
                  </div>

                  {/* Name */}
                  <div>
                    <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                      Name <span className="text-alert">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.name}
                      maxLength={255}
                      onChange={(e) => updateForm({ name: e.target.value })}
                      onBlur={triggerAutoSave}
                      placeholder="e.g. HR Assistant"
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                    />
                  </div>

                  {/* Description */}
                  <div>
                    <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                      Description
                    </label>
                    <textarea
                      value={form.description}
                      maxLength={1000}
                      rows={3}
                      onChange={(e) =>
                        updateForm({ description: e.target.value })
                      }
                      onBlur={triggerAutoSave}
                      placeholder="What does this agent help users with?"
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                    />
                  </div>

                  {/* Category */}
                  <div>
                    <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                      Category
                    </label>
                    <input
                      type="text"
                      value={form.category}
                      maxLength={100}
                      onChange={(e) => updateForm({ category: e.target.value })}
                      onBlur={triggerAutoSave}
                      placeholder="e.g. HR & Legal"
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* ── Section 2: System Prompt ── */}
            <div>
              <SectionHeader
                title="System Prompt"
                isOpen={openSections.systemPrompt}
                onToggle={() => toggleSection("systemPrompt")}
              />
              {openSections.systemPrompt && (
                <div className="pb-5">
                  <textarea
                    value={form.system_prompt}
                    maxLength={3000}
                    rows={8}
                    onChange={(e) =>
                      updateForm({ system_prompt: e.target.value })
                    }
                    onBlur={triggerAutoSave}
                    placeholder="You are a helpful assistant specialising in..."
                    className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:font-sans placeholder:text-text-faint focus:border-accent focus:outline-none"
                  />
                  <div
                    className={cn(
                      "mt-1 text-right text-[11px]",
                      charCountColor,
                    )}
                  >
                    {charCount} / 3000
                  </div>
                </div>
              )}
            </div>

            {/* ── Section 2b: Skills ── */}
            <div>
              <SectionHeader
                title="Skills"
                isOpen={openSections.skills}
                onToggle={() => toggleSection("skills")}
              />
              {openSections.skills && (
                <div className="pb-5">
                  <SkillPickerPanel
                    selectedSkillIds={selectedSkillIds}
                    invocationOverrides={invocationOverrides}
                    onChange={handleSkillsChange}
                  />
                </div>
              )}
            </div>

            {/* ── Section 3: Capabilities (Tools) ── */}
            <div>
              <SectionHeader
                title="Capabilities"
                isOpen={openSections.capabilities}
                onToggle={() => toggleSection("capabilities")}
              />
              {openSections.capabilities && (
                <div className="space-y-4 pb-5">
                  {/* Platform tools */}
                  <div>
                    <p className="mb-2 text-[11px] uppercase tracking-wider text-text-faint">
                      Platform Tools
                    </p>
                    {platformTools.length === 0 ? (
                      <p className="text-body-default text-text-faint">
                        No platform tools available.
                      </p>
                    ) : (
                      <div className="space-y-1.5">
                        {platformTools.map((tool) => (
                          <label
                            key={tool.id}
                            className={cn(
                              "flex cursor-pointer items-center gap-2.5 rounded-control border px-3 py-2 transition-colors",
                              form.attached_tools.includes(tool.id)
                                ? "border-accent bg-accent-dim"
                                : "border-border bg-bg-elevated hover:border-accent-ring",
                            )}
                          >
                            <input
                              type="checkbox"
                              checked={form.attached_tools.includes(tool.id)}
                              onChange={() => toggleTool(tool.id)}
                              className="accent-accent"
                            />
                            <span className="flex-1 text-body-default text-text-primary">
                              {tool.name}
                            </span>
                            <span className="rounded-badge bg-bg-base px-1.5 py-0.5 text-[10px] text-text-faint">
                              {tool.executor_type}
                            </span>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Tenant MCP tools */}
                  <div>
                    <p className="mb-2 text-[11px] uppercase tracking-wider text-text-faint">
                      MCP Tools
                    </p>
                    {tenantTools.length === 0 ? (
                      <p className="text-body-default text-text-faint">
                        No MCP tools available. Register an MCP server in Tools.
                      </p>
                    ) : (
                      <div className="space-y-1.5">
                        {tenantTools.map((tool) => (
                          <label
                            key={tool.id}
                            className={cn(
                              "flex cursor-pointer items-center gap-2.5 rounded-control border px-3 py-2 transition-colors",
                              form.attached_tools.includes(tool.id)
                                ? "border-accent bg-accent-dim"
                                : "border-border bg-bg-elevated hover:border-accent-ring",
                            )}
                          >
                            <input
                              type="checkbox"
                              checked={form.attached_tools.includes(tool.id)}
                              onChange={() => toggleTool(tool.id)}
                              className="accent-accent"
                            />
                            <span className="flex-1 text-body-default text-text-primary">
                              {tool.name}
                            </span>
                            {tool.server_name && (
                              <span className="rounded-badge bg-bg-base px-1.5 py-0.5 text-[10px] text-text-faint">
                                {tool.server_name}
                              </span>
                            )}
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* ── Section 4: Access Control ── */}
            <div>
              <SectionHeader
                title="Access Control"
                isOpen={openSections.access}
                onToggle={() => toggleSection("access")}
              />
              {openSections.access && (
                <div className="space-y-2 pb-5">
                  {(
                    [
                      {
                        value: "workspace" as const,
                        label: "Workspace-wide",
                        description:
                          "All users in this workspace can access the agent",
                      },
                      {
                        value: "role" as const,
                        label: "Role-restricted",
                        description:
                          "Only users with specific roles can access",
                      },
                      {
                        value: "user" as const,
                        label: "User-specific",
                        description: "Only named users can access the agent",
                      },
                    ] as const
                  ).map((opt) => {
                    const isActive =
                      (form.access_rules?.access_control ?? "workspace") ===
                      opt.value;
                    return (
                      <div key={opt.value}>
                        <button
                          type="button"
                          onClick={() => {
                            updateAccessRules({ access_control: opt.value });
                          }}
                          className={cn(
                            "w-full rounded-control border px-3 py-2.5 text-left transition-colors",
                            isActive
                              ? "border-accent bg-accent-dim"
                              : "border-border bg-bg-elevated hover:border-accent-ring",
                          )}
                        >
                          <div className="flex items-center gap-2.5">
                            <span
                              className={cn(
                                "flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border",
                                isActive
                                  ? "border-accent"
                                  : "border-text-faint",
                              )}
                            >
                              {isActive && (
                                <span className="h-2 w-2 rounded-full bg-accent" />
                              )}
                            </span>
                            <span
                              className={cn(
                                "text-body-default font-medium",
                                isActive
                                  ? "text-text-primary"
                                  : "text-text-muted",
                              )}
                            >
                              {opt.label}
                            </span>
                          </div>
                          <p className="mt-0.5 pl-[26px] text-[11px] text-text-faint">
                            {opt.description}
                          </p>
                        </button>

                        {isActive && opt.value === "role" && (
                          <div className="mt-2 pl-1">
                            <label className="mb-1 block text-[11px] text-text-faint">
                              Roles (one per line)
                            </label>
                            <textarea
                              value={rolesText}
                              rows={3}
                              onChange={(e) => {
                                setRolesText(e.target.value);
                                updateAccessRules({
                                  allowed_roles: e.target.value
                                    .split("\n")
                                    .map((r) => r.trim())
                                    .filter(Boolean),
                                });
                              }}
                              placeholder={"admin\nuser"}
                              className="w-full rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                            />
                          </div>
                        )}

                        {isActive && opt.value === "user" && (
                          <div className="mt-2 pl-1">
                            <label className="mb-1 block text-[11px] text-text-faint">
                              User IDs (one per line)
                            </label>
                            <textarea
                              value={usersText}
                              rows={3}
                              onChange={(e) => {
                                setUsersText(e.target.value);
                                updateAccessRules({
                                  allowed_user_ids: e.target.value
                                    .split("\n")
                                    .map((r) => r.trim())
                                    .filter(Boolean),
                                });
                              }}
                              placeholder={"user-id-1\nuser-id-2"}
                              className="w-full rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* ── Section 5: Guardrails ── */}
            <div>
              <SectionHeader
                title="Guardrails"
                isOpen={openSections.guardrails}
                onToggle={() => toggleSection("guardrails")}
              />
              {openSections.guardrails && (
                <div className="space-y-4 pb-5">
                  {/* Blocked topics chip input */}
                  <div>
                    <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                      Blocked Topics
                    </label>
                    <div className="flex flex-wrap gap-1.5 rounded-control border border-border bg-bg-elevated px-2 py-1.5">
                      {(form.guardrails.blocked_topics ?? []).map((topic) => (
                        <span
                          key={topic}
                          className="flex items-center gap-1 rounded-badge bg-alert-dim px-2 py-0.5 text-[11px] text-alert"
                        >
                          {topic}
                          <button
                            type="button"
                            onClick={() => removeTopic(topic)}
                            className="text-alert hover:opacity-70"
                          >
                            <X size={10} />
                          </button>
                        </span>
                      ))}
                      <input
                        type="text"
                        value={topicInput}
                        onChange={(e) => setTopicInput(e.target.value)}
                        onKeyDown={handleTopicKeyDown}
                        placeholder="Type topic + Enter to add"
                        className="min-w-[140px] flex-1 bg-transparent text-body-default text-text-primary placeholder:text-text-faint focus:outline-none"
                      />
                    </div>
                    <p className="mt-1 text-[11px] text-text-faint">
                      Press Enter or comma to add a topic.
                    </p>
                  </div>

                  {/* Confidence threshold */}
                  <div>
                    <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                      Confidence Threshold
                    </label>
                    <div className="flex items-center gap-3">
                      <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={form.guardrails.confidence_threshold ?? 0}
                        onChange={(e) =>
                          updateGuardrails({
                            confidence_threshold: parseFloat(e.target.value),
                          })
                        }
                        className="flex-1 accent-accent"
                      />
                      <span className="w-10 text-right font-mono text-data-value text-text-primary">
                        {(form.guardrails.confidence_threshold ?? 0).toFixed(2)}
                      </span>
                    </div>
                  </div>

                  {/* Max response length */}
                  <div>
                    <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-text-faint">
                      Max Response Length
                    </label>
                    <input
                      type="number"
                      min={100}
                      max={10000}
                      step={100}
                      value={form.guardrails.max_response_length ?? ""}
                      onChange={(e) =>
                        updateGuardrails({
                          max_response_length: e.target.value
                            ? parseInt(e.target.value, 10)
                            : null,
                        })
                      }
                      placeholder="2000"
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:font-sans placeholder:text-text-faint focus:border-accent focus:outline-none"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 border-t border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleSaveDraft}
              disabled={createMutation.isPending || updateMutation.isPending}
              className="rounded-control border border-border px-3 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-50"
            >
              Save Draft
            </button>
            <button
              type="button"
              onClick={() => setTestPaneOpen((p) => !p)}
              disabled={!agentId}
              className="rounded-control border border-border px-3 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              Test Agent
            </button>
            <button
              type="button"
              onClick={handlePublish}
              disabled={!canPublish || isPublishing}
              className="ml-auto rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isPublishing ? "Publishing..." : "Publish"}
            </button>
          </div>
        </div>

        {/* Inline test pane */}
        {testPaneOpen && agentId && (
          <div className="flex-shrink-0 border-t border-border bg-bg-elevated px-5 py-4">
            <p className="mb-3 text-section-heading text-text-primary">
              Test Agent
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={testQuery}
                onChange={(e) => setTestQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !testMutation.isPending)
                    handleTest();
                }}
                placeholder="Type a test query..."
                className="flex-1 rounded-control border border-border bg-bg-base px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
              />
              <button
                type="button"
                onClick={handleTest}
                disabled={testMutation.isPending || !testQuery.trim()}
                className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <Play size={13} />
                Run
              </button>
            </div>

            {testMutation.isPending && (
              <p className="mt-3 text-body-default text-text-faint">
                Running...
              </p>
            )}

            {testResult && !testMutation.isPending && (
              <div className="mt-3 space-y-2">
                {testResult.error ? (
                  <p className="text-body-default text-alert">
                    {testResult.error}
                  </p>
                ) : (
                  <>
                    <p className="text-body-default text-text-primary">
                      {testResult.response}
                    </p>
                    <div className="flex gap-4 font-mono text-data-value text-text-faint">
                      {testResult.confidence !== undefined && (
                        <span>
                          Confidence: {(testResult.confidence * 100).toFixed(0)}
                          %
                        </span>
                      )}
                      {testResult.sources_count !== undefined && (
                        <span>Sources: {testResult.sources_count}</span>
                      )}
                      {testResult.latency_ms !== undefined && (
                        <span>{testResult.latency_ms}ms</span>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
