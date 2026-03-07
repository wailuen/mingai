"use client";

import { useState } from "react";
import { X, ChevronLeft, ChevronRight, Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useSaveSSOConfig,
  useTestSSOConnection,
  type SAMLConfig,
  type OIDCConfig,
} from "@/lib/hooks/useSSO";

interface SSOSetupWizardProps {
  onClose: () => void;
}

type WizardStep = 1 | 2 | 3;
type Provider = "saml" | "oidc";

const HTTPS_PATTERN = /^https:\/\/.+/;
// Vault reference prefix guard — prevents raw secrets from being submitted
const VAULT_REF_PATTERN = /^vault:\/\/.+/;

export function SSOSetupWizard({ onClose }: SSOSetupWizardProps) {
  const [step, setStep] = useState<WizardStep>(1);
  const [provider, setProvider] = useState<Provider | null>(null);

  // SAML fields
  const [entityId, setEntityId] = useState("");
  const [acsUrl, setAcsUrl] = useState("");
  const [metadataUrl, setMetadataUrl] = useState("");

  // OIDC fields
  const [clientId, setClientId] = useState("");
  const [discoveryUrl, setDiscoveryUrl] = useState("");
  const [clientSecretRef, setClientSecretRef] = useState("");

  // Test state
  const [testPassed, setTestPassed] = useState<boolean | null>(null);
  const [testMessage, setTestMessage] = useState("");

  const saveMutation = useSaveSSOConfig();
  const testMutation = useTestSSOConnection();

  const canProceedStep1 = provider !== null;

  const canProceedStep2 =
    provider === "saml"
      ? entityId.trim().length > 0 &&
        HTTPS_PATTERN.test(acsUrl) &&
        HTTPS_PATTERN.test(metadataUrl)
      : provider === "oidc"
        ? clientId.trim().length > 0 &&
          HTTPS_PATTERN.test(discoveryUrl) &&
          VAULT_REF_PATTERN.test(clientSecretRef.trim())
        : false;

  function buildConfig() {
    if (provider === "saml") {
      return {
        provider: "saml" as const,
        saml: {
          entity_id: entityId.trim(),
          acs_url: acsUrl.trim(),
          metadata_url: metadataUrl.trim(),
        },
      };
    }
    return {
      provider: "oidc" as const,
      oidc: {
        client_id: clientId.trim(),
        discovery_url: discoveryUrl.trim(),
        client_secret_ref: clientSecretRef.trim(),
      },
    };
  }

  async function handleTest() {
    setTestPassed(null);
    setTestMessage("");
    try {
      const result = await testMutation.mutateAsync(buildConfig());
      setTestPassed(result.success);
      setTestMessage(result.message);
    } catch (err) {
      setTestPassed(false);
      setTestMessage(
        err instanceof Error ? err.message : "Connection test failed",
      );
    }
  }

  async function handleSave() {
    await saveMutation.mutateAsync(buildConfig());
    onClose();
  }

  function handleNext() {
    if (step < 3) setStep((step + 1) as WizardStep);
  }

  function handleBack() {
    if (step > 1) setStep((step - 1) as WizardStep);
  }

  const progressWidth = step === 1 ? "33.3%" : step === 2 ? "66.6%" : "100%";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Configure Single Sign-On
            </h2>
            <p className="mt-0.5 text-[11px] text-text-faint">
              Step {step} of 3
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-1 w-full bg-bg-elevated">
          <div
            className="h-full bg-accent transition-all duration-200"
            style={{ width: progressWidth }}
          />
        </div>

        {/* Content */}
        <div className="p-5">
          {/* Step 1: Choose Provider */}
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Choose your identity provider protocol.
              </p>
              <div className="grid grid-cols-2 gap-4">
                <ProviderCard
                  title="SAML 2.0"
                  description="Enterprise SSO via SAML assertions. Works with Okta, Azure AD, OneLogin."
                  useCase="Best for enterprise IdPs"
                  selected={provider === "saml"}
                  onSelect={() => setProvider("saml")}
                />
                <ProviderCard
                  title="OpenID Connect (OIDC)"
                  description="Modern OAuth 2.0 based protocol. Works with Google, Auth0, Keycloak."
                  useCase="Best for cloud-native IdPs"
                  selected={provider === "oidc"}
                  onSelect={() => setProvider("oidc")}
                />
              </div>
            </div>
          )}

          {/* Step 2: Configure */}
          {step === 2 && provider === "saml" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Enter your SAML 2.0 identity provider details.
              </p>
              <FormField
                label="Entity ID"
                value={entityId}
                onChange={setEntityId}
                placeholder="https://idp.example.com/entity"
              />
              <FormField
                label="ACS URL"
                value={acsUrl}
                onChange={setAcsUrl}
                placeholder="https://your-app.com/sso/saml/acs"
                hint="Must start with https://"
              />
              <FormField
                label="IdP Metadata URL"
                value={metadataUrl}
                onChange={setMetadataUrl}
                placeholder="https://idp.example.com/metadata.xml"
                hint="Must start with https://"
              />
            </div>
          )}

          {step === 2 && provider === "oidc" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Enter your OpenID Connect provider details.
              </p>
              <FormField
                label="Client ID"
                value={clientId}
                onChange={setClientId}
                placeholder="your-client-id"
              />
              <FormField
                label="Discovery URL"
                value={discoveryUrl}
                onChange={setDiscoveryUrl}
                placeholder="https://accounts.google.com/.well-known/openid-configuration"
                hint="Must start with https://"
              />
              <FormField
                label="Client Secret Reference"
                value={clientSecretRef}
                onChange={setClientSecretRef}
                placeholder="vault://secrets/sso/client-secret"
                hint="Must start with vault:// — store the raw secret in your vault and enter the reference path."
              />
            </div>
          )}

          {/* Step 3: Review + Test */}
          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Review your configuration and test the connection.
              </p>

              <div className="rounded-card border border-border bg-bg-elevated p-4">
                <dl className="space-y-3">
                  <ReviewRow
                    label="Provider"
                    value={
                      provider === "saml" ? "SAML 2.0" : "OpenID Connect (OIDC)"
                    }
                  />
                  {provider === "saml" && (
                    <>
                      <ReviewRow label="Entity ID" value={entityId} mono />
                      <ReviewRow label="ACS URL" value={acsUrl} mono />
                      <ReviewRow
                        label="Metadata URL"
                        value={metadataUrl}
                        mono
                      />
                    </>
                  )}
                  {provider === "oidc" && (
                    <>
                      <ReviewRow label="Client ID" value={clientId} mono />
                      <ReviewRow
                        label="Discovery URL"
                        value={discoveryUrl}
                        mono
                      />
                      <ReviewRow
                        label="Secret Ref"
                        value={clientSecretRef}
                        mono
                      />
                    </>
                  )}
                </dl>
              </div>

              {/* Test connection */}
              <div className="flex items-center gap-3">
                <button
                  onClick={handleTest}
                  disabled={testMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary disabled:opacity-30"
                >
                  {testMutation.isPending && (
                    <Loader2 size={12} className="animate-spin" />
                  )}
                  Test Connection
                </button>
                {testPassed !== null && (
                  <span
                    className={`text-xs font-medium ${
                      testPassed ? "text-accent" : "text-alert"
                    }`}
                  >
                    {testMessage}
                  </span>
                )}
              </div>

              {saveMutation.isError && (
                <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
                  <p className="text-xs text-alert">
                    {saveMutation.error instanceof Error
                      ? saveMutation.error.message
                      : "Failed to save SSO configuration"}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between border-t border-border px-5 py-3">
          <div>
            {step > 1 && (
              <button
                type="button"
                onClick={handleBack}
                disabled={saveMutation.isPending}
                className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
              >
                <ChevronLeft size={14} />
                Back
              </button>
            )}
          </div>

          <div className="flex gap-2">
            {step === 1 && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
              >
                Cancel
              </button>
            )}

            {step < 3 && (
              <button
                type="button"
                onClick={handleNext}
                disabled={
                  (step === 1 && !canProceedStep1) ||
                  (step === 2 && !canProceedStep2)
                }
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                Next
                <ChevronRight size={14} />
              </button>
            )}

            {step === 3 && (
              <button
                type="button"
                onClick={handleSave}
                disabled={saveMutation.isPending}
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                {saveMutation.isPending ? (
                  "Saving..."
                ) : (
                  <>
                    <Check size={14} />
                    Save Configuration
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ProviderCard({
  title,
  description,
  useCase,
  selected,
  onSelect,
}: {
  title: string;
  description: string;
  useCase: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "rounded-card border p-4 text-left transition-colors",
        selected
          ? "border-accent bg-accent-dim"
          : "border-border bg-bg-elevated hover:border-accent-ring",
      )}
    >
      <h3
        className={cn(
          "text-sm font-semibold",
          selected ? "text-accent" : "text-text-primary",
        )}
      >
        {title}
      </h3>
      <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
        {description}
      </p>
      <p className="mt-2 text-[11px] text-text-faint">{useCase}</p>
    </button>
  );
}

function FormField({
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  hint?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
      />
      {hint && <p className="mt-1 text-[11px] text-text-faint">{hint}</p>}
    </div>
  );
}

function ReviewRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-[11px] uppercase tracking-wider text-text-faint">
        {label}
      </dt>
      <dd
        className={`truncate text-sm text-text-primary ${mono ? "font-mono text-text-muted" : ""}`}
      >
        {value}
      </dd>
    </div>
  );
}
