"use client";

import { CheckCircle, Loader2 } from "lucide-react";
import { useCompleteOnboarding } from "@/lib/hooks/useOnboarding";
import { useRouter } from "next/navigation";

interface StepCompleteProps {
  onBack: () => void;
}

const PRODUCT_NAME = "mingai";

export function StepComplete({ onBack }: StepCompleteProps) {
  const completeMutation = useCompleteOnboarding();
  const router = useRouter();

  async function handleComplete() {
    await completeMutation.mutateAsync();
    router.push("/");
  }

  return (
    <div className="flex flex-col items-center py-8 text-center">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-card bg-accent-dim">
        <CheckCircle size={32} className="text-accent" />
      </div>

      <h2 className="text-page-title text-text-primary">
        You&apos;re all set!
      </h2>
      <p className="mt-2 max-w-md text-body-default leading-relaxed text-text-muted">
        Your workspace is ready. Start exploring your AI agents, connect
        knowledge sources, and invite your team as you go.
      </p>

      {completeMutation.isError && (
        <div className="mt-4 rounded-control border border-alert/30 bg-alert-dim px-4 py-2">
          <p className="text-xs text-alert">
            {completeMutation.error instanceof Error
              ? completeMutation.error.message
              : "Failed to complete onboarding"}
          </p>
        </div>
      )}

      <div className="mt-8 flex items-center gap-3">
        <button
          onClick={onBack}
          className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
        >
          Back
        </button>
        <button
          onClick={handleComplete}
          disabled={completeMutation.isPending}
          className="inline-flex items-center gap-1.5 rounded-control bg-accent px-6 py-2 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
        >
          {completeMutation.isPending && (
            <Loader2 size={14} className="animate-spin" />
          )}
          Start using {PRODUCT_NAME}
        </button>
      </div>
    </div>
  );
}
