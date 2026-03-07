"use client";

import { Database, SkipForward } from "lucide-react";
import Link from "next/link";

interface StepKnowledgeBaseProps {
  onNext: () => void;
  onBack: () => void;
  onSkip?: () => void;
}

export function StepKnowledgeBase({
  onNext,
  onBack,
  onSkip,
}: StepKnowledgeBaseProps) {
  return (
    <div className="space-y-6 py-4">
      <div>
        <h2 className="text-section-heading text-text-primary">
          Connect Your Knowledge Base
        </h2>
        <p className="mt-1 text-sm text-text-muted">
          Connect a document source so your AI agents can access your
          organization&apos;s knowledge.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Link
          href="/settings/knowledge-base"
          onClick={onNext}
          className="rounded-card border border-border bg-bg-elevated p-4 text-left transition-colors hover:border-accent-ring hover:bg-accent-dim"
        >
          <Database size={20} className="mb-2 text-text-muted" />
          <h3 className="text-sm font-semibold text-text-primary">
            Connect SharePoint
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-text-muted">
            Index documents from your SharePoint Online libraries for AI-powered
            retrieval.
          </p>
        </Link>

        <button
          onClick={onSkip ?? onNext}
          className="rounded-card border border-border-faint bg-bg-elevated p-4 text-left transition-colors hover:border-accent-ring hover:bg-accent-dim"
        >
          <SkipForward size={20} className="mb-2 text-text-faint" />
          <h3 className="text-sm font-semibold text-text-primary">
            Skip for now
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-text-muted">
            You can connect a knowledge base later from Settings.
          </p>
        </button>
      </div>

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
        >
          Back
        </button>
        <button
          onClick={onSkip ?? onNext}
          className="text-sm text-text-faint transition-colors hover:text-text-muted"
        >
          Skip this step
        </button>
      </div>
    </div>
  );
}
