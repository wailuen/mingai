"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CostSummary {
  total_llm_cost: number;
  total_infra_cost: number;
  total_revenue: number;
  gross_margin_pct: number;
  period: string;
}

export interface TenantCost {
  tenant_id: string;
  tenant_name: string;
  plan: string;
  tokens_consumed: number;
  llm_cost: number;
  infra_cost: number;
  plan_revenue: number;
  gross_margin_pct: number;
}

export interface MarginPoint {
  date: string;
  margin_pct: number;
}

export type CostPeriod = "7d" | "30d" | "90d";

// ---------------------------------------------------------------------------
// usePlatformCostSummary
// ---------------------------------------------------------------------------

export function usePlatformCostSummary(period: CostPeriod) {
  return useQuery({
    queryKey: ["platform-cost-summary", period],
    queryFn: () =>
      apiGet<CostSummary>(
        `/api/v1/platform/analytics/cost/summary?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// useTenantCostBreakdown
// ---------------------------------------------------------------------------

export function useTenantCostBreakdown(period: CostPeriod) {
  return useQuery({
    queryKey: ["platform-cost-tenants", period],
    queryFn: () =>
      apiGet<TenantCost[]>(
        `/api/v1/platform/analytics/cost/tenants?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// useMarginTrend
// ---------------------------------------------------------------------------

export function useMarginTrend(period: CostPeriod) {
  return useQuery({
    queryKey: ["platform-cost-margin-trend", period],
    queryFn: () =>
      apiGet<MarginPoint[]>(
        `/api/v1/platform/analytics/cost/margin-trend?period=${period}`,
      ),
  });
}
