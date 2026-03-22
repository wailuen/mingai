"use client";

const ACCESS_MODE_LABELS: Record<string, string> = {
  workspace_wide: "All workspace members",
  role_restricted: "Role-restricted",
  user_specific: "Specific users",
};

interface DeploySuccessOverlayProps {
  agentName: string;
  kbCount: number;
  accessMode: string;
  onGoToAgents: () => void;
  onDeployAnother: () => void;
}

export function DeploySuccessOverlay({
  agentName,
  kbCount,
  accessMode,
  onGoToAgents,
  onDeployAnother,
}: DeploySuccessOverlayProps) {
  const accessLabel = ACCESS_MODE_LABELS[accessMode] ?? accessMode;
  const summaryParts = [
    kbCount > 0
      ? `Bound to ${kbCount} knowledge base${kbCount !== 1 ? "s" : ""}`
      : "No knowledge bases",
    `Access: ${accessLabel}`,
  ];

  return (
    <div className="flex flex-col items-center gap-4 p-8 text-center">
      {/* Animated checkmark */}
      <div className="flex h-14 w-14 items-center justify-center">
        <svg
          viewBox="0 0 40 40"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="h-10 w-10"
          aria-hidden="true"
        >
          <circle
            cx="20"
            cy="20"
            r="18"
            stroke="var(--accent)"
            strokeWidth="2"
            fill="var(--accent-dim)"
          />
          <path
            d="M12 20.5l5.5 5.5 10-11"
            stroke="var(--accent)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              strokeDasharray: 28,
              strokeDashoffset: 0,
              animation: "checkDraw 600ms ease forwards",
            }}
          />
          <style>{`
            @keyframes checkDraw {
              from { stroke-dashoffset: 28; }
              to   { stroke-dashoffset: 0; }
            }
          `}</style>
        </svg>
      </div>

      {/* Agent name */}
      <div>
        <p className="text-page-title text-text-primary">{agentName}</p>
        <p className="mt-1 text-body-default text-accent">
          Successfully deployed
        </p>
      </div>

      {/* Summary */}
      <p className="text-body-default text-text-muted">
        {summaryParts.join(" · ")}
      </p>

      {/* Actions */}
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:gap-3">
        <button
          type="button"
          onClick={onGoToAgents}
          className="rounded-control bg-accent px-5 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
        >
          Go to Agents
        </button>
        <button
          type="button"
          onClick={onDeployAnother}
          className="rounded-control border border-border px-5 py-2 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
        >
          Deploy Another
        </button>
      </div>
    </div>
  );
}
