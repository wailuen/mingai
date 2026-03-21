"use client";

import { useState } from "react";
import { Plus, BookOpen } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { LibraryList } from "./elements/LibraryList";
import { LibraryForm } from "./elements/LibraryForm";
import type { LLMLibraryEntry } from "@/lib/hooks/useLLMLibrary";

/**
 * P2LLM-013: Platform LLM Library Management.
 * Catalog of model entries with lifecycle management (Draft -> Published -> Deprecated).
 */
export default function LLMLibraryPage() {
  const [showForm, setShowForm] = useState(false);
  const [editingEntry, setEditingEntry] = useState<LLMLibraryEntry | null>(
    null,
  );

  function handleEdit(entry: LLMLibraryEntry) {
    setEditingEntry(entry);
    setShowForm(true);
  }

  function handleCloseForm() {
    setShowForm(false);
    setEditingEntry(null);
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="mb-1 flex items-center gap-2.5">
              <BookOpen size={18} className="text-accent" />
              <h1 className="text-page-title text-text-primary">
                LLM Library
              </h1>
            </div>
            <p className="mt-1 text-body-default text-text-muted">
              Platform catalog of available models with pricing and lifecycle
              management
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setEditingEntry(null);
              setShowForm(true);
            }}
            className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={16} />
            New Entry
          </button>
        </div>

        {/* Library table */}
        <ErrorBoundary>
          <LibraryList onEdit={handleEdit} />
        </ErrorBoundary>

        {/* Create/edit modal */}
        {showForm && (
          <LibraryForm
            entry={editingEntry}
            onClose={handleCloseForm}
            onSaved={handleCloseForm}
          />
        )}
      </div>
    </AppShell>
  );
}
