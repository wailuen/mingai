"use client";

import { useState } from "react";
import {
  X,
  ChevronLeft,
  ChevronRight,
  Check,
  Loader2,
  Download,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useConfigureSAML,
  useConfigureOIDC,
  useConfigureGoogle,
  useConfigureOkta,
  useConfigureEntra,
  useTestSAMLConnection,
  useTestOIDCConnection,
  useTestEntraConnection,
  fetchSAMLSPMetadata,
  type ConfigureResult,
} from "@/lib/hooks/useSSO";

interface SSOSetupWizardProps {
  onClose: () => void;
}

type WizardStep = 1 | 2 | 3;
type Provider = "saml" | "oidc" | "google" | "okta" | "entra";

const HTTPS_PATTERN = /^https:\/\/.+/;

/** Extract a human-readable message from an API error response. */
function extractErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    // Try to parse backend 422 detail from message
    try {
      const parsed = JSON.parse(err.message);
      if (parsed?.detail) {
        if (typeof parsed.detail === "string") return parsed.detail;
        if (Array.isArray(parsed.detail)) {
          return parsed.detail
            .map((d: { msg?: string }) => d.msg ?? String(d))
            .join("; ");
        }
      }
    } catch {
      // not JSON — use raw message
    }
    return err.message;
  }
  return "An unexpected error occurred";
}

