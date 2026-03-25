"use client";

import { useState } from "react";
import { Loader2, Play, ShieldCheck, KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useTestAgentTemplate,
  type AgentTemplateAdmin,
  type TemplateTestResult,
  type CredentialSchema,
} from "@/lib/hooks/useAgentTemplatesAdmin";

interface TestHarnessTabProps {
  template: AgentTemplateAdmin;
  /** When true, Run Test button is disabled due to missing platform credentials */
  credentialsMissing?: boolean;
}

export function TestHarnessTab({ template, credentialsMissing = false }: TestHarnessTabProps) {
  const [query, setQuery] = useState("");
  const [variableValues, setVariableValues] = useState<Record<string, string>>({});
  const [credentialValues, setCredentialValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<TemplateTestResult | null>(null);

  const testMutation = useTestAgentTemplate();

  const variables = template.variable_definitions ?? [];
  const authMode = template.auth_mode ?? "none";

  // Normalise credential schema — support both CredentialSchema[] and legacy string[]
  const credSchema: CredentialSchema[] = (template.credential_schema ?? []).length > 0
    ? (template.credential_schema as CredentialSchema[])
    : (template.required_credentials ?? []).map((k) =>
        typeof k === "string"
          ? { key: k, label: k, type: "string" as const, sensitive: false }
          : k as unknown as CredentialSchema,
      );

  const missingCredentials =
    authMode === "tenant_credentials"
      ? credSchema.filter((c) => !credentialValues[c.key]?.trim())
      : [];

  const canRun =
    !!query.trim() &&
    !testMutation.isPending &&
    missingCredentials.length === 0 &&
    !credentialsMissing;

  async function handleRun() {
    if (!canRun) return;
    try {
      const payload: Parameters<ReturnType<typeof useTestAgentTemplate>["mutateAsync"]>[0]["payload"] =
        {
          query: query.trim(),
          variable_values: variableValues,
        };
      if (authMode === "tenant_credentials" && credSchema.length > 0) {
        payload.credential_overrides = credentialValues;
      }
      const res = await testMutation.mutateAsync({ id: template.id, payload });
      const r = res.result ?? res.tests?.[0] ?? null;
      setResult(r);
    } catch {
      // Error shown via testMutation.error
    }
  }

  return (
    <div className="space-y-4 p-5">
      {/* Auth mode credential section */}
      {authMode === "platform_credentials" && (
        <div className="flex items-start gap-2.5 rounded-control border border-accent/20 bg-accent-dim px-3 py-2.5">
          <ShieldCheck size={14} className="mt-0.5 shrink-0 text-accent" />
          <div>
            <p className="text-body-default font-medium text-accent">Platform credentials</p>
            <p className="text-[11px] text-text-muted">
              Credentials are resolved automatically from the platform vault. No input required.
            </p>
          </div>
        </div>
      )}

      {authMode === "tenant_credentials" && credSchema.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5">
            <KeyRound size={12} className="text-text-faint" />
            <p className="text-[11px] uppercase tracking-wider text-text-faint">
              Test Credentials
            </p>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {credSchema.map((cred) => (
              <div key={cred.key}>
                <label className="mb-0.5 block text-[11px] text-text-muted">
                  {cred.label || cred.key}
                  <span className="ml-0.5 text-alert">*</span>
                </label>
                <input
                  type={cred.sensitive || cred.type === "secret" ? "password" : "text"}
                  value={credentialValues[cred.key] ?? ""}
                  onChange={(e) =>
                    setCredentialValues((prev) => ({ ...prev, [cred.key]: e.target.value }))
                  }
                  placeholder={cred.sensitive ? "••••••••" : `Enter ${cred.label || cred.key}`}
                  className="w-full rounded-control border border-border bg-bg-elevated px-2.5 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Variable fill section */}
      {variables.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] uppercase tracking-wider text-text-faint">
            Variable Values
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {variables.map((v) => (
              <div key={v.name}>
                <label className="mb-0.5 block text-[11px] text-text-muted">
                  {v.name}
                  {v.required && <span className="ml-0.5 text-alert">*</span>}
                </label>
                <input
                  type="text"
                  value={variableValues[v.name] ?? ""}
                  onChange={(e) =>
                    setVariableValues((prev) => ({ ...prev, [v.name]: e.target.value }))
                  }
                  placeholder={`Value for {{${v.name}}}`}
                  className="w-full rounded-control border border-border bg-bg-elevated px-2.5 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Query input */}
      <div>
        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
          Test Query
        </label>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Enter a test query to evaluate template behavior..."
          rows={3}
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleRun}
          disabled={!canRun}
          title={
            credentialsMissing
              ? "Configure missing credentials before testing."
              : undefined
          }
          className={cn(
            "flex items-center gap-2 rounded-control px-4 py-2 text-body-default font-semibold transition-opacity",
            credentialsMissing
              ? "cursor-not-allowed bg-bg-elevated text-text-faint"
              : "bg-accent text-bg-base hover:opacity-90 disabled:opacity-40",
          )}
        >
          {testMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Play size={14} />
          )}
          {testMutation.isPending ? "Running..." : "Run Test"}
        </button>
        {missingCredentials.length > 0 && (
          <p className="text-[11px] text-text-muted">
            Provide {missingCredentials.map((c) => c.label || c.key).join(", ")} to run
          </p>
        )}
      </div>

      {testMutation.error && (
        <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2">
          <p className="text-body-default text-alert">
            {testMutation.error instanceof Error
              ? testMutation.error.message
              : "Test failed"}
          </p>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          <div className="rounded-card border border-border bg-bg-elevated p-4">
            {/* Response */}
            <div className="mb-4">
              <p className="mb-2 text-[11px] uppercase tracking-wider text-text-faint">
                Response
              </p>
              <p className="text-body-default leading-relaxed text-text-primary">
                {result.response || <span className="italic text-text-faint">No response (timed out)</span>}
              </p>
            </div>

            {/* Confidence */}
            {result.confidence !== undefined && (
              <div className="mb-4 flex items-center gap-3">
                <p className="text-[11px] uppercase tracking-wider text-text-faint">
                  Confidence
                </p>
                <div className="flex flex-1 items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-base">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        result.confidence >= 0.7
                          ? "bg-accent"
                          : result.confidence >= 0.5
                            ? "bg-warn"
                            : "bg-alert",
                      )}
                      style={{ width: `${Math.round(result.confidence * 100)}%` }}
                    />
                  </div>
                  <span className="font-mono text-data-value text-accent">
                    {(result.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            )}

            {/* Latency */}
            <div className="mb-4 flex items-center gap-2">
              <p className="text-[11px] uppercase tracking-wider text-text-faint">Latency</p>
              <span className="font-mono text-data-value text-text-muted">
                {result.latency_ms}ms
              </span>
            </div>

            {/* Sources */}
            {result.sources && result.sources.length > 0 && (
              <div className="mb-4">
                <p className="mb-1.5 text-[11px] uppercase tracking-wider text-text-faint">
                  Sources ({result.sources.length})
                </p>
                <ul className="space-y-1">
                  {result.sources.map((src, i) => (
                    <li key={i} className="flex items-start gap-1.5 text-body-default text-text-muted">
                      <span className="font-mono text-data-value text-accent">[{i + 1}]</span>
                      {src}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* KB queries */}
            {result.kb_queries && result.kb_queries.length > 0 && (
              <div className="mb-4">
                <p className="mb-1.5 text-[11px] uppercase tracking-wider text-text-faint">
                  KB Queries
                </p>
                <ul className="space-y-1">
                  {result.kb_queries.map((q, i) => (
                    <li key={i} className="font-mono text-data-value text-text-muted">{q}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Guardrail events */}
            {result.guardrail_events && result.guardrail_events.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] uppercase tracking-wider text-text-faint">
                  Guardrail Events
                </p>
                <ul className="space-y-1">
                  {result.guardrail_events.map((ev, i) => (
                    <li
                      key={i}
                      className="rounded-badge bg-warn-dim px-2 py-1 text-body-default text-warn"
                    >
                      {ev.rule_name && <span className="font-medium">{ev.rule_name}: </span>}
                      {ev.action}
                      {ev.matched && <span className="font-mono"> ({ev.matched})</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
