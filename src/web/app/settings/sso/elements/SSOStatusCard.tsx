"use client";

import { Shield, AlertTriangle } from "lucide-react";
import type { SSOConfig } from "@/lib/hooks/useSSO";

interface SSOStatusCardProps {
  config: SSOConfig;
  onReconfigure: () => void;
  onTest: () => void;
}

export function SSOStatusCard({
  config,
  onReconfigure,
  onTest,
}: SSOStatusCardProps) {
  const isError = config.status === "error";
  const providerLabel =
    config.provider === "saml" ? "SAML 2.0" : "OpenID Connect (OIDC)";

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      {/* Header */}
      <div className="mb-4 flex items-center gap-3">
        <Shield size={20} className="text-text-muted" />
        <div className="flex-1">
          <h3 className="text-section-heading text-text-primary">
            {providerLabel}
          </h3>
          <div className="mt-1 flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                isError ? "bg-alert" : "bg-accent"
              }`}
            />
            <span
              className={`text-xs font-medium ${
                isError ? "text-alert" : "text-accent"
              }`}
            >
              {isError ? "Error" : "Configured"}
            </span>
          </div>
        </div>
      </div>

      {/* Details */}
      <div className="space-y-3 rounded-card border border-border-faint bg-bg-elevated p-4">
        {config.provider === "saml" && config.saml && (
          <>
            <DetailRow label="Entity ID" value={config.saml.entity_id} mono />
            <DetailRow label="ACS URL" value={config.saml.acs_url} mono />
            <DetailRow
              label="Metadata URL"
              value={config.saml.metadata_url}
              mono
            />
          </>
        )}
        {config.provider === "oidc" && config.oidc && (
          <>
            <DetailRow label="Client ID" value={config.oidc.client_id} mono />
            <DetailRow
              label="Discovery URL"
              value={config.oidc.discovery_url}
              mono
            />
          </>
        )}
      </div>

      {/* Error banner */}
      {isError && (
        <div className="mt-4 flex items-center gap-2 rounded-control border border-alert/30 bg-alert-dim px-3 py-2">
          <AlertTriangle size={14} className="text-alert" />
          <p className="text-xs text-alert">
            SSO configuration has errors. Please reconfigure or test the
            connection.
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="mt-4 flex gap-2">
        <button
          onClick={onTest}
          className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary"
        >
          Test SSO
        </button>
        <button
          onClick={onReconfigure}
          className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary"
        >
          Reconfigure
        </button>
      </div>
    </div>
  );
}

function DetailRow({
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
        className={`truncate text-sm text-text-muted ${mono ? "font-mono" : ""}`}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}
