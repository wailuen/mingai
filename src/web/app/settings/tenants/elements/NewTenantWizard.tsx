"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/lib/api";
import { X, ChevronRight, ChevronLeft } from "lucide-react";

const PLANS = ["starter", "professional", "enterprise"] as const;

interface NewTenantWizardProps {
  onClose: () => void;
}

export function NewTenantWizard({ onClose }: NewTenantWizardProps) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [plan, setPlan] = useState<(typeof PLANS)[number]>("professional");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  function handleNameChange(value: string) {
    setName(value);
    // Auto-generate slug from name
    setSlug(
      value
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, ""),
    );
  }

  async function handleCreate() {
    setSubmitting(true);
    setError(null);
    try {
      await apiPost("/api/v1/platform/tenants", {
        name: name.trim(),
        slug: slug.trim(),
        plan,
        primary_contact_email: contactEmail.trim(),
      });
      queryClient.invalidateQueries({ queryKey: ["platform-tenants"] });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create tenant");
    } finally {
      setSubmitting(false);
    }
  }

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contactEmail.trim());
  const canProceed =
    step === 1 &&
    name.trim().length > 0 &&
    slug.trim().length > 0 &&
    emailValid;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Progress bar */}
        <div className="h-1 rounded-t-card bg-bg-elevated">
          <div
            className="h-full rounded-t-card bg-accent transition-all duration-300"
            style={{ width: step === 1 ? "50%" : "100%" }}
          />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              New Tenant
            </h2>
            <span className="text-[11px] text-text-faint">
              Step {step} of 2
            </span>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="p-5">
          {step === 1 ? (
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Tenant Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="Acme Corp"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Slug
                </label>
                <input
                  type="text"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="acme-corp"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
                <p className="mt-1 text-[11px] text-text-faint">
                  URL-safe identifier. Auto-generated from name.
                </p>
              </div>
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Primary Contact Email
                </label>
                <input
                  type="email"
                  value={contactEmail}
                  onChange={(e) => setContactEmail(e.target.value)}
                  placeholder="admin@acmecorp.com"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Plan
                </label>
                <div className="flex gap-2">
                  {PLANS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setPlan(p)}
                      className={`rounded-control border px-3 py-1.5 font-mono text-xs capitalize transition-colors ${
                        plan === p
                          ? "border-accent-ring bg-accent-dim text-accent"
                          : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-text-primary">
                Confirm Tenant Details
              </h3>
              <div className="rounded-card border border-border bg-bg-elevated p-4">
                <div className="space-y-3">
                  <ConfirmRow label="Name" value={name} />
                  <ConfirmRow label="Slug" value={slug} mono />
                  <ConfirmRow label="Plan" value={plan} mono />
                  <ConfirmRow label="Contact" value={contactEmail} />
                </div>
              </div>
              {error && <p className="text-sm text-alert">{error}</p>}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between border-t border-border px-5 py-3">
          <button
            onClick={() => (step === 1 ? onClose() : setStep(1))}
            className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
          >
            {step === 2 && <ChevronLeft size={14} />}
            {step === 1 ? "Cancel" : "Back"}
          </button>
          {step === 1 ? (
            <button
              onClick={() => setStep(2)}
              disabled={!canProceed}
              className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              Next
              <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={handleCreate}
              disabled={submitting}
              className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
            >
              {submitting ? "Creating..." : "Create Tenant"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ConfirmRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-text-faint">{label}</span>
      <span
        className={`text-sm text-text-primary ${mono ? "font-mono text-data-value" : ""}`}
      >
        {value}
      </span>
    </div>
  );
}
