"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TopHitPattern {
  pattern: string;
  count: number;
}

export interface CacheStats {
  hit_rate_pct: number;
  miss_rate_pct: number;
  avg_hit_latency_ms: number;
  avg_miss_latency_ms: number;
  total_cached_queries: number;
  cache_size_mb: number;
  top_hit_patterns: TopHitPattern[];
}

// ---------------------------------------------------------------------------
// useCacheStats
// ---------------------------------------------------------------------------

export function useCacheStats() {
  return useQuery({
    queryKey: ["platform-cache-analytics"],
    queryFn: () => apiGet<CacheStats>("/api/v1/platform/analytics/cache"),
    staleTime: 30 * 1000,
  });
}
