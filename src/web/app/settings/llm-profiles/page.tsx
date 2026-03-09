"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { Plus } from "lucide-react";
import { ProfileList } from "./elements/ProfileList";
import { NewProfileModal } from "./elements/NewProfileModal";

/**
 * Platform Admin: LLM Profiles management page.
 * Lists profiles as cards with slot assignments.
 * "New Profile" button opens creation modal.
 */
export default function LLMProfilesPage() {
  const [showModal, setShowModal] = useState(false);

  return (
    <AppShell>
      <div className="p-7">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">LLM Profiles</h1>
            <p className="mt-1 text-sm text-text-muted">
              Configure AI model assignments for your tenants
            </p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Profile
          </button>
        </div>

        {/* Profile list */}
        <ErrorBoundary>
          <ProfileList />
        </ErrorBoundary>

        {/* New Profile Modal */}
        {showModal && <NewProfileModal onClose={() => setShowModal(false)} />}
      </div>
    </AppShell>
  );
}
