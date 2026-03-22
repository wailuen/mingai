"use client";

import { useState } from "react";
import { X, Play, Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { useTestSkill } from "@/lib/hooks/useSkills";
import type { TenantSkill, TestSkillResult } from "@/lib/hooks/useSkills";
import { cn } from "@/lib/utils";

interface SkillTestDrawerProps {
  skill: TenantSkill;
  onClose: () => void;
}

type FieldType = "string" | "number" | "boolean" | "object";

interface SchemaField {
  name: string;
  type: FieldType;
  required?: boolean;
  description?: string;
}

function extractFields(schema: Record<string, unknown>): SchemaField[] {
  if (!schema || typeof schema !== "object") return [];

  // JSON Schema format: { properties: { fieldName: { type, description } }, required: [] }
  const properties = schema.properties as
    | Record<string, { type?: string; description?: string }>
    | undefined;
  const required = (schema.required as string[]) ?? [];

  if (!properties) return [];

  return Object.entries(properties).map(([name, def]) => ({
    name,
    type: (def?.type as FieldType) ?? "string",
    required: required.includes(name),
    description: def?.description,
  }));
}

export function SkillTestDrawer({ skill, onClose }: SkillTestDrawerProps) {
  const fields = extractFields(skill.input_schema);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, ""])),
  );
  const [result, setResult] = useState<TestSkillResult | null>(null);

  const { mutate: testSkill, isPending } = useTestSkill();

  function handleRun() {
    const input_values: Record<string, unknown> = {};
    for (const field of fields) {
      const raw = values[field.name] ?? "";
      if (field.type === "number") {
        input_values[field.name] = raw === "" ? 0 : Number(raw);
      } else if (field.type === "boolean") {
        input_values[field.name] = raw === "true";
      } else {
        input_values[field.name] = raw;
      }
    }

    testSkill(
      { skillId: skill.id, payload: { input_values } },
      {
        onSuccess: (data) => setResult(data),
        onError: (err) =>
          setResult({
            error: err instanceof Error ? err.message : "Test failed",
          }),
      },
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden
      />

      {/* Drawer panel */}
      <div className="relative z-10 flex h-full w-[400px] flex-col border-l border-border bg-bg-surface shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Test Skill
            </h2>
            <p className="mt-0.5 text-body-default text-text-muted">
              {skill.name}
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

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* Input fields */}
          {fields.length === 0 ? (
            <p className="text-body-default text-text-faint">
              This skill has no input fields.
            </p>
          ) : (
            <div className="space-y-4">
              <p className="text-label-nav uppercase tracking-wider text-text-faint">
                Input Values
              </p>
              {fields.map((field) => (
                <div key={field.name}>
                  <label className="mb-1 flex items-center gap-1.5 text-body-default font-medium text-text-primary">
                    {field.name}
                    {field.required && <span className="text-alert">*</span>}
                    <span className="font-mono text-data-value text-text-faint">
                      {field.type}
                    </span>
                  </label>
                  {field.description && (
                    <p className="mb-1 text-body-default text-text-faint">
                      {field.description}
                    </p>
                  )}
                  {field.type === "boolean" ? (
                    <select
                      value={values[field.name] ?? "false"}
                      onChange={(e) =>
                        setValues((prev) => ({
                          ...prev,
                          [field.name]: e.target.value,
                        }))
                      }
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary outline-none focus:border-accent-ring"
                    >
                      <option value="false">false</option>
                      <option value="true">true</option>
                    </select>
                  ) : (
                    <input
                      type={field.type === "number" ? "number" : "text"}
                      value={values[field.name] ?? ""}
                      onChange={(e) =>
                        setValues((prev) => ({
                          ...prev,
                          [field.name]: e.target.value,
                        }))
                      }
                      placeholder={
                        field.type === "number" ? "0" : `Enter ${field.name}`
                      }
                      className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                    />
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="mt-6 space-y-3">
              <p className="text-label-nav uppercase tracking-wider text-text-faint">
                Result
              </p>

              {result.error ? (
                <div className="flex items-start gap-2 rounded-card border border-alert/30 bg-alert-dim px-4 py-3">
                  <AlertCircle
                    size={15}
                    className="mt-0.5 shrink-0 text-alert"
                  />
                  <p className="text-body-default text-alert">{result.error}</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Meta row */}
                  <div className="flex flex-wrap gap-3">
                    {result.tokens_used != null && (
                      <div className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5">
                        <span className="text-body-default text-text-faint">
                          Tokens:{" "}
                        </span>
                        <span className="font-mono text-data-value text-text-primary">
                          {result.tokens_used}
                        </span>
                      </div>
                    )}
                    {result.latency_ms != null && (
                      <div className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5">
                        <span className="text-body-default text-text-faint">
                          Latency:{" "}
                        </span>
                        <span className="font-mono text-data-value text-text-primary">
                          {result.latency_ms}ms
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Output text */}
                  {result.output && (
                    <div className="rounded-card border border-border bg-bg-elevated p-3">
                      <p className="mb-1 text-label-nav uppercase tracking-wider text-text-faint">
                        Output
                      </p>
                      <p className="whitespace-pre-wrap text-body-default text-text-primary">
                        {result.output}
                      </p>
                    </div>
                  )}

                  {/* Tool calls */}
                  {result.tool_calls && result.tool_calls.length > 0 && (
                    <div className="rounded-card border border-border bg-bg-elevated p-3">
                      <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
                        Tool Calls ({result.tool_calls.length})
                      </p>
                      <div className="space-y-2">
                        {result.tool_calls.map((call, idx) => (
                          <div
                            key={idx}
                            className="rounded-control border border-border-faint bg-bg-deep p-2"
                          >
                            <p className="font-mono text-data-value text-accent">
                              {call.name}
                            </p>
                            {call.args && Object.keys(call.args).length > 0 && (
                              <pre className="mt-1 overflow-x-auto font-mono text-data-value text-text-muted">
                                {JSON.stringify(call.args, null, 2)}
                              </pre>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="flex items-center gap-2 text-body-default text-accent">
                    <CheckCircle size={14} />
                    <span>Test completed successfully</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-border px-5 py-4">
          <button
            type="button"
            onClick={handleRun}
            disabled={isPending}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-control px-4 py-2.5 text-body-default font-medium transition-colors",
              isPending
                ? "cursor-not-allowed bg-accent/50 text-bg-base"
                : "bg-accent text-bg-base hover:bg-accent/90",
            )}
          >
            {isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Play size={14} />
            )}
            {isPending ? "Running..." : "Run Test"}
          </button>
        </div>
      </div>
    </div>
  );
}
