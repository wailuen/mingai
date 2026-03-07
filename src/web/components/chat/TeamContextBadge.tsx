import { Users } from "lucide-react";

interface TeamContextBadgeProps {
  teamName: string | null;
  visible: boolean;
}

/**
 * FE-010: Shows "Using [Team Name] context" when team working memory
 * was injected into the AI response generation.
 */
export function TeamContextBadge({ teamName, visible }: TeamContextBadgeProps) {
  if (!visible || !teamName) return null;

  return (
    <span className="inline-flex items-center gap-1.5 rounded-badge bg-accent-dim px-2 py-0.5 text-label-nav text-accent">
      <Users size={11} />
      Using {teamName} context
    </span>
  );
}
