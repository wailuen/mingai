"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import { BootstrapBanner } from "./elements/BootstrapBanner";
import { ProviderList } from "./elements/ProviderList";
import { ProviderForm } from "./elements/ProviderForm";

/**
 * PVDR-013: Platform Provider List Screen.
 * Manages LLM provider credentials at the platform level.
 */
export default function ProvidersPage() {
  const { data } = useLLMProviders();
  const [showCreateForm, setShowCreateForm] = useState(false);

  const providers = data?.providers ?? [];
  const bootstrapActive = data?.bootstrap_active ?? false;
  const noProviders = providers.length === 0;

  return (
    <AppShell>
      <div className="p-7">
        {/* Bootstrap warning banner */}
        <BootstrapBanner active={bootstrapActive} />

        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">
              LLM Providers
            </h1>
            <p className="mt-1 text-sm text-text-muted">
              {providers.length > 0
                ? `${providers.length} provider${providers.length !== 1 ? "s" : ""}`
                : "Configure LLM provider credentials for the platform"}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreateForm(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            Add Provider
          </button>
        </div>

        {/* Provider table */}
        <ErrorBoundary>
          <ProviderList />
        </ErrorBoundary>

        {/* Create modal */}
        {showCreateForm && (
          <ProviderForm
            provider={null}
            showDefaultToggle={noProviders}
            onClose={() => setShowCreateForm(false)}
            onSaved={() => setShowCreateForm(false)}
          />
        )}
      </div>
    </AppShell>
  );
}
