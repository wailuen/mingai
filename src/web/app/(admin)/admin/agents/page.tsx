"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useAgentTemplates } from "@/lib/hooks/useAgentTemplates";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import { AgentFilterBar } from "./elements/AgentFilterBar";
import { AgentCard, AgentCardSkeleton } from "./elements/AgentCard";
import { TemplatePreviewModal } from "./elements/TemplatePreviewModal";
import { AgentDeployForm } from "./elements/AgentDeployForm";
import { UpgradeNotificationBanner } from "./elements/UpgradeNotificationBanner";

/**
 * FE-035: Agent Library page (Tenant Admin).
 * Browse and deploy agent templates to your workspace.
 */
export default function AgentsPage() {
  const [categoryFilter, setCategoryFilter] = useState("");
  const [previewTemplate, setPreviewTemplate] = useState<AgentTemplate | null>(
    null,
  );
  const [deployTemplate, setDeployTemplate] = useState<AgentTemplate | null>(
    null,
  );

  const { data, isPending, error } = useAgentTemplates(
    categoryFilter || undefined,
  );

  function handleDeploy(template: AgentTemplate) {
    setPreviewTemplate(null);
    setDeployTemplate(template);
  }

  function handleDeployed() {
    setDeployTemplate(null);
  }

  return (
    <AppShell>
      <div className="p-4 sm:p-7">
        {/* Desktop recommended banner for mobile */}
        <div className="mb-4 flex items-center gap-2 rounded-control border border-warn bg-warn-dim px-3 py-2 text-xs text-warn md:hidden">
          <span>
            Desktop recommended for editing. Some features may be limited on
            mobile.
          </span>
        </div>

        {/* Page header */}
        <div className="mb-1">
          <h1 className="text-page-title text-text-primary">Agent Library</h1>
          <p className="mt-1 text-sm text-text-muted">
            Browse and deploy agent templates to your workspace
          </p>
        </div>

        {/* Upgrade banner (future) */}
        <UpgradeNotificationBanner />

        {/* Filter bar */}
        <div className="mb-6 mt-5">
          <AgentFilterBar
            selected={categoryFilter}
            onSelect={setCategoryFilter}
          />
        </div>

        {/* Grid */}
        <ErrorBoundary>
          {error && (
            <p className="text-sm text-alert">
              Failed to load templates: {error.message}
            </p>
          )}

          {isPending && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <AgentCardSkeleton key={i} />
              ))}
            </div>
          )}

          {data && data.items.length === 0 && (
            <p className="py-12 text-center text-sm text-text-faint">
              No agent templates found
              {categoryFilter ? ` in "${categoryFilter}"` : ""}.
            </p>
          )}

          {data && data.items.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {data.items.map((template) => (
                <AgentCard
                  key={template.id}
                  template={template}
                  onPreview={setPreviewTemplate}
                  onDeploy={handleDeploy}
                />
              ))}
            </div>
          )}
        </ErrorBoundary>

        {/* Preview modal */}
        {previewTemplate && (
          <TemplatePreviewModal
            template={previewTemplate}
            onClose={() => setPreviewTemplate(null)}
            onDeploy={handleDeploy}
          />
        )}

        {/* Deploy form */}
        {deployTemplate && (
          <AgentDeployForm
            template={deployTemplate}
            onClose={() => setDeployTemplate(null)}
            onDeployed={handleDeployed}
          />
        )}
      </div>
    </AppShell>
  );
}
