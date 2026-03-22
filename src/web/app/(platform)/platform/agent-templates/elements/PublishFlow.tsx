"use client";

import { useState } from "react";
import { CheckCircle, AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { usePublishAgentTemplate } from "@/lib/hooks/useAgentTemplatesAdmin";
import type { AgentTemplateAdmin } from "@/lib/hooks/useAgentTemplatesAdmin";

interface PublishFlowProps {
  template: AgentTemplateAdmin;
  onClose: () => void;
  onPublished: () => void;
}

const SEMVER_RE = /^\d+\.\d+\.\d+$/;

type ChangeType = "Patch" | "Minor" | "Major";

function detectChangeType(template: AgentTemplateAdmin): ChangeType {
  // If auth_mode or required_credentials changed from defaults → Major
  if (
    template.auth_mode !== "none" ||
    (template.required_credentials && template.required_credentials.length > 0)
  ) {
    return "Major";
  }
  // If system_prompt or guardrails present → Minor
  if (template.system_prompt || (template.guardrails && template.guardrails.length > 0)) {
    return "Minor";
  }
  return "Patch";
}

interface CheckItem {
  label: string;
  passed: boolean;
  warning?: boolean;
}

function buildChecklist(template: AgentTemplateAdmin): CheckItem[] {
  const items: CheckItem[] = [
    {
      label: "Template name provided",
      passed: template.name.trim().length > 0,
    },
    {
      label: "Description provided",
      passed: (template.description ?? "").trim().length > 0,
    },
    {
      label: "Category set",
      passed: (template.category ?? "").trim().length > 0,
    },
    {
      label: "System prompt filled",
      passed: template.system_prompt.trim().length > 0,
    },
  ];

  // Warn if tools assigned but auth_mode is none
  if (
    (template.attached_tools ?? []).length > 0 &&
    template.auth_mode === "none"
  ) {
    items.push({
      label: "Tools assigned but auth_mode is 'none' — credentials may be required",
      passed: false,
      warning: true,
    });
  }

  return items;
}

export function PublishFlow({ template, onClose, onPublished }: PublishFlowProps) {
  const [versionLabel, setVersionLabel] = useState("");
  const [changelog, setChangelog] = useState("");

  const checklist = buildChecklist(template);
  const allPassed = checklist.filter((c) => !c.warning).every((c) => c.passed);
  const changeType = detectChangeType(template);

  const versionValid = SEMVER_RE.test(versionLabel.trim());
  const changelogValid = changelog.trim().length >= 10;
  const canPublish = allPassed && versionValid && changelogValid;

  const publishMutation = usePublishAgentTemplate();

  async function handleConfirm() {
    if (!canPublish) return;
    await publishMutation.mutateAsync({
      id: template.id,
      version_label: versionLabel.trim(),
      changelog: changelog.trim(),
    });
    onPublished();
  }

  const changeTypeBadgeStyles: Record<ChangeType, string> = {
    Patch: "bg-accent-dim text-accent",
    Minor: "bg-warn-dim text-warn",
    Major: "bg-alert-dim text-alert",
  };

  return (
    <div className="mt-4 rounded-card border border-border bg-bg-elevated p-4">
      <h3 className="mb-3 text-section-heading text-text-primary">
        Publish Template
      </h3>

      {/* Pre-publish checklist */}
      <div className="mb-4 space-y-1.5">
        {checklist.map((item, i) => (
          <div key={i} className="flex items-center gap-2">
            {item.passed ? (
              <CheckCircle size={14} className="flex-shrink-0 text-accent" />
            ) : item.warning ? (
              <AlertTriangle size={14} className="flex-shrink-0 text-warn" />
            ) : (
              <AlertTriangle size={14} className="flex-shrink-0 text-alert" />
            )}
            <span
              className={cn(
                "text-body-default",
                item.passed
                  ? "text-text-muted"
                  : item.warning
                    ? "text-warn"
                    : "text-alert",
              )}
            >
              {item.label}
            </span>
          </div>
        ))}
      </div>

      {/* Version label */}
      <div className="mb-3">
        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
          Version Label <span className="text-alert">*</span>
        </label>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={versionLabel}
            onChange={(e) => setVersionLabel(e.target.value)}
            placeholder="1.0.0"
            className={cn(
              "flex-1 rounded-control border bg-bg-base px-3 py-2 font-mono text-body-default text-text-primary placeholder:text-text-faint focus:outline-none",
              versionLabel && !versionValid
                ? "border-alert focus:border-alert"
                : "border-border focus:border-accent",
            )}
          />
          <span
            className={cn(
              "inline-block rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
              changeTypeBadgeStyles[changeType],
            )}
          >
            {changeType}
          </span>
        </div>
        {versionLabel && !versionValid && (
          <p className="mt-0.5 text-[11px] text-alert">
            Use semver format: e.g. 1.0.0
          </p>
        )}
      </div>

      {/* Changelog */}
      <div className="mb-4">
        <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
          Changelog <span className="text-alert">*</span>
        </label>
        <textarea
          value={changelog}
          onChange={(e) => setChangelog(e.target.value)}
          placeholder="Describe what changed in this version (min 10 characters)..."
          rows={3}
          className="w-full rounded-control border border-border bg-bg-base px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
        />
        <p className="mt-0.5 text-[11px] text-text-faint">
          {changelog.trim().length} / 10 min chars
        </p>
      </div>

      {publishMutation.error && (
        <div className="mb-3 rounded-control border border-alert/30 bg-alert-dim px-3 py-2">
          <p className="text-body-default text-alert">
            {publishMutation.error instanceof Error
              ? publishMutation.error.message
              : "Publish failed"}
          </p>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleConfirm}
          disabled={!canPublish || publishMutation.isPending}
          className="flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {publishMutation.isPending && (
            <Loader2 size={14} className="animate-spin" />
          )}
          Confirm Publish
        </button>
        <button
          type="button"
          onClick={onClose}
          className="text-body-default text-text-faint transition-colors hover:text-text-muted"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
