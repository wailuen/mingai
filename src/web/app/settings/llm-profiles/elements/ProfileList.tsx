"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { Skeleton } from "@/components/shared/LoadingState";
import { Cpu, Trash2 } from "lucide-react";
import { DeleteProfileDialog } from "./DeleteProfileDialog";

export interface LLMProfile {
  id: string;
  tenant_id: string;
  name: string;
  provider: string;
  primary_model: string;
  intent_model: string;
  embedding_model: string;
  endpoint_url: string;
  is_default: boolean;
  created_at: string;
}

const SLOT_FIELDS: {
  key: keyof LLMProfile;
  label: string;
}[] = [
  { key: "primary_model", label: "Primary" },
  { key: "intent_model", label: "Intent" },
  { key: "embedding_model", label: "Embedding" },
];

export function ProfileList() {
  const {
    data: profiles,
    isPending,
    error,
  } = useQuery<LLMProfile[]>({
    queryKey: ["llm-profiles"],
    queryFn: () => apiGet<LLMProfile[]>("/api/v1/platform/llm-profiles"),
  });

  const [deleteTarget, setDeleteTarget] = useState<LLMProfile | null>(null);

  if (isPending) {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div
            key={i}
            className="rounded-card border border-border bg-bg-surface p-5"
          >
            <Skeleton className="mb-3 h-4 w-40" />
            <Skeleton className="mb-2 h-3 w-full" />
            <Skeleton className="mb-4 h-3 w-2/3" />
            <div className="grid grid-cols-3 gap-2">
              {Array.from({ length: 6 }).map((_, j) => (
                <Skeleton key={j} className="h-8 w-full" />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load profiles: {error.message}
      </p>
    );
  }

  if (!profiles || profiles.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-card border border-border bg-bg-surface py-16">
        <div className="flex h-12 w-12 items-center justify-center rounded-card bg-bg-elevated">
          <Cpu size={24} className="text-text-faint" />
        </div>
        <div className="text-center">
          <p className="text-body-default font-medium text-text-muted">
            No LLM profiles configured
          </p>
          <p className="mt-1 max-w-sm text-xs text-text-faint">
            Create a profile to control which AI models your tenants use.
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {profiles.map((profile) => (
          <div
            key={profile.id}
            className="rounded-card border border-border bg-bg-surface p-5 transition-colors hover:border-accent-ring"
          >
            <div className="mb-3 flex items-start justify-between">
              <div>
                <h3 className="text-body-default font-medium text-text-primary">
                  {profile.name}
                </h3>
                <p className="mt-0.5 text-xs text-text-faint">
                  {profile.provider}
                  {profile.is_default && (
                    <span className="ml-2 rounded-badge border border-accent/30 bg-accent-dim px-1.5 py-0.5 text-[10px] font-medium text-accent">
                      DEFAULT
                    </span>
                  )}
                </p>
              </div>
              <button
                onClick={() => setDeleteTarget(profile)}
                className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
              >
                <Trash2 size={14} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {SLOT_FIELDS.map(({ key, label }) => (
                <div
                  key={key}
                  className="rounded-control border border-border-faint bg-bg-elevated px-2.5 py-1.5"
                >
                  <span className="block text-[10px] uppercase tracking-wider text-text-faint">
                    {label}
                  </span>
                  <span className="block truncate font-mono text-data-value text-text-muted">
                    {(profile[key] as string) || "\u2014"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {deleteTarget && (
        <DeleteProfileDialog
          profile={deleteTarget}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </>
  );
}
