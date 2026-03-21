"use client";

import { useState } from "react";
import {
  useSuspendTenant,
  useActivateTenant,
} from "@/lib/hooks/usePlatformDashboard";

interface TenantActionsProps {
  tenantId: string;
  status: string;
}

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel: string;
  confirmClassName: string;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
}

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  confirmClassName,
  onConfirm,
  onCancel,
  isPending,
}: ConfirmDialogProps) {
  return (
    <div className="mt-3 rounded-card border border-border bg-bg-elevated p-4">
      <p className="text-body-default font-semibold text-text-primary">{title}</p>
      <p className="mt-1 text-body-default text-text-muted">{message}</p>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={onConfirm}
          disabled={isPending}
          className={confirmClassName}
        >
          {isPending ? "Processing..." : confirmLabel}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={isPending}
          className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export function TenantActions({ tenantId, status }: TenantActionsProps) {
  const [confirmAction, setConfirmAction] = useState<
    "suspend" | "activate" | "delete" | null
  >(null);

  const suspendMutation = useSuspendTenant();
  const activateMutation = useActivateTenant();

  function handleSuspend() {
    suspendMutation.mutate(tenantId, {
      onSuccess: () => setConfirmAction(null),
    });
  }

  function handleActivate() {
    activateMutation.mutate(tenantId, {
      onSuccess: () => setConfirmAction(null),
    });
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        {status === "active" ? (
          <button
            type="button"
            onClick={() => setConfirmAction("suspend")}
            className="rounded-control border border-alert-ring bg-alert-dim px-4 py-2 text-body-default font-medium text-alert transition-colors hover:bg-alert/10"
          >
            Suspend Tenant
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmAction("activate")}
            className="rounded-control border border-accent-ring bg-accent-dim px-4 py-2 text-body-default font-medium text-accent transition-colors hover:bg-accent/10"
          >
            Reactivate Tenant
          </button>
        )}

        <button
          type="button"
          onClick={() => setConfirmAction("delete")}
          className="text-body-default text-text-faint transition-colors hover:text-alert"
        >
          Schedule Deletion
        </button>
      </div>

      {confirmAction === "suspend" && (
        <ConfirmDialog
          title="Suspend Tenant"
          message="This will block all logins and API access for this tenant. Are you sure?"
          confirmLabel="Confirm Suspend"
          confirmClassName="rounded-control bg-alert px-3 py-1.5 text-body-default font-medium text-bg-base transition-opacity hover:opacity-90 disabled:opacity-50"
          onConfirm={handleSuspend}
          onCancel={() => setConfirmAction(null)}
          isPending={suspendMutation.isPending}
        />
      )}

      {confirmAction === "activate" && (
        <ConfirmDialog
          title="Reactivate Tenant"
          message="This will restore all access for this tenant. Proceed?"
          confirmLabel="Confirm Reactivate"
          confirmClassName="rounded-control bg-accent px-3 py-1.5 text-body-default font-medium text-bg-base transition-opacity hover:opacity-90 disabled:opacity-50"
          onConfirm={handleActivate}
          onCancel={() => setConfirmAction(null)}
          isPending={activateMutation.isPending}
        />
      )}

      {confirmAction === "delete" && (
        <ConfirmDialog
          title="Schedule Deletion"
          message="This action is irreversible. The tenant and all associated data will be permanently deleted after a 30-day grace period."
          confirmLabel="Schedule Deletion"
          confirmClassName="rounded-control bg-alert px-3 py-1.5 text-body-default font-medium text-bg-base transition-opacity hover:opacity-90 disabled:opacity-50"
          onConfirm={() => setConfirmAction(null)}
          onCancel={() => setConfirmAction(null)}
          isPending={false}
        />
      )}
    </div>
  );
}
