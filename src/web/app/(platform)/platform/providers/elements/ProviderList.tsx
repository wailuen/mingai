"use client";

import { useState, useEffect, useRef } from "react";
import {
  Pencil,
  Trash2,
  Zap,
  Star,
  CheckCircle2,
  AlertCircle,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useLLMProviders,
  useDeleteProvider,
  useTestProvider,
  useSetDefaultProvider,
  type Provider,
  type ProviderStatus,
} from "@/lib/hooks/useLLMProviders";
import { ProviderForm } from "./ProviderForm";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({
  status,
  error,
}: {
  status: ProviderStatus;
  error?: string;
}) {
  if (status === "healthy") {
    return (
      <span className="inline-flex items-center gap-1 rounded-badge bg-accent-dim px-2 py-0.5 font-mono text-[10px] text-accent">
        <CheckCircle2 size={10} />
        healthy
      </span>
    );
  }
  if (status === "error") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-badge bg-alert-dim px-2 py-0.5 font-mono text-[10px] text-alert"
        title={error}
      >
        <AlertCircle size={10} />
        error
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-badge bg-bg-elevated px-2 py-0.5 font-mono text-[10px] text-text-faint">
      <Clock size={10} />
      unchecked
    </span>
  );
}

function ProviderTypeBadge({ type }: { type: string }) {
  return (
    <span className="rounded-badge border border-border px-1.5 py-0.5 font-mono text-[10px] text-text-muted">
      {type}
    </span>
  );
}

interface ToastState {
  id: string;
  message: string;
  variant: "success" | "error";
}

