"use client";

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { Skeleton } from "@/components/shared/LoadingState";
import { CheckCircle2, Circle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChecklistItem {
  id: string;
  label: string;
  completed: boolean;
  href: string;
}

interface ChecklistResponse {
  items: ChecklistItem[];
  completed_count: number;
  total_count: number;
}

/**
 * Onboarding progress checklist for tenant admin dashboard.
 * Items: workspace setup, auth configured, document store connected,
 * first agent deployed, users invited.
 * Completed items shown with green checkmark.
 */
export function SetupChecklist() {
  const { data, isLoading } = useQuery<ChecklistResponse>({
    queryKey: ["setup-checklist"],
    queryFn: () => apiGet<ChecklistResponse>("/api/v1/admin/setup-checklist"),
  });

  if (isLoading) {
    return (
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <Skeleton className="mb-4 h-4 w-32" />
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || data.completed_count === data.total_count) {
    return null;
  }

  const progressPct =
    data.total_count > 0
      ? Math.round((data.completed_count / data.total_count) * 100)
      : 0;

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-section-heading text-text-primary">
          Getting Started
        </h2>
        <span className="font-mono text-xs text-text-faint">
          {data.completed_count}/{data.total_count} completed
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-4 h-1.5 rounded-full bg-bg-elevated">
        <div
          className="h-full rounded-full bg-accent transition-all duration-300"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      <div className="space-y-2">
        {data.items.map((item) => (
          <a
            key={item.id}
            href={item.href}
            className={cn(
              "flex items-center gap-3 rounded-control px-3 py-2 text-sm transition-colors",
              item.completed
                ? "text-text-faint"
                : "text-text-primary hover:bg-bg-elevated",
            )}
          >
            {item.completed ? (
              <CheckCircle2 size={16} className="flex-shrink-0 text-accent" />
            ) : (
              <Circle size={16} className="flex-shrink-0 text-text-faint" />
            )}
            <span className={item.completed ? "line-through" : ""}>
              {item.label}
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}
