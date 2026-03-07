import { Zap, Circle } from "lucide-react";

interface CacheStateChipProps {
  cacheHit: boolean;
  cacheAgeSeconds?: number | null;
}

function formatAge(seconds: number): string {
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m ago`;
  }
  return `${Math.round(seconds / 3600)}h ago`;
}

/**
 * FE-014: Shows cache hit/miss status per AI message.
 * - Cache hit: lightning bolt + "Fast response" (warn color), tooltip with age
 * - Cache miss: circle dot + "Live response" (accent color)
 */
export function CacheStateChip({
  cacheHit,
  cacheAgeSeconds,
}: CacheStateChipProps) {
  if (cacheHit) {
    const title =
      cacheAgeSeconds != null
        ? `Cached ${formatAge(cacheAgeSeconds)}`
        : "Cached response";

    return (
      <span
        className="inline-flex items-center gap-1 rounded-badge bg-warn-dim px-1.5 py-0.5 font-mono text-label-nav text-warn"
        title={title}
      >
        <Zap size={11} />
        Fast response
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
