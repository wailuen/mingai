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

// ---------------------------------------------------------------------------
// MTTR types & hook — GET /api/v1/platform/analytics/issues/mttr
// ---------------------------------------------------------------------------

export interface MTTREntry {
  severity: string;
  avg_hours: number;
  median_hours: number;
  count: number;
}

export function useIssueMTTR(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-mttr", period],
    queryFn: () =>
      apiGet<MTTREntry[]>(
        `/api/v1/platform/analytics/issues/mttr?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// Top Bugs types & hook — GET /api/v1/platform/analytics/issues/top-bugs
// ---------------------------------------------------------------------------

export interface TopBug {
  id: string;
  title: string;
  report_count: number;
  tenant_count: number;
  status: string;
}

export function useTopBugs(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-top-bugs", period],
    queryFn: () =>
      apiGet<TopBug[]>(
        `/api/v1/platform/analytics/issues/top-bugs?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// Trend types & hook — GET /api/v1/platform/analytics/issues/trend
// ---------------------------------------------------------------------------

export interface TrendEntry {
  week: string;
  p0: number;
  p1: number;
  p2: number;
  p3: number;
  p4: number;
  total: number;
}

export function useIssueTrend(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-trend", period],
    queryFn: () =>
      apiGet<TrendEntry[]>(
        `/api/v1/platform/analytics/issues/trend?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// Duplicate clusters types & hook — GET /api/v1/platform/analytics/issues/duplicates
// ---------------------------------------------------------------------------

export interface DuplicateCluster {
  cluster_id: string;
  title: string;
  affected_tenants: string[];
  tenant_count: number;
  total_reports: number;
  first_report_id: string;
}

export function useIssueDuplicates(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-duplicates", period],
    queryFn: () =>
      apiGet<DuplicateCluster[]>(
        `/api/v1/platform/analytics/issues/duplicates?period=${period}`,
      ),
  });
}

// ---------------------------------------------------------------------------
// SLA adherence types & hook — GET /api/v1/platform/analytics/issues/sla
// ---------------------------------------------------------------------------

export interface SLAAdherenceData {
  adherence_pct: number;
  target_pct: number;
  resolved_in_sla: number;
  resolved_out_sla: number;
  total_resolved: number;
}

export function useIssueSLA(period: AnalyticsPeriod) {
  return useQuery({
    queryKey: ["issue-analytics-sla", period],
    queryFn: () =>
      apiGet<SLAAdherenceData>(
        `/api/v1/platform/analytics/issues/sla?period=${period}`,
      ),
  });
}
