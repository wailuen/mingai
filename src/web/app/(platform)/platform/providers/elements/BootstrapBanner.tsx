"use client";

import { useState, useEffect } from "react";
import { AlertTriangle, X } from "lucide-react";

const DISMISS_KEY = "mingai_pvdr_banner_dismissed_v1";

interface BootstrapBannerProps {
  active: boolean;
}

/**
 * PVDR-015: Bootstrap Banner.
 * Shown when the platform is running on .env credentials instead of
 * database-managed provider credentials.
 */
export function BootstrapBanner({ active }: BootstrapBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (active) {
      // When active transitions to true, un-dismiss (show again)
      const stored = localStorage.getItem(DISMISS_KEY);
      setDismissed(stored === "true");
    }
  }, [active]);

  if (!active || dismissed) return null;

  function handleDismiss() {
    setDismissed(true);
    localStorage.setItem(DISMISS_KEY, "true");
  }

  return (
    <div className="mb-5 flex items-start gap-3 rounded-card border-l-4 border-warn bg-warn-dim px-4 py-3">
      <AlertTriangle
        size={16}
        className="mt-0.5 flex-shrink-0 text-warn"
        aria-hidden="true"
      />
      <div className="flex-1">
        <p className="text-section-heading text-text-primary">
          Running on environment fallback
        </p>
        <p className="mt-1 text-body-default text-text-muted">
          Platform LLM credentials are being read from .env. Add a provider
          above to move credentials into the database and enable rotation
          without restarting the server.
        </p>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        className="flex-shrink-0 rounded-control p-1 text-text-faint transition-colors hover:bg-bg-elevated hover:text-text-primary"
        aria-label="Dismiss banner"
      >
        <X size={14} />
      </button>
    </div>
  );
}
