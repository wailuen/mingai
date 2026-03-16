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
      {entry.status === "Draft" && (
        <button
          type="button"
          onClick={handlePublish}
          disabled={publishMutation.isPending}
          className="inline-flex items-center gap-1 rounded-control bg-accent px-2.5 py-1 text-[11px] font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {publishMutation.isPending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <CheckCircle2 size={12} />
          )}
          Publish
        </button>
      )}

      {entry.status === "Published" && (
        <>
          {!showDeprecateConfirm ? (
            <button
              type="button"
              onClick={() => setShowDeprecateConfirm(true)}
              className="inline-flex items-center gap-1 rounded-control border border-border px-2.5 py-1 text-[11px] text-alert transition-colors hover:bg-alert-dim"
            >
              <Archive size={12} />
              Deprecate
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-text-muted">
                {tenantCount > 0
                  ? `${tenantCount} tenant${tenantCount !== 1 ? "s" : ""} ${tenantCount !== 1 ? "are" : "is"} using this profile. Existing assignments are preserved.`
                  : "No tenants are using this profile. Existing assignments are preserved."}
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
