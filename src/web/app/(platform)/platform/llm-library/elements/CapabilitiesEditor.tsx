"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CapabilitiesState {
  eligible_slots: SlotId[];
  supports_function_calling: boolean;
  context_window?: number;
}

type SlotId = "chat" | "intent" | "vision" | "agent";

interface SlotDef {
  id: SlotId;
  label: string;
  description: string;
}

interface CapabilitiesEditorProps {
  value: CapabilitiesState;
  onChange: (caps: CapabilitiesState) => void;
  disabled?: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const DEFAULT_CAPABILITIES: CapabilitiesState = {
  eligible_slots: [],
  supports_function_calling: false,
  context_window: undefined,
};

const SLOTS: SlotDef[] = [
  { id: "chat", label: "Chat", description: "Main RAG response generation" },
  { id: "intent", label: "Intent", description: "Fast query classification" },
  { id: "vision", label: "Vision", description: "Image & document analysis" },
  { id: "agent", label: "Agent", description: "Agentic tool-calling loops" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build the JSON-serialisable capabilities object for the API payload. */
export function buildCapabilitiesPayload(
  caps: CapabilitiesState,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    eligible_slots: caps.eligible_slots,
    supports_vision: caps.eligible_slots.includes("vision"),
    supports_function_calling: caps.supports_function_calling,
  };
  if (caps.context_window !== undefined) {
    payload.context_window = caps.context_window;
  }
  return payload;
}

/** Parse a raw capabilities object (from API) into structured state. */
export function parseCapabilities(
  raw: Record<string, unknown> | null | undefined,
): CapabilitiesState {
  if (!raw) return DEFAULT_CAPABILITIES;
  const slots = Array.isArray(raw.eligible_slots)
    ? (raw.eligible_slots as string[]).filter((s): s is SlotId =>
        ["chat", "intent", "vision", "agent"].includes(s),
      )
    : [];
  return {
    eligible_slots: slots,
    supports_function_calling: !!raw.supports_function_calling,
    context_window:
      typeof raw.context_window === "number" ? raw.context_window : undefined,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CapabilitiesEditor({
  value,
  onChange,
  disabled = false,
}: CapabilitiesEditorProps) {
  const [advancedOpen, setAdvancedOpen] = useState(
    value.context_window !== undefined,
  );

  function toggleSlot(id: SlotId) {
    const next = value.eligible_slots.includes(id)
      ? value.eligible_slots.filter((s) => s !== id)
      : [...value.eligible_slots, id];
    onChange({ ...value, eligible_slots: next });
  }

  function toggleFunctionCalling() {
    onChange({
      ...value,
      supports_function_calling: !value.supports_function_calling,
    });
  }

  function setContextWindow(raw: string) {
    const n = raw === "" ? undefined : parseInt(raw, 10);
    onChange({
      ...value,
      context_window: n !== undefined && !isNaN(n) && n > 0 ? n : undefined,
    });
  }

  return (
    <div className="space-y-3">
      <label className="block text-label-nav uppercase text-text-faint">
        Capabilities
      </label>

      {/* ── Eligible Slots ── */}
      <div>
        <p className="mb-2 text-[11px] text-text-faint">
          Which pipeline slots can this model serve?
        </p>
        <div className="flex flex-wrap gap-2">
          {SLOTS.map((slot) => {
            const selected = value.eligible_slots.includes(slot.id);
            return (
              <button
                key={slot.id}
                type="button"
                role="checkbox"
                aria-checked={selected}
                disabled={disabled}
                onClick={() => toggleSlot(slot.id)}
                title={slot.description}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-body-default font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  selected
                    ? "border-accent bg-accent-dim text-accent"
                    : "border-border bg-bg-elevated text-text-muted hover:border-accent/40 hover:bg-accent-dim/50 hover:text-text-primary",
                  disabled && "cursor-not-allowed opacity-50",
                )}
              >
                {/* Check indicator */}
                <span className="flex h-3.5 w-3.5 items-center justify-center flex-shrink-0">
                  {selected ? (
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      fill="none"
                      aria-hidden
                    >
                      <path
                        d="M1.5 5l2.5 2.5 4.5-4.5"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  ) : (
                    <span className="block h-1.5 w-1.5 rounded-full bg-text-faint" />
                  )}
                </span>
                {slot.label}
              </button>
            );
          })}
        </div>

        {/* Active slot descriptions */}
        {value.eligible_slots.length > 0 && (
          <ul className="mt-2 space-y-0.5">
            {SLOTS.filter((s) => value.eligible_slots.includes(s.id)).map(
              (s) => (
                <li key={s.id} className="text-[11px] text-text-faint">
                  <span className="font-semibold text-text-muted">
                    {s.label}
                  </span>{" "}
                  — {s.description}
                </li>
              ),
            )}
          </ul>
        )}
      </div>

      {/* ── Function Calling ── */}
      <label
        className={cn(
          "flex cursor-pointer items-center gap-2.5 rounded-control px-3 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <input
          type="checkbox"
          checked={value.supports_function_calling}
          onChange={toggleFunctionCalling}
          disabled={disabled}
          className="accent-accent"
        />
        Supports function calling (tool use)
      </label>

      {/* ── Advanced disclosure ── */}
      <div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setAdvancedOpen((o) => !o)}
          className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-text-faint transition-colors hover:text-text-muted"
          aria-expanded={advancedOpen}
        >
          {advancedOpen ? (
            <ChevronDown size={12} />
          ) : (
            <ChevronRight size={12} />
          )}
          Advanced
        </button>

        {advancedOpen && (
          <div className="mt-2 rounded-card border border-border-faint bg-bg-surface p-4 space-y-1.5">
            <label
              htmlFor="cap-context-window"
              className="block text-label-nav uppercase text-text-faint"
            >
              Context Window (tokens)
            </label>
            <input
              id="cap-context-window"
              type="number"
              min={1}
              step={1}
              disabled={disabled}
              value={value.context_window ?? ""}
              onChange={(e) => setContextWindow(e.target.value)}
              placeholder="e.g. 128000"
              className="w-full max-w-[200px] rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            <p className="text-[11px] text-text-faint">
              Maximum input token limit for this model
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
