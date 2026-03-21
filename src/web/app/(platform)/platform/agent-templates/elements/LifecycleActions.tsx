"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import {
  usePublishAgentTemplate,
  useDeprecateAgentTemplate,
  type AgentTemplateAdmin,
} from "@/lib/hooks/useAgentTemplatesAdmin";

interface LifecycleActionsProps {
  template: AgentTemplateAdmin;
  onClose: () => void;
}

/**
 * Publish/Deprecate lifecycle buttons for Platform Admin template detail.
 *
 * - Draft templates: show "Publish" button (requires changelog).
 * - Published templates: show "Deprecate" button (destructive, visually separated).
 * - Deprecated templates: no actions available.
 */
export function LifecycleActions({
  template,
  onClose,
}: LifecycleActionsProps) {
  const [changelog, setChangelog] = useState("");
  const [showChangelogInput, setShowChangelogInput] = useState(false);
  const publishMutation = usePublishAgentTemplate();
  const deprecateMutation = useDeprecateAgentTemplate();

  const isDraft = template.status === "Draft";
  const isPublished = template.status === "Published";
  const isDeprecated = template.status === "Deprecated";

  async function handlePublish() {
    if (!showChangelogInput) {
      setShowChangelogInput(true);
      return;
    }
    if (!changelog.trim()) return;

    await publishMutation.mutateAsync({
      id: template.id,
      changelog: changelog.trim(),
    });
    onClose();
  }

  async function handleDeprecate() {
    if (
      !window.confirm(
        "Deprecate this template? Tenants using it will no longer receive updates.",
      )
    ) {
      return;
    }
    await deprecateMutation.mutateAsync(template.id);
    onClose();
  }

  if (isDeprecated) {
    return (
      <p className="text-xs text-text-faint">
        This template is deprecated. No lifecycle actions available.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <label className="block text-[11px] uppercase tracking-wider text-text-faint">
        Lifecycle
      </label>

      {isDraft && (
        <div className="space-y-2">
          {showChangelogInput && (
            <div>
              <label className="mb-1 block text-[11px] text-text-muted">
                Changelog (required for publishing)
              </label>
              <textarea
                value={changelog}
                onChange={(e) => setChangelog(e.target.value)}
                placeholder="Describe what changed in this version..."
                rows={3}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
              />
            </div>
          )}
          <button
            type="button"
            onClick={handlePublish}
            disabled={
              publishMutation.isPending ||
              (showChangelogInput && !changelog.trim())
            }
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            {publishMutation.isPending && (
              <Loader2 size={14} className="animate-spin" />
            )}
            {showChangelogInput ? "Confirm Publish" : "Publish Template"}
          </button>

          {publishMutation.error && (
            <p className="text-xs text-alert">
              {publishMutation.error instanceof Error
                ? publishMutation.error.message
                : "Publish failed"}
            </p>
          )}
        </div>
      )}

      {isPublished && (
        <div className="mt-4 border-t border-border pt-4">
          <button
            type="button"
            onClick={handleDeprecate}
            disabled={deprecateMutation.isPending}
            className="flex items-center gap-1.5 rounded-control border border-alert/30 px-4 py-1.5 text-body-default text-alert transition-colors hover:bg-alert-dim disabled:opacity-30"
          >
            {deprecateMutation.isPending && (
              <Loader2 size={14} className="animate-spin" />
            )}
            Deprecate Template
          </button>
          <p className="mt-1 text-[11px] text-text-faint">
            Deprecating prevents tenants from deploying new instances.
          </p>

          {deprecateMutation.error && (
            <p className="mt-1 text-xs text-alert">
              {deprecateMutation.error instanceof Error
                ? deprecateMutation.error.message
                : "Deprecation failed"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
