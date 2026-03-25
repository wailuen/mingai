"use client";

import { useState } from "react";
import { Loader2, CheckCircle2, Archive } from "lucide-react";
import {
  usePublishLLMLibraryEntry,
  useDeprecateLLMLibraryEntry,
  useTenantAssignments,
  type LLMLibraryEntry,
} from "@/lib/hooks/useLLMLibrary";

interface LifecycleActionsProps {
  entry: LLMLibraryEntry;
}

export function LifecycleActions({ entry }: LifecycleActionsProps) {
  const publishMutation = usePublishLLMLibraryEntry();
  const deprecateMutation = useDeprecateLLMLibraryEntry();
  const [showDeprecateConfirm, setShowDeprecateConfirm] = useState(false);

  // Fetch tenant assignments when deprecation dialog is open
  const { data: assignments } = useTenantAssignments(
    showDeprecateConfirm ? entry.id : null,
  );
  const tenantCount = assignments?.length ?? 0;

  function handlePublish() {
    publishMutation.mutate(entry.id);
  }

  function handleDeprecate() {
    deprecateMutation.mutate(entry.id, {
      onSuccess: () => setShowDeprecateConfirm(false),
    });
  }

  if (entry.status === "Deprecated") {
    return (
      <span
        className="inline-flex items-center gap-1 text-[11px] text-text-faint"
        title="Cannot change status of deprecated models"
      >
        <Archive size={12} />
        Deprecated
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      {entry.status === "Draft" && (() => {
        const canPublish = !!entry.last_test_passed_at;
        const publishTitle = canPublish
          ? undefined
          : "Run the connectivity test before publishing";
        return (
          <button
            type="button"
            onClick={handlePublish}
            disabled={publishMutation.isPending || !canPublish}
            title={publishTitle}
            className="inline-flex items-center gap-1 rounded-control bg-accent px-2.5 py-1 text-[11px] font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {publishMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <CheckCircle2 size={12} />
            )}
            Publish
          </button>
        );
      })()}

      {entry.status === "Published" && (
        <>
          {!showDeprecateConfirm ? (
            <div className="flex items-center gap-2">
              {entry.profile_usage_count > 0 && (
                <span
                  className="inline-block rounded-badge border border-border px-1.5 py-0.5 font-mono text-[10px] text-text-faint"
                  title={`Used in ${entry.profile_usage_count} LLM Profile${entry.profile_usage_count !== 1 ? "s" : ""} — remove from profiles before deprecating`}
                >
                  {entry.profile_usage_count} profile{entry.profile_usage_count !== 1 ? "s" : ""}
                </span>
              )}
              <button
                type="button"
                onClick={() => setShowDeprecateConfirm(true)}
                disabled={entry.profile_usage_count > 0}
                title={
                  entry.profile_usage_count > 0
                    ? `Used in ${entry.profile_usage_count} profile${entry.profile_usage_count !== 1 ? "s" : ""} — remove from all profiles first`
                    : undefined
                }
                className="inline-flex items-center gap-1 rounded-control border border-border px-2.5 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Archive size={12} />
                Deprecate
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-text-muted">
                {tenantCount > 0
                  ? `${tenantCount} tenant${tenantCount !== 1 ? "s" : ""} ${tenantCount !== 1 ? "are" : "is"} using this profile. Existing assignments are preserved.`
                  : "No tenants are using this profile. Confirm deprecation?"}
              </span>
              <button
                type="button"
                onClick={handleDeprecate}
                disabled={deprecateMutation.isPending}
                className="inline-flex items-center gap-1 rounded-control bg-alert px-2.5 py-1 text-[11px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {deprecateMutation.isPending ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Archive size={12} />
                )}
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setShowDeprecateConfirm(false)}
                className="rounded-control border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:bg-bg-elevated"
              >
                Cancel
              </button>
            </div>
          )}
        </>
      )}

      {publishMutation.error && (
        <span className="text-[11px] text-alert">
          {publishMutation.error.message}
        </span>
      )}
      {deprecateMutation.error && (
        <span className="text-[11px] text-alert">
          {deprecateMutation.error.message}
        </span>
      )}
    </div>
  );
}
