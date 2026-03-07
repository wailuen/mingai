interface GlossaryExpansionIndicatorProps {
  expansions: string[]; // e.g., ["AWS -> Annual Wage Supplement"]
}

/**
 * MANDATORY: Show on every response with >=1 expansion.
 * Displays "Terms interpreted" badge + up to 3 expanded terms.
 */
export function GlossaryExpansionIndicator({
  expansions,
}: GlossaryExpansionIndicatorProps) {
  if (expansions.length === 0) return null;

  return (
    <div className="mt-2 flex items-center gap-2 text-xs text-text-muted">
      <span className="rounded-badge border border-border px-2 py-0.5">
        Terms interpreted
      </span>
      <span>{expansions.slice(0, 3).join(" · ")}</span>
      {expansions.length > 3 && (
        <button className="underline transition-colors hover:text-text-primary">
          +{expansions.length - 3} more
        </button>
      )}
    </div>
  );
}
