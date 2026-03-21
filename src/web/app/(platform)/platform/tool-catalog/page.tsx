"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ToolList } from "./elements/ToolList";
import { ToolRegistrationForm } from "./elements/ToolRegistrationForm";
import type { Tool } from "@/lib/hooks/useToolCatalog";

/**
 * FE-045: Tool Catalog Management.
 * Platform admin page for registering, monitoring, and retiring tools.
 */
export default function ToolCatalogPage() {
  const [showRegisterForm, setShowRegisterForm] = useState(false);
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
          <button
            type="button"
            onClick={() => setShowRegisterForm(true)}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            Register Tool
          </button>
        </div>

        {/* Tool list */}
        <ErrorBoundary>
          <ToolList onView={handleView} />
        </ErrorBoundary>

        {/* Registration form */}
        {showRegisterForm && (
          <ToolRegistrationForm onClose={() => setShowRegisterForm(false)} />
        )}
      </div>
    </AppShell>
  );
}
