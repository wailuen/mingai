"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { WorkProfileCard } from "@/components/privacy/WorkProfileCard";
import { MemoryNotesList } from "@/components/privacy/MemoryNotesList";
import { DataRightsSection } from "@/components/privacy/DataRightsSection";
import { PrivacyDisclosureDialog } from "@/components/privacy/PrivacyDisclosureDialog";

/**
 * FE-016: Privacy settings page.
 * Displays profile learning card, memory notes, work profile toggles,
 * and data rights (export + clear).
 */
export default function PrivacySettingsPage() {
  return (
    <AppShell>
      <div className="p-7">
        <h1 className="mb-6 text-page-title text-text-primary">
          Privacy Settings
        </h1>

        <div className="mx-auto max-w-2xl space-y-6">
          <ErrorBoundary>
            <WorkProfileCard
              orgContextEnabled={true}
              shareManagerInfo={false}
            />
          </ErrorBoundary>

          <ErrorBoundary>
            <MemoryNotesList />
          </ErrorBoundary>

          <ErrorBoundary>
            <DataRightsSection />
          </ErrorBoundary>
        </div>
      </div>

      {/* First-time transparency disclosure */}
      <PrivacyDisclosureDialog />
    </AppShell>
  );
}