function InlineToast({
  toasts,
  onDismiss,
}: {
  toasts: ToastState[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cn(
            "flex items-center gap-2.5 rounded-card border px-4 py-3 text-[13px]",
            t.variant === "success"
              ? "border-accent-ring bg-bg-surface text-text-primary"
              : "border-alert-ring bg-bg-surface text-text-primary",
          )}
        >
          {t.variant === "success" ? (
            <CheckCircle2 size={14} className="text-accent" />
          ) : (
            <AlertCircle size={14} className="text-alert" />
          )}
          <span>{t.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(t.id)}
            className="ml-1 text-text-faint hover:text-text-muted"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------

interface RowActionsProps {
  provider: Provider;
  onEdit: () => void;
  onToast: (msg: string, variant: "success" | "error") => void;
}

function RowActions({ provider, onEdit, onToast }: RowActionsProps) {
  const deleteMutation = useDeleteProvider();
  const testMutation = useTestProvider();
  const setDefaultMutation = useSetDefaultProvider();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  function handleTest() {
    testMutation.mutate(provider.id, {
      onSuccess: (data) => {
        if (data.success) {
          onToast(`Test passed — ${data.latency_ms}ms`, "success");
        } else {
          onToast(`Test failed: ${data.error ?? "Unknown error"}`, "error");
        }
      },
      onError: (err) => {
        onToast(`Test failed: ${err.message}`, "error");
      },
    });
  }

  function handleSetDefault() {
    setDefaultMutation.mutate(provider.id, {
      onSuccess: () => {
        onToast(`"${provider.display_name}" set as default`, "success");
      },
      onError: (err) => {
        onToast(`Failed to set default: ${err.message}`, "error");
      },
    });
  }

  function handleDelete() {
    if (
      !window.confirm(
        `Delete provider "${provider.display_name}"? This cannot be undone.`,
      )
    ) {
      return;
    }
    deleteMutation.mutate(provider.id, {
      onSuccess: () => onToast("Provider deleted", "success"),
      onError: (err) => onToast(`Delete failed: ${err.message}`, "error"),
    });
  }

  return (
    <div className="flex items-center gap-1.5">
      {/* Edit */}
      <button
        type="button"
        onClick={onEdit}
        className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        title="Edit provider"
      >
        <Pencil size={11} />
        Edit
      </button>

      {/* Test */}
      <button
        type="button"
        onClick={handleTest}
        disabled={testMutation.isPending}
        className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-40"
        title="Test connectivity"
      >
        <Zap size={11} />
        Test
      </button>

      {/* Set Default */}
      <button
        type="button"
        onClick={handleSetDefault}
        disabled={provider.is_default || setDefaultMutation.isPending}
        className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-40"
        title={
          provider.is_default ? "Already default" : "Set as platform default"
        }
      >
        <Star size={11} />
        Default
      </button>

      {/* Delete */}
      <button
        type="button"
        onClick={handleDelete}
        disabled={provider.is_default || deleteMutation.isPending}
        className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim disabled:opacity-40"
        title={
          provider.is_default
            ? "Set another provider as default first"
            : "Delete provider"
        }
      >
        <Trash2 size={11} />
        {deleteMutation.isPending ? "..." : "Delete"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, i) => (
        <tr key={i} className="border-b border-border-faint">
          {Array.from({ length: 6 }).map((__, j) => (
            <td key={j} className="px-3.5 py-3">
              <div className="h-4 w-24 animate-pulse rounded-badge bg-bg-elevated" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ProviderList() {
  const { data, isPending, error } = useLLMProviders();
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [showEditForm, setShowEditForm] = useState(false);
  const [toasts, setToasts] = useState<ToastState[]>([]);

  function addToast(message: string, variant: "success" | "error") {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((prev) => [...prev, { id, message, variant }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }

  function dismissToast(id: string) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  const providers = data?.providers ?? [];

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load providers: {error.message}
      </p>
    );
  }

  return (
    <>
      <div className="rounded-card border border-border bg-bg-surface">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Provider Name
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Type
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Status
                </th>
                <th className="hidden px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint sm:table-cell">
                  Default
                </th>
                <th className="hidden px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint sm:table-cell">
                  Slots Configured
                </th>
                <th className="px-3.5 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {isPending && <SkeletonRows />}

              {!isPending && providers.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-3.5 py-12 text-center text-sm text-text-faint"
                  >
                    No providers configured. Add your first provider to get
                    started.
                  </td>
                </tr>
              )}

              {providers.map((p) => {
                const slotCount = Object.keys(p.models ?? {}).filter(
                  (k) => (p.models ?? {})[k],
                ).length;
                return (
                  <tr
                    key={p.id}
                    className="border-b border-border-faint transition-colors hover:bg-accent-dim"
                  >
                    <td className="px-3.5 py-3">
                      <span className="text-[13px] font-medium text-text-primary">
                        {p.display_name}
                      </span>
                      {p.description && (
                        <p className="mt-0.5 text-[11px] text-text-faint">
                          {p.description}
                        </p>
                      )}
                    </td>
                    <td className="px-3.5 py-3">
                      <ProviderTypeBadge type={p.provider_type} />
                    </td>
                    <td className="px-3.5 py-3">
                      <StatusBadge
                        status={p.provider_status}
                        error={p.health_error}
                      />
                    </td>
                    <td className="hidden px-3.5 py-3 sm:table-cell">
                      {p.is_default ? (
                        <span className="font-mono text-[11px] text-accent">
                          default
                        </span>
                      ) : (
                        <span className="font-mono text-[11px] text-text-faint">
                          —
                        </span>
                      )}
                    </td>
                    <td className="hidden px-3.5 py-3 sm:table-cell">
                      <span className="font-mono text-[12px] text-text-muted">
                        {slotCount} / 6
                      </span>
                    </td>
                    <td className="px-3.5 py-3">
                      <RowActions
                        provider={p}
                        onEdit={() => {
                          setEditingProvider(p);
                          setShowEditForm(true);
                        }}
                        onToast={addToast}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {providers.length > 0 && (
          <div className="border-t border-border px-5 py-2.5">
            <p className="font-mono text-[11px] text-text-faint">
              {providers.length} provider{providers.length !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </div>

      {/* Edit form modal */}
      {showEditForm && editingProvider && (
        <ProviderForm
          provider={editingProvider}
          onClose={() => {
            setShowEditForm(false);
            setEditingProvider(null);
          }}
          onSaved={() => {
            addToast("Provider updated", "success");
            setShowEditForm(false);
            setEditingProvider(null);
          }}
        />
      )}

      <InlineToast toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}
