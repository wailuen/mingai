"use client";

import { useState } from "react";
import { Eye, EyeOff, Loader2, Check, AlertCircle } from "lucide-react";
import { apiPost } from "@/lib/api";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import type { WizardFormData } from "../AgentDeployWizard";

interface CredentialSchemaItem {
  key: string;
  label?: string;
  sensitive?: boolean;
  required?: boolean;
  description?: string;
}

interface TestCredentialsResponse {
  success: boolean;
  message?: string;
}

interface WizardStep4CredentialsProps {
  template: AgentTemplate | null;
  formData: WizardFormData;
  onChange: (data: Partial<WizardFormData>) => void;
}

function resolveCredentialSchema(
  template: AgentTemplate | null,
): CredentialSchemaItem[] {
  if (!template) return [];

  // Prefer structured credential_schema if present (future field)
  const raw = (template as AgentTemplate & { credential_schema?: unknown })
    .credential_schema;
  if (Array.isArray(raw) && raw.length > 0) {
    return raw as CredentialSchemaItem[];
  }

  // Fall back to required_credentials string array
  if (
    template.required_credentials &&
    template.required_credentials.length > 0
  ) {
    return template.required_credentials.map((key) => ({
      key,
      label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      sensitive:
        key.toLowerCase().includes("secret") ||
        key.toLowerCase().includes("key") ||
        key.toLowerCase().includes("password") ||
        key.toLowerCase().includes("token"),
      required: true,
    }));
  }

  return [];
}

interface CredentialFieldProps {
  item: CredentialSchemaItem;
  value: string;
  onChange: (value: string) => void;
}

function CredentialField({ item, value, onChange }: CredentialFieldProps) {
  const [showSecret, setShowSecret] = useState(false);
  const inputType = item.sensitive && !showSecret ? "password" : "text";

  return (
    <div>
      <label className="mb-1.5 block text-body-default font-medium text-text-primary">
        {item.label ?? item.key}
        {item.required && <span className="ml-0.5 text-alert">*</span>}
      </label>
      {item.description && (
        <p className="mb-1.5 text-[11px] text-text-muted">{item.description}</p>
      )}
      <div className="relative">
        <input
          type={inputType}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            item.sensitive ? "••••••••" : `Enter ${item.label ?? item.key}…`
          }
          autoComplete={item.sensitive ? "new-password" : "off"}
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          style={item.sensitive ? { paddingRight: "2.5rem" } : undefined}
        />
        {item.sensitive && (
          <button
            type="button"
            onClick={() => setShowSecret((v) => !v)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-faint transition-colors hover:text-text-primary"
            aria-label={showSecret ? "Hide" : "Show"}
          >
            {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
      </div>
    </div>
  );
}

export function WizardStep4Credentials({
  template,
  formData,
  onChange,
}: WizardStep4CredentialsProps) {
  const [testStatus, setTestStatus] = useState<
    "idle" | "loading" | "success" | "error"
  >("idle");
  const [testError, setTestError] = useState<string | null>(null);

  const credentialSchema = resolveCredentialSchema(template);

  async function handleTestConnection() {
    if (!template) return;
    setTestStatus("loading");
    setTestError(null);
    try {
      const result = await apiPost<TestCredentialsResponse>(
        "/api/v1/admin/agents/test-credentials",
        {
          template_id: template.id,
          credentials: formData.credentials,
        },
      );
      if (result.success) {
        setTestStatus("success");
      } else {
        setTestStatus("error");
        setTestError(result.message ?? "Connection test failed.");
      }
    } catch (err) {
      setTestStatus("error");
      setTestError(
        err instanceof Error ? err.message : "Connection test failed.",
      );
    }
  }

  if (credentialSchema.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <p className="text-body-default text-text-faint">
          No credentials required for this template.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-section-heading text-text-primary">Credentials</p>
        <p className="mt-1 text-[11px] text-text-muted">
          These credentials are stored for this agent only and are never shared
          across tenants.
        </p>
      </div>

      {/* Credential inputs */}
      <div className="flex flex-col gap-4">
        {credentialSchema.map((item) => (
          <CredentialField
            key={item.key}
            item={item}
            value={formData.credentials[item.key] ?? ""}
            onChange={(val) =>
              onChange({
                credentials: { ...formData.credentials, [item.key]: val },
              })
            }
          />
        ))}
      </div>

      {/* Test connection */}
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={handleTestConnection}
          disabled={testStatus === "loading"}
          className="flex w-full items-center justify-center gap-2 rounded-control border border-border bg-bg-elevated px-4 py-2 text-body-default font-medium text-text-primary transition-colors hover:border-accent-ring hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
        >
          {testStatus === "loading" && (
            <Loader2 size={14} className="animate-spin" />
          )}
          {testStatus === "success" && (
            <Check size={14} className="text-accent" />
          )}
          {testStatus === "error" && (
            <AlertCircle size={14} className="text-alert" />
          )}
          {testStatus === "idle" && "Test Connection"}
          {testStatus === "loading" && "Testing…"}
          {testStatus === "success" && "Connection successful"}
          {testStatus === "error" && "Retry Connection Test"}
        </button>

        {testStatus === "error" && testError && (
          <p className="text-[11px] text-alert">{testError}</p>
        )}

        <button
          type="button"
          onClick={() => setTestStatus("idle")}
          className="text-[11px] text-text-faint hover:text-text-muted"
        >
          Skip test, save credentials
        </button>
      </div>
    </div>
  );
}
