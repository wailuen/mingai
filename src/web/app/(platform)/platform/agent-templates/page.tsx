"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TemplateList } from "./elements/TemplateList";
import { TemplateStudioPanel } from "./elements/TemplateStudioPanel";
import type { AgentTemplateAdmin } from "@/lib/hooks/useAgentTemplatesAdmin";

type StatusTab = "all" | "published" | "draft" | "deprecated";

const TABS: { value: StatusTab; label: string }[] = [
  { value: "all", label: "All Templates" },
  { value: "published", label: "Published" },
  { value: "draft", label: "Draft" },
  { value: "deprecated", label: "Deprecated" },
];

/**
 * FE-044 / TODO-20: Agent Template Studio (Phase 2 full authoring surface).
 * Platform admin page for managing and authoring agent templates.
 */
export default function AgentTemplatesPage() {
  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  // null = create mode, string = edit mode with template id
  const [panelTemplateId, setPanelTemplateId] = useState<string | null | undefined>(
    undefined,
  );

  const panelOpen = panelTemplateId !== undefined;

  function handleEdit(template: AgentTemplateAdmin) {
    setPanelTemplateId(template.id);
  }

  function handleCreate() {
    setPanelTemplateId(null);
  }

  function handleClosePanel() {
    setPanelTemplateId(undefined);
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">
              Agent Templates
            </h1>
            <p className="mt-1 text-body-default text-text-muted">
              Manage and author agent templates — publish across tenants
            </p>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Template
          </button>
        </div>

        {/* Tab bar */}
        <div className="mb-5 flex border-b border-border">
          {TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setActiveTab(tab.value)}
              className={cn(
                "border-b-2 px-3.5 py-2 text-[12px] font-medium transition-colors",
                activeTab === tab.value
                  ? "border-accent text-text-primary"
                  : "border-transparent text-text-faint hover:text-text-muted",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Template list */}
        <ErrorBoundary>
          <TemplateList statusFilter={activeTab} onEdit={handleEdit} />
        </ErrorBoundary>
      </div>

      {/* Studio panel — rendered outside the scrolling area so it overlays correctly */}
      {panelOpen && (
        <TemplateStudioPanel
          templateId={panelTemplateId ?? null}
          onClose={handleClosePanel}
          onCreated={setPanelTemplateId}
        />
      )}
    </AppShell>
  );
}
