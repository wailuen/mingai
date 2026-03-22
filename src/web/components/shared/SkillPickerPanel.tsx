"use client";

import { useState, useMemo, useCallback } from "react";
import { Search, X, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTenantSkills } from "@/lib/hooks/useSkills";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SkillPickerPanelProps {
  selectedSkillIds: string[];
  invocationOverrides: Record<string, string>;
  onChange: (selectedIds: string[], overrides: Record<string, string>) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SkillPickerPanel({
  selectedSkillIds,
  invocationOverrides,
  onChange,
}: SkillPickerPanelProps) {
  const { data, isPending } = useTenantSkills();
  const skills = data?.items ?? [];

  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [expandedOverrides, setExpandedOverrides] = useState<
    Record<string, boolean>
  >({});

  // Derive category list from data
  const categories = useMemo(() => {
    const cats = new Set<string>();
    skills.forEach((s) => {
      if (s.category) cats.add(s.category);
    });
    return ["All", ...Array.from(cats).sort()];
  }, [skills]);

  // Filter skills by search + category
  const filteredSkills = useMemo(() => {
    const q = search.toLowerCase();
    return skills.filter((s) => {
      const matchesSearch =
        !q ||
        s.name.toLowerCase().includes(q) ||
        (s.description ?? "").toLowerCase().includes(q);
      const matchesCategory =
        categoryFilter === "All" || s.category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [skills, search, categoryFilter]);

  const toggleSkill = useCallback(
    (skillId: string) => {
      const isSelected = selectedSkillIds.includes(skillId);
      if (isSelected) {
        const nextIds = selectedSkillIds.filter((id) => id !== skillId);
        const nextOverrides = { ...invocationOverrides };
        delete nextOverrides[skillId];
        onChange(nextIds, nextOverrides);
      } else {
        onChange([...selectedSkillIds, skillId], invocationOverrides);
      }
    },
    [selectedSkillIds, invocationOverrides, onChange],
  );

  const updateOverride = useCallback(
    (skillId: string, value: string) => {
      onChange(selectedSkillIds, {
        ...invocationOverrides,
        [skillId]: value,
      });
    },
    [selectedSkillIds, invocationOverrides, onChange],
  );

  const removeChip = useCallback(
    (skillId: string) => {
      const nextIds = selectedSkillIds.filter((id) => id !== skillId);
      const nextOverrides = { ...invocationOverrides };
      delete nextOverrides[skillId];
      onChange(nextIds, nextOverrides);
    },
    [selectedSkillIds, invocationOverrides, onChange],
  );

  const toggleOverrideExpand = useCallback((skillId: string) => {
    setExpandedOverrides((prev) => ({
      ...prev,
      [skillId]: !prev[skillId],
    }));
  }, []);

  const selectedSkills = useMemo(
    () => skills.filter((s) => selectedSkillIds.includes(s.id)),
    [skills, selectedSkillIds],
  );

  return (
    <div className="space-y-3">
      {/* Selected chips */}
      {selectedSkillIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] uppercase tracking-wider text-text-faint">
            {selectedSkillIds.length} selected
          </span>
          {selectedSkills.map((s) => (
            <span
              key={s.id}
              className="flex items-center gap-1 rounded-badge bg-accent-dim px-2 py-0.5 text-[11px] text-accent"
            >
              {s.name}
              <button
                type="button"
                onClick={() => removeChip(s.id)}
                className="ml-0.5 text-accent hover:text-text-primary"
              >
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="relative">
        <Search
          size={13}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-faint"
        />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search skills..."
          className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
        />
      </div>

      {/* Category filter chips */}
      <div className="flex flex-wrap gap-1.5">
        {categories.map((cat) => (
          <button
            key={cat}
            type="button"
            onClick={() => setCategoryFilter(cat)}
            className={cn(
              "rounded-badge border px-2.5 py-0.5 text-[11px] transition-colors",
              categoryFilter === cat
                ? "border-accent bg-accent-dim text-accent"
                : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Skills list */}
      {isPending ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-control bg-bg-elevated"
            />
          ))}
        </div>
      ) : filteredSkills.length === 0 ? (
        <p className="py-4 text-center text-body-default text-text-faint">
          {skills.length === 0
            ? "No skills available. Go to Skills to adopt platform skills."
            : "No skills match your search."}
        </p>
      ) : (
        <div className="space-y-1.5">
          {filteredSkills.map((skill) => {
            const isSelected = selectedSkillIds.includes(skill.id);
            const isPipeline =
              skill.invocation_mode === "pipeline" &&
              skill.execution_pattern !== "prompt";
            const overrideOpen = expandedOverrides[skill.id] ?? false;

            return (
              <div key={skill.id}>
                <label
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-control border px-3 py-2.5 transition-colors",
                    isSelected
                      ? "border-accent bg-accent-dim"
                      : "border-border bg-bg-elevated hover:border-accent-ring",
                  )}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleSkill(skill.id)}
                    className="mt-0.5 accent-accent"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-body-default font-medium text-text-primary">
                        {skill.name}
                      </span>
                      <span className="rounded-badge bg-bg-base px-1.5 py-0.5 text-[10px] text-text-faint">
                        {skill.execution_pattern}
                      </span>
                      {skill.category && (
                        <span className="rounded-badge bg-bg-base px-1.5 py-0.5 text-[10px] text-text-faint">
                          {skill.category}
                        </span>
                      )}
                    </div>
                    {skill.description && (
                      <p className="mt-0.5 line-clamp-1 text-[11px] text-text-faint">
                        {skill.description}
                      </p>
                    )}
                  </div>
                </label>

                {/* Override trigger input for pipeline skills */}
                {isSelected && isPipeline && (
                  <div className="ml-3 mt-1 border-l border-border pl-3">
                    <button
                      type="button"
                      onClick={() => toggleOverrideExpand(skill.id)}
                      className="flex items-center gap-1 text-[11px] text-text-faint hover:text-text-muted"
                    >
                      <ChevronDown
                        size={12}
                        className={cn(
                          "transition-transform",
                          overrideOpen ? "rotate-180" : "",
                        )}
                      />
                      Override trigger phrase
                    </button>
                    {overrideOpen && (
                      <input
                        type="text"
                        value={invocationOverrides[skill.id] ?? ""}
                        onChange={(e) =>
                          updateOverride(skill.id, e.target.value)
                        }
                        placeholder={
                          skill.pipeline_trigger ?? "e.g. run report"
                        }
                        className="mt-1.5 w-full rounded-control border border-border bg-bg-base px-2 py-1.5 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
