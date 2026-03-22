"use client";

import { useState, useMemo } from "react";
import {
  Search,
  Lock,
  CheckCircle,
  ChevronDown,
  Loader2,
  Zap,
  Wrench,
  GitBranch,
} from "lucide-react";
import {
  usePlatformSkills,
  useAdoptSkill,
  useUnadoptSkill,
  usePinSkillVersion,
} from "@/lib/hooks/useSkills";
import type { PlatformSkill } from "@/lib/hooks/useSkills";
import { cn } from "@/lib/utils";

type AdoptFilter = "all" | "adopted" | "not_adopted" | "mandatory";

const ADOPT_FILTERS: { id: AdoptFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "adopted", label: "Adopted" },
  { id: "not_adopted", label: "Not Adopted" },
  { id: "mandatory", label: "Mandatory" },
];

const EXECUTION_PATTERN_COLORS: Record<
  PlatformSkill["execution_pattern"],
  string
> = {
  prompt: "text-accent bg-accent-dim border-accent/30",
  tool_composing: "text-warn bg-warn-dim border-warn/30",
  sequential_pipeline: "text-text-muted bg-bg-elevated border-border",
};

const EXECUTION_PATTERN_LABELS: Record<
  PlatformSkill["execution_pattern"],
  string
> = {
  prompt: "Prompt",
  tool_composing: "Tool-Composing",
  sequential_pipeline: "Sequential Pipeline",
};

const EXECUTION_PATTERN_ICONS: Record<
  PlatformSkill["execution_pattern"],
  typeof Zap
> = {
  prompt: Zap,
  tool_composing: Wrench,
  sequential_pipeline: GitBranch,
};

const PLAN_BADGE: Record<string, string> = {
  starter: "text-text-muted bg-bg-elevated border-border",
  professional: "text-warn bg-warn-dim border-warn/30",
  enterprise: "text-accent bg-accent-dim border-accent/30",
};

