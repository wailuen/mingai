"use client";

import { cn } from "@/lib/utils";
import type { ProviderType } from "@/lib/hooks/useLLMProviders";

// ---------------------------------------------------------------------------
// Slot definitions
// ---------------------------------------------------------------------------

export const SLOTS = [
  {
    key: "primary",
    label: "Primary",
    description: "Main chat completions model",
  },
  {
    key: "intent",
    label: "Intent",
    description: "Intent classification and routing",
  },
  {
    key: "vision",
    label: "Vision",
    description: "Multimodal / image understanding",
  },
  {
    key: "doc_embedding",
    label: "Doc Embedding",
    description: "Document indexing embeddings",
  },
  {
    key: "kb_embedding",
    label: "KB Embedding",
    description: "Knowledge base retrieval embeddings",
  },
  {
    key: "intent_fallback",
    label: "Intent Fallback",
    description: "Fallback model when intent model unavailable",
  },
] as const;

export type SlotKey = (typeof SLOTS)[number]["key"];

// Slot support matrix — true = supported, false = not supported
const SLOT_SUPPORT: Record<SlotKey, Partial<Record<ProviderType, boolean>>> = {
  primary: {
    azure_openai: true,
    openai: true,
    anthropic: true,
    deepseek: true,
    dashscope: true,
    doubao: true,
    gemini: true,
  },
  intent: {
    azure_openai: true,
    openai: true,
    anthropic: true,
    deepseek: true,
    dashscope: true,
    doubao: true,
    gemini: true,
  },
  vision: {
    azure_openai: true,
    openai: false,
    anthropic: false,
    deepseek: false,
    dashscope: false,
    doubao: false,
    gemini: true,
  },
  doc_embedding: {
    azure_openai: true,
    openai: true,
    anthropic: false,
    deepseek: false,
    dashscope: true,
    doubao: true,
    gemini: true,
  },
  kb_embedding: {
    azure_openai: true,
    openai: true,
    anthropic: false,
    deepseek: false,
    dashscope: true,
    doubao: true,
    gemini: false,
  },
  intent_fallback: {
    azure_openai: true,
    openai: true,
    anthropic: false,
    deepseek: false,
    dashscope: false,
    doubao: false,
    gemini: false,
  },
};

export function isSlotSupported(
  slot: SlotKey,
  providerType: ProviderType,
): boolean {
  return SLOT_SUPPORT[slot]?.[providerType] ?? false;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface SlotMappingGridProps {
  providerType: ProviderType;
  models: Record<string, string>;
  onChange: (models: Record<string, string>) => void;
}

/**
 * PVDR-014 Step 2: Slot-to-deployment mapping grid.
 * Renders one row per slot. Unsupported slots are greyed out.
 */
export function SlotMappingGrid({
  providerType,
  models,
  onChange,
}: SlotMappingGridProps) {
  function handleSlotChange(slot: SlotKey, value: string) {
    onChange({ ...models, [slot]: value });
  }

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-text-muted">
        Enter the deployment or model name for each slot. Leave blank to skip.
        Greyed-out slots are not supported by this provider.
      </p>

      {SLOTS.map(({ key, label, description }) => {
        const supported = isSlotSupported(key, providerType);
        return (
          <div
            key={key}
            className={cn(
              "flex items-center gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5",
              !supported && "opacity-40",
            )}
            title={!supported ? `Not supported by ${providerType}` : undefined}
          >
            <div className="w-36 flex-shrink-0">
              <p className="text-[13px] font-medium text-text-primary">
                {label}
              </p>
              <p className="text-[11px] text-text-faint">{description}</p>
            </div>
            <input
              type="text"
              value={models[key] ?? ""}
              onChange={(e) => handleSlotChange(key, e.target.value)}
              disabled={!supported}
              placeholder={
                supported ? `e.g. ${key}-deployment` : "Not supported"
              }
              className={cn(
                "flex-1 rounded-control border border-border bg-bg-base px-2.5 py-1.5 font-mono text-[12px] text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none",
                !supported && "cursor-not-allowed",
              )}
            />
          </div>
        );
      })}
    </div>
  );
}
