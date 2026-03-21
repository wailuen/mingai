"use client";

import { useState } from "react";
import { Loader2, CheckCircle2, Star, AlertCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useLLMLibraryOptions,
  useUpdateLLMConfig,
  useAvailableProviders,
  useSelectProvider,
  type LLMConfig,
  type LibraryOption,
  type AvailableProvider,
} from "@/lib/hooks/useLLMConfig";

interface LibraryModeTabProps {
  config: LLMConfig;
}

// ---------------------------------------------------------------------------
// Skeleton loaders
// ---------------------------------------------------------------------------

function SkeletonCards() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="rounded-card border border-border bg-bg-surface p-4"
        >
          <div className="h-4 w-40 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="mt-2 h-3 w-64 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

function SkeletonProviderCards() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 2 }).map((_, i) => (
        <div
          key={i}
          className="rounded-control border border-border bg-bg-surface p-3"
        >
          <div className="h-4 w-32 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="mt-1.5 h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Health dot
// ---------------------------------------------------------------------------

function HealthDot({ status }: { status: AvailableProvider["provider_status"] }) {
  const color =
    status === "healthy"
      ? "bg-accent"
      : status === "error"
        ? "bg-alert"
        : "bg-text-faint";
  return <span className={cn("inline-block h-2 w-2 rounded-full", color)} />;
}

// ---------------------------------------------------------------------------
// Anthropic embedding note
// ---------------------------------------------------------------------------

function AnthropicEmbeddingNote() {
  return (
    <div className="mt-3 flex items-start gap-2 rounded-control border border-border bg-bg-elevated px-3 py-2.5">
      <Info size={13} className="mt-0.5 flex-shrink-0 text-text-muted" />
      <p className="text-body-default text-text-muted">
        This provider does not support embeddings. The platform will
        automatically use an Azure OpenAI provider for document indexing.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Platform Provider section (PVDR-016)
// ---------------------------------------------------------------------------

interface PlatformProviderSectionProps {
  selectedProviderId: string | null;
  onSelect: (id: string | null) => void;
}

function PlatformProviderSection({
  selectedProviderId,
  onSelect,
}: PlatformProviderSectionProps) {
  const { data: providers, isPending, error } = useAvailableProviders();

  if (error) {
    return (
      <div className="mb-6">
        <h3 className="mb-2 text-section-heading text-text-primary">
          Platform Provider
        </h3>
        <p className="text-body-default text-alert">{error.message}</p>
      </div>
    );
  }

  const providerList = providers ?? [];
  // Determine if selection is using default: selectedProviderId is null OR
  // matches the default provider and hasn't been explicitly set
  const hasExplicitSelection = selectedProviderId !== null;
  const selectedProvider = providerList.find(
    (p) => p.id === selectedProviderId,
  );
  const showEmbeddingNote =
    selectedProvider?.provider_type === "anthropic" ||
    (selectedProvider !== undefined &&
      !(selectedProvider.slots_available ?? []).includes("doc_embedding"));

  return (
    <div className="mb-6">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-section-heading text-text-primary">
          Platform Provider
        </h3>
        {hasExplicitSelection && (
          <button
            type="button"
            onClick={() => onSelect(null)}
            className="text-[11px] text-text-muted underline underline-offset-2 transition-colors hover:text-text-primary"
          >
            Reset to platform default
          </button>
        )}
      </div>

      <p className="mb-3 text-body-default text-text-muted">
        Choose which LLM provider this workspace uses for AI processing.
      </p>

      {isPending && <SkeletonProviderCards />}

      {!isPending && providerList.length === 0 && (
        <div className="rounded-control border border-border bg-bg-surface px-4 py-3">
          <p className="text-body-default text-text-faint">
            No providers are currently available. Contact the platform
            administrator.
          </p>
        </div>
      )}

      {/* "Using platform default" option */}
      {providerList.length > 0 && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => onSelect(null)}
            className={cn(
              "w-full rounded-card border px-4 py-3 text-left transition-colors",
              !hasExplicitSelection
                ? "border-accent bg-accent-dim"
                : "border-dashed border-border bg-bg-surface hover:border-accent-ring hover:bg-bg-elevated",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="text-body-default font-medium text-text-primary">
                Using platform default
              </span>
              {!hasExplicitSelection && (
                <CheckCircle2 size={13} className="ml-auto text-accent" />
              )}
            </div>
            <p className="mt-0.5 text-[11px] text-text-faint">
              Automatically uses the platform default provider
            </p>
          </button>

          {providerList.map((p) => {
            const isSelected = selectedProviderId === p.id;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => onSelect(p.id)}
                className={cn(
                  "w-full rounded-card border px-4 py-3 text-left transition-colors",
                  isSelected
                    ? "border-accent bg-accent-dim"
                    : "border-border bg-bg-surface hover:border-accent-ring hover:bg-bg-elevated",
                )}
              >
                <div className="flex items-center gap-2">
                  <HealthDot status={p.provider_status} />
                  <span className="text-body-default font-medium text-text-primary">
                    {p.display_name}
                  </span>
                  {p.is_default && (
                    <span className="font-mono text-[10px] text-accent">
                      default
                    </span>
                  )}
                  <span className="ml-auto font-mono text-data-value text-text-faint">
                    {p.provider_type}
                  </span>
                  {isSelected && (
                    <CheckCircle2 size={13} className="text-accent" />
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {showEmbeddingNote && <AnthropicEmbeddingNote />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toast (simple inline)
// ---------------------------------------------------------------------------

function SuccessToast({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2.5 rounded-card border border-accent-ring bg-bg-surface px-4 py-3 shadow-lg">
      <CheckCircle2 size={14} className="text-accent" />
      <span className="text-body-default text-text-primary">{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="ml-1 text-text-faint hover:text-text-muted"
      >
        ×
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function LibraryModeTab({ config }: LibraryModeTabProps) {
  const { data: entries, isPending, error } = useLLMLibraryOptions();
  const updateConfig = useUpdateLLMConfig();
  const selectProvider = useSelectProvider();

  const [selectedId, setSelectedId] = useState<string | null>(
    config.llm_library_id,
  );
  const [showConfirm, setShowConfirm] = useState(false);

  // Provider selection state — initialised to null (platform default)
  // In a real app this would come from a GET endpoint; we start at null.
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(
    null,
  );
  const [providerToast, setProviderToast] = useState<string | null>(null);

  function handleProviderSelect(id: string | null) {
    const previous = selectedProviderId;
    setSelectedProviderId(id);
    selectProvider.mutate(
      { provider_id: id },
      {
        onSuccess: () => {
          setProviderToast(
            id === null
              ? "Reset to platform default"
              : "Provider selection saved",
          );
          setTimeout(() => setProviderToast(null), 4000);
        },
        onError: () => {
          // Roll back on error
          setSelectedProviderId(previous);
        },
      },
    );
  }

  function handleApply() {
    if (!selectedId) return;
    setShowConfirm(true);
  }

  function handleConfirmApply() {
    if (!selectedId) return;
    updateConfig.mutate(
      { model_source: "library", llm_library_id: selectedId },
      { onSuccess: () => setShowConfirm(false) },
    );
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load published models: {error.message}
      </p>
    );
  }

  if (isPending) {
    return <SkeletonCards />;
  }

  if (entries && entries.length === 0) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-8 text-center">
        <p className="text-body-default text-text-faint">
          No published models available in the library yet.
        </p>
      </div>
    );
  }

  const hasChanged = selectedId !== config.llm_library_id;

  return (
    <div>
      {/* PVDR-016: Platform Provider section — ABOVE library picker */}
      <PlatformProviderSection
        selectedProviderId={selectedProviderId}
        onSelect={handleProviderSelect}
      />

      {selectProvider.error && (
        <div className="mb-4 flex items-center gap-1.5 text-body-default text-alert">
          <AlertCircle size={12} />
          {selectProvider.error.message}
        </div>
      )}

      {/* Library model picker */}
      <div className="mb-1 border-t border-border pt-5">
        <p className="mb-4 text-body-default text-text-muted">
          Select a model from the platform library to use for all AI
          conversations in your workspace.
        </p>
      </div>

      <div className="space-y-3">
        {entries?.map((entry: LibraryOption) => {
          const isSelected = selectedId === entry.id;
          return (
            <button
              key={entry.id}
              type="button"
              onClick={() => setSelectedId(entry.id)}
              className={cn(
                "w-full rounded-card border p-4 text-left transition-colors",
                isSelected
                  ? "border-accent bg-accent-dim"
                  : "border-border bg-bg-surface hover:border-accent-ring hover:bg-bg-elevated",
              )}
            >
              <div className="flex items-center gap-2">
                <span className="text-body-default font-medium text-text-primary">
                  {entry.display_name}
                </span>
                {entry.is_recommended && (
                  <Star size={12} className="fill-accent text-accent" />
                )}
                <span className="ml-auto font-mono text-data-value text-text-faint">
                  {entry.provider}
                </span>
              </div>
              <p className="mt-1.5 text-body-default text-text-muted">
                {entry.model_name}
              </p>
              <div className="mt-2 flex items-center gap-3 font-mono text-data-value text-text-faint">
                <span>
                  In: $
                  {entry.pricing_per_1k_tokens_in != null
                    ? entry.pricing_per_1k_tokens_in.toFixed(6)
                    : "—"}
                  /1K
                </span>
                <span>
                  Out: $
                  {entry.pricing_per_1k_tokens_out != null
                    ? entry.pricing_per_1k_tokens_out.toFixed(6)
                    : "—"}
                  /1K
                </span>
                <span className="capitalize">{entry.plan_tier} tier</span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Apply button */}
      <div className="mt-5 flex items-center gap-3">
        <button
          type="button"
          onClick={handleApply}
          disabled={!hasChanged || !selectedId || updateConfig.isPending}
          className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {updateConfig.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <CheckCircle2 size={14} />
          )}
          Apply Profile
        </button>
        {config.llm_library_id && !hasChanged && (
          <span className="text-body-default text-accent">Currently active</span>
        )}
      </div>

      {updateConfig.error && (
        <p className="mt-3 text-body-default text-alert">{updateConfig.error.message}</p>
      )}

      {/* Confirmation dialog */}
      {showConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowConfirm(false);
          }}
        >
          <div className="mx-4 w-full max-w-md rounded-card border border-border bg-bg-surface p-6">
            <h3 className="text-section-heading text-text-primary">
              Change LLM Profile
            </h3>
            <p className="mt-2 text-body-default text-text-muted">
              Changing LLM profile will affect all future conversations.
              Existing conversation history will not be affected.
            </p>
            <div className="mt-5 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowConfirm(false)}
                className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmApply}
                disabled={updateConfig.isPending}
                className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {updateConfig.isPending && (
                  <Loader2 size={14} className="animate-spin" />
                )}
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Provider selection toast */}
      {providerToast && (
        <SuccessToast
          message={providerToast}
          onDismiss={() => setProviderToast(null)}
        />
      )}
    </div>
  );
}