export function PlatformSkillsTab() {
  const [search, setSearch] = useState("");
  const [adoptFilter, setAdoptFilter] = useState<AdoptFilter>("all");

  const { data, isPending, error } = usePlatformSkills();
  const { mutate: adopt, isPending: isAdopting } = useAdoptSkill();
  const { mutate: unadopt, isPending: isUnadopting } = useUnadoptSkill();
  const { mutate: pin } = usePinSkillVersion();

  const [adoptingId, setAdoptingId] = useState<string | null>(null);

  const allSkills = data?.items ?? [];

  // Collect unique categories
  const categories = useMemo(() => {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const s of allSkills) {
      if (s.category && !seen.has(s.category)) {
        seen.add(s.category);
        result.push(s.category);
      }
    }
    return result;
  }, [allSkills]);

  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  // Client-side filtering
  const filtered = useMemo(() => {
    let items = allSkills;

    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.description?.toLowerCase().includes(q) ||
          s.category?.toLowerCase().includes(q),
      );
    }

    if (selectedCategory) {
      items = items.filter((s) => s.category === selectedCategory);
    }

    if (adoptFilter === "adopted") items = items.filter((s) => s.adopted);
    else if (adoptFilter === "not_adopted")
      items = items.filter((s) => !s.adopted && !s.is_mandatory);
    else if (adoptFilter === "mandatory")
      items = items.filter((s) => s.is_mandatory);

    return items;
  }, [allSkills, search, selectedCategory, adoptFilter]);

  function handleAdopt(skill: PlatformSkill) {
    setAdoptingId(skill.id);
    adopt(skill.id, { onSettled: () => setAdoptingId(null) });
  }

  function handleUnadopt(skill: PlatformSkill) {
    setAdoptingId(skill.id);
    unadopt(skill.id, { onSettled: () => setAdoptingId(null) });
  }

  function handlePinVersion(skill: PlatformSkill, version: string | null) {
    pin({ skillId: skill.id, payload: { pinned_version: version } });
  }

  if (error) {
    return (
      <div className="py-12 text-center">
        <p className="text-body-default text-alert">
          Failed to load platform skills.{" "}
          {error instanceof Error ? error.message : "Unknown error."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1" style={{ minWidth: 200 }}>
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint"
          />
          <input
            type="text"
            placeholder="Search skills..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-control border border-border bg-bg-elevated py-2 pl-8 pr-3 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
          />
        </div>

        {/* Adopt filter chips */}
        <div className="flex flex-wrap gap-1.5">
          {ADOPT_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setAdoptFilter(f.id)}
              className={cn(
                "rounded-control border px-3 py-1.5 text-body-default transition-colors",
                adoptFilter === f.id
                  ? "border-accent/50 bg-accent-dim text-accent"
                  : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Category chips */}
      {categories.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setSelectedCategory(null)}
            className={cn(
              "rounded-badge border px-2.5 py-1 text-body-default transition-colors",
              selectedCategory === null
                ? "border-accent/40 bg-accent-dim text-accent"
                : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
            )}
          >
            All Categories
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() =>
                setSelectedCategory(cat === selectedCategory ? null : cat)
              }
              className={cn(
                "rounded-badge border px-2.5 py-1 text-body-default transition-colors",
                selectedCategory === cat
                  ? "border-accent/40 bg-accent-dim text-accent"
                  : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
              )}
            >
              {cat}
            </button>
          ))}
        </div>
      )}

      {/* Loading skeleton */}
      {isPending && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-card border border-border bg-bg-surface"
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isPending && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <p className="text-body-default text-text-faint">
            {allSkills.length === 0
              ? "No platform skills have been published yet."
              : "No skills match your filters."}
          </p>
          {allSkills.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setSearch("");
                setAdoptFilter("all");
                setSelectedCategory(null);
              }}
              className="mt-2 text-body-default text-accent hover:underline"
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {/* Skill cards */}
      {!isPending && filtered.length > 0 && (
        <div className="space-y-3">
          {filtered.map((skill) => {
            const PatternIcon =
              EXECUTION_PATTERN_ICONS[skill.execution_pattern];
            const isProcessing = adoptingId === skill.id;

            return (
              <div
                key={skill.id}
                className="flex items-start gap-4 rounded-card border border-border bg-bg-surface p-4 transition-colors hover:border-border"
              >
                {/* Left: icon + pattern color indicator */}
                <div
                  className={cn(
                    "flex h-10 w-10 shrink-0 items-center justify-center rounded-control border",
                    EXECUTION_PATTERN_COLORS[skill.execution_pattern],
                  )}
                >
                  <PatternIcon size={18} />
                </div>

                {/* Content */}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-body-default font-medium text-text-primary">
                      {skill.name}
                    </span>

                    {/* Category chip */}
                    {skill.category && (
                      <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                        {skill.category}
                      </span>
                    )}

                    {/* Execution pattern badge */}
                    <span
                      className={cn(
                        "rounded-badge border px-2 py-0.5 font-mono text-data-value uppercase",
                        EXECUTION_PATTERN_COLORS[skill.execution_pattern],
                      )}
                    >
                      {EXECUTION_PATTERN_LABELS[skill.execution_pattern]}
                    </span>

                    {/* Invocation mode badge */}
                    <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                      {skill.invocation_mode === "llm_invoked"
                        ? "LLM-Invoked"
                        : "Pipeline"}
                    </span>

                    {/* Plan required */}
                    {skill.plan_required && (
                      <span
                        className={cn(
                          "rounded-badge border px-2 py-0.5 font-mono text-data-value uppercase",
                          PLAN_BADGE[skill.plan_required],
                        )}
                      >
                        {skill.plan_required}+
                      </span>
                    )}

                    {/* Mandatory badge */}
                    {skill.is_mandatory && (
                      <span className="flex items-center gap-1 rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                        <Lock size={10} />
                        Required
                      </span>
                    )}
                  </div>

                  {/* Description */}
                  {skill.description && (
                    <p className="mt-1 line-clamp-2 text-body-default text-text-muted">
                      {skill.description}
                    </p>
                  )}

                  {/* Version + pin info when adopted */}
                  {skill.adopted && (
                    <div className="mt-2 flex items-center gap-2">
                      <span className="font-mono text-data-value text-text-faint">
                        v{skill.version}
                      </span>
                      {skill.pinned_version && (
                        <span className="font-mono text-data-value text-warn">
                          pinned: v{skill.pinned_version}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Right: action */}
                <div className="shrink-0">
                  {skill.is_mandatory ? (
                    <div className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-body-default text-text-faint">
                      <Lock size={13} />
                      Platform Required
                    </div>
                  ) : skill.adopted ? (
                    <div className="flex items-center gap-2">
                      {/* Version pin dropdown */}
                      <PinVersionDropdown
                        skill={skill}
                        onPin={handlePinVersion}
                      />
                      {/* Unadopt */}
                      <button
                        type="button"
                        onClick={() => handleUnadopt(skill)}
                        disabled={isProcessing || isUnadopting}
                        className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:border-alert/40 hover:text-alert disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isProcessing ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : null}
                        Remove
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleAdopt(skill)}
                      disabled={isProcessing || isAdopting}
                      className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-body-default font-medium text-bg-base transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isProcessing ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <CheckCircle size={13} />
                      )}
                      Adopt
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pin version dropdown
// ---------------------------------------------------------------------------

function PinVersionDropdown({
  skill,
  onPin,
}: {
  skill: PlatformSkill;
  onPin: (skill: PlatformSkill, version: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  // Generate version options: current version and a few prior
  const currentVersion = skill.version;
  const versions: string[] = [];
  for (let v = currentVersion; v >= Math.max(1, currentVersion - 4); v--) {
    versions.push(String(v));
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
      >
        <span className="font-mono text-data-value">
          {skill.pinned_version ? `v${skill.pinned_version}` : "Latest"}
        </span>
        <ChevronDown size={12} />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div className="absolute right-0 top-full z-20 mt-1 w-36 overflow-hidden rounded-card border border-border bg-bg-surface shadow-lg">
            <button
              type="button"
              onClick={() => {
                onPin(skill, null);
                setOpen(false);
              }}
              className={cn(
                "w-full px-3 py-2 text-left text-body-default transition-colors hover:bg-bg-elevated",
                !skill.pinned_version ? "text-accent" : "text-text-muted",
              )}
            >
              Always Latest
            </button>
            {versions.map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => {
                  onPin(skill, v);
                  setOpen(false);
                }}
                className={cn(
                  "w-full px-3 py-2 text-left font-mono text-data-value transition-colors hover:bg-bg-elevated",
                  skill.pinned_version === v
                    ? "text-accent"
                    : "text-text-muted",
                )}
              >
                v{v}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
