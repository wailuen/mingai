"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useEffectiveProfile } from "@/lib/hooks/useLLMProfileConfig";
import { StarterProfileView } from "./elements/StarterProfileView";
import { ProfessionalProfileView } from "./elements/ProfessionalProfileView";
import { EnterpriseProfileView } from "./elements/EnterpriseProfileView";

function SkeletonSlotTable() {
  return (
    <div className="overflow-x-auto rounded-card border border-border bg-bg-surface">
      <table className="min-w-full">
        <thead className="border-b border-border">
          <tr>
            {["Slot", "Model", "Provider"].map((h) => (
              <th
                key={h}
                className="px-4 py-2.5 text-left text-label-nav uppercase tracking-wider text-text-faint"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: 4 }).map((_, i) => (
            <tr key={i} className="border-b border-border-faint">
              <td className="px-4 py-3">
                <div className="h-4 w-12 animate-pulse rounded-badge bg-bg-elevated" />
              </td>
              <td className="px-4 py-3">
                <div className="h-4 w-32 animate-pulse rounded-badge bg-bg-elevated" />
              </td>
              <td className="px-4 py-3">
                <div className="h-4 w-20 animate-pulse rounded-badge bg-bg-elevated" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LLMProfileContent() {
  const { data: profile, isPending, error } = useEffectiveProfile();

  if (isPending) {
    return (
      <div className="space-y-6">
        <div className="h-5 w-48 animate-pulse rounded-badge bg-bg-elevated" />
        <SkeletonSlotTable />
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load LLM profile: {error.message}
      </p>
    );
  }

  if (!profile) return null;

  if (profile.plan_tier === "starter") {
    return <StarterProfileView profile={profile} />;
  }

  if (profile.plan_tier === "professional") {
    return <ProfessionalProfileView profile={profile} />;
  }

  return <EnterpriseProfileView profile={profile} />;
}

export default function LLMProfilePage() {
  return (
    <AppShell>
      <div className="p-7">
        {/* Mobile banner — authoring context */}
        <div className="md:hidden mb-4 rounded-card border border-warn/30 bg-warn-dim p-4">
          <p className="text-body-default text-warn">
            Desktop recommended for managing LLM profiles.
          </p>
        </div>

        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">LLM Profile</h1>
          <p className="mt-1 text-body-default text-text-muted">
            AI model configuration for your workspace
          </p>
        </div>

        <ErrorBoundary>
          <LLMProfileContent />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
