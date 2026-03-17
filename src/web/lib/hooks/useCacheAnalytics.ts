"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — Platform Admin (existing endpoint)
// ---------------------------------------------------------------------------

export interface TopHitPattern {
  pattern: string;
  count: number;
}

export interface CacheStats {
  hit_rate_pct: number | null;
  miss_rate_pct: number | null;
  avg_hit_latency_ms: number | null;
  avg_miss_latency_ms: number | null;
  total_cached_queries: number | null;
  cache_size_mb: number | null;
  top_hit_patterns: TopHitPattern[];
}

// ---------------------------------------------------------------------------
// Types — Tenant Admin (CACHE-017 new endpoints)
// ---------------------------------------------------------------------------

export type CachePeriod = "7d" | "30d" | "90d";

export interface CacheSummary {
  hit_rate: number;
  total_requests: number;
  cost_saved_usd: number;
  cache_hits: number;
  cache_misses: number;
}

export interface CacheByIndex {
  index_id: string;
  hit_rate: number;
  cost_saved_usd: number;
  total_requests: number;
}

export interface TopCachedQuery {
  query_hash_prefix: string;
  hit_count: number;
}

export interface DailyCostSaving {
  date: string;
  cost_saved_usd: number;
}

// ---------------------------------------------------------------------------
// Platform Admin hook (existing)
// ---------------------------------------------------------------------------

export function useCacheStats() {
  return useQuery({
    queryKey: ["platform-cache-analytics"],
    queryFn: () => apiGet<CacheStats>("/api/v1/platform/analytics/cache"),
    staleTime: 30 * 1000,
  });
}

// ---------------------------------------------------------------------------
// Tenant Admin hooks (CACHE-017)
// ---------------------------------------------------------------------------

export function useCacheSummary(period: CachePeriod) {
  return useQuery({
    queryKey: ["cache-summary", period],
    queryFn: () =>
      apiGet<CacheSummary>(
        `/api/v1/admin/analytics/cache/summary?period=${period}`,
      ),
    staleTime: 30 * 1000,
  });
}

export function useCacheByIndex(period: CachePeriod) {
  return useQuery({
    queryKey: ["cache-by-index", period],
    queryFn: () =>
      apiGet<CacheByIndex[]>(
        `/api/v1/admin/analytics/cache/by-index?period=${period}`,
      ),
    staleTime: 30 * 1000,
  });
}

export function useTopCachedQueries(period: CachePeriod) {
  return useQuery({
    queryKey: ["cache-top-queries", period],
    queryFn: () =>
      apiGet<TopCachedQuery[]>(
        `/api/v1/admin/analytics/cache/top-cached-queries?period=${period}`,
      ),
    staleTime: 30 * 1000,
  });
}

export function useDailyCostSavings(period: CachePeriod) {
  return useQuery({
    queryKey: ["cache-daily-savings", period],
    queryFn: () =>
      apiGet<DailyCostSaving[]>(
        `/api/v1/admin/analytics/cache/cost-savings?period=${period}`,
      ),
    staleTime: 30 * 1000,
  });
}
