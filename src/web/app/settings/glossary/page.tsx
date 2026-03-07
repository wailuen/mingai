"use client";

import { useState, useDeferredValue } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TermList } from "./elements/TermList";
import { TermForm } from "./elements/TermForm";
import { BulkImportDialog } from "./elements/BulkImportDialog";
import { Search, Plus, Upload } from "lucide-react";
import type { GlossaryTerm } from "@/lib/hooks/useGlossary";

/**
 * FE-033: Glossary Management page (Tenant Admin).
 * Orchestrator only -- business logic lives in elements/.
 * Search, filter by status, server-side pagination, add/edit/delete terms, CSV import.
 */
export default function GlossaryPage() {
  const [searchInput, setSearchInput] = useState("");
  const searchQuery = useDeferredValue(searchInput);
  const [statusFilter, setStatusFilter] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 });

  const [editingTerm, setEditingTerm] = useState<GlossaryTerm | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [showImport, setShowImport] = useState(false);

  function handleEdit(term: GlossaryTerm) {
    setEditingTerm(term);
    setShowAddForm(true);
  }

  function handleCloseForm() {
    setShowAddForm(false);
    setEditingTerm(null);
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-1">
          <h1 className="text-page-title text-text-primary">Glossary</h1>
          <p className="mt-1 text-sm text-text-muted">
            Define terms to improve AI response accuracy
          </p>
        </div>

        {/* Action bar */}
        <div className="mb-4 mt-5 flex flex-wrap items-center gap-3">
          {/* Search */}
          <div className="relative flex-1 sm:max-w-xs">
            <Search
              size={14}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-faint"
            />
            <input
              type="text"
              placeholder="Search terms..."
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                setPagination((prev) => ({ ...prev, pageIndex: 0 }));
              }}
              className="w-full rounded-control border border-border bg-bg-elevated py-1.5 pl-8 pr-3 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPagination((prev) => ({ ...prev, pageIndex: 0 }));
            }}
            className="rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-muted transition-colors focus:border-accent focus:outline-none"
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Import CSV */}
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <Upload size={14} />
            Import CSV
          </button>

          {/* Add Term */}
          <button
            onClick={() => {
              setEditingTerm(null);
              setShowAddForm(true);
            }}
            className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={14} />
            Add Term
          </button>
        </div>

        {/* Term list */}
        <ErrorBoundary>
          <TermList
            searchQuery={searchQuery}
            statusFilter={statusFilter}
            pagination={pagination}
            onPaginationChange={setPagination}
            onEdit={handleEdit}
          />
        </ErrorBoundary>

        {/* Modals */}
        {showAddForm && (
          <TermForm term={editingTerm} onClose={handleCloseForm} />
        )}
        {showImport && (
          <BulkImportDialog onClose={() => setShowImport(false)} />
        )}
      </div>
    </AppShell>
  );
}
