"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ProfileLearningPolicy } from "./elements/ProfileLearningPolicy";
import { WorkingMemoryPolicy } from "./elements/WorkingMemoryPolicy";
import { MemoryNotesPolicy } from "./elements/MemoryNotesPolicy";
import {
  useMemoryPolicy,
  useUpdateMemoryPolicy,
  type MemoryPolicy,
} from "@/lib/hooks/useMemoryPolicy";

/**
 * FE-052: Memory policy settings page (Tenant Admin).
 * Orchestrator only -- toggle cards live in elements/.
 */
export default function MemoryPolicyPage() {
  const { data: policy, isPending, error } = useMemoryPolicy();
  const updateMutation = useUpdateMemoryPolicy();

  const [localPolicy, setLocalPolicy] = useState<MemoryPolicy>({
    profile_learning_enabled: true,
    working_memory_enabled: true,
    working_memory_ttl_days: 7,
    memory_notes_enabled: true,
    memory_notes_auto_extract: true,
  });

  useEffect(() => {
    if (policy) {
      setLocalPolicy(policy);
    }
  }, [policy]);

  const handleUpdate = useCallback(
    (patch: Partial<MemoryPolicy>) => {
      const updated = { ...localPolicy, ...patch };
      setLocalPolicy(updated);
      updateMutation.mutate(updated);
    },
    [localPolicy, updateMutation],
  );

  if (error) {
    return (
      <AppShell>
        <div className="p-7">
          <p className="text-body-default text-alert">
            Failed to load memory policy settings.
          </p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Memory Settings</h1>
          <p className="mt-1 text-body-default text-text-muted">
            Configure how AI memory and learning works across your workspace
          </p>
        </div>

        <div className="mx-auto max-w-2xl space-y-5">
          {isPending ? (
            <div className="space-y-5">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-32 animate-pulse rounded-card border border-border bg-bg-surface"
                />
              ))}
            </div>
          ) : (
            <>
              <ErrorBoundary>
                <ProfileLearningPolicy
                  enabled={localPolicy.profile_learning_enabled}
                  onToggle={(v) =>
                    handleUpdate({ profile_learning_enabled: v })
                  }
                  saving={updateMutation.isPending}
                />
              </ErrorBoundary>

              <ErrorBoundary>
                <WorkingMemoryPolicy
                  enabled={localPolicy.working_memory_enabled}
                  ttlDays={localPolicy.working_memory_ttl_days}
                  onToggle={(v) => handleUpdate({ working_memory_enabled: v })}
                  onTtlChange={(days) =>
                    handleUpdate({ working_memory_ttl_days: days })
                  }
                  saving={updateMutation.isPending}
                />
              </ErrorBoundary>

              <ErrorBoundary>
                <MemoryNotesPolicy
                  enabled={localPolicy.memory_notes_enabled}
                  autoExtract={localPolicy.memory_notes_auto_extract}
                  onToggle={(v) => handleUpdate({ memory_notes_enabled: v })}
                  onAutoExtractToggle={(v) =>
                    handleUpdate({ memory_notes_auto_extract: v })
                  }
                  saving={updateMutation.isPending}
                />
              </ErrorBoundary>
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