export function SSOSetupWizard({ onClose }: SSOSetupWizardProps) {
  const [step, setStep] = useState<WizardStep>(1);
  const [provider, setProvider] = useState<Provider | null>(null);

  // SAML fields
  const [samlInputMode, setSamlInputMode] = useState<"url" | "xml">("url");
  const [samlMetadataUrl, setSamlMetadataUrl] = useState("");
  const [samlMetadataXml, setSamlMetadataXml] = useState("");

  // OIDC fields
  const [oidcIssuer, setOidcIssuer] = useState("");
  const [oidcClientId, setOidcClientId] = useState("");
  const [oidcClientSecret, setOidcClientSecret] = useState("");

  // Google fields
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleClientSecret, setGoogleClientSecret] = useState("");

  // Okta fields
  const [oktaDomain, setOktaDomain] = useState("");
  const [oktaClientId, setOktaClientId] = useState("");
  const [oktaClientSecret, setOktaClientSecret] = useState("");

  // Entra fields
  const [entraDomain, setEntraDomain] = useState("");
  const [entraClientId, setEntraClientId] = useState("");
  const [entraClientSecret, setEntraClientSecret] = useState("");

  // Post-save state
  const [savedResult, setSavedResult] = useState<ConfigureResult | null>(null);
  const [testUrl, setTestUrl] = useState<string | null>(null);
  const [spMetadataError, setSpMetadataError] = useState<string | null>(null);

  const samlMutation = useConfigureSAML();
  const oidcMutation = useConfigureOIDC();
  const googleMutation = useConfigureGoogle();
  const oktaMutation = useConfigureOkta();
  const entraMutation = useConfigureEntra();
  const testSAMLMutation = useTestSAMLConnection();
  const testOIDCMutation = useTestOIDCConnection();
  const testEntraMutation = useTestEntraConnection();

  const activeMutation =
    provider === "saml"
      ? samlMutation
      : provider === "oidc"
        ? oidcMutation
        : provider === "google"
          ? googleMutation
          : provider === "okta"
            ? oktaMutation
            : provider === "entra"
              ? entraMutation
              : null;

  const isSaving = activeMutation?.isPending ?? false;
  const saveError = activeMutation?.isError
    ? extractErrorMessage(activeMutation.error)
    : null;

  const canProceedStep2 = (() => {
    if (!provider) return false;
    if (provider === "saml") {
      return samlInputMode === "url"
        ? HTTPS_PATTERN.test(samlMetadataUrl.trim())
        : samlMetadataXml.trim().length > 0;
    }
    if (provider === "oidc") {
      return (
        HTTPS_PATTERN.test(oidcIssuer.trim()) &&
        oidcClientId.trim().length > 0 &&
        oidcClientSecret.trim().length > 0
      );
    }
    if (provider === "google") {
      return (
        googleClientId.trim().length > 0 && googleClientSecret.trim().length > 0
      );
    }
    if (provider === "okta") {
      return (
        HTTPS_PATTERN.test(oktaDomain.trim()) &&
        oktaClientId.trim().length > 0 &&
        oktaClientSecret.trim().length > 0
      );
    }
    if (provider === "entra") {
      return (
        entraDomain.trim().length > 0 &&
        entraClientId.trim().length > 0 &&
        entraClientSecret.trim().length > 0
      );
    }
    return false;
  })();

  async function handleSave() {
    setSavedResult(null);
    setTestUrl(null);
    try {
      let result: ConfigureResult;
      if (provider === "saml") {
        const payload =
          samlInputMode === "url"
            ? { metadata_url: samlMetadataUrl.trim() }
            : { metadata_xml: samlMetadataXml.trim() };
        result = await samlMutation.mutateAsync(payload);
      } else if (provider === "oidc") {
        result = await oidcMutation.mutateAsync({
          issuer: oidcIssuer.trim(),
          client_id: oidcClientId.trim(),
          client_secret: oidcClientSecret.trim(),
        });
      } else if (provider === "google") {
        result = await googleMutation.mutateAsync({
          client_id: googleClientId.trim(),
          client_secret: googleClientSecret.trim(),
        });
      } else if (provider === "okta") {
        result = await oktaMutation.mutateAsync({
          okta_domain: oktaDomain.trim(),
          client_id: oktaClientId.trim(),
          client_secret: oktaClientSecret.trim(),
        });
      } else if (provider === "entra") {
        result = await entraMutation.mutateAsync({
          domain: entraDomain.trim(),
          client_id: entraClientId.trim(),
          client_secret: entraClientSecret.trim(),
        });
      } else {
        return;
      }
      setSavedResult(result);
    } catch {
      // error surfaced via activeMutation.error
    }
  }

  async function handleTest() {
    setTestUrl(null);
    try {
      let result: { test_url: string };
      if (provider === "saml") {
        result = await testSAMLMutation.mutateAsync();
      } else if (
        provider === "oidc" ||
        provider === "google" ||
        provider === "okta"
      ) {
        result = await testOIDCMutation.mutateAsync();
      } else if (provider === "entra") {
        result = await testEntraMutation.mutateAsync();
      } else {
        return;
      }
      window.open(result.test_url, "_blank", "noopener,noreferrer");
      setTestUrl(result.test_url);
    } catch {
      // error surfaced via test mutation errors
    }
  }

  async function handleDownloadSPMetadata() {
    setSpMetadataError(null);
    try {
      const blob = await fetchSAMLSPMetadata();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "sp-metadata.xml";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setSpMetadataError(
        err instanceof Error ? err.message : "Failed to download SP metadata",
      );
    }
  }

  function handleNext() {
    if (step < 3) setStep((step + 1) as WizardStep);
  }

  function handleBack() {
    if (step > 1) setStep((step - 1) as WizardStep);
  }

  const testMutationPending =
    testSAMLMutation.isPending ||
    testOIDCMutation.isPending ||
    testEntraMutation.isPending;
  const testMutationError = testSAMLMutation.isError
    ? extractErrorMessage(testSAMLMutation.error)
    : testOIDCMutation.isError
      ? extractErrorMessage(testOIDCMutation.error)
      : testEntraMutation.isError
        ? extractErrorMessage(testEntraMutation.error)
        : null;

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
        <div className="max-h-[70vh] overflow-y-auto p-5">
          {/* Step 1: Choose Provider */}
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Choose your identity provider.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <ProviderCard
                  title="SAML 2.0"
                  description="Enterprise SSO via SAML assertions. Works with Okta, Azure AD, OneLogin."
                  useCase="Best for enterprise IdPs"
                  selected={provider === "saml"}
                  onSelect={() => setProvider("saml")}
                />
                <ProviderCard
                  title="OpenID Connect"
                  description="Modern OAuth 2.0 based protocol. Works with Auth0, Keycloak, generic OIDC."
                  useCase="Best for cloud-native IdPs"
                  selected={provider === "oidc"}
                  onSelect={() => setProvider("oidc")}
                />
                <ProviderCard
                  title="Google Workspace"
                  description="Sign in with Google accounts from your organisation's Workspace."
                  useCase="Google Workspace tenants"
                  selected={provider === "google"}
                  onSelect={() => setProvider("google")}
                />
                <ProviderCard
                  title="Okta"
                  description="Connect your Okta tenant for workforce identity."
                  useCase="Okta customers"
                  selected={provider === "okta"}
                  onSelect={() => setProvider("okta")}
                />
                <ProviderCard
                  title="Microsoft Entra ID"
                  description="Azure Active Directory SSO for Microsoft 365 and Azure tenants."
                  useCase="Microsoft / Azure AD tenants"
                  selected={provider === "entra"}
                  onSelect={() => setProvider("entra")}
                />
              </div>
            </div>
          )}

          {/* Step 2: Configure */}
          {step === 2 && provider === "saml" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Provide your IdP SAML metadata — either a URL or paste the XML
                directly.
              </p>
              {/* Input mode toggle */}
              <div className="flex gap-1 rounded-control border border-border bg-bg-elevated p-0.5 w-fit">
                {(["url", "xml"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setSamlInputMode(mode)}
                    className={cn(
                      "rounded-[5px] px-3 py-1 text-xs font-medium transition-colors",
                      samlInputMode === mode
                        ? "bg-bg-surface text-text-primary"
                        : "text-text-faint hover:text-text-muted",
                    )}
                  >
                    {mode === "url" ? "Metadata URL" : "Paste XML"}
                  </button>
                ))}
              </div>
              {samlInputMode === "url" ? (
                <FormField
                  label="IdP Metadata URL"
                  value={samlMetadataUrl}
                  onChange={setSamlMetadataUrl}
                  placeholder="https://idp.example.com/metadata.xml"
                  hint="Must start with https://"
                />
              ) : (
                <div>
                  <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                    IdP Metadata XML
                  </label>
                  <textarea
                    value={samlMetadataXml}
                    onChange={(e) => setSamlMetadataXml(e.target.value)}
                    placeholder='<?xml version="1.0"?><EntityDescriptor ...'
                    rows={6}
                    className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-xs text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none resize-none"
                  />
                </div>
              )}
            </div>
          )}

          {step === 2 && provider === "oidc" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Enter your OpenID Connect provider details.
              </p>
              <FormField
                label="Issuer URL"
                value={oidcIssuer}
                onChange={setOidcIssuer}
                placeholder="https://accounts.google.com"
                hint="Must start with https://"
              />
              <FormField
                label="Client ID"
                value={oidcClientId}
                onChange={setOidcClientId}
                placeholder="your-client-id"
              />
              <FormField
                label="Client Secret"
                value={oidcClientSecret}
                onChange={setOidcClientSecret}
                placeholder="your-client-secret"
                type="password"
              />
            </div>
          )}

          {step === 2 && provider === "google" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Enter your Google OAuth 2.0 application credentials.
              </p>
              <FormField
                label="Client ID"
                value={googleClientId}
                onChange={setGoogleClientId}
                placeholder="123456789-abc.apps.googleusercontent.com"
              />
              <FormField
                label="Client Secret"
                value={googleClientSecret}
                onChange={setGoogleClientSecret}
                placeholder="GOCSPX-..."
                type="password"
              />
            </div>
          )}

          {step === 2 && provider === "okta" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Enter your Okta tenant details.
              </p>
              <FormField
                label="Okta Domain"
                value={oktaDomain}
                onChange={setOktaDomain}
                placeholder="https://your-org.okta.com"
                hint="Must start with https://"
              />
              <FormField
                label="Client ID"
                value={oktaClientId}
                onChange={setOktaClientId}
                placeholder="0oabcdefghijklmnop"
              />
              <FormField
                label="Client Secret"
                value={oktaClientSecret}
                onChange={setOktaClientSecret}
                placeholder="your-client-secret"
                type="password"
              />
            </div>
          )}

          {step === 2 && provider === "entra" && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Enter your Azure Active Directory application credentials.
                Create an App Registration in the Azure portal and grant{" "}
                <span className="font-mono text-xs text-text-primary">
                  GroupMember.Read.All
                </span>{" "}
                permission.
              </p>
              <FormField
                label="Azure AD Domain"
                value={entraDomain}
                onChange={setEntraDomain}
                placeholder="contoso.com"
                hint="Your organisation's Azure AD domain (e.g. contoso.com)"
              />
              <FormField
                label="Application (Client) ID"
                value={entraClientId}
                onChange={setEntraClientId}
                placeholder="00000000-0000-0000-0000-000000000000"
                hint="Found in Azure portal under App Registration > Overview"
              />
              <FormField
                label="Client Secret"
                value={entraClientSecret}
                onChange={setEntraClientSecret}
                placeholder="your-client-secret-value"
                type="password"
                hint="Secret value (not the Secret ID)"
              />
            </div>
          )}

          {/* Step 3: Review + Save */}
          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Review your configuration and save to activate SSO.
              </p>

              {/* Review table */}
              <div className="rounded-card border border-border bg-bg-elevated p-4">
                <dl className="space-y-3">
                  <ReviewRow
                    label="Provider"
                    value={
                      provider === "saml"
                        ? "SAML 2.0"
                        : provider === "oidc"
                          ? "OpenID Connect (OIDC)"
                          : provider === "google"
                            ? "Google Workspace"
                            : provider === "entra"
                              ? "Microsoft Entra ID"
                              : "Okta"
                    }
                  />
                  {provider === "saml" && (
                    <ReviewRow
                      label={
                        samlInputMode === "url"
                          ? "Metadata URL"
                          : "Metadata XML"
                      }
                      value={
                        samlInputMode === "url"
                          ? samlMetadataUrl
                          : `${samlMetadataXml.slice(0, 60)}…`
                      }
                      mono
                    />
                  )}
                  {provider === "oidc" && (
                    <>
                      <ReviewRow label="Issuer" value={oidcIssuer} mono />
                      <ReviewRow label="Client ID" value={oidcClientId} mono />
                      <ReviewRow label="Client Secret" value="••••••••" mono />
                    </>
                  )}
                  {provider === "google" && (
                    <>
                      <ReviewRow
                        label="Client ID"
                        value={googleClientId}
                        mono
                      />
                      <ReviewRow label="Client Secret" value="••••••••" mono />
                    </>
                  )}
                  {provider === "okta" && (
                    <>
                      <ReviewRow label="Okta Domain" value={oktaDomain} mono />
                      <ReviewRow label="Client ID" value={oktaClientId} mono />
                      <ReviewRow label="Client Secret" value="••••••••" mono />
                    </>
                  )}
                  {provider === "entra" && (
                    <>
                      <ReviewRow
                        label="Azure AD Domain"
                        value={entraDomain}
                        mono
                      />
                      <ReviewRow label="Client ID" value={entraClientId} mono />
                      <ReviewRow label="Client Secret" value="••••••••" mono />
                    </>
                  )}
                </dl>
              </div>

              {/* Success state */}
              {savedResult && (
                <div className="rounded-card border border-accent/30 bg-accent-dim p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Check size={14} className="text-accent shrink-0" />
                    <p className="text-sm font-medium text-accent">
                      SSO configured successfully
                    </p>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] uppercase tracking-wider text-text-faint">
                      Connection ID
                    </span>
                    <span className="font-mono text-xs text-text-muted">
                      {savedResult.connection_id}
                    </span>
                  </div>

                  {/* SAML SP metadata download */}
                  {provider === "saml" && (
                    <div className="space-y-1">
                      <p className="text-xs text-text-muted">
                        Download the Service Provider metadata and upload it to
                        your IdP to complete the setup.
                      </p>
                      <button
                        type="button"
                        onClick={handleDownloadSPMetadata}
                        className="inline-flex items-center gap-1.5 rounded-control border border-accent/40 bg-accent-dim px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/10"
                      >
                        <Download size={12} />
                        Download SP Metadata XML
                      </button>
                      {spMetadataError && (
                        <p className="text-xs text-alert">{spMetadataError}</p>
                      )}
                    </div>
                  )}

                  {/* Test connection */}
                  <div className="flex items-center gap-3 pt-1">
                    <button
                      type="button"
                      onClick={handleTest}
                      disabled={testMutationPending}
                      className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary disabled:opacity-30"
                    >
                      {testMutationPending ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <ExternalLink size={12} />
                      )}
                      Test Connection
                    </button>
                    {testUrl && (
                      <span className="text-xs text-accent">
                        Test URL opened in new tab
                      </span>
                    )}
                    {testMutationError && (
                      <span className="text-xs text-alert">
                        {testMutationError}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* API error */}
              {saveError && (
                <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
                  <p className="text-xs text-alert">{saveError}</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between border-t border-border px-5 py-3">
          <div>
            {step > 1 && !savedResult && (
              <button
                type="button"
                onClick={handleBack}
                disabled={isSaving}
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
                  (step === 1 && provider === null) ||
                  (step === 2 && !canProceedStep2)
                }
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                Next
                <ChevronRight size={14} />
              </button>
            )}

            {step === 3 && !savedResult && (
              <button
                type="button"
                onClick={handleSave}
                disabled={isSaving}
                className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                {isSaving ? (
                  <>
                    <Loader2 size={13} className="animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Check size={14} />
                    Save Configuration
                  </>
                )}
              </button>
            )}

            {step === 3 && savedResult && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
              >
                Done
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
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  hint?: string;
  type?: "text" | "password";
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
        {label}
      </label>
      <input
        type={type}
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
