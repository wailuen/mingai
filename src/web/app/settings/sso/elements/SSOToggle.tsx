"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useAdminSSOConfig, useUpdateAdminSSOConfig } from "@/lib/hooks/useSSO";

const PROVIDER_LABELS: Record<string, string> = {
  entra: "Microsoft Entra",
  google: "Google Workspace",
  okta: "Okta",
  saml: "SAML 2.0",
  oidc: "OpenID Connect",
};

/**
 * TA-005: SSO enable/disable toggle card.
 * Reads from GET /api/v1/admin/sso/config and PATCHes to flip enabled state.
 */
export function SSOToggle() {
  const { data, isPending, error } = useAdminSSOConfig();
  const updateMutation = useUpdateAdminSSOConfig();

  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [toastKind, setToastKind] = useState<"success" | "error">("success");

  function showToast(message: string, kind: "success" | "error") {
    setToastMessage(message);
    setToastKind(kind);
    setTimeout(() => setToastMessage(null), 3500);
  }

  async function handleToggle() {
    if (!data || updateMutation.isPending) return;
    const next = !data.enabled;

    try {
      await updateMutation.mutateAsync({
        provider_type: data.provider_type,
        auth0_connection_id: data.auth0_connection_id,
        enabled: next,
      });
      showToast(
        next ? "SSO enabled successfully." : "SSO disabled successfully.",
        "success",
      );
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : "Failed to update SSO status.",
        "error",
      );
    }
  }

  if (isPending) {
    return (
      <div className="flex items-center gap-2 text-body-default text-text-muted">
        <Loader2 size={14} className="animate-spin" />
        Loading SSO status...
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load SSO status: {error.message}
      </p>
    );
  }

  // No SSO configured on this endpoint yet
  if (data === null || data === undefined) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-section-heading text-text-primary">
              SSO Status
            </h3>
            <p className="mt-1 text-xs text-text-muted">
              Configure SSO first before enabling or disabling it.
            </p>
          </div>
          <button
            disabled
            aria-disabled="true"
            className="relative flex h-6 w-11 cursor-not-allowed items-center rounded-full bg-bg-elevated opacity-40"
            aria-label="SSO toggle — not configured"
          >
            <span className="absolute left-1 h-4 w-4 rounded-full bg-text-faint" />
          </button>
        </div>
      </div>
    );
  }

  const providerLabel =
    PROVIDER_LABELS[data.provider_type] ?? data.provider_type;
  const isEnabled = data.enabled;

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5 space-y-4">
      {/* Header row with toggle */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-section-heading text-text-primary">SSO Status</h3>
          <p className="mt-1 text-body-default text-text-muted">
            SSO is currently{" "}
            <span
              className={
                isEnabled
                  ? "font-semibold text-accent"
                  : "font-semibold text-text-faint"
              }
            >
              {isEnabled ? "enabled" : "disabled"}
            </span>
          </p>
        </div>

        {/* Toggle switch */}
        <button
          type="button"
          role="switch"
          aria-checked={isEnabled}
          aria-label={isEnabled ? "Disable SSO" : "Enable SSO"}
          onClick={handleToggle}
          disabled={updateMutation.isPending}
          className="relative flex h-6 w-11 flex-shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:cursor-wait focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-ring"
          style={{
            backgroundColor: isEnabled ? "var(--accent)" : "var(--bg-elevated)",
            border: isEnabled ? undefined : "1px solid var(--border)",
          }}
        >
          <span
            className="absolute h-4 w-4 rounded-full transition-transform"
            style={{
              backgroundColor: isEnabled
                ? "var(--bg-base)"
                : "var(--text-faint)",
              transform: isEnabled ? "translateX(20px)" : "translateX(4px)",
            }}
          />
          {updateMutation.isPending && (
            <Loader2
              size={10}
              className="absolute inset-0 m-auto animate-spin text-bg-base"
            />
          )}
        </button>
      </div>

      {/* Provider + connection info */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-xs text-text-muted">
          Provider:{" "}
          <span className="ml-1 font-medium text-text-primary">
            {providerLabel}
          </span>
        </span>

        {data.auth0_connection_id && (
          <span
            className="inline-flex items-center rounded-badge border border-border bg-bg-elevated px-2 py-0.5"
            title={data.auth0_connection_id}
          >
            <span className="font-mono text-data-value text-text-muted">
              {data.auth0_connection_id}
            </span>
          </span>
        )}

        {/* Enabled/disabled indicator dot */}
        <span className="ml-auto flex items-center gap-1.5">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              isEnabled ? "bg-accent" : "bg-text-faint"
            }`}
          />
          <span className="text-[11px] uppercase tracking-wider text-text-faint">
            {isEnabled ? "Active" : "Inactive"}
          </span>
        </span>
      </div>

      {/* Inline feedback */}
      {toastMessage && (
        <div
          className={`rounded-control border p-2.5 ${
            toastKind === "success"
              ? "border-accent-ring bg-accent-dim"
              : "border-alert-ring bg-alert-dim"
          }`}
        >
          <p
            className={`text-xs ${
              toastKind === "success" ? "text-accent" : "text-alert"
            }`}
          >
            {toastMessage}
          </p>
        </div>
      )}
    </div>
  );
}
