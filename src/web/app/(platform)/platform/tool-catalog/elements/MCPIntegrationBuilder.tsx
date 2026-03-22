"use client";

import { useState, useCallback } from "react";
import { X, AlertTriangle, ChevronLeft, Loader2, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useParseAPIDoc,
  useRegisterPlatformTools,
  type ParsedAPIDoc,
  type ParsedEndpoint,
  type ToolRegistration,
} from "@/lib/hooks/usePlatformToolsAdmin";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type DocFormat = "auto" | "openapi_json" | "openapi_yaml" | "postman";

const FORMAT_OPTIONS: { value: DocFormat; label: string }[] = [
  { value: "auto", label: "Auto-detect" },
  { value: "openapi_json", label: "OpenAPI JSON" },
  { value: "openapi_yaml", label: "OpenAPI YAML" },
  { value: "postman", label: "Postman Collection" },
];

type PlanGate = "starter" | "professional" | "enterprise" | null;
type CredentialSource = "none" | "platform_managed" | "tenant_managed";

const PLAN_OPTIONS: { value: PlanGate; label: string }[] = [
  { value: null, label: "All plans" },
  { value: "starter", label: "Starter+" },
  { value: "professional", label: "Professional+" },
  { value: "enterprise", label: "Enterprise only" },
];

const CREDENTIAL_OPTIONS: {
  value: CredentialSource;
  label: string;
  hint: string;
}[] = [
  { value: "none", label: "None", hint: "No auth required" },
  {
    value: "platform_managed",
    label: "Platform-managed",
    hint: "Credentials stored at platform level",
  },
  {
    value: "tenant_managed",
    label: "Tenant-managed",
    hint: "Each tenant provides their own credentials",
  },
];

// ---------------------------------------------------------------------------
// Method badge colours (design system: no hardcoded hex — use Tailwind tokens)
// ---------------------------------------------------------------------------

