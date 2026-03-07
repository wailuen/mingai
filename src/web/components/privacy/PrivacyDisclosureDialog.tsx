"use client";

import { useState, useEffect } from "react";
import { Shield, X } from "lucide-react";

/**
 * FE-017: Privacy Disclosure Dialog.
 * Shown ONCE on first profile use.
 * Transparency only -- NOT a consent gate.
 * Explains: queries, org context, working memory collected.
 * Sets profile_disclosure_shown cookie after display.
 */
export function PrivacyDisclosureDialog() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const shown = document.cookie
      .split("; ")
      .some((row) => row.startsWith("profile_disclosure_shown=true"));
    if (!shown) {
      setVisible(true);
    }
  }, []);

  function handleDismiss() {
    setVisible(false);
    // Set cookie - expires in 1 year
    const expires = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000);
    document.cookie = `profile_disclosure_shown=true; path=/; expires=${expires.toUTCString()}; SameSite=Lax`;
  }

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-md rounded-card border border-border bg-bg-surface p-6">
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Shield size={20} className="text-accent" />
            <h2 className="text-section-heading text-text-primary">
              How mingai learns about you
            </h2>
          </div>
          <button
            onClick={handleDismiss}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3 text-sm text-text-muted">
          <p>
            To give you better answers, mingai collects the following when
            profile learning is enabled:
          </p>

          <ul className="list-inside list-disc space-y-1.5 text-text-muted">
            <li>
              <strong className="text-text-primary">Your queries</strong> --
              analyzed every 10 interactions to understand your interests
            </li>
            <li>
              <strong className="text-text-primary">
                Organizational context
              </strong>{" "}
              -- your role, department, and team from your identity provider
            </li>
            <li>
              <strong className="text-text-primary">Working memory</strong> --
              recent topics and patterns from your conversations (auto-expires
              after 7 days)
            </li>
          </ul>

          <p className="text-xs text-text-faint">
            You can review, export, or delete all collected data at any time
            from Privacy Settings. This is a transparency notice, not a consent
            gate -- your data rights are fully respected under GDPR.
          </p>
        </div>

        <button
          onClick={handleDismiss}
          className="mt-5 w-full rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
        >
          Got it
        </button>
      </div>
    </div>
  );
}
