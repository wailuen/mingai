import { User } from "lucide-react";

interface ProfileIndicatorProps {
  layersActive: string[];
}

/**
 * "Profile used" badge shown in AI response meta row
 * when profile context was used in generating the response.
 */
export function ProfileIndicator({ layersActive }: ProfileIndicatorProps) {
  if (layersActive.length === 0) return null;

  const labels = layersActive.map(formatLayerName);

  return (
    <div className="flex items-center gap-1.5 text-xs text-text-muted">
      <User size={12} className="text-accent" />
      <span>Profile used</span>
      <span className="font-mono text-text-faint">({labels.join(", ")})</span>
    </div>
  );
}

function formatLayerName(layer: string): string {
  const map: Record<string, string> = {
    org_context: "org",
    profile: "profile",
    working_memory: "memory",
    team_memory: "team",
  };
  return map[layer] ?? layer;
}
