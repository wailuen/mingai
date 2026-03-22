"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { GuardrailRule } from "@/lib/hooks/useAgentTemplatesAdmin";

interface GuardrailsEditorProps {
  rules: GuardrailRule[];
  onChange: (rules: GuardrailRule[]) => void;
  confidenceThreshold: number;
  onConfidenceChange: (value: number) => void;
  citationMode: "inline" | "footnote" | "none";
  onCitationModeChange: (value: "inline" | "footnote" | "none") => void;
  maxResponseLength: number | null;
  onMaxResponseLengthChange: (value: number | null) => void;
  piiMaskingEnabled: boolean;
  onPiiMaskingChange: (value: boolean) => void;
}

function makeEmptyRule(): GuardrailRule {
  return {
    name: "",
    rule_type: "keyword_block",
    pattern: "",
    action: "block",
    violation_action: "block",
    user_message: "",
    reason: "",
  };
}

const RULE_TYPE_OPTIONS = [
  { value: "keyword_block", label: "Keyword Block" },
  { value: "regex_match", label: "Regex Match" },
  { value: "content_filter", label: "Content Filter" },
] as const;

const VIOLATION_ACTION_OPTIONS = [
  { value: "block", label: "Block" },
  { value: "redact", label: "Redact" },
  { value: "warn", label: "Warn" },
] as const;

/**
 * Shared guardrails editor used in PA template studio and TA custom agent studio.
 */
