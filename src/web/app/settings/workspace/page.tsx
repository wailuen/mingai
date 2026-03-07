"use client";

import { useState, useEffect } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { apiGet, apiPatch } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { Settings, Save, CheckCircle2 } from "lucide-react";
import { Skeleton } from "@/components/shared/LoadingState";
import { LogoUpload } from "./elements/LogoUpload";
import { TimezoneSelector } from "./elements/TimezoneSelector";

interface WorkspaceSettings {
  tenant_name: string;
  slug: string;
  logo_url: string | null;
  timezone: string;
  locale: string;
  plan: string;
  welcome_message: string;
  system_prompt_budget: number;
  max_conversation_length: number;
}

const SUPPORTED_LOCALES = [
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
  { value: "ms-MY", label: "Malay (Malaysia)" },
  { value: "zh-CN", label: "Chinese (Simplified)" },
  { value: "zh-TW", label: "Chinese (Traditional)" },
  { value: "ja-JP", label: "Japanese" },
  { value: "ko-KR", label: "Korean" },
  { value: "de-DE", label: "German" },
  { value: "fr-FR", label: "French" },
  { value: "es-ES", label: "Spanish" },
  { value: "pt-BR", label: "Portuguese (Brazil)" },
];

/**
 * FE-028: Workspace settings page.
 * Display name (100-char limit), logo, timezone, locale, plan info.
 * Save button with success toast. Unsaved changes warning.
 */
export default function WorkspaceSettingsPage() {
  const { data: settings, isLoading } = useQuery<WorkspaceSettings>({
    queryKey: ["workspace-settings"],
    queryFn: () =>
      apiGet<WorkspaceSettings>("/api/v1/admin/workspace-settings"),
  });

  const [form, setForm] = useState<WorkspaceSettings>({
    tenant_name: "",
    slug: "",
    logo_url: null,
    timezone: "UTC",
    locale: "en-US",
    plan: "",
    welcome_message: "",
    system_prompt_budget: 2000,
    max_conversation_length: 50,
  });
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  // Track dirty state for unsaved changes warning
  useEffect(() => {
    if (!settings) return;
    const hasChanges =
      form.tenant_name !== settings.tenant_name ||
      form.timezone !== settings.timezone ||
      form.locale !== settings.locale ||
      form.welcome_message !== settings.welcome_message ||
      form.system_prompt_budget !== settings.system_prompt_budget ||
      logoFile !== null;
    setDirty(hasChanges);
  }, [form, settings, logoFile]);

  // Unsaved changes warning
  useEffect(() => {
    function handleBeforeUnload(e: BeforeUnloadEvent) {
      if (dirty) {
        e.preventDefault();
      }
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    try {
      await apiPatch("/api/v1/admin/workspace-settings", {
        tenant_name: form.tenant_name,
        timezone: form.timezone,
        locale: form.locale,
        welcome_message: form.welcome_message,
        system_prompt_budget: form.system_prompt_budget,
        max_conversation_length: form.max_conversation_length,
      });
      setSaved(true);
      setDirty(false);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      // Error surfaced by API layer
    } finally {
      setSaving(false);
    }
  }

  function updateField<K extends keyof WorkspaceSettings>(
    field: K,
    value: WorkspaceSettings[K],
  ) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  if (isLoading) {
    return (
      <AppShell>
        <div className="p-7">
          <Skeleton className="mb-6 h-7 w-48" />
          <div className="mx-auto max-w-2xl space-y-6">
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <Skeleton className="mb-3 h-3 w-32" />
              <Skeleton className="h-9 w-full" />
            </div>
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <Skeleton className="mb-3 h-3 w-32" />
              <Skeleton className="h-20 w-full" />
            </div>
          </div>
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
          <div className="flex items-center gap-2">
            {saved && (
              <span className="flex items-center gap-1 text-sm text-accent">
                <CheckCircle2 size={14} />
                Saved
              </span>
            )}
            <button
              onClick={handleSave}
              disabled={saving || !dirty}
              className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
            >
              <Save size={14} />
              {saving ? "Saving..." : "Save Changes"}
            </button>
          </div>
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
                  updateField("tenant_name", e.target.value.slice(0, 100))
                }
                maxLength={100}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent focus:outline-none"
              />
              <div className="mt-1 flex items-center justify-between">
                <span className="text-xs text-text-faint">
                  Visible to all workspace members
                </span>
                <span className="font-mono text-xs text-text-faint">
                  {form.tenant_name.length}/100
                </span>
              </div>
            </div>

            {/* Slug (read-only) */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Workspace Slug
              </label>
              <input
                type="text"
                value={form.slug}
                readOnly
                className="w-full rounded-control border border-border-faint bg-bg-deep px-3 py-2 font-mono text-data-value text-text-faint"
              />
              <span className="mt-1 block text-xs text-text-faint">
                Cannot be changed after creation
              </span>
            </div>

            {/* Plan badge */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Current Plan
              </label>
              <span className="inline-block rounded-badge border border-accent/30 bg-accent/10 px-3 py-1 font-mono text-sm font-medium text-accent">
                {form.plan || "Standard"}
              </span>
            </div>

            {/* Logo upload */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-3 block text-label-nav uppercase tracking-wider text-text-faint">
                Workspace Logo
              </label>
              <LogoUpload
                currentLogo={form.logo_url}
                onLogoChange={setLogoFile}
              />
            </div>

            {/* Timezone */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Timezone
              </label>
              <TimezoneSelector
                value={form.timezone}
                onChange={(tz) => updateField("timezone", tz)}
              />
            </div>

            {/* Locale */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Locale
              </label>
              <select
                value={form.locale}
                onChange={(e) => updateField("locale", e.target.value)}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary transition-colors focus:border-accent focus:outline-none"
              >
                {SUPPORTED_LOCALES.map((loc) => (
                  <option key={loc.value} value={loc.value}>
                    {loc.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Welcome message */}
            <div className="rounded-card border border-border bg-bg-surface p-5">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Welcome Message
              </label>
              <textarea
                value={form.welcome_message}
                onChange={(e) => updateField("welcome_message", e.target.value)}
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
                    updateField("system_prompt_budget", Number(e.target.value))
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
