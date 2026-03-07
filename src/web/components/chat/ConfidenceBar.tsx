import { cn } from "@/lib/utils";

interface ConfidenceBarProps {
  score: number; // 0.0 to 1.0
}

/**
 * Retrieval confidence visualization.
 * Label MUST be "retrieval confidence" -- never "AI confidence" or "answer quality".
 * Color: >=80% -> accent (#4FFFB0), >=60% -> warn (#f5c518), <60% -> alert (#ff6b35)
 */
export function ConfidenceBar({ score }: ConfidenceBarProps) {
  const pct = Math.round(score * 100);
  const colorClass =
    score >= 0.8 ? "bg-accent" : score >= 0.6 ? "bg-warn" : "bg-alert";

  return (
    <div className="flex items-center gap-2 text-xs text-text-muted">
      <span>retrieval confidence</span>
      <div className="h-1.5 w-20 rounded-full bg-bg-elevated">
        <div
          className={cn("h-full rounded-full", colorClass)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-text-primary">{pct}%</span>
    </div>
  );
}
