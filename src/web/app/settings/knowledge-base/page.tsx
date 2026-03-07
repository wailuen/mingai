"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { FileText } from "lucide-react";
import { Skeleton } from "@/components/shared/LoadingState";
import {
  SourceStatusCard,
  type Integration,
} from "./elements/SourceStatusCard";
import { SharePointWizard } from "./elements/SharePointWizard";

/**
 * FE-029: Document store list + SharePoint connection wizard.
 * Orchestrator only -- business logic in elements/.
 * Shows connected integrations with status cards.
 */
export default function KnowledgeBasePage() {
  const [showWizard, setShowWizard] = useState(false);

  const { data: integrations = [], isLoading } = useQuery<Integration[]>({
    queryKey: ["integrations"],
    queryFn: () => apiGet<Integration[]>("/api/v1/integrations"),
  });

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText size={20} className="text-text-faint" />
            <h1 className="text-page-title text-text-primary">
              Document Stores
            </h1>
          </div>
          <button
            onClick={() => setShowWizard(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            Connect Source
          </button>
        </div>

        <ErrorBoundary>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <div
                  key={i}
                  className="rounded-card border border-border bg-bg-surface px-5 py-4"
                >
                  <div className="flex items-center gap-3">
                    <Skeleton className="h-5 w-5 rounded-full" />
                    <div className="flex-1">
                      <Skeleton className="mb-2 h-4 w-32" />
                      <Skeleton className="h-3 w-48" />
                    </div>
                    <Skeleton className="h-6 w-20" />
                  </div>
                </div>
              ))}
            </div>
          ) : integrations.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-border py-16">
              <FileText size={32} className="mb-3 text-text-faint" />
              <p className="text-sm text-text-muted">
                No document sources connected
              </p>
              <button
                onClick={() => setShowWizard(true)}
                className="mt-3 text-sm text-accent transition-colors hover:underline"
              >
                Connect your first source
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {integrations.map((integration) => (
                <SourceStatusCard
                  key={integration.id}
                  integration={integration}
                />
              ))}
            </div>
          )}
        </ErrorBoundary>

        {showWizard && (
          <SharePointWizard onClose={() => setShowWizard(false)} />
        )}
      </div>
    </AppShell>
  );
}
