"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

export interface SatisfactionTrendPoint {
  date: string;
  satisfaction_pct: number;
  total: number;
}

export interface AnalyticsSatisfactionResponse {
  trend: SatisfactionTrendPoint[];
  satisfaction_7d: number;
}

export interface LowConfidenceItem {
  message_id: string;
  query_text: string;
  created_at: string;
  retrieval_confidence: number;
}

export interface LowConfidenceResponse {
  items: LowConfidenceItem[];
}

const ANALYTICS_KEY = "analytics";

export function useSatisfactionData() {
  return useQuery({
    queryKey: [ANALYTICS_KEY, "satisfaction"],
    queryFn: () =>
      apiGet<AnalyticsSatisfactionResponse>(
        "/api/v1/admin/analytics/satisfaction",
      ),
    staleTime: 60 * 1000, // 1 minute
  });
}

export function useLowConfidenceItems(limit?: number) {
  const params = new URLSearchParams();
  if (limit !== undefined) {
    params.set("limit", String(limit));
  }
  const qs = params.toString();
  const path = `/api/v1/admin/analytics/low-confidence${qs ? `?${qs}` : ""}`;

  return useQuery({
    queryKey: [ANALYTICS_KEY, "low-confidence", limit],
    queryFn: () => apiGet<LowConfidenceResponse>(path),
    staleTime: 60 * 1000,
  });
}
