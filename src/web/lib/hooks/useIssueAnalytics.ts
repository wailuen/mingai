"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AnalyticsPeriod = "7d" | "30d" | "90d";

export interface IssuesSummary {
  total: number;
  open: number;
  resolved_in_sla_pct: number;
  avg_resolution_hours: number;
  p0_count: number;
  p1_count: number;
}

export interface TenantIssueStat {
  tenant_name: string;
  total: number;
  open: number;
  p0_count: number;
}

export interface SeverityBreakdown {
  severity: string;
  count: number;
  pct: number;
}

// ---------------------------------------------------------------------------
// useIssueAnalyticsSummary — GET /api/v1/platform/analytics/issues/summary
// ---------------------------------------------------------------------------

export function useIssueAnalyticsSummary(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-summary", period],
    queryFn: () =>
      apiGet<IssuesSummary>(
        `/api/v1/platform/analytics/issues/summary?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// useIssuesByTenant — GET /api/v1/platform/analytics/issues/by-tenant
// ---------------------------------------------------------------------------

export function useIssuesByTenant(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-by-tenant", period],
    queryFn: () =>
      apiGet<TenantIssueStat[]>(
        `/api/v1/platform/analytics/issues/by-tenant?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// useIssuesBySeverity — GET /api/v1/platform/analytics/issues/by-severity
// ---------------------------------------------------------------------------

export function useIssuesBySeverity(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-by-severity", period],
    queryFn: () =>
      apiGet<SeverityBreakdown[]>(
        `/api/v1/platform/analytics/issues/by-severity?period=${period}`,
      ),
  });
}
