"use client";

import { useState } from "react";
import { X, Loader2, AlertTriangle } from "lucide-react";
import {
  useTestAgentTemplate,
  type AgentTemplateAdmin,
  type TemplateTestResult,
} from "@/lib/hooks/useAgentTemplatesAdmin";

interface TestHarnessPanelProps {
  template: AgentTemplateAdmin;
  onClose: () => void;
}

function TestResultCard({ result }: { result: TemplateTestResult }) {
  return (
    <div className="rounded-control border border-border bg-bg-elevated p-4">
      {/* Prompt */}
      <div className="mb-2">
        <span className="text-[11px] uppercase tracking-wider text-text-faint">
          Prompt
        </span>
        <p className="mt-0.5 text-sm text-text-muted">{result.prompt}</p>
      </div>

      {/* Response */}
      <div className="mb-3">
        <span className="text-[11px] uppercase tracking-wider text-text-faint">
          Response
        </span>
        {result.timed_out ? (
          <div className="mt-1 flex items-center gap-1.5">
            <span className="rounded-badge bg-warn-dim px-2 py-0.5 font-mono text-[10px] uppercase text-warn">
              Timed Out
            </span>
          </div>
        ) : (
          <p className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-text-primary">
            {result.response}
          </p>
        )}
      </div>

      {/* Guardrail warning */}
      {result.guardrail_triggered && (
        <div className="mb-3 flex items-start gap-1.5 rounded-control border border-alert/30 bg-alert-dim p-2">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-alert" />
          <div>
            <span className="text-xs font-medium text-alert">
              Guardrail triggered
            </span>
            {result.guardrail_reason && (
              <p className="mt-0.5 text-xs text-text-muted">
                {result.guardrail_reason}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Metrics row (DM Mono) */}
      <div className="flex items-center gap-4 border-t border-border-faint pt-2">
        <span className="font-mono text-[11px] text-text-faint">
          {result.tokens_in} in / {result.tokens_out} out tokens
        </span>
        <span className="font-mono text-[11px] text-text-faint">
          {result.latency_ms}ms
        </span>
      </div>
    </div>
  );
}

export function TestHarnessPanel({
  template,
  onClose,
}: TestHarnessPanelProps) {
  const [prompts, setPrompts] = useState<string[]>([""]);
  const [variableValues, setVariableValues] = useState<
    Record<string, string>
  >({});
  const testMutation = useTestAgentTemplate();
  const results = testMutation.data?.tests ?? [];
  const varDefs = template.variable_definitions ?? [];

  function addPrompt() {
    if (prompts.length >= 5) return;
    setPrompts([...prompts, ""]);
  }

  function removePrompt(index: number) {
    if (prompts.length <= 1) return;
    setPrompts(prompts.filter((_, i) => i !== index));
  }

  function updatePrompt(index: number, value: string) {
    setPrompts(prompts.map((p, i) => (i === index ? value : p)));
  }

  function handleRun() {
    const validPrompts = prompts.filter((p) => p.trim().length > 0);
    if (validPrompts.length === 0) return;

    testMutation.mutate({
      id: template.id,
      payload: {
        variable_values: variableValues,
        test_prompts: validPrompts,
      },
    });
  }

  const hasValidPrompts = prompts.some((p) => p.trim().length > 0);

  return (
    <div className="fixed inset-y-0 right-0 z-[60] flex w-[480px] flex-col border-l border-border bg-bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <h3 className="text-section-heading text-text-primary">
          Test Harness
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto p-5">
        {/* Variable values (if template has variables) */}
        {varDefs.length > 0 && (
          <div>
            <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
              Variable Values
            </label>
            <div className="space-y-2">
              {varDefs.map((v) => (
                <div key={v.name}>
                  <label className="mb-0.5 block text-xs text-text-muted">
                    {v.label || v.name}
                    {v.required && (
                      <span className="ml-0.5 text-alert">*</span>
                    )}
                  </label>
                  <input
                    type={v.type === "number" ? "number" : "text"}
                    value={variableValues[v.name] ?? ""}
                    onChange={(e) =>
                      setVariableValues({
                        ...variableValues,
                        [v.name]: e.target.value,
                      })
                    }
                    placeholder={`Value for {{${v.name}}}`}
                    className="w-full rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Test prompts */}
        <div>
          <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
            Test Prompts ({prompts.length}/5)
          </label>
          <div className="space-y-2">
            {prompts.map((prompt, index) => (
              <div key={index} className="flex gap-2">
                <textarea
                  value={prompt}
                  onChange={(e) => updatePrompt(index, e.target.value)}
                  placeholder={`Test prompt ${index + 1}...`}
                  rows={2}
                  className="flex-1 rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
                {prompts.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removePrompt(index)}
                    className="self-start rounded-control p-1 text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>

          {prompts.length < 5 && (
            <button
              type="button"
              onClick={addPrompt}
              className="mt-2 rounded-control border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              + Add Prompt
            </button>
          )}
        </div>

        {/* Run button */}
        <button
          type="button"
          onClick={handleRun}
          disabled={!hasValidPrompts || testMutation.isPending}
          className="flex w-full items-center justify-center gap-1.5 rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
        >
          {testMutation.isPending ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              Running tests...
            </>
          ) : (
            "Run Tests"
          )}
        </button>

        {/* Error */}
        {testMutation.error && (
          <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
            <p className="text-xs text-alert">
              {testMutation.error instanceof Error
                ? testMutation.error.message
                : "Test failed"}
            </p>
          </div>
        )}

        {/* Results */}
        {results.length > 0 && (
          <div>
            <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
              Results ({results.length})
            </label>
            <div className="space-y-3">
              {results.map((result, index) => (
                <TestResultCard key={index} result={result} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
