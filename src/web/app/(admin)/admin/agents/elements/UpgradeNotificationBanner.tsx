"use client";

import { useState } from "react";
import { X, ArrowUpCircle } from "lucide-react";

interface UpgradeNotificationBannerProps {
  templateId?: string;
  currentVersion?: string;
  latestVersion?: string;
  onUpgrade?: () => void;
}

/**
 * FE-035: Upgrade notification banner.
 * Displays when a template version exceeds the deployed version.
 */
export function UpgradeNotificationBanner({
  templateId,
  currentVersion,
  latestVersion,
  onUpgrade,
}: UpgradeNotificationBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (
    !templateId ||
    !currentVersion ||
    !latestVersion ||
    latestVersion === currentVersion ||
    dismissed
  ) {
    return null;
  }

  return (
    <div className="mt-4 flex items-center justify-between rounded-control border border-warn bg-warn-dim px-4 py-2.5">
      <div className="flex items-center gap-2.5">
        <ArrowUpCircle size={16} className="text-warn" />
        <span className="text-body-default text-text-primary">
          Template v{latestVersion} available. Your deployed agent uses v
          {currentVersion}.
        </span>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onUpgrade}
          className="rounded-control bg-warn px-3 py-1 text-xs font-semibold text-bg-base transition-opacity hover:opacity-90"
        >
          Upgrade
        </button>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
