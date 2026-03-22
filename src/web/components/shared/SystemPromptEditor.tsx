"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

interface SystemPromptEditorProps {
  value: string;
  onChange: (value: string) => void;
  validationError?: string | null;
  disabled?: boolean;
  rows?: number;
}

const WARN_AT = 1600;
const ALERT_AT = 1800;
const MAX_CHARS = 2000;

/**
 * Shared system prompt textarea with:
 * - DM Mono font
 * - {{variable}} token detection/highlighting (character-level overlay not practical
 *   in a plain textarea; detection fires onChange to sync variable schema)
 * - Character counter: green → warn at 1600 → alert at 1800 → blocked at 2000
 * - Validation error banner
 */
export function SystemPromptEditor({
  value,
  onChange,
  validationError,
  disabled = false,
  rows = 10,
}: SystemPromptEditorProps) {
  const id = useId();
  const len = value.length;

  const counterColor =
    len >= MAX_CHARS
      ? "text-alert"
      : len >= ALERT_AT
        ? "text-alert"
        : len >= WARN_AT
          ? "text-warn"
          : "text-text-faint";

  return (
    <div className="space-y-1.5">
      <div className="relative">
        <textarea
          id={id}
          value={value}
          onChange={(e) => {
            if (e.target.value.length <= MAX_CHARS) {
              onChange(e.target.value);
            }
          }}
          disabled={disabled}
          rows={rows}
          placeholder="You are an assistant that helps with {{topic}}. Use {{tone}} tone."
          className={cn(
            "w-full rounded-control border bg-bg-elevated px-3 py-2.5 font-mono text-body-default leading-relaxed text-text-primary placeholder:font-sans placeholder:text-text-faint focus:outline-none",
            len >= MAX_CHARS
              ? "border-alert focus:border-alert"
              : validationError
                ? "border-alert focus:border-alert"
                : "border-border focus:border-accent",
            disabled && "cursor-not-allowed opacity-50",
          )}
          style={{ resize: "vertical" }}
        />
      </div>

      <div className="flex items-center justify-between">
        <p className="text-[11px] text-text-faint">
          Use{" "}
          <code className="rounded-badge bg-accent-dim px-1 font-mono text-[10px] text-accent">
            {"{{variable_name}}"}
          </code>{" "}
          for dynamic placeholders — they auto-sync to the Variable Schema table
          below.
        </p>
        <span className={cn("font-mono text-[11px] tabular-nums", counterColor)}>
          {len} / {MAX_CHARS}
        </span>
      </div>

      {validationError && (
        <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2">
          <p className="text-body-default text-alert">{validationError}</p>
        </div>
      )}
    </div>
  );
}

/**
 * Extract {{variable_name}} tokens from a system prompt string.
 * Returns unique variable names in order of first appearance.
 */
export function extractVariableTokens(prompt: string): string[] {
  const matches = Array.from(prompt.matchAll(/{{([^}]+)}}/g));
  const seen = new Set<string>();
  const result: string[] = [];
  for (const match of matches) {
    const name = match[1].trim();
    if (name && !seen.has(name)) {
      seen.add(name);
      result.push(name);
    }
  }
  return result;
}
