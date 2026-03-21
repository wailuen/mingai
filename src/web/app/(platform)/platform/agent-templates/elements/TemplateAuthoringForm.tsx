"use client";

import { useState, useCallback, type ReactNode } from "react";
import { X } from "lucide-react";
import {
  useCreateAgentTemplate,
  useUpdateAgentTemplate,
  type AgentTemplateAdmin,
  type AgentTemplateVariable,
  type GuardrailRule,
} from "@/lib/hooks/useAgentTemplatesAdmin";
import { VariableDefinitions } from "./VariableDefinitions";
import { LifecycleActions } from "./LifecycleActions";
import { TestHarnessPanel } from "./TestHarnessPanel";
import { VersionHistoryDrawer } from "./VersionHistoryDrawer";

interface TemplateAuthoringFormProps {
  template: AgentTemplateAdmin | null;
  onClose: () => void;
}

const CATEGORY_OPTIONS = [
  "HR",
  "IT",
  "Procurement",
  "Onboarding",
  "Legal",
  "Finance",
  "Custom",
] as const;

/**
 * Renders a system prompt string, highlighting {{variable}} tokens
 * with accent-colored spans.
 */
function renderPromptWithHighlights(text: string): ReactNode[] {
  const parts = text.split(/({{[^}]+}})/g);
  return parts.map((part, i) => {
    if (/^{{[^}]+}}$/.test(part)) {
      return (
        <span key={i} className="font-mono text-accent">
          {part}
        </span>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export function TemplateAuthoringForm({
  template,
  onClose,
}: TemplateAuthoringFormProps) {
  const isEditing = template !== null;

  const [name, setName] = useState(template?.name ?? "");
  const [description, setDescription] = useState(
    template?.description ?? "",
  );
  const [category, setCategory] = useState(template?.category ?? "Custom");
  const [systemPrompt, setSystemPrompt] = useState(
    template?.system_prompt ?? "",
  );
  const [variables, setVariables] = useState<AgentTemplateVariable[]>(
    template?.variable_definitions ?? [],
  );
  const [guardrails, setGuardrails] = useState<GuardrailRule[]>(
    template?.guardrails ?? [],
  );
  const [confidenceThreshold, setConfidenceThreshold] = useState(
    template?.confidence_threshold ?? 0.7,
  );
  const [showPreview, setShowPreview] = useState(false);
  const [showTestHarness, setShowTestHarness] = useState(false);
  const [showVersionHistory, setShowVersionHistory] = useState(false);

  const createMutation = useCreateAgentTemplate();
  const updateMutation = useUpdateAgentTemplate();

  const isPending = createMutation.isPending || updateMutation.isPending;

  const canSave = name.trim().length > 0 && systemPrompt.trim().length > 0;

  const handleSaveDraft = useCallback(async () => {
    const payload = {
      name: name.trim(),
      description: description.trim() || undefined,
      category,
      system_prompt: systemPrompt,
      variable_definitions: variables,
      guardrails,
      confidence_threshold: confidenceThreshold,
    };

    if (isEditing && template) {
      await updateMutation.mutateAsync({ id: template.id, payload });
    } else {
      await createMutation.mutateAsync(payload);
    }
    onClose();
  }, [
    name,
    description,
    category,
    systemPrompt,
    variables,
    guardrails,
    confidenceThreshold,
    isEditing,
    template,
    updateMutation,
    createMutation,
    onClose,
  ]);

  const mutationError = createMutation.error || updateMutation.error;

  // Guardrail management helpers
  function addGuardrail() {
    setGuardrails([
      ...guardrails,
      { pattern: "", action: "block", reason: "" },
    ]);
  }

  function removeGuardrail(index: number) {
    setGuardrails(guardrails.filter((_, i) => i !== index));
  }

  function updateGuardrail(
    index: number,
    field: keyof GuardrailRule,
    value: string,
  ) {
    setGuardrails(
      guardrails.map((g, i) => (i === index ? { ...g, [field]: value } : g)),
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-bg-deep/60"
        onClick={onClose}
        role="presentation"
      />

      {/* Panel */}
      <div className="relative flex w-[560px] flex-col border-l border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">
            {isEditing ? "Edit Template" : "New Template"}
          </h2>
          <div className="flex items-center gap-2">
            {isEditing && template && (
              <>
                <button
                  type="button"
                  onClick={() => setShowTestHarness(true)}
                  className="rounded-control border border-border px-3 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                >
                  Test
                </button>
                <button
                  type="button"
                  onClick={() => setShowVersionHistory(true)}
                  className="rounded-control border border-border px-3 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
                >
                  Versions
                </button>
              </>
            )}
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {/* Name */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Template Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. HR Policy Assistant"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
          </div>

          {/* Description */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief description of what this template does"
              rows={2}
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
          </div>

          {/* Category */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary focus:border-accent focus:outline-none"
            >
              {CATEGORY_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>

          {/* System Prompt */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="text-[11px] uppercase tracking-wider text-text-faint">
                System Prompt
              </label>
              <button
                type="button"
                onClick={() => setShowPreview(!showPreview)}
                className="text-[11px] text-text-muted transition-colors hover:text-accent"
              >
                {showPreview ? "Edit" : "Preview"}
              </button>
            </div>
            {showPreview ? (
              <div className="min-h-[160px] rounded-control border border-border bg-bg-elevated p-3 text-body-default leading-relaxed text-text-primary">
                {renderPromptWithHighlights(systemPrompt)}
              </div>
            ) : (
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="You are an assistant that helps with {{topic}}. Use {{tone}} tone."
                rows={7}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
              />
            )}
            <p className="mt-1 text-[11px] text-text-faint">
              Use {"{{variable_name}}"} syntax for dynamic placeholders.
            </p>
          </div>

          {/* Guardrails */}
          <div className="space-y-3">
            <label className="block text-[11px] uppercase tracking-wider text-text-faint">
              Guardrails
            </label>

            {guardrails.map((rule, index) => (
              <div
                key={index}
                className="flex items-start gap-2 rounded-control border border-border bg-bg-elevated p-2"
              >
                <div className="flex-1 space-y-1.5">
                  <input
                    type="text"
                    value={rule.pattern}
                    onChange={(e) =>
                      updateGuardrail(index, "pattern", e.target.value)
                    }
                    placeholder="Pattern (regex or substring)"
                    className="w-full rounded-control border border-border bg-bg-base px-2 py-1 font-mono text-xs text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                  />
                  <div className="flex items-center gap-2">
                    <select
                      value={rule.action}
                      onChange={(e) =>
                        updateGuardrail(index, "action", e.target.value)
                      }
                      className="rounded-control border border-border bg-bg-base px-2 py-1 text-xs text-text-primary focus:border-accent focus:outline-none"
                    >
                      <option value="block">Block</option>
                      <option value="warn">Warn</option>
                    </select>
                    <input
                      type="text"
                      value={rule.reason}
                      onChange={(e) =>
                        updateGuardrail(index, "reason", e.target.value)
                      }
                      placeholder="Reason"
                      className="flex-1 rounded-control border border-border bg-bg-base px-2 py-1 text-xs text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                    />
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => removeGuardrail(index)}
                  className="mt-1 flex h-6 w-6 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
                >
                  <X size={12} />
                </button>
              </div>
            ))}

            <button
              type="button"
              onClick={addGuardrail}
              className="rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              + Add Guardrail
            </button>

            <div>
              <label className="mb-1 block text-[11px] text-text-muted">
                Confidence Threshold
              </label>
              <input
                type="number"
                value={confidenceThreshold}
                onChange={(e) =>
                  setConfidenceThreshold(
                    Math.min(1, Math.max(0, parseFloat(e.target.value) || 0)),
                  )
                }
                min={0}
                max={1}
                step={0.05}
                className="w-32 rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary focus:border-accent focus:outline-none"
              />
            </div>
          </div>

          {/* Variables */}
          <VariableDefinitions variables={variables} onChange={setVariables} />

          {/* Lifecycle Actions (edit mode only) */}
          {isEditing && template && (
            <div className="border-t border-border pt-5">
              <LifecycleActions template={template} onClose={onClose} />
            </div>
          )}

          {/* Error display */}
          {mutationError && (
            <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
              <p className="text-xs text-alert">
                {mutationError instanceof Error
                  ? mutationError.message
                  : "Operation failed"}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={handleSaveDraft}
            disabled={!canSave || isPending}
            className="rounded-control border border-border px-4 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
          >
            {isPending ? "Saving..." : "Save Draft"}
          </button>
        </div>
      </div>

      {/* Test Harness slide-in */}
      {showTestHarness && template && (
        <TestHarnessPanel
          template={template}
          onClose={() => setShowTestHarness(false)}
        />
      )}

      {/* Version History drawer */}
      {showVersionHistory && template && (
        <VersionHistoryDrawer
          templateId={template.id}
          onClose={() => setShowVersionHistory(false)}
        />
      )}
    </div>
  );
}
