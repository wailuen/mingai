"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { HARAgent, KYBLevel } from "@/lib/hooks/useRegistry";
import {
  useInitiateConnection,
  type InitiateConnectionResult,
} from "@/lib/hooks/useRegistry";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function trustScoreColor(score: number): string {
  if (score >= 80) return "text-accent";
  if (score >= 50) return "text-warn";
  return "text-alert";
}

function kybLabelColor(level: KYBLevel): string {
  if (level === "none") return "text-text-faint border-border";
  return "text-accent border-accent/30 bg-accent-dim";
}

const KYB_LABELS: Record<KYBLevel, string> = {
  none: "No KYB",
  basic: "Basic",
  verified: "Verified",
  enterprise: "Enterprise",
};

interface ConnectModalProps {
  agent: HARAgent;
  onClose: () => void;
}

const _UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function ConnectModal({ agent, onClose }: ConnectModalProps) {
  const [fromAgentId, setFromAgentId] = useState("");
  const [success, setSuccess] = useState<InitiateConnectionResult | null>(null);
  const { mutate, isPending, error } = useInitiateConnection();
  const isValidUuid = _UUID_RE.test(fromAgentId.trim());

  function handleSubmit() {
    mutate(
      {
        from_agent_id: fromAgentId.trim(),
        to_agent_id: agent.id,
        message_type: "CAPABILITY_QUERY",
      },
      {
        onSuccess: (result) => setSuccess(result),
      },
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-card border border-border bg-bg-surface p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-1 text-section-heading text-text-primary">
          Connect to {agent.name}
        </h3>
        <p className="mb-4 text-body-default text-text-muted">
          Initiate an A2A connection request to this agent.
        </p>

        {success ? (
          <>
            <div className="mb-4 rounded-control border border-accent/30 bg-accent-dim p-3">
              <p className="text-xs font-medium text-accent">
                Connection request sent
              </p>
              <p className="mt-1 font-mono text-data-value text-text-faint">
                Transaction ID: {success.txn_id}
              </p>
              <p className="font-mono text-data-value text-text-faint">
                Status: {success.status}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="w-full rounded-control border border-border py-2 text-xs font-medium text-text-muted hover:text-text-primary"
            >
              Close
            </button>
          </>
        ) : (
          <>
            <div className="mb-4 space-y-2 rounded-control border border-border bg-bg-elevated p-3">
              <div className="flex justify-between text-xs">
                <span className="text-text-faint">Target Agent</span>
                <span className="font-mono text-text-primary">
                  {agent.id.slice(0, 8)}…
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-text-faint">KYB Level</span>
                <span className="font-mono text-text-primary">
                  {KYB_LABELS[agent.kyb_level]}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-text-faint">Trust Score</span>
                <span
                  className={cn("font-mono", trustScoreColor(agent.trust_score))}
                >
                  {agent.trust_score}
                </span>
              </div>
            </div>

            <label className="mb-1 block text-xs font-medium text-text-muted">
              Your Agent ID
            </label>
            <input
              type="text"
              value={fromAgentId}
              onChange={(e) => setFromAgentId(e.target.value)}
              placeholder="UUID of your registered agent"
              className={cn(
                "mb-4 w-full rounded-control border bg-bg-elevated px-3 py-2 font-mono text-xs text-text-primary placeholder:text-text-faint focus:outline-none",
                fromAgentId && !isValidUuid
                  ? "border-alert focus:border-alert"
                  : "border-border focus:border-accent",
              )}
            />

            {error && (
              <p className="mb-3 text-xs text-alert">
                {(error as Error).message}
              </p>
            )}

            <p className="mb-5 text-xs text-text-faint">
              A2A requests are brokered through the registry. Your workspace
              credentials will be shared with this agent.
            </p>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 rounded-control border border-border py-2 text-xs font-medium text-text-muted hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!isValidUuid || isPending}
                className={cn(
                  "flex-1 rounded-control border py-2 text-xs font-medium transition-colors",
                  isValidUuid && !isPending
                    ? "border-accent bg-accent-dim text-accent hover:bg-accent/10"
                    : "cursor-not-allowed border-border text-text-faint opacity-50",
                )}
              >
                {isPending ? "Sending…" : "Initiate Connection"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

interface HARAgentCardProps {
  agent: HARAgent;
  onConnect: (agent: HARAgent) => void;
}

export function HARAgentCard({ agent, onConnect }: HARAgentCardProps) {
  const isAvailable = agent.health_status === "AVAILABLE";

  return (
    <div className="flex flex-col rounded-card border border-border bg-bg-surface p-5 transition-colors hover:border-accent-ring">
      {/* Header row */}
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {/* Health indicator */}
            <span
              className={cn(
                "mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full",
                isAvailable ? "bg-accent" : "bg-alert",
              )}
            />
            <h3 className="truncate text-[15px] font-semibold text-text-primary">
              {agent.name}
            </h3>
          </div>
          {/* Industries */}
          {agent.industries.length > 0 && (
            <p className="mt-0.5 truncate text-xs text-text-faint">
              {agent.industries.join(", ")}
            </p>
          )}
        </div>

        {/* KYB badge */}
        <span
          className={cn(
            "shrink-0 rounded-badge border px-2 py-0.5 text-[10px] font-medium",
            kybLabelColor(agent.kyb_level),
          )}
        >
          {KYB_LABELS[agent.kyb_level]}
        </span>
      </div>

      {/* Description */}
      <p className="mb-4 line-clamp-2 text-body-default text-text-muted">
        {agent.description}
      </p>

      {/* Transaction type chips */}
      {agent.transaction_types.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {agent.transaction_types.map((tt) => (
            <span
              key={tt}
              className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[10px] font-medium text-text-muted"
            >
              {tt}
            </span>
          ))}
        </div>
      )}

      {/* Footer row */}
      <div className="mt-auto flex items-center justify-between border-t border-border-faint pt-3">
        {/* Trust score */}
        <div className="flex items-baseline gap-1">
          <span
            className={cn(
              "font-mono text-body-default font-medium",
              trustScoreColor(agent.trust_score),
            )}
          >
            {agent.trust_score}
          </span>
          <span className="text-[10px] text-text-faint">trust</span>
        </div>

        {/* Connect button */}
        <button
          type="button"
          onClick={() => onConnect(agent)}
          disabled={!isAvailable}
          className={cn(
            "rounded-control border px-3 py-1.5 text-xs font-medium transition-colors",
            isAvailable
              ? "border-accent text-accent hover:bg-accent-dim"
              : "cursor-not-allowed border-border text-text-faint opacity-50",
          )}
        >
          {isAvailable ? "Connect" : "Unavailable"}
        </button>
      </div>
    </div>
  );
}

export { ConnectModal };