export function GuardrailsEditor({
  rules,
  onChange,
  confidenceThreshold,
  onConfidenceChange,
  citationMode,
  onCitationModeChange,
  maxResponseLength,
  onMaxResponseLengthChange,
  piiMaskingEnabled,
  onPiiMaskingChange,
}: GuardrailsEditorProps) {
  const [regexErrors, setRegexErrors] = useState<Record<number, string>>({});

  function validateRegex(index: number, pattern: string) {
    if (rules[index]?.rule_type !== "regex_match") {
      setRegexErrors((prev) => {
        const next = { ...prev };
        delete next[index];
        return next;
      });
      return;
    }
    try {
      new RegExp(pattern);
      setRegexErrors((prev) => {
        const next = { ...prev };
        delete next[index];
        return next;
      });
    } catch {
      setRegexErrors((prev) => ({
        ...prev,
        [index]: "Invalid regular expression",
      }));
    }
  }

  function handleAdd() {
    onChange([...rules, makeEmptyRule()]);
  }

  function handleRemove(index: number) {
    onChange(rules.filter((_, i) => i !== index));
    setRegexErrors((prev) => {
      const next: Record<number, string> = {};
      Object.entries(prev).forEach(([k, v]) => {
        const ki = parseInt(k, 10);
        if (ki < index) next[ki] = v;
        else if (ki > index) next[ki - 1] = v;
      });
      return next;
    });
  }

  function handleUpdate<K extends keyof GuardrailRule>(
    index: number,
    field: K,
    value: GuardrailRule[K],
  ) {
    const updated = rules.map((r, i) =>
      i === index ? { ...r, [field]: value } : r,
    );
    onChange(updated);
    if (field === "pattern") {
      validateRegex(index, value as string);
    }
  }

  return (
    <div className="space-y-4">
      {/* Rule cards */}
      {rules.map((rule, i) => (
        <div
          key={i}
          className="rounded-card border border-border bg-bg-elevated p-4"
        >
          <div className="mb-3 flex items-center justify-between">
            <input
              type="text"
              value={rule.name ?? ""}
              onChange={(e) => handleUpdate(i, "name", e.target.value)}
              placeholder="Rule name"
              className="flex-1 rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
            <button
              type="button"
              onClick={() => handleRemove(i)}
              title="Remove rule"
              className="ml-2 flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
            >
              <Trash2 size={13} />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {/* Rule type */}
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                Rule Type
              </label>
              <select
                value={rule.rule_type ?? "keyword_block"}
                onChange={(e) =>
                  handleUpdate(
                    i,
                    "rule_type",
                    e.target.value as GuardrailRule["rule_type"],
                  )
                }
                className="w-full rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary focus:border-accent focus:outline-none"
              >
                {RULE_TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Violation action */}
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                Violation Action
              </label>
              <div className="flex gap-3">
                {VIOLATION_ACTION_OPTIONS.map((opt) => (
                  <label
                    key={opt.value}
                    className="flex cursor-pointer items-center gap-1.5 text-body-default text-text-muted"
                  >
                    <input
                      type="radio"
                      name={`violation-action-${i}`}
                      value={opt.value}
                      checked={
                        (rule.violation_action ?? rule.action) === opt.value
                      }
                      onChange={() => {
                        handleUpdate(i, "violation_action", opt.value);
                        handleUpdate(i, "action", opt.value as GuardrailRule["action"]);
                      }}
                      className="accent-accent"
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
            </div>
          </div>

          {/* Pattern */}
          <div className="mt-3">
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Pattern
            </label>
            <textarea
              value={rule.pattern}
              onChange={(e) => handleUpdate(i, "pattern", e.target.value)}
              onBlur={() => validateRegex(i, rule.pattern)}
              placeholder={
                rule.rule_type === "regex_match"
                  ? "^(?:credit|debit)\\s*card"
                  : "forbidden keyword or phrase"
              }
              rows={2}
              className={cn(
                "w-full rounded-control border bg-bg-base px-2 py-1.5 font-mono text-body-default text-text-primary placeholder:font-sans placeholder:text-text-faint focus:outline-none",
                regexErrors[i]
                  ? "border-alert focus:border-alert"
                  : "border-border focus:border-accent",
              )}
            />
            {regexErrors[i] && (
              <p className="mt-0.5 text-[11px] text-alert">{regexErrors[i]}</p>
            )}
          </div>

          {/* User message */}
          <div className="mt-3">
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              User Message (shown when triggered)
            </label>
            <input
              type="text"
              value={rule.user_message ?? ""}
              onChange={(e) => handleUpdate(i, "user_message", e.target.value)}
              placeholder="I can't help with that request."
              className="w-full rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
          </div>
        </div>
      ))}

      <button
        type="button"
        onClick={handleAdd}
        className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
      >
        <Plus size={13} />
        Add Rule
      </button>

      {/* Global guardrail settings */}
      <div className="mt-4 grid grid-cols-1 gap-4 rounded-card border border-border bg-bg-elevated p-4 sm:grid-cols-2">
        {/* Confidence threshold */}
        <div>
          <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
            Confidence Threshold
          </label>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={confidenceThreshold}
              onChange={(e) => onConfidenceChange(parseFloat(e.target.value))}
              className="flex-1 accent-accent"
            />
            <span className="w-10 text-right font-mono text-data-value text-text-primary">
              {confidenceThreshold.toFixed(2)}
            </span>
          </div>
        </div>

        {/* Citation mode */}
        <div>
          <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
            Citation Mode
          </label>
          <select
            value={citationMode}
            onChange={(e) =>
              onCitationModeChange(
                e.target.value as "inline" | "footnote" | "none",
              )
            }
            className="w-full rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary focus:border-accent focus:outline-none"
          >
            <option value="inline">Inline</option>
            <option value="footnote">Footnote</option>
            <option value="none">None</option>
          </select>
        </div>

        {/* Max response length */}
        <div>
          <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
            Max Response Length (tokens)
          </label>
          <input
            type="number"
            value={maxResponseLength ?? ""}
            onChange={(e) =>
              onMaxResponseLengthChange(
                e.target.value ? parseInt(e.target.value, 10) : null,
              )
            }
            min={100}
            max={8000}
            step={100}
            placeholder="No limit"
            className="w-full rounded-control border border-border bg-bg-base px-2 py-1.5 font-mono text-body-default text-text-primary placeholder:font-sans placeholder:text-text-faint focus:border-accent focus:outline-none"
          />
        </div>

        {/* PII masking */}
        <div className="flex items-center gap-3">
          <label className="text-body-default text-text-muted">
            PII Masking
          </label>
          <button
            type="button"
            role="switch"
            aria-checked={piiMaskingEnabled}
            onClick={() => onPiiMaskingChange(!piiMaskingEnabled)}
            className={cn(
              "relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
              piiMaskingEnabled ? "bg-accent" : "bg-bg-base",
            )}
          >
            <span
              className={cn(
                "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition-transform",
                piiMaskingEnabled ? "translate-x-4" : "translate-x-0",
              )}
            />
          </button>
          <span className="text-body-default text-text-faint">
            {piiMaskingEnabled ? "Enabled" : "Disabled"}
          </span>
        </div>
      </div>
    </div>
  );
}
