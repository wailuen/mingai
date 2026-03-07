"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest, apiPost } from "@/lib/api";
import {
  FileText,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ChevronRight,
  ChevronLeft,
  X,
} from "lucide-react";

interface Integration {
  id: string;
  type: "sharepoint" | "googledrive";
  status: "connected" | "disconnected" | "error";
  last_sync: string | null;
  document_count: number;
}

/**
 * FE-029: Document store list + SharePoint connection wizard.
 * Shows connected integrations and their sync status.
 * Provides a wizard to connect new SharePoint sites.
 */
export default function KnowledgeBasePage() {
  const [showWizard, setShowWizard] = useState(false);
  const queryClient = useQueryClient();

  const { data: integrations = [], isLoading } = useQuery<Integration[]>({
    queryKey: ["integrations"],
    queryFn: async () => {
      const sp = await apiRequest<Integration>(
        "/api/v1/integrations/sharepoint/status",
      ).catch(() => null);
      const gd = await apiRequest<Integration>(
        "/api/v1/integrations/googledrive/status",
      ).catch(() => null);
      return [sp, gd].filter(Boolean) as Integration[];
    },
  });

  async function handleSync() {
    await apiPost("/api/v1/sync/trigger", {});
    queryClient.invalidateQueries({ queryKey: ["integrations"] });
  }

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText size={20} className="text-text-faint" />
            <h1 className="text-page-title text-text-primary">
              Document Stores
            </h1>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleSync}
              className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              <RefreshCw size={14} />
              Sync Now
            </button>
            <button
              onClick={() => setShowWizard(true)}
              className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
            >
              Connect Source
            </button>
          </div>
        </div>

        <ErrorBoundary>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 2 }).map((_, i) => (
                <div
                  key={i}
                  className="h-20 animate-pulse rounded-card border border-border bg-bg-surface"
                />
              ))}
            </div>
          ) : integrations.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-card border border-dashed border-border py-16">
              <FileText size={32} className="mb-3 text-text-faint" />
              <p className="text-sm text-text-muted">
                No document sources connected
              </p>
              <button
                onClick={() => setShowWizard(true)}
                className="mt-3 text-sm text-accent transition-colors hover:underline"
              >
                Connect your first source
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {integrations.map((integration) => (
                <IntegrationCard
                  key={integration.id}
                  integration={integration}
                />
              ))}
            </div>
          )}
        </ErrorBoundary>

        {showWizard && (
          <SharePointWizard onClose={() => setShowWizard(false)} />
        )}
      </div>
    </AppShell>
  );
}

function IntegrationCard({ integration }: { integration: Integration }) {
  const StatusIcon =
    integration.status === "connected"
      ? CheckCircle2
      : integration.status === "error"
        ? AlertCircle
        : Loader2;

  const statusColor =
    integration.status === "connected"
      ? "text-accent"
      : integration.status === "error"
        ? "text-alert"
        : "text-text-faint";

  const label =
    integration.type === "sharepoint" ? "SharePoint" : "Google Drive";

  return (
    <div className="flex items-center justify-between rounded-card border border-border bg-bg-surface px-5 py-4">
      <div className="flex items-center gap-3">
        <StatusIcon size={18} className={statusColor} />
        <div>
          <span className="text-sm font-medium text-text-primary">{label}</span>
          <div className="flex items-center gap-2 text-xs text-text-faint">
            <span className="font-mono">
              {integration.document_count.toLocaleString()} documents
            </span>
            {integration.last_sync && (
              <>
                <span>·</span>
                <span>
                  Last sync: {new Date(integration.last_sync).toLocaleString()}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
      <span
        className={`rounded-badge border px-2 py-0.5 text-xs font-medium ${
          integration.status === "connected"
            ? "border-accent/30 bg-accent/10 text-accent"
            : integration.status === "error"
              ? "border-alert/30 bg-alert/10 text-alert"
              : "border-border bg-bg-elevated text-text-muted"
        }`}
      >
        {integration.status}
      </span>
    </div>
  );
}

/**
 * SharePoint Connection Wizard.
 * 3-step wizard: Site URL -> Credentials -> Test + Confirm.
 */
function SharePointWizard({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(1);
  const [siteUrl, setSiteUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<"success" | "error" | null>(
    null,
  );
  const [connecting, setConnecting] = useState(false);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      await apiPost("/api/v1/integrations/sharepoint/connect", {
        site_url: siteUrl,
        client_id: clientId,
        client_secret: clientSecret,
        test_only: true,
      });
      setTestResult("success");
    } catch {
      setTestResult("error");
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
      });
      onClose();
    } catch {
      setTestResult("error");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Progress bar */}
        <div className="h-1 rounded-t-card bg-bg-elevated">
          <div
            className="h-full rounded-l-card bg-accent transition-all duration-200"
            style={{ width: `${(step / 3) * 100}%` }}
          />
        </div>

        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Connect SharePoint
            </h2>
            <span className="text-xs text-text-faint">Step {step} of 3</span>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5">
          {step === 1 && (
            <div>
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                SharePoint Site URL
              </label>
              <input
                type="url"
                value={siteUrl}
                onChange={(e) => setSiteUrl(e.target.value)}
                placeholder="https://company.sharepoint.com/sites/docs"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Client ID
                </label>
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="Azure AD app client ID"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Client Secret
                </label>
                <input
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder="Azure AD app client secret"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <button
                onClick={handleTest}
                disabled={testing}
                className="w-full rounded-control border border-border px-4 py-2.5 text-sm text-text-primary transition-colors hover:bg-bg-elevated"
              >
                {testing ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 size={14} className="animate-spin" />
                    Testing connection...
                  </span>
                ) : (
                  "Test Connection"
                )}
              </button>

              {testResult === "success" && (
                <div className="flex items-center gap-2 rounded-control border border-accent/30 bg-accent/10 px-3 py-2 text-sm text-accent">
                  <CheckCircle2 size={14} />
                  Connection successful
                </div>
              )}

              {testResult === "error" && (
                <div className="flex items-center gap-2 rounded-control border border-alert/30 bg-alert/10 px-3 py-2 text-sm text-alert">
                  <AlertCircle size={14} />
                  Connection failed. Please check your credentials.
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <button
            onClick={() => setStep(Math.max(1, step - 1))}
            disabled={step === 1}
            className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
          >
            <ChevronLeft size={14} />
            Back
          </button>

          {step < 3 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={
                (step === 1 && !siteUrl.trim()) ||
                (step === 2 && (!clientId.trim() || !clientSecret.trim()))
              }
              className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              Next
              <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={handleConnect}
              disabled={connecting || testResult !== "success"}
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
