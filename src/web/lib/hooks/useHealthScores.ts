"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — PA-008: At-risk tenants list
// ---------------------------------------------------------------------------

export interface AtRiskTenantComponentBreakdown {
  usage_trend_score: number | null;
  feature_breadth_score: number | null;
  satisfaction_score: number | null;
  error_rate_score: number | null;
}

export interface AtRiskTenant {
  tenant_id: string;
  name: string;
  composite_score: number | null;
  at_risk_reason: string | null;
  weeks_at_risk: number;
  component_breakdown: AtRiskTenantComponentBreakdown;
}

// ---------------------------------------------------------------------------
// Types — PA-009: Tenant health drilldown with 12-week trend
// ---------------------------------------------------------------------------

export interface HealthCurrent {
  composite: number | null;
  usage_trend: number | null;
  feature_breadth: number | null;
  satisfaction: number | null;
  error_rate: number | null;
  at_risk_flag: boolean;
}

export interface HealthTrendPoint {
  week: string; // "2026-W10"
  composite: number | null;
  usage_trend: number | null;
  satisfaction: number | null;
}

export interface TenantHealthDrilldown {
  current: HealthCurrent;
  trend: HealthTrendPoint[];
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/**
 * PA-008: Fetch tenants flagged at-risk from the latest health score snapshot.
 * Returns an empty array when no tenants are at risk.
 */
export function useAtRiskTenants() {
  return useQuery({
    queryKey: ["platform", "tenants", "at-risk"],
    queryFn: () => apiGet<AtRiskTenant[]>("/api/v1/platform/tenants/at-risk"),
  });
}

/**
 * PA-009: Health score drilldown for a single tenant.
 * Returns current snapshot + 12 weekly trend data points.
 */
export function useTenantHealthDrilldown(tenantId: string | null | undefined) {
  return useQuery({
    queryKey: ["platform", "tenants", tenantId, "health"],
    queryFn: () =>
      apiGet<TenantHealthDrilldown>(
        `/api/v1/platform/tenants/${tenantId}/health`,
      ),
    enabled: !!tenantId,
  });
}
