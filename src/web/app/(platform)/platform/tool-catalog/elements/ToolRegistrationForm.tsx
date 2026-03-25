"use client";

import { useState } from "react";
import {
  X,
  AlertTriangle,
  Search,
  CheckSquare,
  Square,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useRegisterTool,
  useDiscoverTools,
  type SafetyClass,
  type AuthType,
  type DiscoveredTool,
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
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Discovered tools panel
// ---------------------------------------------------------------------------

interface DiscoveredToolsPanelProps {
  tools: DiscoveredTool[];
  serverName: string | null;
  selectedNames: Set<string>;
  onToggle: (name: string) => void;
  onToggleAll: () => void;
}

function DiscoveredToolsPanel({
  tools,
  serverName,
  selectedNames,
  onToggle,
  onToggleAll,
}: DiscoveredToolsPanelProps) {
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const allSelected = tools.every((t) => selectedNames.has(t.name));

  return (
    <div className="rounded-control border border-accent/30 bg-accent-dim/20">
      <div className="flex items-center justify-between border-b border-accent/20 px-3 py-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onToggleAll}
            className="text-accent transition-colors hover:opacity-80"
          >
            {allSelected ? <CheckSquare size={14} /> : <Square size={14} />}
          </button>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-accent">
            {tools.length} tool{tools.length !== 1 ? "s" : ""} found
            {serverName && (
              <span className="ml-1 font-normal normal-case text-text-faint">
                from {serverName}
              </span>
            )}
          </span>
        </div>
        <span className="text-[11px] text-text-faint">
          {selectedNames.size} selected
        </span>
      </div>
      <div className="max-h-[280px] divide-y divide-border/40 overflow-y-auto">
        {tools.map((tool) => {
          const isSelected = selectedNames.has(tool.name);
          const isExpanded = expandedTool === tool.name;
          return (
            <div
              key={tool.name}
              className={cn(isSelected && "bg-accent-dim/30")}
            >
              <div className="flex items-start gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() => onToggle(tool.name)}
                  className={cn(
                    "mt-0.5 shrink-0 transition-colors",
                    isSelected ? "text-accent" : "text-text-faint",
                  )}
                >
                  {isSelected ? (
                    <CheckSquare size={14} />
                  ) : (
                    <Square size={14} />
                  )}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-body-default font-medium text-text-primary">
                      {tool.name}
                    </span>
                    {tool.tags.length > 0 && (
                      <span className="rounded-badge bg-bg-elevated px-1.5 py-0.5 text-[10px] text-text-faint">
                        {tool.tags[0]}
                      </span>
                    )}
                  </div>
                  {tool.description && (
                    <p className="mt-0.5 text-[11px] text-text-muted line-clamp-2">
                      {tool.description}
                    </p>
                  )}
                </div>
                {Object.keys(tool.input_schema).length > 0 && (
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedTool(isExpanded ? null : tool.name)
                    }
                    className="shrink-0 text-text-faint transition-colors hover:text-text-primary"
                  >
                    {isExpanded ? (
                      <ChevronDown size={13} />
                    ) : (
                      <ChevronRight size={13} />
                    )}
                  </button>
                )}
              </div>
              {isExpanded && Object.keys(tool.input_schema).length > 0 && (
                <div className="border-t border-border/40 bg-bg-deep px-3 py-2">
                  <p className="mb-1 text-[10px] uppercase tracking-wider text-text-faint">
                    Input Schema
                  </p>
                  <pre className="overflow-x-auto text-[11px] text-text-muted">
                    {JSON.stringify(tool.input_schema, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main form
// ---------------------------------------------------------------------------

export function ToolRegistrationForm({ onClose }: ToolRegistrationFormProps) {
  const [quickFill, setQuickFill] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [description, setDescription] = useState("");
  const [mcpEndpoint, setMcpEndpoint] = useState("");
  const [authType, setAuthType] = useState<AuthType>("none");
  const [safetyClass, setSafetyClass] = useState<SafetyClass>("read_only");
  const [capabilities, setCapabilities] = useState("");

  // Discover state
  const [discoveredTools, setDiscoveredTools] = useState<
    DiscoveredTool[] | null
  >(null);
  const [discoveredServerName, setDiscoveredServerName] = useState<
    string | null
  >(null);
  const [selectedToolNames, setSelectedToolNames] = useState<Set<string>>(
    new Set(),
  );
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const registerMutation = useRegisterTool();
  const discoverMutation = useDiscoverTools();

  const endpointValid =
    mcpEndpoint.length === 0 || isValidEndpoint(mcpEndpoint);
  const endpointReady =
    mcpEndpoint.trim().length > 0 && isValidEndpoint(mcpEndpoint);

  // Manual registration: need name + endpoint
  const canRegisterManual = name.trim().length > 0 && endpointReady;

  // Bulk import: need endpoint + at least one tool selected
  const canImportSelected = endpointReady && selectedToolNames.size > 0;

  function handleQuickFill(key: string) {
    if (key === "pitchbook") {
      setName("Pitchbook");
      setProvider("Pitchbook");
      setDescription(
        "Investment data platform providing company profiles, deal analytics, investor research, fund performance, and private market intelligence via PitchBook API V2.",
      );
      setMcpEndpoint("http://localhost:8022/api/v1/mcp/pitchbook");
      setAuthType("api_key");
      setSafetyClass("read_only");
      setCapabilities(
        "company research, deal analysis, investor lookup, fund data, people search, LP data",
      );
    }
    setQuickFill(key);
    setDiscoveredTools(null);
    setDiscoverError(null);
  }

  async function handleDiscover() {
    setDiscoverError(null);
    setDiscoveredTools(null);
    setSelectedToolNames(new Set());
    try {
      const result = await discoverMutation.mutateAsync({
        endpoint: mcpEndpoint.trim(),
      });
      setDiscoveredTools(result.tools);
      setDiscoveredServerName(result.server_name);
      // Auto-select all discovered tools
      setSelectedToolNames(new Set(result.tools.map((t) => t.name)));
      // Auto-fill provider from server name if not set
      if (!provider && result.server_name) {
        setProvider(result.server_name);
      }
    } catch (err) {
      setDiscoverError(
        err instanceof Error ? err.message : "Could not reach the MCP server.",
      );
    }
  }

  function handleToggleTool(toolName: string) {
    setSelectedToolNames((prev) => {
      const next = new Set(prev);
      if (next.has(toolName)) {
        next.delete(toolName);
      } else {
        next.add(toolName);
      }
      return next;
    });
  }

  function handleToggleAll() {
    if (!discoveredTools) return;
    const allSelected = discoveredTools.every((t) =>
      selectedToolNames.has(t.name),
    );
    if (allSelected) {
      setSelectedToolNames(new Set());
    } else {
      setSelectedToolNames(new Set(discoveredTools.map((t) => t.name)));
    }
  }

  async function handleImportSelected() {
    if (!discoveredTools) return;
    const toImport = discoveredTools.filter((t) =>
      selectedToolNames.has(t.name),
    );
    const providerName = provider.trim() || discoveredServerName || "Unknown";

    for (const tool of toImport) {
      await registerMutation.mutateAsync({
        name: tool.name,
        provider: providerName,
        description: tool.description,
        mcp_endpoint: mcpEndpoint.trim(),
        auth_type: authType,
        safety_class: safetyClass,
        capabilities: tool.tags,
      });
    }
    onClose();
  }

  async function handleRegister() {
    const capList = capabilities
      .split(",")
      .map((c) => c.trim())
      .filter((c) => c.length > 0);

    await registerMutation.mutateAsync({
      name: name.trim(),
      provider: provider.trim(),
      description: description.trim(),
      mcp_endpoint: mcpEndpoint.trim(),
      auth_type: authType,
      safety_class: safetyClass,
      capabilities: capList,
    });
    onClose();
  }

  const pitchbookSelected =
    quickFill === "pitchbook" || name.toLowerCase() === "pitchbook";

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
          {/* Quick Fill */}
          <div>
            <p className="mb-2 text-[11px] uppercase tracking-wider text-text-faint">
              Known Integrations
            </p>
            <button
              type="button"
              onClick={() => handleQuickFill("pitchbook")}
              className={cn(
                "flex items-center gap-2 rounded-control border px-3 py-1.5 transition-colors",
                pitchbookSelected
                  ? "border-accent bg-accent-dim"
                  : "border-border bg-bg-elevated hover:border-accent-ring hover:bg-bg-elevated",
              )}
            >
              <span className="flex h-5 w-7 items-center justify-center rounded-badge bg-accent text-[10px] font-semibold text-bg-base">
                PB
              </span>
              <span className="text-body-default text-text-primary">
                Pitchbook
              </span>
              <span className="ml-1 text-[11px] text-text-faint">
                read-only
              </span>
            </button>
          </div>

          {/* MCP Endpoint — moved up to enable discover early */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              MCP Endpoint
            </label>
            <div className="flex gap-2">
              <input
                type="url"
                value={mcpEndpoint}
                onChange={(e) => {
                  setMcpEndpoint(e.target.value);
                  setDiscoveredTools(null);
                  setDiscoverError(null);
                }}
                placeholder="https://tools.example.com/mcp"
                className={cn(
                  "flex-1 rounded-control border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint focus:outline-none",
                  !endpointValid
                    ? "border-alert focus:border-alert"
                    : "border-border focus:border-accent",
                )}
              />
              <button
                type="button"
                onClick={handleDiscover}
                disabled={!endpointReady || discoverMutation.isPending}
                className="flex shrink-0 items-center gap-1.5 rounded-control border border-border px-3 py-2 text-[12px] text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:opacity-30"
              >
                <Search size={13} />
                {discoverMutation.isPending ? "Probing…" : "Discover"}
              </button>
            </div>
            {!endpointValid && mcpEndpoint.length > 0 && (
              <p className="mt-1 text-[11px] text-alert">
                Must be a valid http:// or https:// URL
              </p>
            )}
          </div>

          {/* Discover error */}
          {discoverError && (
            <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
              <p className="text-[12px] text-alert">{discoverError}</p>
            </div>
          )}

          {/* Discovered tools panel */}
          {discoveredTools && discoveredTools.length > 0 && (
            <div className="space-y-2">
              <DiscoveredToolsPanel
                tools={discoveredTools}
                serverName={discoveredServerName}
                selectedNames={selectedToolNames}
                onToggle={handleToggleTool}
                onToggleAll={handleToggleAll}
              />
            </div>
          )}

          {discoveredTools && discoveredTools.length === 0 && (
            <p className="text-[12px] text-text-faint">
              Server responded but advertises no tools.
            </p>
          )}

          {/* Provider */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Provider
            </label>
            <input
              type="text"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              placeholder="e.g. Pitchbook, Microsoft, Stripe"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
            />
            <p className="mt-1 text-[11px] text-text-faint">
              Tools registered here appear in the &ldquo;MCP Integrations&rdquo;
              section, grouped by provider name.
            </p>
          </div>

          {/* Auth Type */}
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
              Authentication
            </label>
            <select
              value={authType}
              onChange={(e) => setAuthType(e.target.value as AuthType)}
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary focus:border-accent focus:outline-none"
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
                        "text-body-default font-medium",
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

          {/* Manual fields — only shown when no discovered tools to import */}
          {!discoveredTools && (
            <>
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
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              {/* Description */}
              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Description{" "}
                  <span className="normal-case tracking-normal text-text-faint opacity-60">
                    (optional)
                  </span>
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What this tool does and when to use it"
                  rows={3}
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
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
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
                <p className="mt-1 text-[11px] text-text-faint">
                  Comma-separated list of capabilities
                </p>
              </div>
            </>
          )}

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
            className="rounded-control border border-border px-4 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Cancel
          </button>
          {discoveredTools && discoveredTools.length > 0 ? (
            <button
              type="button"
              onClick={handleImportSelected}
              disabled={!canImportSelected || registerMutation.isPending}
              className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
            >
              {registerMutation.isPending
                ? "Importing…"
                : `Import ${selectedToolNames.size} Tool${selectedToolNames.size !== 1 ? "s" : ""}`}
            </button>
          ) : (
            <button
              type="button"
              onClick={handleRegister}
              disabled={!canRegisterManual || registerMutation.isPending}
              className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
            >
              {registerMutation.isPending
                ? "Registering..."
                : "Register & Test"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
