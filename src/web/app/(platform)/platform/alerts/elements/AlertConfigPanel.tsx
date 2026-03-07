"use client";

import { useState } from "react";
import { X } from "lucide-react";
import type { PlatformAlert } from "@/lib/hooks/usePlatformAlerts";
import { useConfigureAlert } from "@/lib/hooks/usePlatformAlerts";

interface AlertConfigPanelProps {
  alert: PlatformAlert;
  onClose: () => void;
}

export function AlertConfigPanel({ alert, onClose }: AlertConfigPanelProps) {
  const [threshold, setThreshold] = useState(String(alert.threshold));
  const configure = useConfigureAlert();

  function handleSave() {
    const value = parseFloat(threshold);
    if (Number.isNaN(value) || value < 0) return;
    configure.mutate(
      { id: alert.id, config: { threshold: value } },
      { onSuccess: () => onClose() },
    );
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40 bg-bg-deep/60" onClick={onClose} />

      {/* Panel */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-border bg-bg-surface animate-slide-in-right">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Configure Alert
            </h2>
            <p className="mt-0.5 text-[12px] text-text-muted">{alert.type}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
          {/* Alert info */}
          <div className="mb-6 rounded-card border border-border bg-bg-base p-4">
            <p className="text-[13px] text-text-muted">{alert.message}</p>
            <div className="mt-2 flex items-center gap-3 font-mono text-[11px] text-text-faint">
              <span>Tenant: {alert.tenant_name}</span>
              <span>Current: {alert.current_value}</span>
            </div>
          </div>

          {/* Threshold config */}
          <div className="space-y-3">
            <label className="text-label-nav uppercase tracking-wider text-text-faint">
              Threshold Value
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                step="any"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-[13px] text-text-primary outline-none transition-colors focus:border-accent-ring"
              />
            </div>
            <p className="text-[11px] text-text-faint">
              An alert will fire when the metric exceeds this value.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-border px-5 py-4">
          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-4 py-1.5 text-[13px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={configure.isPending}
              className="rounded-control bg-accent px-4 py-1.5 text-[13px] font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {configure.isPending ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
