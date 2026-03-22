"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { PlatformSkillsTable } from "./elements/PlatformSkillsTable";
import { PlatformSkillAuthoringPanel } from "./elements/PlatformSkillAuthoringPanel";
import type { PlatformSkillAdmin } from "@/lib/hooks/usePlatformSkillsAdmin";

type StatusTab = "all" | "draft" | "published" | "deprecated";

const TABS: { value: StatusTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "published", label: "Published" },
  { value: "deprecated", label: "Deprecated" },
];

/**
 * TODO-21: PA Skills Library — platform admin page for authoring and managing
 * platform-wide skills available to all tenants.
 */
export default function PlatformSkillsLibraryPage() {
  const [activeTab, setActiveTab] = useState<StatusTab>("all");
  // undefined = panel closed; null = create mode; string = edit mode (skill id)
  const [panelSkillId, setPanelSkillId] = useState<string | null | undefined>(
    undefined,
  );

  const panelOpen = panelSkillId !== undefined;

  function handleEdit(skill: PlatformSkillAdmin) {
    setPanelSkillId(skill.id);
  }

  function handleCreate() {
    setPanelSkillId(null);
  }

  function handleClosePanel() {
    setPanelSkillId(undefined);
  }

  function handleSaved(_id: string) {
    // Panel stays open so user can continue editing; list auto-refreshes via
    // React Query cache invalidation triggered by the mutation.
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">
              Skills Library
            </h1>
            <p className="mt-1 text-body-default text-text-muted">
              Author and publish platform skills available to all tenants
            </p>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Skill
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

        {/* Skills table */}
        <ErrorBoundary>
          <PlatformSkillsTable statusFilter={activeTab} onEdit={handleEdit} />
        </ErrorBoundary>
      </div>

      {/* Authoring panel — rendered outside the scrolling area so it overlays correctly */}
      {panelOpen && (
        <PlatformSkillAuthoringPanel
          skillId={panelSkillId ?? null}
          onClose={handleClosePanel}
          onSaved={handleSaved}
        />
      )}
    </AppShell>
  );
}
