"use client";

import { useState } from "react";
import { User } from "lucide-react";
import { apiPatch } from "@/lib/api";

interface WorkProfileCardProps {
  orgContextEnabled: boolean;
  shareManagerInfo: boolean;
}

/**
 * FE-018: Work profile card with toggles.
 * - Org context: "Use org context in responses"
 * - Sub-toggle: "Include manager name"
 * Both write to user_profiles via PATCH /api/v1/me/profile/privacy
 */
export function WorkProfileCard({
  orgContextEnabled: initialOrgContext,
  shareManagerInfo: initialShareManager,
}: WorkProfileCardProps) {
  const [orgContextEnabled, setOrgContextEnabled] = useState(initialOrgContext);
  const [shareManagerInfo, setShareManagerInfo] = useState(initialShareManager);
  const [saving, setSaving] = useState(false);

  async function toggleOrgContext() {
    const newValue = !orgContextEnabled;
    setOrgContextEnabled(newValue);
    if (!newValue) {
      setShareManagerInfo(false);
    }
    await saveSettings({
      org_context_enabled: newValue,
      share_manager_info: newValue ? shareManagerInfo : false,
    });
  }

  async function toggleShareManager() {
    const newValue = !shareManagerInfo;
    setShareManagerInfo(newValue);
    await saveSettings({
      org_context_enabled: orgContextEnabled,
      share_manager_info: newValue,
    });
  }

  async function saveSettings(settings: Record<string, boolean>) {
    setSaving(true);
    try {
      await apiPatch("/api/v1/me/profile/privacy", settings);
    } catch {
      // Revert on error
      setOrgContextEnabled(initialOrgContext);
      setShareManagerInfo(initialShareManager);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 flex items-center gap-2">
        <User size={18} className="text-accent" />
        <h3 className="text-section-heading text-text-primary">Work Profile</h3>
      </div>

      <div className="space-y-4">
        <ToggleRow
          label="Use organizational context in responses"
          description="Your role, department, and team info will personalize answers"
          checked={orgContextEnabled}
          onChange={toggleOrgContext}
          disabled={saving}
        />

        {orgContextEnabled && (
          <div className="ml-6">
            <ToggleRow
              label="Include manager name"
              description="Share your manager's name for org-aware responses"
              checked={shareManagerInfo}
              onChange={toggleShareManager}
              disabled={saving}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: () => void;
  disabled: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-sm font-medium text-text-primary">{label}</p>
        <p className="text-xs text-text-muted">{description}</p>
      </div>
      <button
        onClick={onChange}
        disabled={disabled}
        className={`relative h-5 w-9 flex-shrink-0 rounded-full transition-colors ${
          checked ? "bg-accent" : "bg-bg-elevated"
        }`}
        role="switch"
        aria-checked={checked}
      >
        <span
          className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </button>
    </div>
  );
}
