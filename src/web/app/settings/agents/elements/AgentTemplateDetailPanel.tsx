"use client";

import { X } from "lucide-react";
import { AgentTemplate } from "@/lib/hooks/useAgentTemplates";

const PLAN_RANK: Record<string, number> = {
  starter: 0,
  professional: 1,
  enterprise: 2,
};

function planOk(tenantPlan: string, planRequired: string | null): boolean {
  if (!planRequired) return true;
  return (PLAN_RANK[tenantPlan] ?? 0) >= (PLAN_RANK[planRequired] ?? 0);
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
  rag: { label: "RAG", className: "bg-bg-elevated text-text-muted" },
  skill_augmented: { label: "Skills+", className: "bg-accent-dim text-accent" },
  tool_augmented: { label: "Tools+", className: "bg-warn-dim text-warn" },
  credentialed: { label: "Credentialed", className: "bg-alert-dim text-alert" },
  registered_a2a: {
    label: "A2A",
    className: "border border-border bg-bg-elevated text-text-muted",
  },
};

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <div className="border-t border-border pt-4">
      <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
        {title}
      </p>
      {children}
    </div>
  );
}

export interface AgentTemplateDetailPanelProps {
  template: AgentTemplate;
  tenantPlan: string;
  onClose: () => void;
  onDeploy: (template: AgentTemplate) => void;
}

