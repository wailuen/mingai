"use client";

import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useCacheStats } from "@/lib/hooks/useCacheAnalytics";
import { CacheKPICards } from "./elements/CacheKPICards";
import { TopHitPatterns } from "./elements/TopHitPatterns";

function CacheKPISkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="rounded-card border border-border bg-bg-surface p-5"
        >
          <div className="h-3 w-20 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="mt-3 h-7 w-24 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="rounded-card border border-border bg-bg-surface">
      <div className="border-b border-border px-5 py-3">
        <div className="h-4 w-32 animate-pulse rounded-badge bg-bg-elevated" />
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex gap-4 border-b border-border-faint px-3.5 py-3"
        >
          <div className="h-4 w-48 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="ml-auto h-4 w-16 animate-pulse rounded-badge bg-bg-elevated" />
          <div className="h-4 w-12 animate-pulse rounded-badge bg-bg-elevated" />
        </div>
      ))}
    </div>
  );
}

function CacheAnalyticsContent() {
  const { data, isPending, error } = useCacheStats();

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load cache analytics: {error.message}
      </p>
    );
  }

  if (isPending) {
    return (
      <div className="space-y-6">
        <CacheKPISkeleton />
        <TableSkeleton />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-12 text-center">
        <p className="text-body-default text-text-muted">
          No cache data available yet. Cache analytics will appear here once the
          system starts processing queries.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <CacheKPICards stats={data} />
      <TopHitPatterns patterns={data.top_hit_patterns} />
    </div>
  );
}

/**
 * FE-048: Cache Analytics Panel.
 * Displays cache hit/miss rates, latency, and top hit patterns.
 */
export default function CacheAnalyticsPage() {
  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Cache Analytics</h1>
          <p className="mt-1 text-body-default text-text-muted">
            Monitor cache performance and query patterns
          </p>
        </div>

        <ErrorBoundary>
          <CacheAnalyticsContent />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
