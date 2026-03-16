"use client";

import { Zap, Circle, RefreshCw } from "lucide-react";

interface CacheStateChipProps {
  cacheHit: boolean;
  cacheAgeSeconds?: number | null;
  /** CACHE-018: Called when user requests a fresh (non-cached) response */
  onBypassCache?: () => void;
}

function formatAge(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s ago`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m ago`;
  }
  return `${Math.round(seconds / 3600)}h ago`;
}

/**
 * FE-014 + CACHE-018: Shows cache hit/miss status per AI message.
 * - Cache hit: lightning bolt + "Fast response" (warn color), age display, refresh button
 * - Cache miss: circle dot + "Live response" (accent color)
 */
export function CacheStateChip({
  cacheHit,
  cacheAgeSeconds,
  onBypassCache,
}: CacheStateChipProps) {
  if (cacheHit) {
    const ageLabel =
      cacheAgeSeconds != null ? formatAge(cacheAgeSeconds) : null;
    const title =
      ageLabel != null ? `Cached ${ageLabel}` : "Cached response";

    return (
      <span className="inline-flex items-center gap-1.5">
        <span
          className="inline-flex items-center gap-1 rounded-badge bg-warn-dim px-1.5 py-0.5 font-mono text-label-nav text-warn"
          title={title}
        >
          <Zap size={11} />
          Fast response
          {ageLabel != null && (
            <span className="ml-0.5 text-text-faint">{ageLabel}</span>
          )}
        </span>
        {onBypassCache && (
          <button
            type="button"
            onClick={onBypassCache}
            className="inline-flex items-center gap-1 rounded-control border border-border px-2 py-0.5 text-[11px] text-text-muted transition-colors hover:border-accent hover:text-accent"
            title="Get a fresh response (bypass cache)"
          >
            <RefreshCw size={10} />
            Refresh
          </button>
        )}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 rounded-badge bg-accent-dim px-1.5 py-0.5 font-mono text-label-nav text-accent">
      <Circle size={11} fill="currentColor" />
      Live response
    </span>
  );
}
