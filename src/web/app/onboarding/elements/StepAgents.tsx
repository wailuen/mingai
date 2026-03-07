"use client";

import Link from "next/link";

interface StepAgentsProps {
  onNext: () => void;
  onBack: () => void;
  onSkip?: () => void;
}

interface AgentSuggestion {
  name: string;
  description: string;
  slug: string;
}

const SUGGESTED_AGENTS: AgentSuggestion[] = [
  {
    name: "HR Assistant",
    description:
      "Answer employee questions about policies, benefits, and leave management.",
    slug: "hr-assistant",
  },
  {
    name: "IT Helpdesk",
    description:
      "Troubleshoot common IT issues, manage access requests, and guide through setups.",
    slug: "it-helpdesk",
  },
  {
    name: "Onboarding Guide",
    description:
      "Walk new hires through company processes, tools, and resources.",
    slug: "onboarding-guide",
  },
];

export function StepAgents({ onNext, onBack, onSkip }: StepAgentsProps) {
  return (
    <div className="space-y-6 py-4">
      <div>
        <h2 className="text-section-heading text-text-primary">
          Explore Your First Agent
        </h2>
        <p className="mt-1 text-sm text-text-muted">
          Try one of these pre-built agents to see what your AI workspace can
          do.
        </p>
      </div>

      <div className="space-y-3">
        {SUGGESTED_AGENTS.map((agent) => (
          <div
            key={agent.slug}
            className="flex items-center justify-between rounded-card border border-border bg-bg-elevated p-4 transition-colors hover:border-accent-ring"
          >
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-text-primary">
                {agent.name}
              </h3>
              <p className="mt-0.5 text-xs text-text-muted">
                {agent.description}
              </p>
            </div>
            <Link
              href={`/chat?agent=${agent.slug}`}
              onClick={onNext}
              className="ml-4 shrink-0 rounded-control border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:border-accent-ring hover:bg-accent-dim hover:text-text-primary"
            >
              Try this agent
            </Link>
          </div>
        ))}
      </div>

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
        >
          Back
        </button>
        <div className="flex items-center gap-3">
          <button
            onClick={onSkip ?? onNext}
            className="text-sm text-text-faint transition-colors hover:text-text-muted"
          >
            Skip this step
          </button>
          <button
            onClick={onNext}
            className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
