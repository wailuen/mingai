"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ProfileList } from "./elements/ProfileList";
import { ProfileForm } from "./elements/ProfileForm";
import type { LLMProfile } from "@/lib/hooks/useLLMProfiles";

/**
 * FE-043: LLM Profile Library Management.
 * Lists all LLM deployment profiles. Provides create/edit modal.
 */
export default function LLMProfilesPage() {
  const [showForm, setShowForm] = useState(false);
  const [editingProfile, setEditingProfile] = useState<LLMProfile | null>(null);

  function handleEdit(profile: LLMProfile) {
    setEditingProfile(profile);
    setShowForm(true);
  }

  function handleCloseForm() {
    setShowForm(false);
    setEditingProfile(null);
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">LLM Profiles</h1>
            <p className="mt-1 text-body-default text-text-muted">
              Configure model deployments for tenant workspaces
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setEditingProfile(null);
              setShowForm(true);
            }}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Profile
          </button>
        </div>

        {/* Profile table */}
        <ErrorBoundary>
          <ProfileList onEdit={handleEdit} />
        </ErrorBoundary>

        {/* Create/edit modal */}
        {showForm && (
          <ProfileForm
            profile={editingProfile}
            onClose={handleCloseForm}
            onSaved={handleCloseForm}
          />
        )}
      </div>
    </AppShell>
  );
}
