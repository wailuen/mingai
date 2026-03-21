"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

interface Integration {
  id: string;
  name: string;
  source_type: string;
  status: "connected" | "disconnected" | "syncing";
  document_count?: number;
}

interface IntegrationsResponse {
  items: Integration[];
  total: number;
}

export interface KBSelection {
  integrationId: string;
  mode: "grounded" | "extended";
}

interface KBSelectorProps {
  value: KBSelection[];
  onChange: (kbs: KBSelection[]) => void;
}

function useIntegrations() {
  return useQuery({
    queryKey: ["integrations"],
    queryFn: () => apiGet<IntegrationsResponse>("/api/v1/integrations"),
  });
}

function KBSelectorSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5 animate-pulse"
        >
          <div className="h-4 w-4 rounded-badge bg-border" />
          <div className="h-3.5 w-28 rounded-badge bg-border" />
          <div className="ml-auto h-5 w-20 rounded-badge bg-border" />
        </div>
      ))}
    </div>
  );
}

export function KBSelector({ value, onChange }: KBSelectorProps) {
  const { data, isPending, error } = useIntegrations();

  if (isPending) return <KBSelectorSkeleton />;

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load knowledge bases: {error.message}
      </p>
    );
  }

  const integrations = data?.items ?? [];

  if (integrations.length === 0) {
    return (
      <p className="text-body-default text-text-faint">
        No knowledge bases connected. Connect a source in Documents first.
      </p>
    );
  }

  function isSelected(id: string): boolean {
    return value.some((kb) => kb.integrationId === id);
  }

  function getMode(id: string): "grounded" | "extended" {
    const found = value.find((kb) => kb.integrationId === id);
    return found?.mode ?? "grounded";
  }

  function handleToggle(id: string) {
    if (isSelected(id)) {
      onChange(value.filter((kb) => kb.integrationId !== id));
    } else {
      onChange([...value, { integrationId: id, mode: "grounded" }]);
    }
  }

  function handleModeSwitch(id: string, mode: "grounded" | "extended") {
    onChange(
      value.map((kb) => (kb.integrationId === id ? { ...kb, mode } : kb)),
    );
  }

  return (
    <div className="space-y-2">
      {integrations.map((integration) => {
        const selected = isSelected(integration.id);
        const mode = getMode(integration.id);

        return (
          <div
            key={integration.id}
            className={`flex items-center gap-3 rounded-control border px-3 py-2.5 transition-colors ${
              selected
                ? "border-accent-ring bg-accent-dim"
                : "border-border bg-bg-elevated opacity-60"
            }`}
          >
            {/* Checkbox */}
            <input
              type="checkbox"
              checked={selected}
              onChange={() => handleToggle(integration.id)}
              className="h-4 w-4 rounded-badge accent-accent"
            />

            {/* Source name */}
            <span
              className={`text-body-default ${
                selected ? "text-text-primary" : "text-text-faint"
              }`}
            >
              {integration.name}
            </span>

            {/* Document count */}
            {integration.document_count !== undefined && (
              <span className="font-mono text-xs text-text-faint">
                {integration.document_count.toLocaleString()} docs
              </span>
            )}

            {/* Mode toggle (only when selected) */}
            {selected && (
              <div className="ml-auto flex overflow-hidden rounded-control border border-border text-xs">
                <button
                  type="button"
                  onClick={() => handleModeSwitch(integration.id, "grounded")}
                  className={`px-2 py-0.5 font-medium transition-colors ${
                    mode === "grounded"
                      ? "bg-accent text-bg-base"
                      : "bg-bg-elevated text-text-muted hover:text-text-primary"
                  }`}
                >
                  Grounded
                </button>
                <button
                  type="button"
                  onClick={() => handleModeSwitch(integration.id, "extended")}
                  className={`border-l border-border px-2 py-0.5 font-medium transition-colors ${
                    mode === "extended"
                      ? "bg-bg-elevated text-text-primary border-border"
                      : "bg-bg-elevated text-text-muted hover:text-text-primary"
                  }`}
                >
                  Extended
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
