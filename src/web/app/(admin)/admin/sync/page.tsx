"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SourceHealthCard } from "./elements/SourceHealthCard";
import { SyncJobHistory } from "./elements/SyncJobHistory";
import { SyncFailureList } from "./elements/SyncFailureList";
import { useIntegrations } from "@/lib/hooks/useSyncHealth";
import { Loader2 } from "lucide-react";

/**
 * FE-034: Sync Health dashboard (Tenant Admin).
 * Orchestrator only -- business logic lives in elements/.
 * Shows document source integrations with sync status and job history.
 */
export default function SyncHealthPage() {
  const { data, isPending, error } = useIntegrations();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const integrations = data?.items ?? [];

  // Auto-select the first integration when data loads
  const effectiveSelectedId =
    selectedId ?? (integrations.length > 0 ? integrations[0].id : null);

  return (
    <AppShell>
      <div className="space-y-6 p-4 sm:p-7">
        {/* Page header */}
        <div>
          <h1 className="text-page-title text-text-primary">Sync Health</h1>
          <p className="mt-1 text-sm text-text-muted">
            Document source sync status and health
          </p>
        </div>

        {/* Source cards */}
        <ErrorBoundary>
          {isPending && (
            <div className="flex items-center gap-2 text-sm text-text-muted">
              <Loader2 size={14} className="animate-spin" />
              Loading integrations...
            </div>
          )}

          {error && (
            <p className="text-sm text-alert">
              Failed to load integrations: {error.message}
            </p>
          )}

          {!isPending && !error && integrations.length === 0 && (
            <div className="rounded-card border border-border-faint bg-bg-surface p-8 text-center">
              <p className="text-sm text-text-muted">
                No document sources connected. Connect a SharePoint library to
                get started.
              </p>
            </div>
          )}

          {integrations.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {integrations.map((integration) => (
                <SourceHealthCard
                  key={integration.id}
                  integration={integration}
                  isSelected={effectiveSelectedId === integration.id}
                  onSelect={setSelectedId}
                />
              ))}
            </div>
          )}
        </ErrorBoundary>

        {/* Sync Job History */}
        <ErrorBoundary>
          <SyncJobHistory integrationId={effectiveSelectedId} />
        </ErrorBoundary>

        {/* FE-031: Sync Failure List */}
        <ErrorBoundary>
          <SyncFailureList integrationId={effectiveSelectedId ?? undefined} />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
