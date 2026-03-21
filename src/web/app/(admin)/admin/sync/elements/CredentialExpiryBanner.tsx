"use client";

import { X } from "lucide-react";

interface CredentialExpiryBannerProps {
  daysUntilExpiry: number;
  integrationName: string;
  onDismiss: () => void;
}

export function CredentialExpiryBanner({
  daysUntilExpiry,
  integrationName,
  onDismiss,
}: CredentialExpiryBannerProps) {
  if (daysUntilExpiry > 30) return null;

  return (
    <div className="flex items-center justify-between rounded-card border border-warn bg-warn-dim p-4">
      <p className="text-body-default text-text-primary">
        <span className="font-semibold">{integrationName}</span> credentials
        expire in{" "}
        <span className="font-mono font-medium">{daysUntilExpiry}</span>{" "}
        {daysUntilExpiry === 1 ? "day" : "days"}. Renew to avoid sync
        interruptions.
      </p>
      <button
        type="button"
        onClick={onDismiss}
        className="ml-4 flex-shrink-0 text-text-muted transition-colors hover:text-text-primary"
        aria-label="Dismiss"
      >
        <X size={16} />
      </button>
    </div>
  );
}
