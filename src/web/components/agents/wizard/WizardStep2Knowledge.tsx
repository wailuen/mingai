"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import type { WizardFormData } from "../AgentDeployWizard";

interface KBSource {
  id: string;
  name: string;
  type?: string;
  document_count?: number;
}

interface KBSourcesResponse {
  items: KBSource[];
  total: number;
}

interface WizardStep2KnowledgeProps {
  template: AgentTemplate | null;
  formData: WizardFormData;
  onChange: (data: Partial<WizardFormData>) => void;
}

export function WizardStep2Knowledge({
  template,
  formData,
  onChange,
}: WizardStep2KnowledgeProps) {
  const variableSchema =
    template?.variable_schema ??
    template?.variable_definitions?.map((v) => ({
      name: v.name,
      type: v.type,
      required: v.required,
      description: v.label ?? "",
    })) ??
    [];

  const { data: kbData, isPending: kbPending } = useQuery({
    queryKey: ["admin-kb-sources"],
    queryFn: () => apiGet<KBSourcesResponse>("/api/v1/admin/kb-sources"),
    retry: false,
  });

  const kbSources = kbData?.items ?? [];
  const selectedKbIds = formData.kbIds;

  function toggleKb(id: string) {
    const next = selectedKbIds.includes(id)
      ? selectedKbIds.filter((k) => k !== id)
      : [...selectedKbIds, id];
    onChange({ kbIds: next });
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Agent name */}
      <div>
        <label className="mb-1.5 block text-body-default font-medium text-text-primary">
          Agent Name
          <span className="ml-0.5 text-alert">*</span>
        </label>
        <input
          type="text"
          value={formData.agentName}
          onChange={(e) => onChange({ agentName: e.target.value })}
          placeholder="e.g. HR Assistant"
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
      </div>

      {/* Variable inputs */}
      {variableSchema.length > 0 && (
        <div>
          <p className="mb-3 text-section-heading text-text-primary">
            Template Variables
          </p>
          <div className="flex flex-col gap-4">
            {variableSchema.map((variable) => (
              <div key={variable.name}>
                <label className="mb-1 block text-body-default font-medium text-text-primary">
                  {variable.description || variable.name}
                  {variable.required && (
                    <span className="ml-0.5 text-alert">*</span>
                  )}
                </label>
                {variable.description &&
                  variable.name !== variable.description && (
                    <p className="mb-1 text-[11px] text-text-muted">
                      {variable.name}
                    </p>
                  )}
                <input
                  type="text"
                  value={formData.variableValues[variable.name] ?? ""}
                  onChange={(e) =>
                    onChange({
                      variableValues: {
                        ...formData.variableValues,
                        [variable.name]: e.target.value,
                      },
                    })
                  }
                  placeholder={
                    variable.type === "number" ? "0" : "Enter value…"
                  }
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Knowledge bases */}
      <div>
        <p className="mb-1 text-section-heading text-text-primary">
          Knowledge Bases
        </p>
        <p className="mb-3 text-[11px] text-text-muted">
          Select which knowledge bases this agent can search.
        </p>

        {kbPending && (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-10 animate-pulse rounded-control bg-bg-elevated"
              />
            ))}
          </div>
        )}

        {!kbPending && kbSources.length === 0 && (
          <div className="rounded-card border border-border-faint bg-bg-elevated px-4 py-5 text-center">
            <p className="text-body-default text-text-faint">
              No knowledge bases configured.
            </p>
            <p className="mt-0.5 text-[11px] text-text-faint">
              Add a knowledge base in Settings → Knowledge Base to enable RAG.
            </p>
          </div>
        )}

        {!kbPending && kbSources.length > 0 && (
          <div className="flex flex-col gap-2">
            {kbSources.map((kb) => {
              const checked = selectedKbIds.includes(kb.id);
              return (
                <label
                  key={kb.id}
                  className="flex cursor-pointer items-center gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5 transition-colors hover:border-accent-ring"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleKb(kb.id)}
                    className="h-4 w-4 shrink-0 rounded-badge border-border bg-bg-base accent-accent"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-body-default text-text-primary">
                      {kb.name}
                    </p>
                    {(kb.type || kb.document_count != null) && (
                      <p className="text-[11px] text-text-muted">
                        {[
                          kb.type,
                          kb.document_count != null
                            ? `${kb.document_count} docs`
                            : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
        )}
      </div>

      {/* KB search mode — only when multiple KBs selected */}
      {selectedKbIds.length > 1 && (
        <div>
          <p className="mb-2 text-body-default font-medium text-text-primary">
            Search Mode
          </p>
          <div className="flex flex-col gap-2">
            {(
              [
                {
                  value: "parallel" as const,
                  label: "Search all KBs in parallel",
                  desc: "Queries all selected knowledge bases simultaneously for best recall.",
                },
                {
                  value: "priority" as const,
                  label: "Search by priority order",
                  desc: "Queries knowledge bases in the order listed, stopping when results are found.",
                },
              ] as const
            ).map((opt) => (
              <label
                key={opt.value}
                className="flex cursor-pointer items-start gap-3 rounded-control border border-border bg-bg-elevated px-3 py-2.5 transition-colors hover:border-accent-ring"
              >
                <input
                  type="radio"
                  name="kbSearchMode"
                  value={opt.value}
                  checked={formData.kbSearchMode === opt.value}
                  onChange={() => onChange({ kbSearchMode: opt.value })}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
                />
                <div>
                  <p className="text-body-default text-text-primary">
                    {opt.label}
                  </p>
                  <p className="text-[11px] text-text-muted">{opt.desc}</p>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