export function AgentTemplateDetailPanel({
  template,
  tenantPlan,
  onClose,
  onDeploy,
}: AgentTemplateDetailPanelProps) {
  const icon = resolveIcon(template);
  const typeConfig =
    TEMPLATE_TYPE_LABELS[template.template_type ?? "rag"] ??
    TEMPLATE_TYPE_LABELS["rag"];
  const canDeploy = planOk(tenantPlan, template.plan_required ?? null);
  const skillCount = (template.attached_skills ?? []).length;
  const toolCount = (template.attached_tools ?? []).length;
  const guardrailCount = (template.guardrails ?? []).length;
  const a2aEnabled = template.a2a_interface?.a2a_enabled ?? false;
  const a2aOperationCount = (template.a2a_interface?.operations ?? []).length;

  const variableNames =
    (template.variable_schema ?? template.variable_definitions ?? [])
      .map((v) => ("name" in v ? v.name : ""))
      .filter(Boolean)
      .join(", ");

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-bg-base/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-[360px] flex-col border-l border-border bg-bg-surface shadow-xl">
        {/* Header */}
        <div className="flex items-start gap-3 border-b border-border p-5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-bg-elevated text-xl">
            {icon}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-section-heading text-text-primary">
              {template.name}
            </p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <span
                className={`rounded-badge px-2 py-0.5 text-[11px] ${typeConfig.className}`}
              >
                {typeConfig.label}
              </span>
              {template.plan_required && !canDeploy && (
                <span className="rounded-badge border border-border px-2 py-0.5 text-[10px] text-text-faint">
                  🔒 {template.plan_required}
                </span>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="Close panel"
          >
            <X size={16} />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex flex-col gap-4 overflow-y-auto p-5">
          {/* Identity */}
          <Section title="Identity">
            <div className="space-y-2">
              {template.category && (
                <div className="flex items-center gap-2">
                  <span className="text-label-nav uppercase tracking-wider text-text-faint">
                    Category
                  </span>
                  <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted">
                    {template.category}
                  </span>
                </div>
              )}
              {(template.tags ?? []).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {(template.tags ?? []).map((tag) => (
                    <span
                      key={tag}
                      className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              <p className="text-body-default text-text-muted">
                {template.description ?? "No description provided."}
              </p>
            </div>
            {variableNames && (
              <p className="mt-2 text-body-default text-text-muted">
                <span className="font-medium text-text-primary">
                  Variables:{" "}
                </span>
                {variableNames}
              </p>
            )}
          </Section>

          {/* LLM Policy */}
          {template.llm_policy && (
            <Section title="LLM Policy">
              <div className="space-y-1">
                <p className="text-body-default text-text-muted">
                  Tenant override:{" "}
                  <span className="text-text-primary">
                    {template.llm_policy.tenant_can_override
                      ? "Allowed"
                      : "Fixed"}
                  </span>
                </p>
                {template.llm_policy.required_model && (
                  <p className="font-mono text-data-value text-text-muted">
                    Required model: {template.llm_policy.required_model}
                  </p>
                )}
                {template.llm_policy.defaults?.temperature !== undefined && (
                  <p className="font-mono text-data-value text-text-muted">
                    Temperature: {template.llm_policy.defaults.temperature}
                  </p>
                )}
                {template.llm_policy.defaults?.max_tokens !== undefined && (
                  <p className="font-mono text-data-value text-text-muted">
                    Max tokens: {template.llm_policy.defaults.max_tokens}
                  </p>
                )}
              </div>
            </Section>
          )}

          {/* Knowledge */}
          {template.kb_policy && (
            <Section title="Knowledge">
              <div className="space-y-1">
                <p className="text-body-default text-text-muted">
                  Ownership:{" "}
                  <span className="text-text-primary">
                    {template.kb_policy.ownership}
                  </span>
                </p>
                {(template.kb_policy.recommended_categories ?? []).length >
                  0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {template.kb_policy.recommended_categories.map((cat) => (
                      <span
                        key={cat}
                        className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-[11px] text-text-muted"
                      >
                        {cat}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </Section>
          )}

          {/* Capabilities */}
          {(skillCount > 0 ||
            toolCount > 0 ||
            template.auth_mode !== "none") && (
            <Section title="Capabilities">
              <div className="space-y-1">
                {skillCount > 0 && (
                  <p className="text-body-default text-text-muted">
                    Skills:{" "}
                    <span className="text-text-primary">
                      {(template.attached_skills ?? [])
                        .map(
                          (s) =>
                            s.skill_name ?? s.name ?? s.skill_id ?? "unknown",
                        )
                        .join(", ")}
                    </span>
                  </p>
                )}
                {toolCount > 0 && (
                  <p className="text-body-default text-text-muted">
                    Tools:{" "}
                    <span className="text-text-primary">
                      {(template.attached_tools ?? [])
                        .map(
                          (t) =>
                            t.tool_name ?? t.name ?? t.tool_id ?? "unknown",
                        )
                        .join(", ")}
                    </span>
                  </p>
                )}
                {template.auth_mode !== "none" && (
                  <p className="text-body-default text-text-muted">
                    Auth:{" "}
                    <span className="text-text-primary">
                      {template.auth_mode === "tenant_credentials"
                        ? "Tenant credentials required"
                        : "Platform credentials"}
                    </span>
                  </p>
                )}
              </div>
            </Section>
          )}

          {/* A2A Interface */}
          <Section title="A2A Interface">
            <div className="space-y-1">
              <p className="text-body-default text-text-muted">
                Status:{" "}
                <span
                  className={a2aEnabled ? "text-accent" : "text-text-primary"}
                >
                  {a2aEnabled ? "Enabled" : "Disabled"}
                </span>
              </p>
              {a2aEnabled && a2aOperationCount > 0 && (
                <p className="text-body-default text-text-muted">
                  Operations:{" "}
                  <span className="text-text-primary">{a2aOperationCount}</span>
                </p>
              )}
            </div>
          </Section>

          {/* Guardrails */}
          <Section title="Guardrails">
            <p className="text-body-default text-text-muted">
              {guardrailCount > 0
                ? `${guardrailCount} rule${guardrailCount !== 1 ? "s" : ""} configured`
                : "None"}
            </p>
          </Section>

          {/* Version */}
          <Section title="Version">
            <p className="font-mono text-data-value text-text-muted">
              v{template.version}
            </p>
          </Section>
        </div>

        {/* Footer */}
        <div className="border-t border-border p-5">
          {canDeploy ? (
            <button
              type="button"
              onClick={() => onDeploy(template)}
              className="w-full rounded-control bg-accent py-2.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
            >
              Deploy this template
            </button>
          ) : (
            <button
              type="button"
              disabled
              className="w-full cursor-not-allowed rounded-control bg-bg-elevated py-2.5 text-body-default text-text-faint"
            >
              Requires {template.plan_required} plan
            </button>
          )}
        </div>
      </div>
    </>
  );
}
