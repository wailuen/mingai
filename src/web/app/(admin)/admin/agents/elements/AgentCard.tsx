"use client";

import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";

interface AgentCardProps {
  template: AgentTemplate;
  onPreview: (template: AgentTemplate) => void;
  onDeploy: (template: AgentTemplate) => void;
}

export function AgentCard({ template, onPreview, onDeploy }: AgentCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-card border border-border bg-bg-surface p-5">
      {/* Header row */}
      <div className="flex items-center gap-2">
        {template.is_seed && (
          <span className="rounded-badge bg-accent-dim px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-accent">
            Seed
          </span>
        )}
        <h3 className="text-section-heading text-text-primary">
          {template.name}
        </h3>
        <span className="ml-auto font-mono text-xs text-text-faint">
          v{template.version}
        </span>
      </div>

      {/* Description */}
      {/* Category chip */}
      {template.category && (
        <div className="flex flex-wrap gap-1.5">
          <span className="rounded-badge bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted">
            {template.category}
          </span>
        </div>
      )}

      {/* Description */}
      <p className="line-clamp-2 text-body-default leading-relaxed text-text-muted">
        {template.description ?? "No description available."}
      </p>

      {/* Capability pills */}
      {template.capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {template.capabilities.map((cap) => (
            <span
              key={cap}
              className="rounded-badge bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted"
            >
              {cap}
            </span>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="mt-auto flex items-center justify-between pt-1">
        <button
          onClick={() => onPreview(template)}
          className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          Preview
        </button>
        <button
          onClick={() => onDeploy(template)}
          className="rounded-control bg-accent px-3 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
        >
          Deploy &rarr;
        </button>
      </div>
    </div>
  );
}

export function AgentCardSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-card border border-border bg-bg-surface p-5">
      <div className="flex items-center gap-2">
        <div className="h-4 w-10 animate-pulse rounded-badge bg-bg-elevated" />
        <div className="h-5 w-40 animate-pulse rounded-badge bg-bg-elevated" />
        <div className="ml-auto h-4 w-8 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
      <div className="space-y-1.5">
        <div className="h-3.5 w-full animate-pulse rounded-badge bg-bg-elevated" />
        <div className="h-3.5 w-3/4 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
      <div className="flex gap-1.5">
        <div className="h-5 w-20 animate-pulse rounded-badge bg-bg-elevated" />
        <div className="h-5 w-24 animate-pulse rounded-badge bg-bg-elevated" />
        <div className="h-5 w-16 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
      <div className="mt-auto flex items-center justify-between pt-1">
        <div className="h-8 w-20 animate-pulse rounded-control bg-bg-elevated" />
        <div className="h-8 w-24 animate-pulse rounded-control bg-bg-elevated" />
      </div>
    </div>
  );
}
