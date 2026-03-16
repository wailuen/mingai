"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { FileText } from "lucide-react";
import { Skeleton } from "@/components/shared/LoadingState";
import { cn } from "@/lib/utils";
import {
  SourceStatusCard,
  type Integration,
} from "./elements/SourceStatusCard";
import { SharePointWizard } from "./elements/SharePointWizard";
import { GoogleDriveWizard } from "./elements/GoogleDriveWizard";
import { GoogleDriveConnectionList } from "./elements/GoogleDriveConnectionList";
import { AccessControlPanel } from "./elements/AccessControlPanel";

type DocTab = "sharepoint" | "google-drive" | "access-control";

/**
 * FE-029 + FE-030: Document store list with SharePoint and Google Drive tabs.
 * Orchestrator only -- business logic in elements/.
 */
export default function KnowledgeBasePage() {
  const [activeTab, setActiveTab] = useState<DocTab>("sharepoint");
  const [showSharePointWizard, setShowSharePointWizard] = useState(false);
  const [showGoogleDriveWizard, setShowGoogleDriveWizard] = useState(false);
  const [selectedKbId, setSelectedKbId] = useState<string | null>(null);

  const { data: integrations = [], isLoading } = useQuery<Integration[]>({
    queryKey: ["integrations"],
    queryFn: () => apiGet<Integration[]>("/api/v1/integrations"),
  });

  const sharepointIntegrations = integrations.filter(
    (i) => i.type === "sharepoint",
  );

  function handleConnectSource() {
    if (activeTab === "google-drive") {
      setShowGoogleDriveWizard(true);
    } else {
      setShowSharePointWizard(true);
    }
  }

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
            onClick={handleConnectSource}
            className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            Connect Source
          </button>
        </div>

        {/* Tab navigation */}
        <div className="mb-5 flex items-center border-b border-border">
          <button
            type="button"
            onClick={() => setActiveTab("sharepoint")}
            className={cn(
              "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
              activeTab === "sharepoint"
                ? "border-b-accent text-text-primary"
                : "border-b-transparent text-text-faint hover:text-accent",
            )}
          >
            SharePoint
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("google-drive")}
            className={cn(
              "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
              activeTab === "google-drive"
                ? "border-b-accent text-text-primary"
                : "border-b-transparent text-text-faint hover:text-accent",
            )}
          >
            Google Drive
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("access-control")}
            className={cn(
              "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
              activeTab === "access-control"
                ? "border-b-accent text-text-primary"
                : "border-b-transparent text-text-faint hover:text-accent",
            )}
          >
            Access Control
          </button>
        </div>

        {/* SharePoint tab */}
        {activeTab === "sharepoint" && (
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
            ) : sharepointIntegrations.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-border py-16">
                <FileText size={32} className="mb-3 text-text-faint" />
                <p className="text-sm text-text-muted">
                  No SharePoint sources connected
                </p>
                <button
                  onClick={() => setShowSharePointWizard(true)}
                  className="mt-3 text-sm text-accent transition-colors hover:underline"
                >
                  Connect your first source
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {sharepointIntegrations.map((integration) => (
                  <SourceStatusCard
                    key={integration.id}
                    integration={integration}
                  />
                ))}
              </div>
            )}
          </ErrorBoundary>
        )}

        {/* Google Drive tab */}
        {activeTab === "google-drive" && (
          <ErrorBoundary>
            <GoogleDriveConnectionList />
          </ErrorBoundary>
        )}

        {/* Access Control tab */}
        {activeTab === "access-control" && (
          <ErrorBoundary>
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 2 }).map((_, i) => (
                  <div
                    key={i}
                    className="rounded-card border border-border bg-bg-surface px-5 py-4"
                  >
                    <Skeleton className="h-4 w-40" />
                  </div>
                ))}
              </div>
            ) : integrations.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-border py-16">
                <FileText size={32} className="mb-3 text-text-faint" />
                <p className="text-sm text-text-muted">
                  No knowledge bases available. Connect a source first.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* KB selector */}
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-text-faint">
                    Select Knowledge Base
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {integrations.map((integration) => {
                      const label =
                        integration.type === "sharepoint"
                          ? "SharePoint"
                          : "Google Drive";
                      const isSelected = selectedKbId === integration.id;
                      return (
                        <button
                          key={integration.id}
                          type="button"
                          onClick={() => setSelectedKbId(integration.id)}
                          className={`rounded-control border px-3 py-2 text-left transition-colors ${
                            isSelected
                              ? "border-accent bg-accent-dim"
                              : "border-border bg-bg-elevated hover:border-accent-ring"
                          }`}
                        >
                          <span
                            className={`text-sm font-medium ${isSelected ? "text-text-primary" : "text-text-muted"}`}
                          >
                            {label}
                          </span>
                          <span className="ml-2 font-mono text-xs text-text-faint">
                            {integration.id.slice(0, 8)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Access control panel */}
                {selectedKbId ? (
                  <AccessControlPanel kbId={selectedKbId} />
                ) : (
                  <div className="rounded-card border border-dashed border-border py-10 text-center">
                    <p className="text-sm text-text-muted">
                      Select a knowledge base to configure access control.
                    </p>
                  </div>
                )}
              </div>
            )}
          </ErrorBoundary>
        )}

        {showSharePointWizard && (
          <SharePointWizard onClose={() => setShowSharePointWizard(false)} />
        )}

        {showGoogleDriveWizard && (
          <GoogleDriveWizard onClose={() => setShowGoogleDriveWizard(false)} />
        )}
      </div>
    </AppShell>
  );
}
