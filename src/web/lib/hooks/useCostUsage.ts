"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import type { CostPeriod } from "./useCostAnalytics";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ModelUsage {
  provider: string;
  model: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

export interface DayUsage {
  date: string;
  cost_usd: number;
}

export interface TenantCostUsage {
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
  by_model: ModelUsage[];
  by_day: DayUsage[];
}

export interface CostAnalyticsSummaryEntry {
  tenant_id: string;
  tenant_name: string;
  total_cost_usd: number;
  total_tokens: number;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** GET /api/v1/platform/tenants/:id/cost-usage?period=... */
export function useTenantCostUsage(
  tenantId: string | null,
  period: CostPeriod
) {
  return useQuery({
    queryKey: ["tenant-cost-usage", tenantId, period],
    queryFn: () =>
      apiGet<TenantCostUsage>(
        `/api/v1/platform/tenants/${tenantId}/cost-usage?period=${period}`
      ),
    enabled: !!tenantId,
  });
}

/** GET /api/v1/platform/cost-analytics/summary */
export function useCostAnalyticsSummary() {
  return useQuery({
    queryKey: ["platform-cost-analytics-summary"],
    queryFn: () =>
      apiGet<CostAnalyticsSummaryEntry[]>(
        "/api/v1/platform/cost-analytics/summary"
      ),
  });
}
