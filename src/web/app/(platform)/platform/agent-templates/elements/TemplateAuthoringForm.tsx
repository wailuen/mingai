"use client";

import { useState, useCallback, type ReactNode } from "react";
import { X } from "lucide-react";
import {
  useCreateAgentTemplate,
  useUpdateAgentTemplate,
  usePublishAgentTemplate,
  type AgentTemplateAdmin,
  type AgentTemplateVariable,
  type AgentTemplateGuardrails,
} from "@/lib/hooks/useAgentTemplatesAdmin";
import { VariableDefinitions } from "./VariableDefinitions";
import { VersionHistory } from "./VersionHistory";

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
  const [category, setCategory] = useState(template?.category ?? "Custom");
  const [systemPrompt, setSystemPrompt] = useState(
    template?.system_prompt ?? "",
  );
  const [variables, setVariables] = useState<AgentTemplateVariable[]>(
    template?.variables ?? [],
  );
  const [guardrails, setGuardrails] = useState<AgentTemplateGuardrails>(
    template?.guardrails ?? { blocked_topics: "", confidence_threshold: 0.7 },
  );
  const [showPreview, setShowPreview] = useState(false);

  const createMutation = useCreateAgentTemplate();
  const updateMutation = useUpdateAgentTemplate();
  const publishMutation = usePublishAgentTemplate();

  const isPending =
    createMutation.isPending ||
    updateMutation.isPending ||
    publishMutation.isPending;

  const canSave = name.trim().length > 0 && systemPrompt.trim().length > 0;

  const canPublish =
    canSave &&
    category.trim().length > 0 &&
    variables.every((v) => v.name.trim().length > 0);

  const handleSaveDraft = useCallback(async () => {
    const payload = {
      name: name.trim(),
      category,
      system_prompt: systemPrompt,
      variables,
      guardrails,
    };

    if (isEditing && template) {
      await updateMutation.mutateAsync({ id: template.id, payload });
    } else {
      await createMutation.mutateAsync(payload);
    }
    onClose();
  }, [
    name,
    category,
    systemPrompt,
    variables,
    guardrails,
    isEditing,
    template,
    updateMutation,
    createMutation,
    onClose,
  ]);

  const handlePublish = useCallback(async () => {
    if (isEditing && template) {
      await updateMutation.mutateAsync({
        id: template.id,
        payload: {
          name: name.trim(),
          category,
          system_prompt: systemPrompt,
          variables,
          guardrails,
        },
      });
      await publishMutation.mutateAsync(template.id);
    } else {
      const created = await createMutation.mutateAsync({
        name: name.trim(),
        category,
        system_prompt: systemPrompt,
        variables,
        guardrails,
      });
      await publishMutation.mutateAsync(created.id);
    }
    onClose();
  }, [
    name,
    category,
    systemPrompt,
    variables,
    guardrails,
    isEditing,
    template,
    updateMutation,
    publishMutation,
    createMutation,
    onClose,
  ]);

  const mutationError =
    createMutation.error || updateMutation.error || publishMutation.error;

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
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
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
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
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
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
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
              <div className="min-h-[160px] rounded-control border border-border bg-bg-elevated p-3 text-sm leading-relaxed text-text-primary">
                {renderPromptWithHighlights(systemPrompt)}
              </div>
            ) : (
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="You are an assistant that helps with {{topic}}. Use {{tone}} tone."
                rows={7}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
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
            <div>
              <label className="mb-1 block text-[11px] text-text-muted">
                Blocked Topics (one per line)
              </label>
              <textarea
                value={guardrails.blocked_topics}
                onChange={(e) =>
                  setGuardrails({
                    ...guardrails,
                    blocked_topics: e.target.value,
                  })
                }
                placeholder="competitor pricing&#10;internal salaries"
                rows={3}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-text-muted">
                Confidence Threshold
              </label>
              <input
                type="number"
                value={guardrails.confidence_threshold}
                onChange={(e) =>
                  setGuardrails({
                    ...guardrails,
                    confidence_threshold: Math.min(
                      1,
                      Math.max(0, parseFloat(e.target.value) || 0),
                    ),
                  })
                }
                min={0}
                max={1}
                step={0.05}
                className="w-32 rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary focus:border-accent focus:outline-none"
              />
            </div>
          </div>

          {/* Variables */}
          <VariableDefinitions variables={variables} onChange={setVariables} />

          {/* Version History (edit mode only) */}
          {isEditing && template && (
            <div className="border-t border-border pt-5">
              <VersionHistory templateId={template.id} />
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
            className="rounded-control border border-border px-4 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-30"
          >
            Save as Draft
          </button>
          <button
            type="button"
            onClick={handlePublish}
            disabled={!canPublish || isPending}
            className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            {isPending ? "Saving..." : "Publish"}
          </button>
        </div>
      </div>
    </div>
  );
}
