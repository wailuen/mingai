"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useIssueDuplicates,
  type AnalyticsPeriod,
  type DuplicateCluster,
} from "@/lib/hooks/useIssueAnalytics";
import { Skeleton } from "@/components/shared/LoadingState";

// ---------------------------------------------------------------------------
// ClusterRow (expandable)
// ---------------------------------------------------------------------------

function ClusterRow({ cluster }: { cluster: DuplicateCluster }) {
  const [expanded, setExpanded] = useState(false);
  const ExpandIcon = expanded ? ChevronDown : ChevronRight;

  return (
    <div className="border-b border-border-faint last:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className={cn(
          "flex w-full items-center gap-3 px-5 py-3.5 text-left transition-colors hover:bg-accent-dim",
          expanded && "bg-bg-elevated",
        )}
      >
        <ExpandIcon size={14} className="shrink-0 text-text-faint" />

        <span className="flex-1 text-sm font-medium text-text-primary">
          {cluster.title}
        </span>

        <span className="shrink-0 font-mono text-xs text-text-muted">
          {cluster.tenant_count} tenants
        </span>

        <span className="shrink-0 font-mono text-xs text-text-muted">
          {cluster.total_reports} reports
        </span>

        <Link
          href={`/platform/issues/${encodeURIComponent(cluster.first_report_id)}`}
          onClick={(e) => e.stopPropagation()}
          className="shrink-0 text-accent transition-colors hover:text-text-primary"
          title="View first report"
        >
          <ExternalLink size={14} />
        </Link>
      </button>

      {expanded && (
        <div className="bg-bg-elevated px-10 py-3">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-text-faint">
            Affected Tenants
          </p>
          <div className="flex flex-wrap gap-2">
            {cluster.affected_tenants.map((tenant) => (
              <span
                key={tenant}
                className="rounded-badge border border-border bg-bg-surface px-2 py-0.5 text-xs text-text-muted"
              >
                {tenant}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DuplicateView
// ---------------------------------------------------------------------------

interface DuplicateViewProps {
  period: AnalyticsPeriod;
}

export function DuplicateView({ period }: DuplicateViewProps) {
  const { data: clusters, isPending, error } = useIssueDuplicates(period);

  if (error) {
    return (
      <p className="text-sm text-alert">
        Failed to load duplicate clusters: {error.message}
      </p>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-section-heading text-text-primary">
        Cross-Tenant Duplicate Clusters
      </h2>

      {isPending ? (
        <div className="space-y-2 rounded-card border border-border bg-bg-surface p-5">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : !clusters || clusters.length === 0 ? (
        <p className="text-sm text-text-faint">
          No duplicate clusters found for this period.
        </p>
      ) : (
        <div className="overflow-hidden rounded-card border border-border bg-bg-surface">
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-border px-5 py-2.5">
            <span className="w-5" />
            <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Cluster Title
            </span>
            <span className="w-24 text-right text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Tenants
            </span>
            <span className="w-24 text-right text-[11px] font-medium uppercase tracking-wider text-text-faint">
              Reports
            </span>
            <span className="w-5" />
          </div>

          {clusters.map((cluster) => (
            <ClusterRow key={cluster.cluster_id} cluster={cluster} />
          ))}
        </div>
      )}
    </div>
  );
}
