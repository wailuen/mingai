/**
 * Resolves Obsidian Intelligence CSS custom properties for use in Recharts
 * SVG attributes (fill, stroke) where Tailwind classes cannot be applied.
 *
 * Usage:
 *   import { CHART_COLORS } from "@/lib/chartColors";
 *   <Bar fill={CHART_COLORS.accent} />
 *
 * These are resolved from the CSS variables defined in globals.css.
 * They default to the dark-mode values, which are the canonical values
 * per the design system. Light mode overrides are handled via CSS.
 */
export const CHART_COLORS = {
  // Design system tokens (dark-mode canonical values)
  accent: "#4fffb0",
  alert: "#ff6b35",
  warn: "#f5c518",
  bgBase: "#0c0e14",
  bgSurface: "#161a24",
  bgElevated: "#1e2330",
  border: "#2a3042",
  textPrimary: "#f1f5fb",
  textMuted: "#8892a4",
  textFaint: "#4a5568",

  // Issue severity colors (per design system table)
  severity: {
    P0: "#FF3547", // red
    P1: "#ff6b35", // --alert orange
    P2: "#f5c518", // --warn yellow
    P3: "#1e2330", // --bg-elevated grey
    P4: "#1e2330", // --bg-elevated grey
  },
} as const;

/** Resolve accent/warn/alert from adherence percentage for SLA gauge. */
export function slaAdherenceColor(pct: number): string {
  if (pct > 80) return CHART_COLORS.accent;
  if (pct >= 50) return CHART_COLORS.warn;
  return CHART_COLORS.alert; // --alert orange, not P0 red
}

/** Resolve accent/warn/alert from health score (0-100). */
export function healthScoreColor(score: number | null): string {
  if (score === null) return CHART_COLORS.textFaint;
  if (score >= 70) return CHART_COLORS.accent;
  if (score >= 50) return CHART_COLORS.warn;
  return CHART_COLORS.alert;
}

/** Resolve color by issue severity string. */
export function severityColor(severity: string): string {
  return (
    CHART_COLORS.severity[severity as keyof typeof CHART_COLORS.severity] ??
    CHART_COLORS.bgElevated
  );
}
