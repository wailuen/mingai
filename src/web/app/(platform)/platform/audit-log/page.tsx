"use client";

import { useState, useCallback } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { useAuditLog, type AuditLogFilters } from "@/lib/hooks/useAuditLog";
import { AuditFilterBar } from "./elements/AuditFilterBar";
import { AuditLogTable } from "./elements/AuditLogTable";

const ROWS_PER_PAGE = 50;

const EMPTY_FILTERS: AuditLogFilters = {};

/**
 * FE-056: Platform Audit Log UI.
 * Displays a paginated, filterable table of all platform audit events.
 */
export default function AuditLogPage() {
  const [page, setPage] = useState(1);
  const [draftFilters, setDraftFilters] =
    useState<AuditLogFilters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] =
    useState<AuditLogFilters>(EMPTY_FILTERS);

  const { data, isPending, error } = useAuditLog(
    page,
    ROWS_PER_PAGE,
    appliedFilters,
  );

  const handleApply = useCallback(() => {
    setAppliedFilters({ ...draftFilters });
    setPage(1);
  }, [draftFilters]);

  const handleClear = useCallback(() => {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setPage(1);
  }, []);

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6">
          <h1 className="text-page-title text-text-primary">Audit Log</h1>
          <p className="mt-1 text-sm text-text-muted">
            Track all platform activity and administrative actions
          </p>
        </div>

        <div className="mb-5">
          <AuditFilterBar
            filters={draftFilters}
            onFiltersChange={setDraftFilters}
            onApply={handleApply}
            onClear={handleClear}
          />
        </div>

        <ErrorBoundary>
          <AuditLogTable
            data={data}
            isPending={isPending}
            error={error}
            page={page}
            onPageChange={setPage}
          />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
