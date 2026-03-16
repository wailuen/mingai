"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TemplateList } from "./elements/TemplateList";
import { TemplateAuthoringForm } from "./elements/TemplateAuthoringForm";
import type { AgentTemplateAdmin } from "@/lib/hooks/useAgentTemplatesAdmin";

type StatusTab = "all" | "published" | "draft" | "deprecated";

const TABS: { value: StatusTab; label: string }[] = [
  { value: "all", label: "All Templates" },
  { value: "published", label: "Published" },
  { value: "draft", label: "Draft" },
  { value: "deprecated", label: "Deprecated" },
];

/**
 * FE-044: Agent Template Library Management.
 * Platform admin page for managing agent templates across tenants.
 */
export default function AgentTemplatesPage() {
  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  const [editingTemplate, setEditingTemplate] =
    useState<AgentTemplateAdmin | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  function handleEdit(template: AgentTemplateAdmin) {
    setEditingTemplate(template);
    setShowCreateForm(true);
  }

  function handleCloseForm() {
    setShowCreateForm(false);
    setEditingTemplate(null);
  }

  function handleCreate() {
    setEditingTemplate(null);
    setShowCreateForm(true);
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
            <p className="mt-1 text-sm text-text-muted">
              Manage agent templates and publish across tenants
            </p>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
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
                "border-b-2 px-3.5 py-2 text-xs font-medium transition-colors",
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

        {/* Slide-in form */}
        {showCreateForm && (
          <TemplateAuthoringForm
            template={editingTemplate}
            onClose={handleCloseForm}
          />
        )}
      </div>
    </AppShell>
  );
}