const METHOD_BADGE: Record<string, string> = {
  GET: "border border-accent/30 bg-accent-dim text-accent",
  POST: "border border-warn/30 bg-warn-dim text-warn",
  PUT: "border border-border bg-bg-elevated text-text-muted",
  PATCH: "border border-border bg-bg-elevated text-text-muted",
  DELETE: "border border-alert/30 bg-alert-dim text-alert",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert an endpoint path into a reasonable default tool name. */
function defaultToolName(endpoint: ParsedEndpoint): string {
  const method = endpoint.method.toLowerCase();
  const parts = endpoint.path
    .replace(/^\//, "")
    .split("/")
    .filter((p) => !p.startsWith("{"))
    .map((p) => p.replace(/-/g, "_"));
  return `${method}_${parts.join("_")}`.slice(0, 64);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MethodBadge({ method }: { method: string }) {
  return (
    <span
      className={cn(
        "rounded-badge px-1.5 py-0.5 font-mono text-[10px] font-medium",
        METHOD_BADGE[method] ??
          "border border-border bg-bg-elevated text-text-muted",
      )}
    >
      {method}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Step components
// ---------------------------------------------------------------------------

interface Step1Props {
  content: string;
  setContent: (v: string) => void;
  format: DocFormat;
  setFormat: (v: DocFormat) => void;
  onParse: () => void;
  isParsing: boolean;
  parseError: string | null;
}

function Step1Upload({
  content,
  setContent,
  format,
  setFormat,
  onParse,
  isParsing,
  parseError,
}: Step1Props) {
  return (
    <div className="space-y-5">
      {/* Informational banner */}
      <div className="flex items-start gap-2.5 rounded-control border border-border bg-bg-elevated p-3">
        <Info size={14} className="mt-0.5 shrink-0 text-text-faint" />
        <p className="text-body-default text-text-muted">
          Paste an OpenAPI (JSON or YAML) or Postman Collection document.
          Endpoints will be parsed and you can select which ones to register as
          platform tools.
        </p>
      </div>

      {/* Format selector */}
      <div>
        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
          Format
        </label>
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value as DocFormat)}
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary focus:border-accent focus:outline-none"
        >
          {FORMAT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Content textarea */}
      <div>
        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
          API Documentation
        </label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder='Paste your OpenAPI spec or Postman collection here...\n\n{\n  "openapi": "3.0.0",\n  "info": { "title": "My API", ... },\n  ...\n}'
          rows={12}
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
        />
        <p className="mt-1 text-[11px] text-text-faint">
          Supports OpenAPI 2.0, 3.0, 3.1 (JSON or YAML) and Postman Collection
          v2.x
        </p>
      </div>

      {/* Parse error */}
      {parseError && (
        <div className="flex items-start gap-2.5 rounded-control border border-alert/30 bg-alert-dim p-3">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-alert" />
          <p className="text-body-default text-alert">{parseError}</p>
        </div>
      )}

      {/* Parse button */}
      <button
        type="button"
        onClick={onParse}
        disabled={content.trim().length === 0 || isParsing}
        className="w-full rounded-control bg-accent py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
      >
        {isParsing ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            Parsing API documentation...
          </span>
        ) : (
          "Parse"
        )}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------

interface Step2Props {
  doc: ParsedAPIDoc;
  selected: Set<number>;
  onToggle: (idx: number) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
}

function Step2Select({
  doc,
  selected,
  onToggle,
  onSelectAll,
  onDeselectAll,
}: Step2Props) {
  return (
    <div className="space-y-4">
      {/* Doc header */}
      <div className="rounded-control border border-border bg-bg-elevated px-4 py-3">
        {doc.title && (
          <p className="text-section-heading text-text-primary">{doc.title}</p>
        )}
        {doc.base_url && (
          <p className="mt-0.5 font-mono text-data-value text-text-faint">
            {doc.base_url}
          </p>
        )}
        <p className="mt-1 text-[11px] text-text-faint">
          Format: {doc.format} · {doc.endpoints.length} endpoint
          {doc.endpoints.length !== 1 ? "s" : ""} discovered
        </p>
      </div>

      {/* Select controls */}
      <div className="flex items-center justify-between">
        <p className="text-body-default text-text-muted">
          <span className="font-medium text-text-primary">{selected.size}</span>{" "}
          endpoint{selected.size !== 1 ? "s" : ""} selected
        </p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onSelectAll}
            className="text-[11px] text-accent hover:underline"
          >
            Select All
          </button>
          <button
            type="button"
            onClick={onDeselectAll}
            className="text-[11px] text-text-muted hover:underline"
          >
            Deselect All
          </button>
        </div>
      </div>

      {/* Endpoint table */}
      <div className="overflow-hidden rounded-card border border-border">
        <table className="w-full">
          <thead className="bg-bg-elevated">
            <tr className="border-b border-border">
              <th className="w-8 px-3.5 py-2.5" />
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Method
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Path
              </th>
              <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                Summary
              </th>
            </tr>
          </thead>
          <tbody>
            {doc.endpoints.map((ep, idx) => (
              <tr
                key={idx}
                onClick={() => onToggle(idx)}
                className={cn(
                  "cursor-pointer border-b border-border-faint transition-colors last:border-0",
                  selected.has(idx)
                    ? "bg-accent-dim hover:bg-accent-dim"
                    : "hover:bg-bg-elevated",
                )}
              >
                <td className="px-3.5 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(idx)}
                    onChange={() => onToggle(idx)}
                    onClick={(e) => e.stopPropagation()}
                    className="accent-accent"
                  />
                </td>
                <td className="px-3.5 py-3">
                  <MethodBadge method={ep.method} />
                </td>
                <td className="px-3.5 py-3 font-mono text-data-value text-text-primary">
                  {ep.path}
                </td>
                <td className="px-3.5 py-3 text-body-default text-text-muted">
                  {ep.summary ?? ep.description ?? (
                    <span className="text-text-faint">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

interface EndpointConfig {
  name: string;
  description: string;
  rate_limit: string;
  plan_required: PlanGate;
  credential_source: CredentialSource;
}

interface Step3Props {
  doc: ParsedAPIDoc;
  selectedIndices: number[];
  configs: Record<number, EndpointConfig>;
  onChange: (
    idx: number,
    field: keyof EndpointConfig,
    value: string | PlanGate | CredentialSource,
  ) => void;
  onRegister: () => void;
  isRegistering: boolean;
  registerError: string | null;
}

function Step3Configure({
  doc,
  selectedIndices,
  configs,
  onChange,
  onRegister,
  isRegistering,
  registerError,
}: Step3Props) {
  return (
    <div className="space-y-5">
      <p className="text-body-default text-text-muted">
        Configure each tool before registering. Name and description are
        required.
      </p>

      {selectedIndices.map((idx) => {
        const ep = doc.endpoints[idx];
        const cfg = configs[idx];
        return (
          <div
            key={idx}
            className="rounded-card border border-border bg-bg-elevated"
          >
            {/* Card header */}
            <div className="flex items-center gap-2.5 border-b border-border px-4 py-2.5">
              <MethodBadge method={ep.method} />
              <span className="font-mono text-data-value text-text-primary">
                {ep.path}
              </span>
            </div>

            {/* Config fields */}
            <div className="space-y-4 p-4">
              {/* Tool name */}
              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Tool Name
                </label>
                <input
                  type="text"
                  value={cfg.name}
                  onChange={(e) => onChange(idx, "name", e.target.value)}
                  maxLength={128}
                  className="w-full rounded-control border border-border bg-bg-surface px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              {/* Description */}
              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Description
                </label>
                <textarea
                  value={cfg.description}
                  onChange={(e) => onChange(idx, "description", e.target.value)}
                  rows={2}
                  maxLength={512}
                  className="w-full rounded-control border border-border bg-bg-surface px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                {/* Rate limit */}
                <div>
                  <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                    Rate Limit / min
                  </label>
                  <input
                    type="number"
                    value={cfg.rate_limit}
                    onChange={(e) =>
                      onChange(idx, "rate_limit", e.target.value)
                    }
                    min={0}
                    placeholder="60"
                    className="w-full rounded-control border border-border bg-bg-surface px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                  />
                </div>

                {/* Plan gate */}
                <div>
                  <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                    Plan Gate
                  </label>
                  <select
                    value={cfg.plan_required ?? ""}
                    onChange={(e) =>
                      onChange(
                        idx,
                        "plan_required",
                        (e.target.value || null) as PlanGate,
                      )
                    }
                    className="w-full rounded-control border border-border bg-bg-surface px-3 py-2 text-body-default text-text-primary focus:border-accent focus:outline-none"
                  >
                    {PLAN_OPTIONS.map((opt) => (
                      <option key={String(opt.value)} value={opt.value ?? ""}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Credential source */}
              <div>
                <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
                  Credential Source
                </label>
                <div className="flex gap-2">
                  {CREDENTIAL_OPTIONS.map((opt) => (
                    <label
                      key={opt.value}
                      className={cn(
                        "flex flex-1 cursor-pointer flex-col rounded-control border p-2.5 transition-colors",
                        cfg.credential_source === opt.value
                          ? "border-accent bg-accent-dim"
                          : "border-border hover:border-accent-ring",
                      )}
                    >
                      <input
                        type="radio"
                        name={`cred-${idx}`}
                        value={opt.value}
                        checked={cfg.credential_source === opt.value}
                        onChange={() =>
                          onChange(idx, "credential_source", opt.value)
                        }
                        className="sr-only"
                      />
                      <span className="text-body-default font-medium text-text-primary">
                        {opt.label}
                      </span>
                      <span className="mt-0.5 text-[11px] text-text-faint">
                        {opt.hint}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        );
      })}

      {/* Register error */}
      {registerError && (
        <div className="flex items-start gap-2.5 rounded-control border border-alert/30 bg-alert-dim p-3">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-alert" />
          <p className="text-body-default text-alert">{registerError}</p>
        </div>
      )}

      {/* Register button */}
      <button
        type="button"
        onClick={onRegister}
        disabled={
          isRegistering ||
          selectedIndices.some((idx) => configs[idx].name.trim().length === 0)
        }
        className="w-full rounded-control bg-accent py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
      >
        {isRegistering ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            Registering tools...
          </span>
        ) : (
          `Register ${selectedIndices.length} Tool${selectedIndices.length !== 1 ? "s" : ""}`
        )}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export interface MCPIntegrationBuilderProps {
  onClose: () => void;
  onRegistered?: () => void;
}

type Step = 1 | 2 | 3;

const STEP_LABELS: Record<Step, string> = {
  1: "Upload API Doc",
  2: "Select Endpoints",
  3: "Configure Tools",
};

export function MCPIntegrationBuilder({
  onClose,
  onRegistered,
}: MCPIntegrationBuilderProps) {
  // ---- Step state ----
  const [step, setStep] = useState<Step>(1);

  // ---- Step 1 state ----
  const [content, setContent] = useState("");
  const [format, setFormat] = useState<DocFormat>("auto");
  const [parsedDoc, setParsedDoc] = useState<ParsedAPIDoc | null>(null);

  // ---- Step 2 state ----
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // ---- Step 3 state ----
  const [configs, setConfigs] = useState<Record<number, EndpointConfig>>({});

  const parseMutation = useParseAPIDoc();
  const registerMutation = useRegisterPlatformTools();

  // ---- Parse handler ----
  const handleParse = useCallback(async () => {
    try {
      const doc = await parseMutation.mutateAsync({ content, format });
      setParsedDoc(doc);
      // Pre-select all endpoints
      setSelected(new Set(doc.endpoints.map((_, i) => i)));
      // Pre-fill config defaults
      const defaultConfigs: Record<number, EndpointConfig> = {};
      doc.endpoints.forEach((ep, idx) => {
        defaultConfigs[idx] = {
          name: defaultToolName(ep),
          description: ep.summary ?? ep.description ?? "",
          rate_limit: "60",
          plan_required: null,
          credential_source: "none",
        };
      });
      setConfigs(defaultConfigs);
      setStep(2);
    } catch {
      // error surfaced via parseMutation.error
    }
  }, [content, format, parseMutation]);

  // ---- Step 2 handlers ----
  const handleToggle = useCallback((idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (!parsedDoc) return;
    setSelected(new Set(parsedDoc.endpoints.map((_, i) => i)));
  }, [parsedDoc]);

  const handleDeselectAll = useCallback(() => {
    setSelected(new Set());
  }, []);

  // ---- Step 3 handlers ----
  const handleConfigChange = useCallback(
    (
      idx: number,
      field: keyof EndpointConfig,
      value: string | PlanGate | CredentialSource,
    ) => {
      setConfigs((prev) => ({
        ...prev,
        [idx]: { ...prev[idx], [field]: value },
      }));
    },
    [],
  );

  const handleRegister = useCallback(async () => {
    if (!parsedDoc) return;
    const selectedIndices = Array.from(selected).sort((a, b) => a - b);
    const registrations: ToolRegistration[] = selectedIndices.map((idx) => {
      const cfg = configs[idx];
      const rawLimit = parseInt(cfg.rate_limit, 10);
      return {
        endpoint_index: idx,
        name: cfg.name.trim(),
        description: cfg.description.trim(),
        rate_limit_per_minute:
          isNaN(rawLimit) || rawLimit <= 0 ? undefined : rawLimit,
        plan_required: cfg.plan_required,
        credential_source: cfg.credential_source,
      };
    });

    try {
      await registerMutation.mutateAsync({
        parsed_doc: parsedDoc,
        registrations,
      });
      onRegistered?.();
      onClose();
    } catch {
      // error surfaced via registerMutation.error
    }
  }, [parsedDoc, selected, configs, registerMutation, onRegistered, onClose]);

  const selectedIndices = Array.from(selected).sort((a, b) => a - b);

  const parseError =
    parseMutation.isError && parseMutation.error instanceof Error
      ? parseMutation.error.message
      : null;

  const registerError =
    registerMutation.isError && registerMutation.error instanceof Error
      ? registerMutation.error.message
      : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-bg-deep/70"
        onClick={onClose}
        role="presentation"
      />

      {/* Modal */}
      <div className="relative flex max-h-[90vh] w-full max-w-[720px] flex-col overflow-hidden rounded-card border border-border bg-bg-surface shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
          <div>
            <h2 className="text-section-heading text-text-primary">
              MCP Integration Builder
            </h2>
            <p className="mt-0.5 text-[11px] text-text-faint">
              {STEP_LABELS[step]} · Step {step} of 3
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-0.5 bg-bg-elevated">
          <div
            className="h-full bg-accent transition-all duration-300"
            style={{ width: `${(step / 3) * 100}%` }}
          />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {step === 1 && (
            <Step1Upload
              content={content}
              setContent={setContent}
              format={format}
              setFormat={setFormat}
              onParse={handleParse}
              isParsing={parseMutation.isPending}
              parseError={parseError}
            />
          )}

          {step === 2 && parsedDoc && (
            <Step2Select
              doc={parsedDoc}
              selected={selected}
              onToggle={handleToggle}
              onSelectAll={handleSelectAll}
              onDeselectAll={handleDeselectAll}
            />
          )}

          {step === 3 && parsedDoc && (
            <Step3Configure
              doc={parsedDoc}
              selectedIndices={selectedIndices}
              configs={configs}
              onChange={handleConfigChange}
              onRegister={handleRegister}
              isRegistering={registerMutation.isPending}
              registerError={registerError}
            />
          )}
        </div>

        {/* Footer — shared navigation (steps 2–3 show Back; step 2 shows Continue) */}
        {step !== 1 && (
          <div className="flex items-center justify-between border-t border-border px-5 py-3">
            <button
              type="button"
              onClick={() => {
                if (step === 2) setStep(1);
                if (step === 3) setStep(2);
              }}
              className="flex items-center gap-1 rounded-control border border-border px-4 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              <ChevronLeft size={14} />
              Back
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-control border border-border px-4 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                Cancel
              </button>

              {step === 2 && (
                <button
                  type="button"
                  onClick={() => setStep(3)}
                  disabled={selected.size === 0}
                  className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
                >
                  Continue ({selected.size})
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
