"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useSSOConfig, useTestSSOConnection } from "@/lib/hooks/useSSO";
import { SSOStatusCard } from "./elements/SSOStatusCard";
import { SSOSetupWizard } from "./elements/SSOSetupWizard";
import { Loader2 } from "lucide-react";

/**
 * FE-032: SSO Configuration page (Tenant Admin).
 * Orchestrator only -- business logic lives in elements/.
 */
export default function SSOPage() {
  const { data, isPending, error } = useSSOConfig();
  const [showWizard, setShowWizard] = useState(false);
  const testMutation = useTestSSOConnection();

  const isConfigured =
    data?.status === "configured" || data?.status === "error";

  async function handleTestFromCard() {
    if (!data || !data.provider) return;

    const config =
      data.provider === "saml" && data.saml
        ? { provider: "saml" as const, saml: data.saml }
        : data.provider === "oidc" && data.oidc
          ? { provider: "oidc" as const, oidc: data.oidc }
          : null;

    if (!config) return;

    await testMutation.mutateAsync(config);
  }

  return (
    <AppShell>
      <div className="space-y-6 p-7">
        {/* Page header */}
        <div>
          <h1 className="text-page-title text-text-primary">Single Sign-On</h1>
          <p className="mt-1 text-sm text-text-muted">
            Configure SAML or OIDC authentication for your workspace
          </p>
        </div>

        <ErrorBoundary>
          {isPending && (
            <div className="flex items-center gap-2 text-sm text-text-muted">
              <Loader2 size={14} className="animate-spin" />
              Loading SSO configuration...
            </div>
          )}

          {error && (
            <p className="text-sm text-alert">
              Failed to load SSO config: {error.message}
            </p>
          )}

          {!isPending && !error && !isConfigured && !showWizard && (
            <div className="rounded-card border border-border-faint bg-bg-surface p-8 text-center">
              <p className="mb-4 text-sm text-text-muted">
                SSO is not configured. Set up SAML or OIDC to enable single
                sign-on for your workspace.
              </p>
              <button
                onClick={() => setShowWizard(true)}
                className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
              >
                Configure SSO
              </button>
            </div>
          )}

          {!isPending && !error && isConfigured && data && (
            <SSOStatusCard
              config={data}
              onReconfigure={() => setShowWizard(true)}
              onTest={handleTestFromCard}
            />
          )}
        </ErrorBoundary>

        {/* Test result inline */}
        {testMutation.isSuccess && (
          <div
            className={`rounded-control border p-3 ${
              testMutation.data.success
                ? "border-accent/30 bg-accent-dim"
                : "border-alert/30 bg-alert-dim"
            }`}
          >
            <p
              className={`text-xs ${
                testMutation.data.success ? "text-accent" : "text-alert"
              }`}
            >
              {testMutation.data.message}
            </p>
          </div>
        )}
      </div>

      {/* Wizard modal */}
      {showWizard && <SSOSetupWizard onClose={() => setShowWizard(false)} />}
    </AppShell>
  );
}
