"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/lib/api";
import {
  X,
  ChevronLeft,
  ChevronRight,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
} from "lucide-react";

interface SharePointSite {
  id: string;
  name: string;
  url: string;
}

/**
 * SharePoint Connection Wizard (4 steps):
 * 1. Permission instructions (Azure AD setup guide)
 * 2. Credential entry (tenant URL + client ID + secret)
 * 3. Connection test
 * 4. Site selector (multi-select discovered sites)
 *
 * Wizard state preserved (can go back/forward).
 * Credentials never shown after initial entry (masked).
 */
export function SharePointWizard({ onClose }: { onClose: () => void }) {
  const totalSteps = 4;
  const [step, setStep] = useState(1);
  const queryClient = useQueryClient();

  // Step 2: credentials
  const [siteUrl, setSiteUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  // Step 3: test
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<"success" | "error" | null>(
    null,
  );
  const [testError, setTestError] = useState("");

  // Step 4: site selection
  const [sites, setSites] = useState<SharePointSite[]>([]);
  const [selectedSiteIds, setSelectedSiteIds] = useState<Set<string>>(
    new Set(),
  );
  const [connecting, setConnecting] = useState(false);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    setTestError("");
    try {
      const result = await apiPost<{ sites: SharePointSite[] }>(
        "/api/v1/integrations/sharepoint/connect",
        {
          site_url: siteUrl,
          client_id: clientId,
          client_secret: clientSecret,
          test_only: true,
        },
      );
      setTestResult("success");
      setSites(result.sites ?? []);
    } catch (err) {
      setTestResult("error");
      setTestError(
        err instanceof Error
          ? err.message
          : "Connection failed. Please check your credentials.",
      );
    } finally {
      setTesting(false);
    }
  }

  async function handleConnect() {
    setConnecting(true);
    try {
      await apiPost("/api/v1/integrations/sharepoint/connect", {
        site_url: siteUrl,
        client_id: clientId,
        client_secret: clientSecret,
        selected_sites: Array.from(selectedSiteIds),
      });
      queryClient.invalidateQueries({ queryKey: ["integrations"] });
      onClose();
    } catch {
      setTestResult("error");
      setTestError("Connection failed during final setup.");
    } finally {
      setConnecting(false);
    }
  }

  function toggleSite(siteId: string) {
    setSelectedSiteIds((prev) => {
      const next = new Set(prev);
      if (next.has(siteId)) {
        next.delete(siteId);
      } else {
        next.add(siteId);
      }
      return next;
    });
  }

  const canProceed =
    step === 1 ||
    (step === 2 &&
      siteUrl.trim() !== "" &&
      clientId.trim() !== "" &&
      clientSecret.trim() !== "") ||
    (step === 3 && testResult === "success") ||
    (step === 4 && selectedSiteIds.size > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Progress bar */}
        <div className="h-1 rounded-t-card bg-bg-elevated">
          <div
            className="h-full rounded-l-card bg-accent transition-all duration-200"
            style={{ width: `${(step / totalSteps) * 100}%` }}
          />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Connect SharePoint
            </h2>
            <span className="text-xs text-text-faint">
              Step {step} of {totalSteps}
            </span>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="p-5">
          {step === 1 && <PermissionInstructions />}
          {step === 2 && (
            <CredentialEntry
              siteUrl={siteUrl}
              clientId={clientId}
              clientSecret={clientSecret}
              onSiteUrlChange={setSiteUrl}
              onClientIdChange={setClientId}
              onClientSecretChange={setClientSecret}
            />
          )}
          {step === 3 && (
            <ConnectionTest
              testing={testing}
              testResult={testResult}
              testError={testError}
              onTest={handleTest}
            />
          )}
          {step === 4 && (
            <SiteSelector
              sites={sites}
              selectedIds={selectedSiteIds}
              onToggle={toggleSite}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <button
            onClick={() => setStep(Math.max(1, step - 1))}
            disabled={step === 1}
            className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
          >
            <ChevronLeft size={14} />
            Back
          </button>

          {step < totalSteps ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={!canProceed}
              className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              Next
              <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={handleConnect}
              disabled={connecting || selectedSiteIds.size === 0}
              className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              {connecting ? "Connecting..." : "Connect"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Step 1: Permission setup instructions for Azure AD.
 */
function PermissionInstructions() {
  return (
    <div className="space-y-4">
      <p className="text-sm text-text-muted">
        Before connecting, you need to register an application in Azure AD with
        SharePoint permissions. Follow these steps:
      </p>

      <ol className="space-y-3 text-sm">
        <li className="flex gap-3">
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-bg-elevated font-mono text-xs text-accent">
            1
          </span>
          <div>
            <span className="font-medium text-text-primary">
              Go to Azure Portal &gt; App Registrations
            </span>
            <p className="mt-0.5 text-xs text-text-faint">
              Navigate to{" "}
              <span className="font-mono text-text-muted">
                portal.azure.com &gt; Azure Active Directory &gt; App
                registrations
              </span>
            </p>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-bg-elevated font-mono text-xs text-accent">
            2
          </span>
          <div>
            <span className="font-medium text-text-primary">
              Register a new application
            </span>
            <p className="mt-0.5 text-xs text-text-faint">
              Click &quot;New registration&quot;, name it (e.g.
              &quot;mingai-sharepoint&quot;), select &quot;Single tenant&quot;
            </p>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-bg-elevated font-mono text-xs text-accent">
            3
          </span>
          <div>
            <span className="font-medium text-text-primary">
              Add API permissions
            </span>
            <p className="mt-0.5 text-xs text-text-faint">
              Add Microsoft Graph &gt; Application permissions: Sites.Read.All,
              Files.Read.All
            </p>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-bg-elevated font-mono text-xs text-accent">
            4
          </span>
          <div>
            <span className="font-medium text-text-primary">
              Grant admin consent
            </span>
            <p className="mt-0.5 text-xs text-text-faint">
              Click &quot;Grant admin consent for [tenant]&quot; and confirm
            </p>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-bg-elevated font-mono text-xs text-accent">
            5
          </span>
          <div>
            <span className="font-medium text-text-primary">
              Create a client secret
            </span>
            <p className="mt-0.5 text-xs text-text-faint">
              Go to &quot;Certificates &amp; secrets&quot; &gt; &quot;New client
              secret&quot;. Copy the value immediately.
            </p>
          </div>
        </li>
      </ol>

      <a
        href="https://learn.microsoft.com/en-us/graph/auth-register-app-v2"
        target="_blank"
        rel="noopener noreferrer"
        className="mt-2 inline-flex items-center gap-1 text-sm text-accent transition-colors hover:underline"
      >
        Microsoft documentation
        <ExternalLink size={12} />
      </a>
    </div>
  );
}

/**
 * Step 2: Credential entry form.
 */
function CredentialEntry({
  siteUrl,
  clientId,
  clientSecret,
  onSiteUrlChange,
  onClientIdChange,
  onClientSecretChange,
}: {
  siteUrl: string;
  clientId: string;
  clientSecret: string;
  onSiteUrlChange: (v: string) => void;
  onClientIdChange: (v: string) => void;
  onClientSecretChange: (v: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
          SharePoint Tenant URL
        </label>
        <input
          type="url"
          value={siteUrl}
          onChange={(e) => onSiteUrlChange(e.target.value)}
          placeholder="https://company.sharepoint.com"
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
      </div>
      <div>
        <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
          Application (Client) ID
        </label>
        <input
          type="text"
          value={clientId}
          onChange={(e) => onClientIdChange(e.target.value)}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
      </div>
      <div>
        <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
          Client Secret
        </label>
        <input
          type="password"
          value={clientSecret}
          onChange={(e) => onClientSecretChange(e.target.value)}
          placeholder="Enter client secret"
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
        <p className="mt-1 text-xs text-text-faint">
          Credentials are encrypted and stored securely. They will not be
          displayed after this step.
        </p>
      </div>
    </div>
  );
}

/**
 * Step 3: Connection test with spinner -> success/failure.
 */
function ConnectionTest({
  testing,
  testResult,
  testError,
  onTest,
}: {
  testing: boolean;
  testResult: "success" | "error" | null;
  testError: string;
  onTest: () => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-text-muted">
        Test the connection to verify your credentials are correct.
      </p>

      <button
        onClick={onTest}
        disabled={testing}
        className="w-full rounded-control border border-border px-4 py-2.5 text-sm text-text-primary transition-colors hover:bg-bg-elevated"
      >
        {testing ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            Testing connection...
          </span>
        ) : testResult === "success" ? (
          <span className="flex items-center justify-center gap-2 text-accent">
            <CheckCircle2 size={14} />
            Connection successful -- click Next to select sites
          </span>
        ) : (
          "Test Connection"
        )}
      </button>

      {testResult === "success" && (
        <div className="flex items-center gap-2 rounded-control border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">
          <CheckCircle2 size={14} />
          Connected successfully
        </div>
      )}

      {testResult === "error" && (
        <div className="flex items-center gap-2 rounded-control border border-alert/30 bg-alert/10 px-3 py-2 text-sm text-alert">
          <AlertCircle size={14} />
          {testError}
        </div>
      )}
    </div>
  );
}

/**
 * Step 4: Multi-select site list from discovered SharePoint sites.
 */
function SiteSelector({
  sites,
  selectedIds,
  onToggle,
}: {
  sites: SharePointSite[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-text-muted">
        Select the SharePoint sites to index. Documents from these sites will be
        available for search.
      </p>

      {sites.length === 0 ? (
        <div className="rounded-control border border-border-faint px-4 py-6 text-center text-sm text-text-faint">
          No sites discovered. The connection test may need to be re-run.
        </div>
      ) : (
        <div className="max-h-56 space-y-1 overflow-y-auto">
          {sites.map((site) => (
            <label
              key={site.id}
              className="flex cursor-pointer items-center gap-3 rounded-control px-3 py-2 transition-colors hover:bg-bg-elevated"
            >
              <input
                type="checkbox"
                checked={selectedIds.has(site.id)}
                onChange={() => onToggle(site.id)}
                className="h-4 w-4 rounded border-border accent-accent"
              />
              <div>
                <span className="text-sm font-medium text-text-primary">
                  {site.name}
                </span>
                <span className="ml-2 font-mono text-xs text-text-faint">
                  {site.url}
                </span>
              </div>
            </label>
          ))}
        </div>
      )}

      <div className="text-xs text-text-faint">
        <span className="font-mono text-accent">{selectedIds.size}</span> site
        {selectedIds.size !== 1 ? "s" : ""} selected
      </div>
    </div>
  );
}
