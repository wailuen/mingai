"use client";

import { useState, useRef, useEffect } from "react";
import { X, UserPlus } from "lucide-react";

interface AssignDialogProps {
  count?: number;
  onConfirm: (email: string) => void;
  onClose: () => void;
}

/**
 * FE-054: Dialog for assigning one or multiple issues to an engineer by email.
 */
export function AssignDialog({ count, onConfirm, onClose }: AssignDialogProps) {
  const [email, setEmail] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) return;
    onConfirm(trimmed);
  }

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-card border border-border bg-bg-surface p-6 shadow-xl">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-text-primary">
            <UserPlus size={16} className="text-accent" />
            <h2 className="text-[15px] font-semibold">
              {count && count > 1 ? `Assign ${count} Issues` : "Assign Issue"}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-muted">
              Assignee email
            </label>
            <input
              ref={inputRef}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="engineer@company.com"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              required
            />
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!email.trim()}
              className="rounded-control border border-accent/30 bg-accent-dim px-4 py-2 text-body-default font-medium text-accent transition-colors hover:bg-accent hover:text-bg-base disabled:cursor-not-allowed disabled:opacity-40"
            >
              Assign
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
