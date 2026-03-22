"use client";

import { AgentTemplate } from "@/lib/hooks/useAgentTemplates";

// Plan rank for gating check
const PLAN_RANK: Record<string, number> = {
  starter: 0,
  professional: 1,
  enterprise: 2,
};

function planOk(tenantPlan: string, planRequired: string | null): boolean {
  if (!planRequired) return true;
  const tenantRank = PLAN_RANK[tenantPlan] ?? 0;
  const requiredRank = PLAN_RANK[planRequired] ?? 0;
  return tenantRank >= requiredRank;
}

const CATEGORY_ICONS: Record<string, string> = {
  HR: "👥",
  IT: "🖥",
  Finance: "💰",
  Legal: "⚖️",
  Procurement: "📦",
  Onboarding: "🌟",
  Custom: "⭐",
};

function resolveIcon(template: AgentTemplate): string {
  if (template.icon) return template.icon;
  return CATEGORY_ICONS[template.category ?? ""] ?? "⭐";
}

const TEMPLATE_TYPE_LABELS: Record<
  string,
  { label: string; className: string }
> = {
  rag: {
    label: "RAG",
    className: "bg-bg-elevated text-text-muted",
  },
  skill_augmented: {
    label: "Skills+",
    className: "bg-accent-dim text-accent",
  },
  tool_augmented: {
    label: "Tools+",
    className: "bg-warn-dim text-warn",
  },
  credentialed: {
    label: "Credentialed",
    className: "bg-alert-dim text-alert",
  },
  registered_a2a: {
    label: "A2A",
    className: "border border-border bg-bg-elevated text-text-muted",
  },
};

export interface AgentTemplateCardProps {
  template: AgentTemplate;
  tenantPlan: string;
  onDeploy: (template: AgentTemplate) => void;
  onClick: (template: AgentTemplate) => void;
}

export function AgentTemplateCard({
  template,
  tenantPlan,
  onDeploy,
  onClick,
}: AgentTemplateCardProps) {
  const icon = resolveIcon(template);
  const canDeploy = planOk(tenantPlan, template.plan_required ?? null);
  const typeConfig =
    TEMPLATE_TYPE_LABELS[template.template_type ?? "rag"] ??
    TEMPLATE_TYPE_LABELS["rag"];

  // Resolve skill/tool counts defensively
  const skillCount = (template.attached_skills ?? []).length;
  const toolCount = (template.attached_tools ?? []).length;
  const isDeployed = (template.instance_count ?? 0) > 0;

  return (
    <div
      className="flex cursor-pointer flex-col rounded-card border border-border bg-bg-surface p-5 transition-colors hover:border-accent-ring"
      onClick={() => onClick(template)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick(template);
      }}
    >
      {/* Row 1: Icon + Name + Plan badge */}
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-bg-elevated text-xl">
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-section-heading text-text-primary">
              {template.name}
            </p>
            {template.plan_required && !canDeploy && (
              <span className="shrink-0 text-[10px] text-text-faint">
                🔒 {template.plan_required}
              </span>
            )}
          </div>

          {/* Row 2: Category + template_type badge */}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {template.category && (
              <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted">
                {template.category}
              </span>
            )}
            <span
              className={`rounded-badge px-2 py-0.5 text-[11px] ${typeConfig.className}`}
            >
              {typeConfig.label}
            </span>
          </div>
        </div>
      </div>

      {/* Row 3: Description */}
      <p className="mt-3 line-clamp-2 text-body-default text-text-muted">
        {template.description ?? "No description provided."}
      </p>

      {/* Row 4: Capability chips */}
      {(skillCount > 0 || toolCount > 0 || template.auth_mode !== "none") && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {skillCount > 0 && (
            <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted">
              {skillCount} skill{skillCount !== 1 ? "s" : ""}
            </span>
          )}
          {toolCount > 0 && (
            <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted">
              {toolCount} tool{toolCount !== 1 ? "s" : ""}
            </span>
          )}
          {template.auth_mode !== "none" && (
            <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted">
              🔑 credentials
            </span>
          )}
        </div>
      )}

      {/* Separator */}
      <div className="mb-3 mt-3 border-t border-border" />

      {/* Row 6: Deploy button or deployed badge */}
      <div
        className="flex items-center justify-between"
        onClick={(e) => e.stopPropagation()}
      >
        {isDeployed ? (
          <span className="rounded-badge bg-accent-dim px-2 py-1 text-[11px] text-accent">
            ✓ Deployed
          </span>
        ) : canDeploy ? (
          <button
            type="button"
            onClick={() => onDeploy(template)}
            className="rounded-control bg-accent px-3 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            Deploy
          </button>
        ) : (
          <button
            type="button"
            disabled
            title={`Requires ${template.plan_required} plan`}
            className="cursor-not-allowed rounded-control bg-bg-elevated px-3 py-1.5 text-body-default text-text-faint"
          >
            Deploy
          </button>
        )}
      </div>
    </div>
  );
}
