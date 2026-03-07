"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiPatch, apiDelete } from "@/lib/api";
import { MoreHorizontal } from "lucide-react";
import type { UserRow } from "./UserTable";

/**
 * Per-user action menu: role change, suspend/activate, delete (anonymize).
 * Destructive actions show confirmation dialogs.
 */
export function UserActionMenu({ user }: { user: UserRow }) {
  const [open, setOpen] = useState(false);
  const [showSuspendDialog, setShowSuspendDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const queryClient = useQueryClient();

  async function handleRoleChange() {
    const newRole = user.role === "tenant_admin" ? "user" : "tenant_admin";
    await apiPatch(`/api/v1/users/${user.id}/role`, { role: newRole });
    queryClient.invalidateQueries({ queryKey: ["users"] });
    setOpen(false);
  }

  async function handleStatusToggle() {
    const newStatus = user.status === "active" ? "suspended" : "active";
    await apiPatch(`/api/v1/users/${user.id}/status`, { status: newStatus });
    queryClient.invalidateQueries({ queryKey: ["users"] });
    setShowSuspendDialog(false);
    setOpen(false);
  }

  async function handleDelete() {
    await apiDelete(`/api/v1/users/${user.id}`);
    queryClient.invalidateQueries({ queryKey: ["users"] });
    setShowDeleteDialog(false);
    setOpen(false);
  }

  return (
    <>
      <div className="relative">
        <button
          onClick={() => setOpen(!open)}
          className="flex h-7 w-7 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-muted"
        >
          <MoreHorizontal size={14} />
        </button>
        {open && (
          <>
            {/* Backdrop to close menu */}
            <div
              className="fixed inset-0 z-10"
              onClick={() => setOpen(false)}
            />
            <div className="absolute right-0 top-full z-20 mt-1 w-48 rounded-card border border-border bg-bg-surface p-1 shadow-lg">
              <button
                onClick={handleRoleChange}
                className="w-full rounded-control px-3 py-1.5 text-left text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                {user.role === "tenant_admin"
                  ? "Demote to User"
                  : "Promote to Admin"}
              </button>
              <button
                onClick={() => {
                  setOpen(false);
                  setShowSuspendDialog(true);
                }}
                className="w-full rounded-control px-3 py-1.5 text-left text-sm text-warn transition-colors hover:bg-warn-dim"
              >
                {user.status === "active" ? "Suspend User" : "Activate User"}
              </button>
              <div className="my-1 border-t border-border-faint" />
              <button
                onClick={() => {
                  setOpen(false);
                  setShowDeleteDialog(true);
                }}
                className="w-full rounded-control px-3 py-1.5 text-left text-sm text-alert transition-colors hover:bg-alert-dim"
              >
                Delete (Anonymize)
              </button>
            </div>
          </>
        )}
      </div>

      {/* Suspend confirmation dialog */}
      {showSuspendDialog && (
        <ConfirmDialog
          title={user.status === "active" ? "Suspend User" : "Activate User"}
          description={
            user.status === "active"
              ? `Suspending ${user.name} will prevent them from accessing the workspace. They can be reactivated later.`
              : `Reactivating ${user.name} will restore their access to the workspace.`
          }
          confirmLabel={user.status === "active" ? "Suspend" : "Activate"}
          variant={user.status === "active" ? "warn" : "accent"}
          onConfirm={handleStatusToggle}
          onCancel={() => setShowSuspendDialog(false)}
        />
      )}

      {/* Delete confirmation dialog */}
      {showDeleteDialog && (
        <ConfirmDialog
          title="Delete User"
          description={`This will anonymize all conversations and data for ${user.name}. This action cannot be undone.`}
          confirmLabel="Delete and Anonymize"
          variant="alert"
          onConfirm={handleDelete}
          onCancel={() => setShowDeleteDialog(false)}
        />
      )}
    </>
  );
}

function ConfirmDialog({
  title,
  description,
  confirmLabel,
  variant,
  onConfirm,
  onCancel,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  variant: "alert" | "warn" | "accent";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [processing, setProcessing] = useState(false);

  async function handleConfirm() {
    setProcessing(true);
    try {
      await onConfirm();
    } finally {
      setProcessing(false);
    }
  }

  const buttonStyles = {
    alert: "bg-alert text-bg-base hover:opacity-90",
    warn: "bg-warn text-bg-base hover:opacity-90",
    accent: "bg-accent text-bg-base hover:opacity-90",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-md rounded-card border border-border bg-bg-surface p-5">
        <h2 className="mb-2 text-section-heading text-text-primary">{title}</h2>
        <p className="mb-5 text-sm text-text-muted">{description}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={processing}
            className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={processing}
            className={`rounded-control px-4 py-1.5 text-sm font-semibold transition-opacity disabled:opacity-50 ${buttonStyles[variant]}`}
          >
            {processing ? "Processing..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
