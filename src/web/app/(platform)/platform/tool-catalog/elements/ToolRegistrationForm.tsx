"use client";

import { useState } from "react";
import { X, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useRegisterTool,
  type SafetyClass,
  type AuthType,
} from "@/lib/hooks/useToolCatalog";

interface ToolRegistrationFormProps {
  onClose: () => void;
}

const AUTH_OPTIONS: { value: AuthType; label: string }[] = [
  { value: "none", label: "None" },
  { value: "api_key", label: "API Key" },
  { value: "oauth2", label: "OAuth 2.0" },
];

const SAFETY_OPTIONS: {
  value: SafetyClass;
  label: string;
  description: string;
}[] = [
  {
    value: "read_only",
    label: "Read-Only",
    description: "Can only read data, no side effects",
  },
  { value: "write", label: "Write", description: "Can create or modify data" },
  {
    value: "destructive",
    label: "Destructive",
    description: "Can delete or irreversibly alter data",
  },
];

function isValidEndpoint(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function ToolRegistrationForm({ onClose }: ToolRegistrationFormProps) {
  const [name, setName] = useState("");
  const [mcpEndpoint, setMcpEndpoint] = useState("");
  const [authType, setAuthType] = useState<AuthType>("none");
  const [safetyClass, setSafetyClass] = useState<SafetyClass>("read_only");
  const [capabilities, setCapabilities] = useState("");

  const registerMutation = useRegisterTool();

  const endpointValid =
    mcpEndpoint.length === 0 || isValidEndpoint(mcpEndpoint);
  const canRegister =
    name.trim().length > 0 &&
    mcpEndpoint.trim().length > 0 &&
    isValidEndpoint(mcpEndpoint);

  async function handleRegister() {
    const capList = capabilities
      .split(",")
      .map((c) => c.trim())
      .filter((c) => c.length > 0);

    await registerMutation.mutateAsync({
      name: name.trim(),
      mcp_endpoint: mcpEndpoint.trim(),
      auth_type: authType,
      safety_class: safetyClass,
      capabilities: capList,
    });
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-bg-deep/60"
        onClick={onClose}
        role="presentation"
      />

      {/* Panel */}
      <div className="relative flex w-[560px] flex-col border-l border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">
            Register Tool
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {/* Name */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Tool Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. SharePoint Reader"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
          </div>

          {/* MCP Endpoint */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              MCP Endpoint
            </label>
            <input
              type="url"
              value={mcpEndpoint}
              onChange={(e) => setMcpEndpoint(e.target.value)}
              placeholder="https://tools.example.com/mcp"
              className={cn(
                "w-full rounded-control border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint focus:outline-none",
                !endpointValid
                  ? "border-alert focus:border-alert"
                  : "border-border focus:border-accent",
              )}
            />
            {!endpointValid && (
              <p className="mt-1 text-[11px] text-alert">
                Must be a valid https:// URL
              </p>
            )}
          </div>

          {/* Auth Type */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Authentication
            </label>
            <select
              value={authType}
              onChange={(e) => setAuthType(e.target.value as AuthType)}
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
            >
              {AUTH_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Safety Classification */}
          <div>
            <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
              Safety Classification
            </label>
            <div className="space-y-2">
              {SAFETY_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-control border p-3 transition-colors",
                    safetyClass === opt.value
                      ? "border-accent bg-accent-dim"
                      : "border-border bg-bg-elevated hover:border-accent-ring",
                  )}
                >
                  <input
                    type="radio"
                    name="safety_class"
                    value={opt.value}
                    checked={safetyClass === opt.value}
                    onChange={() => setSafetyClass(opt.value)}
                    className="mt-0.5 accent-accent"
                  />
                  <div>
                    <span
                      className={cn(
                        "text-sm font-medium",
                        safetyClass === opt.value
                          ? "text-text-primary"
                          : "text-text-muted",
                      )}
                    >
                      {opt.label}
                    </span>
                    <p className="mt-0.5 text-[11px] text-text-faint">
                      {opt.description}
                    </p>
                  </div>
                </label>
              ))}
            </div>
            <div className="mt-2 flex items-start gap-2 rounded-control border border-warn/30 bg-warn-dim p-2.5">
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warn" />
              <p className="text-[11px] leading-relaxed text-warn">
                Safety classification cannot be changed after registration.
                Choose carefully.
              </p>
            </div>
          </div>

          {/* Capabilities */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Capabilities
            </label>
            <textarea
              value={capabilities}
              onChange={(e) => setCapabilities(e.target.value)}
              placeholder="search documents, read files, query database"
              rows={3}
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
            <p className="mt-1 text-[11px] text-text-faint">
              Comma-separated list of capabilities
            </p>
          </div>

          {/* Error display */}
          {registerMutation.isError && (
            <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
              <p className="text-xs text-alert">
                {registerMutation.error instanceof Error
                  ? registerMutation.error.message
                  : "Registration failed"}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-4 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleRegister}
            disabled={!canRegister || registerMutation.isPending}
            className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            {registerMutation.isPending ? "Registering..." : "Register & Test"}
          </button>
        </div>
      </div>
    </div>
  );
}
