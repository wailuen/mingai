"use client";

import { useState, useMemo, useCallback } from "react";
import { Search } from "lucide-react";
import { useAgentTemplates } from "@/lib/hooks/useAgentTemplates";
import type { AgentTemplate } from "@/lib/hooks/useAgentTemplates";
import { AgentTemplateCard } from "./AgentTemplateCard";
import { AgentTemplateDetailPanel } from "./AgentTemplateDetailPanel";
import { getStoredToken, decodeToken } from "@/lib/auth";

function getTenantPlan(): string {
  try {
    const token = getStoredToken();
    if (!token) return "starter";
    const claims = decodeToken(token);
    return claims.plan ?? "starter";
  } catch {
    return "starter";
  }
}

interface AgentLibraryTabProps {
  onDeploy?: (template: AgentTemplate) => void;
}

export function AgentLibraryTab({ onDeploy }: AgentLibraryTabProps) {
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState("All");
  const [detailTemplate, setDetailTemplate] = useState<AgentTemplate | null>(
    null,
  );

  const tenantPlan = getTenantPlan();
  const { data, isPending, error } = useAgentTemplates();

  const templates = data?.items ?? [];

  const categories = useMemo(() => {
    const cats = new Set<string>();
    for (const t of templates) {
      if (t.category) cats.add(t.category);
    }
    return ["All", ...Array.from(cats).sort()];
  }, [templates]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return templates.filter((t) => {
      if (activeCategory !== "All" && t.category !== activeCategory)
        return false;
      if (!q) return true;
      return (
        t.name.toLowerCase().includes(q) ||
        (t.description ?? "").toLowerCase().includes(q) ||
        (t.category ?? "").toLowerCase().includes(q)
      );
    });
  }, [templates, activeCategory, search]);

  const handleDeploy = useCallback(
    (template: AgentTemplate) => {
      if (onDeploy) {
        onDeploy(template);
      } else {
        console.log("Deploy template:", template.id, template.name);
      }
    },
    [onDeploy],
  );

  return (
    <div>
      {/* Action bar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 sm:max-w-xs">
          <Search
            size={14}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-faint"
          />
          <input
            type="text"
            placeholder="Search templates..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-control border border-border bg-bg-elevated py-2 pl-8 pr-3 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
        </div>
      </div>

      {/* Category filter chips */}
      {!isPending && templates.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={
                activeCategory === cat
                  ? "rounded-badge border border-accent px-3 py-1 text-[11px] font-medium text-accent transition-colors"
                  : "rounded-badge border border-border bg-bg-elevated px-3 py-1 text-[11px] font-medium text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
              }
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      {/* Template count */}
      {!isPending && !error && (
        <p className="mb-4 text-[11px] text-text-faint">
          {filtered.length === templates.length
            ? `${templates.length} template${templates.length !== 1 ? "s" : ""} available`
            : `${filtered.length} of ${templates.length} templates`}
        </p>
      )}

      {/* Error state */}
      {error && (
        <p className="py-8 text-center text-body-default text-alert">
          Failed to load templates. Please try again.
        </p>
      )}

      {/* Loading skeleton */}
      {isPending && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="h-52 animate-pulse rounded-card border border-border bg-bg-surface"
            />
          ))}
        </div>
      )}

      {/* Empty state after filtering */}
      {!isPending && !error && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16">
          <p className="text-body-default text-text-faint">
            No templates match your search.
          </p>
          {(search || activeCategory !== "All") && (
            <button
              onClick={() => {
                setSearch("");
                setActiveCategory("All");
              }}
              className="mt-2 text-body-default text-accent hover:underline"
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {/* Template grid */}
      {!isPending && !error && filtered.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((template) => (
            <AgentTemplateCard
              key={template.id}
              template={template}
              tenantPlan={tenantPlan}
              onDeploy={handleDeploy}
              onClick={setDetailTemplate}
            />
          ))}
        </div>
      )}

      {/* Detail panel */}
      {detailTemplate && (
        <AgentTemplateDetailPanel
          template={detailTemplate}
          tenantPlan={tenantPlan}
          onClose={() => setDetailTemplate(null)}
          onDeploy={(t) => {
            handleDeploy(t);
            setDetailTemplate(null);
          }}
        />
      )}
    </div>
  );
}
