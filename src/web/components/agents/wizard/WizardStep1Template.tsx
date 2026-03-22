"use client";

import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";

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
  rag: { label: "RAG", className: "bg-bg-elevated text-text-muted" },
  skill_augmented: { label: "Skills+", className: "bg-accent-dim text-accent" },
  tool_augmented: { label: "Tools+", className: "bg-warn-dim text-warn" },
  credentialed: { label: "Credentialed", className: "bg-alert-dim text-alert" },
  registered_a2a: {
    label: "A2A",
    className: "border border-border bg-bg-elevated text-text-muted",
  },
};

const AUTH_MODE_LABELS: Record<string, string> = {
  none: "No credentials",
  tenant_credentials: "Tenant credentials required",
  platform_credentials: "Platform credentials",
};

interface WizardStep1TemplateProps {
  template: AgentTemplate | null;
}

export function WizardStep1Template({ template }: WizardStep1TemplateProps) {
  if (!template) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <p className="text-body-default text-text-faint">
          No template selected.
        </p>
      </div>
    );
  }

  const icon = resolveIcon(template);
  const typeConfig =
    TEMPLATE_TYPE_LABELS[template.template_type ?? "rag"] ??
    TEMPLATE_TYPE_LABELS["rag"];
  const skillCount = (template.attached_skills ?? []).length;
  const toolCount = (template.attached_tools ?? []).length;
  const tagList = template.tags ?? [];
  const authLabel = AUTH_MODE_LABELS[template.auth_mode] ?? template.auth_mode;

  return (
    <div className="flex flex-col gap-5">
      <p className="text-section-heading text-text-primary">Template</p>

      {/* Identity card */}
      <div className="rounded-card border border-border bg-bg-elevated p-4">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-control bg-bg-base text-2xl">
            {icon}
          </div>

          {/* Name + badges */}
          <div className="min-w-0 flex-1">
            <p className="text-section-heading text-text-primary">
              {template.name}
            </p>

            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {template.category && (
                <span className="rounded-badge border border-border bg-bg-base px-2 py-0.5 text-[11px] text-text-muted">
                  {template.category}
                </span>
              )}
              <span
                className={`rounded-badge px-2 py-0.5 text-[11px] ${typeConfig.className}`}
              >
                {typeConfig.label}
              </span>
              {template.auth_mode !== "none" && (
                <span className="rounded-badge border border-border bg-bg-base px-2 py-0.5 text-[11px] text-text-muted">
                  🔑 {authLabel}
                </span>
              )}
              {template.plan_required && (
                <span className="rounded-badge border border-border px-2 py-0.5 text-[10px] text-text-faint">
                  🔒 {template.plan_required}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Description */}
        {template.description && (
          <p className="mt-3 text-body-default text-text-muted">
            {template.description}
          </p>
        )}
      </div>

      {/* Capabilities */}
      {(skillCount > 0 || toolCount > 0 || tagList.length > 0) && (
        <div>
          <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
            Capabilities
          </p>
          <div className="flex flex-wrap gap-1.5">
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
            {tagList.map((tag) => (
              <span
                key={tag}
                className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
