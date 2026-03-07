"use client";

/**
 * Full-page skeleton for the tenant detail view.
 * Displayed while the tenant detail API call is in flight.
 */
export function TenantDetailSkeleton() {
  return (
    <div className="animate-pulse space-y-6">
      {/* Header skeleton */}
      <div>
        <div className="flex items-center gap-3">
          <div className="h-7 w-48 rounded-badge bg-bg-elevated" />
          <div className="h-5 w-16 rounded-badge bg-bg-elevated" />
          <div className="h-5 w-20 rounded-badge bg-bg-elevated" />
        </div>
        <div className="mt-2 h-4 w-64 rounded-badge bg-bg-elevated" />
      </div>

      {/* Actions skeleton */}
      <div className="flex gap-3">
        <div className="h-9 w-36 rounded-control bg-bg-elevated" />
        <div className="h-9 w-32 rounded-control bg-bg-elevated" />
      </div>

      {/* Cards skeleton */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="h-64 rounded-card bg-bg-elevated" />
        <div className="h-64 rounded-card bg-bg-elevated" />
      </div>
    </div>
  );
}
