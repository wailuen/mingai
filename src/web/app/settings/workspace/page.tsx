"use client";

import { useState, useEffect } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { apiRequest, apiPatch } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { Settings, Save } from "lucide-react";

interface WorkspaceSettings {
  tenant_name: string;
  default_agent_id: string;
  system_prompt_budget: number;
  max_conversation_length: number;
  welcome_message: string;
}

/**
 * FE-028: Workspace settings page.
 * General workspace configuration for tenant admins.
 */
export default function WorkspaceSettingsPage() {
  const { data: settings, isLoading } = useQuery<WorkspaceSettings>({
    queryKey: ["workspace-settings"],
    queryFn: () =>
      apiRequest<WorkspaceSettings>("/api/v1/admin/workspace-settings"),
  });

  const [form, setForm] = useState<WorkspaceSettings>({
    tenant_name: "",
    default_agent_id: "",
    system_prompt_budget: 2000,
    max_conversation_length: 50,
    welcome_message: "",
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    try {
      await apiPatch("/api/v1/admin/workspace-settings", form);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      // Error handled
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return (
      <AppShell>
        <div className="p-7">
          <div className="h-6 w-48 animate-pulse rounded bg-bg-elevated" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Settings size={20} className="text-text-faint" />
            <h1 className="text-page-title text-text-primary">
              Workspace Settings
            </h1>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            <Save size={14} />
            {saving ? "Saving..." : saved ? "Saved" : "Save Changes"}
          </button>
        </div>

        <ErrorBoundary>
          <div className="mx-auto max-w-2xl space-y-6">
            {/* Workspace name */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Workspace Name
              </label>
              <input
                type="text"
                value={form.tenant_name}
                onChange={(e) =>
                  setForm({ ...form, tenant_name: e.target.value })
                }
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent focus:outline-none"
              />
            </div>

            {/* Welcome message */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Welcome Message
              </label>
              <textarea
                value={form.welcome_message}
                onChange={(e) =>
                  setForm({ ...form, welcome_message: e.target.value })
                }
                rows={3}
                placeholder="Good morning! What would you like to know today?"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>

            {/* System prompt budget */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                System Prompt Token Budget
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1000}
                  max={4000}
                  step={100}
                  value={form.system_prompt_budget}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      system_prompt_budget: Number(e.target.value),
                    })
                  }
                  className="flex-1"
                />
                <span className="font-mono text-sm text-text-primary">
                  {form.system_prompt_budget}
                </span>
              </div>
              <p className="mt-1 text-xs text-text-faint">
                Higher budget allows more context but costs more tokens per
                query
              </p>
            </div>
          </div>
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
