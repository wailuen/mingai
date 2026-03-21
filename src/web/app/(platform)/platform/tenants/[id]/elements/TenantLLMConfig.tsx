"use client";

import { useState } from "react";
import { Cpu, BookOpen, Key } from "lucide-react";
import { useLLMLibraryOptions, type LibraryOption } from "@/lib/hooks/useLLMLibrary";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TenantLLMConfigProps {
  tenantId: string;
  /** Current library profile id assigned to this tenant (from tenant detail API) */
  currentProfileId: string | null;
  /** Whether tenant uses BYOLLM mode */
  isByollm: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * PA-005: LLM Config section in the Platform Admin tenant drilldown.
 * Shows current profile name, mode (Library / BYOLLM), and best practices snippet.
 */
export function TenantLLMConfig({
  tenantId,
  currentProfileId,
  isByollm,
}: TenantLLMConfigProps) {
  const { data: options, isPending, error } = useLLMLibraryOptions();
  const [hoveredProfile, setHoveredProfile] = useState<string | null>(null);

  const currentProfile: LibraryOption | undefined = options?.find(
    (o) => o.id === currentProfileId,
  );

  const mode = isByollm ? "BYOLLM" : "Library";

  function bestPracticesSnippet(md: string | undefined | null): string {
    if (!md) return "No best practices documented.";
    const trimmed = md.trim();
    if (trimmed.length <= 80) return trimmed;
    return trimmed.slice(0, 77) + "...";
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      {/* Section heading */}
      <div className="mb-4 flex items-center gap-2">
        <Cpu size={16} className="text-accent" />
        <h3 className="text-[15px] font-semibold text-text-primary">
          LLM Configuration
        </h3>
      </div>

      {/* Loading skeleton */}
      {isPending && (
        <div className="space-y-3">
          <div className="h-4 w-48 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="h-4 w-32 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      )}

      {/* Error state */}
      {error && (
        <p className="text-body-default text-alert">
          Failed to load LLM config: {error.message}
        </p>
      )}

      {/* Config display */}
      {!isPending && !error && (
        <div className="space-y-3">
          {/* Mode badge */}
          <div className="flex items-center gap-3">
            <span className="text-label-nav uppercase text-text-faint">
              Mode
            </span>
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-badge px-2 py-0.5 font-mono text-[10px] uppercase",
                isByollm
                  ? "border border-warn bg-warn-dim text-warn"
                  : "border border-accent bg-accent-dim text-accent",
              )}
            >
              {isByollm ? (
                <Key size={10} />
              ) : (
                <BookOpen size={10} />
              )}
              {mode}
            </span>
          </div>

          {/* Current profile */}
          <div className="flex items-center gap-3">
            <span className="text-label-nav uppercase text-text-faint">
              Profile
            </span>
            {currentProfile ? (
              <span
                className="relative cursor-default text-body-default font-medium text-text-primary"
                onMouseEnter={() => setHoveredProfile(currentProfile.id)}
                onMouseLeave={() => setHoveredProfile(null)}
              >
                {currentProfile.display_name}
                <span className="ml-2 font-mono text-data-value text-text-faint">
                  {currentProfile.model_name}
                </span>

                {/* Tooltip: best practices snippet */}
                {hoveredProfile === currentProfile.id && (
                  <span className="absolute -top-8 left-0 z-10 max-w-xs whitespace-nowrap rounded-control border border-border bg-bg-elevated px-2.5 py-1 text-[11px] text-text-muted shadow-sm">
                    {bestPracticesSnippet(currentProfile.best_practices_md)}
                  </span>
                )}
              </span>
            ) : (
              <span className="text-body-default text-text-faint">
                {isByollm
                  ? "Tenant provides own keys"
                  : currentProfileId
                    ? "Profile not found"
                    : "No profile assigned"}
              </span>
            )}
          </div>

          {/* Provider */}
          {currentProfile && (
            <div className="flex items-center gap-3">
              <span className="text-label-nav uppercase text-text-faint">
                Provider
              </span>
              <span className="text-body-default text-text-muted">
                {currentProfile.provider === "azure_openai"
                  ? "Azure OpenAI"
                  : currentProfile.provider === "openai_direct"
                    ? "OpenAI Direct"
                    : currentProfile.provider === "anthropic"
                      ? "Anthropic"
                      : currentProfile.provider}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
