"use client";

import { useMemo } from "react";
import { X } from "lucide-react";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";

interface TemplatePreviewModalProps {
  template: AgentTemplate;
  onClose: () => void;
  onDeploy: (template: AgentTemplate) => void;
}

/**
 * Extracts {{variable}} patterns from a system prompt string.
 */
function extractVariables(prompt: string): string[] {
  const matches = prompt.match(/\{\{(\w+)\}\}/g);
  if (!matches) return [];
  const unique = Array.from(new Set(matches.map((m) => m.slice(2, -2))));
  return unique;
}

export function TemplatePreviewModal({
  template,
  onClose,
  onDeploy,
}: TemplatePreviewModalProps) {
  const variables = useMemo(
    () => extractVariables(template.system_prompt),
    [template.system_prompt],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="mx-4 w-full max-w-2xl rounded-card border border-border bg-bg-surface p-6">
        {/* Header */}
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-page-title text-text-primary">
              {template.name}
            </h2>
            <div className="mt-1 flex items-center gap-2 text-xs text-text-muted">
              {template.is_seed && (
                <span className="rounded-badge bg-accent-dim px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-accent">
                  Seed
                </span>
              )}
              {template.category && (
                <>
                  <span>&middot;</span>
                  <span>{template.category}</span>
                </>
              )}
              <span>&middot;</span>
              <span className="font-mono">v{template.version}</span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        {/* System Prompt */}
        <div className="mb-4">
          <h3 className="mb-2 text-label-nav uppercase text-text-faint">
            System Prompt
          </h3>
          <div className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-card bg-bg-elevated p-4 font-mono text-sm text-text-muted">
            {template.system_prompt}
          </div>
        </div>

        {/* Capabilities */}
        {template.capabilities.length > 0 && (
          <div className="mb-4">
            <h3 className="mb-2 text-label-nav uppercase text-text-faint">
              Capabilities
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {template.capabilities.map((cap) => (
                <span
                  key={cap}
                  className="rounded-badge bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted"
                >
                  {cap}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Variables */}
        {variables.length > 0 && (
          <div className="mb-6">
            <h3 className="mb-2 text-label-nav uppercase text-text-faint">
              Variables detected
            </h3>
            <ul className="space-y-1">
              {variables.map((v) => (
                <li
                  key={v}
                  className="flex items-center gap-1.5 text-sm text-text-muted"
                >
                  <span className="text-text-faint">&bull;</span>
                  <code className="font-mono text-xs text-text-primary">
                    {`{{${v}}}`}
                  </code>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end">
          <button
            onClick={() => onDeploy(template)}
            className="rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            Deploy &rarr;
          </button>
        </div>
      </div>
    </div>
  );
}
