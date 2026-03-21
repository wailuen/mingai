"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import {
  usePlatformAlerts,
  type PlatformAlert,
} from "@/lib/hooks/usePlatformAlerts";
import { AlertList } from "./elements/AlertList";
import { AlertConfigPanel } from "./elements/AlertConfigPanel";

function AlertsSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="rounded-card border border-border bg-bg-surface p-4"
        >
          <div className="flex items-start gap-3">
            <div className="mt-1 h-2 w-2 animate-pulse rounded-full bg-bg-elevated" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-40 animate-pulse rounded-badge bg-bg-elevated" />
              <div className="h-3 w-72 animate-pulse rounded-badge bg-bg-elevated" />
              <div className="h-3 w-48 animate-pulse rounded-badge bg-bg-elevated" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function AlertsContent({
  onConfigureAlert,
}: {
  onConfigureAlert: (alert: PlatformAlert) => void;
}) {
  const { data, isPending, error } = usePlatformAlerts();

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load alerts: {error.message}
      </p>
    );
  }

  if (isPending) {
    return <AlertsSkeleton />;
  }

  return <AlertList alerts={data ?? []} onConfigureAlert={onConfigureAlert} />;
}

function UnacknowledgedBadge() {
  const { data } = usePlatformAlerts();
  const count = data?.filter((a) => a.acknowledged_at === null).length ?? 0;

  if (count === 0) return null;

  return (
    <span className="ml-2 inline-flex items-center justify-center rounded-badge bg-alert px-1.5 py-0.5 font-mono text-[10px] font-semibold text-bg-base">
      {count}
    </span>
  );
}

/**
 * FE-057: Platform Alert Center.
 * Displays alerts with severity indicators, acknowledge actions, and threshold configuration.
 */
export default function AlertCenterPage() {
  const [configuringAlert, setConfiguringAlert] =
    useState<PlatformAlert | null>(null);

  return (
    <AppShell>
      <div className="p-7">
        <div className="mb-6">
          <div className="flex items-center">
            <h1 className="text-page-title text-text-primary">Alert Center</h1>
            <ErrorBoundary>
              <UnacknowledgedBadge />
            </ErrorBoundary>
          </div>
          <p className="mt-1 text-body-default text-text-muted">
            Monitor and manage platform alerts and threshold breaches
          </p>
        </div>

        <ErrorBoundary>
          <AlertsContent onConfigureAlert={setConfiguringAlert} />
        </ErrorBoundary>

        {configuringAlert && (
          <AlertConfigPanel
            alert={configuringAlert}
            onClose={() => setConfiguringAlert(null)}
          />
        )}
      </div>
    </AppShell>
  );
}
