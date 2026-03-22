"use client";

import { useState, useRef, useEffect } from "react";
import { Search, CheckCircle2, AlertCircle, HelpCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useAvailableModels,
  type ProfileSlot,
  type AvailableModel,
} from "@/lib/hooks/usePlatformLLMProfiles";
import Link from "next/link";

interface SlotSelectorProps {
  slot: ProfileSlot;
  currentEntryId: string | null;
  onSelect: (model: AvailableModel) => void;
  onCancel: () => void;
}

function HealthDot({ status }: { status: AvailableModel["health_status"] }) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 flex-shrink-0 rounded-full",
        status === "healthy" && "bg-accent",
        status === "unknown" && "bg-warn",
        status === "degraded" && "bg-alert",
      )}
    />
  );
}

function formatTestAge(testPassedAt: string | null): string {
  if (!testPassedAt) return "Not tested";
  const diff = Date.now() - new Date(testPassedAt).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `Tested ${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `Tested ${hrs}h ago`;
  return `Tested ${Math.floor(hrs / 24)}d ago`;
}

export function SlotSelector({
  slot,
  currentEntryId,
  onSelect,
  onCancel,
}: SlotSelectorProps) {
  const [search, setSearch] = useState("");
  const [pendingModel, setPendingModel] = useState<AvailableModel | null>(null);
  const { data: models, isPending, error } = useAvailableModels(slot);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const filtered = (models ?? []).filter((m) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      m.model_name.toLowerCase().includes(q) ||
      m.provider.toLowerCase().includes(q) ||
      m.display_name.toLowerCase().includes(q)
    );
  });

  function handleConfirm() {
    if (pendingModel) {
      onSelect(pendingModel);
    }
  }

  return (
    <div className="w-80 rounded-card border border-border bg-bg-surface shadow-md">
      {/* Search */}
      <div className="border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <Search size={13} className="flex-shrink-0 text-text-faint" />
          <input
            ref={inputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search model or provider..."
            className="flex-1 bg-transparent text-body-default text-text-primary outline-none placeholder:text-text-faint"
          />
        </div>
      </div>

      {/* Model list */}
      <div className="max-h-64 overflow-y-auto">
        {isPending && (
          <div className="py-8 text-center text-body-default text-text-faint">
            Loading models...
          </div>
        )}

        {error && (
          <div className="py-8 text-center text-body-default text-alert">
            Failed to load models.
          </div>
        )}

        {!isPending && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <p className="text-body-default text-text-faint">
              No eligible models for this slot.
            </p>
            <Link
              href="/platform/llm-library"
              className="text-[11px] text-accent hover:underline"
            >
              Add entries in LLM Library
            </Link>
          </div>
        )}

        {filtered.map((model) => {
          const isSelected =
            pendingModel?.library_entry_id === model.library_entry_id;
          const isCurrent = model.library_entry_id === currentEntryId;
          const notTested = model.test_passed_at === null;

          return (
            <button
              key={model.library_entry_id}
              type="button"
              disabled={model.is_deprecated}
              onClick={() => setPendingModel(isSelected ? null : model)}
              className={cn(
                "flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors",
                isSelected && "bg-accent-dim",
                !isSelected && !model.is_deprecated && "hover:bg-bg-elevated",
                model.is_deprecated && "cursor-not-allowed opacity-50",
              )}
            >
              <HealthDot status={model.health_status} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="font-mono text-data-value text-text-primary truncate">
                    {model.model_name}
                  </span>
                  {model.is_deprecated && (
                    <span className="rounded-badge bg-alert-dim px-1.5 py-0.5 text-[10px] text-alert">
                      Deprecated
                    </span>
                  )}
                  {isCurrent && (
                    <span className="rounded-badge bg-accent-dim px-1.5 py-0.5 text-[10px] text-accent">
                      Current
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-2">
                  <span className="rounded-badge bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-muted">
                    {model.provider}
                  </span>
                  <span
                    className={cn(
                      "text-[11px]",
                      notTested ? "text-alert" : "text-text-faint",
                    )}
                  >
                    {formatTestAge(model.test_passed_at)}
                  </span>
                </div>
              </div>
              {isSelected && (
                <CheckCircle2 size={14} className="flex-shrink-0 text-accent" />
              )}
            </button>
          );
        })}
      </div>

      {/* Footer actions */}
      <div className="flex items-center justify-end gap-2 border-t border-border px-3 py-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-control border border-border px-3 py-1 text-[11px] text-text-muted hover:bg-bg-elevated"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={!pendingModel}
          onClick={handleConfirm}
          className="rounded-control bg-accent px-3 py-1 text-[11px] font-semibold text-bg-base disabled:opacity-40"
        >
          Assign
        </button>
      </div>
    </div>
  );
}
