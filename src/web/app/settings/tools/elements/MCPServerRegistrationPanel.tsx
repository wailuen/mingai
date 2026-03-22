"use client";

import { useState, useEffect } from "react";
import { X, Loader2, Eye, EyeOff } from "lucide-react";
import { useRegisterMCPServer } from "@/lib/hooks/useTools";
import type { MCPTransport, MCPAuthType } from "@/lib/hooks/useTools";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FormState {
  name: string;
  description: string;
  endpoint_url: string;
  transport: MCPTransport;
  auth_type: MCPAuthType;
  auth_token: string;
  auth_header_name: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  endpoint_url: "",
  transport: "sse",
  auth_type: "none",
  auth_token: "",
  auth_header_name: "X-API-Key",
};

interface ValidationErrors {
  name?: string;
  endpoint_url?: string;
}

// ---------------------------------------------------------------------------
// URL validation helper
// ---------------------------------------------------------------------------

function validateUrl(url: string): string | undefined {
  if (!url.trim()) return "Endpoint URL is required.";
  try {
    const parsed = new URL(url);
    const isLocalHttp =
      parsed.protocol === "http:" &&
      (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1");
    const isHttps = parsed.protocol === "https:";
    if (!isHttps && !isLocalHttp) {
      return "URL must use HTTPS (or HTTP for localhost only).";
    }
  } catch {
    return "Invalid URL format.";
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Panel component
// ---------------------------------------------------------------------------

interface MCPServerRegistrationPanelProps {
  onClose: () => void;
}

export function MCPServerRegistrationPanel({
  onClose,
}: MCPServerRegistrationPanelProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [errors, setErrors] = useState<ValidationErrors>({});
  const [showToken, setShowToken] = useState(false);
  const {
    mutate: register,
    isPending,
    error: mutationError,
  } = useRegisterMCPServer();

  // Reset form when panel mounts
  useEffect(() => {
    setForm(EMPTY_FORM);
    setErrors({});
  }, []);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    // Clear specific field error on change
    if (key in errors) {
      setErrors((prev) => ({ ...prev, [key]: undefined }));
    }
  }

  function validate(): boolean {
    const next: ValidationErrors = {};
    if (!form.name.trim()) next.name = "Server name is required.";
    const urlError = validateUrl(form.endpoint_url);
    if (urlError) next.endpoint_url = urlError;
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;

    const payload = {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      endpoint_url: form.endpoint_url.trim(),
      transport: form.transport,
      auth_type: form.auth_type,
      ...(form.auth_type !== "none" && form.auth_token
        ? { auth_token: form.auth_token }
        : {}),
      ...(form.auth_type === "api_key" && form.auth_header_name
        ? { auth_header_name: form.auth_header_name }
        : {}),
    };

    register(payload, {
      onSuccess: () => {
        onClose();
      },
    });
  }

  const needsToken =
    form.auth_type === "bearer" || form.auth_type === "api_key";
  const needsHeaderName = form.auth_type === "api_key";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-bg-base/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div
        className="fixed right-0 top-0 z-40 flex h-full flex-col border-l border-border bg-bg-surface shadow-xl"
        style={{ width: 480 }}
        role="dialog"
        aria-label="Register MCP Server"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Register MCP Server
            </h2>
            <p className="mt-0.5 text-body-default text-text-muted">
              Connect an external MCP-compliant tool server
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1.5 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form
          onSubmit={handleSubmit}
          className="flex flex-1 flex-col overflow-y-auto"
        >
          <div className="flex-1 space-y-5 px-6 py-5">
            {/* Name */}
            <div>
              <label className="mb-1.5 block text-body-default font-medium text-text-primary">
                Name <span className="text-alert">*</span>
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="e.g. Internal Data MCP"
                className={cn(
                  "w-full rounded-control border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring",
                  errors.name ? "border-alert/60" : "border-border",
                )}
              />
              {errors.name && (
                <p className="mt-1 text-body-default text-alert">
                  {errors.name}
                </p>
              )}
            </div>

            {/* Description */}
            <div>
              <label className="mb-1.5 block text-body-default font-medium text-text-primary">
                Description
              </label>
              <textarea
                value={form.description}
                onChange={(e) => set("description", e.target.value)}
                placeholder="Optional description of what this server provides"
                rows={2}
                className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
              />
            </div>

            {/* Endpoint URL */}
            <div>
              <label className="mb-1.5 block text-body-default font-medium text-text-primary">
                Endpoint URL <span className="text-alert">*</span>
              </label>
              <input
                type="text"
                value={form.endpoint_url}
                onChange={(e) => set("endpoint_url", e.target.value)}
                placeholder="https://mcp.example.com/sse"
                className={cn(
                  "w-full rounded-control border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring",
                  errors.endpoint_url ? "border-alert/60" : "border-border",
                )}
              />
              {errors.endpoint_url && (
                <p className="mt-1 text-body-default text-alert">
                  {errors.endpoint_url}
                </p>
              )}
              <p className="mt-1 text-body-default text-text-faint">
                HTTPS required (HTTP only for localhost).
              </p>
            </div>

            {/* Transport */}
            <div>
              <p className="mb-2 text-body-default font-medium text-text-primary">
                Transport
              </p>
              <div className="flex gap-3">
                {(["sse", "streamable_http"] as MCPTransport[]).map((t) => (
                  <label
                    key={t}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-control border px-3 py-2 text-body-default transition-colors",
                      form.transport === t
                        ? "border-accent/50 bg-accent-dim text-accent"
                        : "border-border bg-bg-elevated text-text-muted hover:border-border hover:text-text-primary",
                    )}
                  >
                    <input
                      type="radio"
                      name="transport"
                      value={t}
                      checked={form.transport === t}
                      onChange={() => set("transport", t)}
                      className="sr-only"
                    />
                    {t === "sse" ? "SSE" : "Streamable HTTP"}
                  </label>
                ))}
              </div>
            </div>

            {/* Auth type */}
            <div>
              <p className="mb-2 text-body-default font-medium text-text-primary">
                Authentication
              </p>
              <div className="flex gap-3">
                {(
                  [
                    { value: "none", label: "None" },
                    { value: "bearer", label: "Bearer Token" },
                    { value: "api_key", label: "API Key" },
                  ] as { value: MCPAuthType; label: string }[]
                ).map((opt) => (
                  <label
                    key={opt.value}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-control border px-3 py-2 text-body-default transition-colors",
                      form.auth_type === opt.value
                        ? "border-accent/50 bg-accent-dim text-accent"
                        : "border-border bg-bg-elevated text-text-muted hover:border-border hover:text-text-primary",
                    )}
                  >
                    <input
                      type="radio"
                      name="auth_type"
                      value={opt.value}
                      checked={form.auth_type === opt.value}
                      onChange={() => set("auth_type", opt.value)}
                      className="sr-only"
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
            </div>

            {/* Auth token (conditional) */}
            {needsToken && (
              <div>
                <label className="mb-1.5 block text-body-default font-medium text-text-primary">
                  {form.auth_type === "bearer"
                    ? "Bearer Token"
                    : "API Key Value"}
                </label>
                <div className="relative">
                  <input
                    type={showToken ? "text" : "password"}
                    value={form.auth_token}
                    onChange={(e) => set("auth_token", e.target.value)}
                    placeholder={
                      form.auth_type === "bearer"
                        ? "eyJhbGciOiJSUzI1NiJ9..."
                        : "sk-..."
                    }
                    className="w-full rounded-control border border-border bg-bg-elevated py-2 pl-3 pr-10 font-mono text-data-value text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken((p) => !p)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-faint hover:text-text-muted"
                    aria-label={showToken ? "Hide token" : "Show token"}
                  >
                    {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
            )}

            {/* Auth header name (API key only) */}
            {needsHeaderName && (
              <div>
                <label className="mb-1.5 block text-body-default font-medium text-text-primary">
                  Header Name
                </label>
                <input
                  type="text"
                  value={form.auth_header_name}
                  onChange={(e) => set("auth_header_name", e.target.value)}
                  placeholder="X-API-Key"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                />
              </div>
            )}

            {/* Mutation error */}
            {mutationError && (
              <div className="rounded-control border border-alert/30 bg-alert-dim px-4 py-3">
                <p className="text-body-default text-alert">
                  {mutationError instanceof Error
                    ? mutationError.message
                    : "Failed to register server. Please try again."}
                </p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-body-default font-medium text-bg-base transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPending && <Loader2 size={14} className="animate-spin" />}
              {isPending ? "Registering..." : "Register Server"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
