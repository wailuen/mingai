"use client";

import { useState } from "react";
import { Plus, FileCode } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ToolList } from "./elements/ToolList";
import { ToolRegistrationForm } from "./elements/ToolRegistrationForm";
import { MCPIntegrationBuilder } from "./elements/MCPIntegrationBuilder";
import type { Tool } from "@/lib/hooks/useToolCatalog";

/**
 * FE-045: Tool Catalog Management.
 * Platform admin page for registering, monitoring, and retiring tools.
 * TODO-22: Adds MCP Integration Builder for importing tools from API docs.
 */
export default function ToolCatalogPage() {
  const [showRegisterForm, setShowRegisterForm] = useState(false);
  const [showMCPBuilder, setShowMCPBuilder] = useState(false);
  const [_selectedTool, setSelectedTool] = useState<Tool | null>(null);

  function handleView(tool: Tool) {
    setSelectedTool(tool);
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-page-title text-text-primary">Tool Catalog</h1>
            <p className="mt-1 text-body-default text-text-muted">
              Register, monitor, and manage MCP tools
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowMCPBuilder(true)}
              className="flex items-center gap-1.5 rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              <FileCode size={15} />
              From API Doc
            </button>
            <button
              type="button"
              onClick={() => setShowRegisterForm(true)}
              className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
            >
              <Plus size={16} />
              Register Tool
            </button>
          </div>
        </div>

        {/* Tool list */}
        <ErrorBoundary>
          <ToolList onView={handleView} />
        </ErrorBoundary>

        {/* Manual registration slide-in */}
        {showRegisterForm && (
          <ToolRegistrationForm onClose={() => setShowRegisterForm(false)} />
        )}

        {/* MCP Integration Builder wizard */}
        {showMCPBuilder && (
          <MCPIntegrationBuilder onClose={() => setShowMCPBuilder(false)} />
        )}
      </div>
    </AppShell>
  );
}
