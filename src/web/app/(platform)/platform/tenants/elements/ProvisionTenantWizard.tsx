"use client";

import { useState } from "react";
import { X, ChevronLeft, ChevronRight, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCreateTenant,
  type CreateTenantPayload,
} from "@/lib/hooks/usePlatformDashboard";

interface ProvisionTenantWizardProps {
  onClose: () => void;
}

type WizardStep = 1 | 2 | 3;

const PLAN_OPTIONS: { value: CreateTenantPayload["plan"]; label: string }[] = [
  { value: "starter", label: "Starter" },
  { value: "professional", label: "Professional" },
  { value: "enterprise", label: "Enterprise" },
];

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 100);
}

export function ProvisionTenantWizard({ onClose }: ProvisionTenantWizardProps) {
  const [step, setStep] = useState<WizardStep>(1);

  // Step 1: Basics
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [plan, setPlan] = useState<CreateTenantPayload["plan"]>("professional");
  const [contactEmail, setContactEmail] = useState("");

  // Step 2: Config (optional)
  const [timezone, setTimezone] = useState("UTC");
  const [maxUsers, setMaxUsers] = useState("");

  const createMutation = useCreateTenant();

  const _emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const canProceedStep1 =
    name.trim().length > 0 &&
    _emailRegex.test(contactEmail.trim()) &&
    slug.length > 0;

  function handleNameChange(value: string) {
    setName(value);
    if (!slug || slug === slugify(name)) {
      setSlug(slugify(value));
    }
  }

  function handleNext() {
    if (step < 3) setStep((step + 1) as WizardStep);
  }

  function handleBack() {
    if (step > 1) setStep((step - 1) as WizardStep);
  }

  async function handleProvision() {
    const payload: CreateTenantPayload = {
      name: name.trim(),
      plan,
      primary_contact_email: contactEmail.trim(),
      slug: slug.trim() || undefined,
    };

    await createMutation.mutateAsync(payload);
    onClose();
  }

  const progressWidth = step === 1 ? "33.3%" : step === 2 ? "66.6%" : "100%";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-[640px] rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Provision New Tenant
            </h2>
            <p className="mt-0.5 text-[11px] text-text-faint">
              Step {step} of 3
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="h-1 w-full bg-bg-elevated">
          <div
            className="h-full bg-accent transition-all duration-200"
            style={{ width: progressWidth }}
          />
        </div>

        {/* Content */}
        <div className="p-5">
          {/* Step 1: Basics */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Tenant Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="Acme Corporation"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Slug
                </label>
                <input
                  type="text"
                  value={slug}
                  onChange={(e) => setSlug(slugify(e.target.value))}
                  placeholder="acme-corporation"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-muted placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Plan
                </label>
                <div className="flex gap-2">
                  {PLAN_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setPlan(option.value)}
                      className={cn(
                        "rounded-control border px-4 py-2 text-sm transition-colors",
                        plan === option.value
                          ? "border-accent bg-accent-dim text-accent"
                          : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Primary Contact Email
                </label>
                <input
                  type="email"
                  value={contactEmail}
                  onChange={(e) => setContactEmail(e.target.value)}
                  placeholder="admin@acme.com"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>
            </div>
          )}

          {/* Step 2: Configuration */}
          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Optional configuration. These can be changed later in tenant
                settings.
              </p>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Timezone
                </label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
                >
                  <option value="UTC">UTC</option>
                  <option value="America/New_York">Eastern Time (US)</option>
                  <option value="America/Chicago">Central Time (US)</option>
                  <option value="America/Los_Angeles">Pacific Time (US)</option>
                  <option value="Europe/London">London (GMT)</option>
                  <option value="Europe/Berlin">Berlin (CET)</option>
                  <option value="Asia/Singapore">Singapore (SGT)</option>
                  <option value="Asia/Tokyo">Tokyo (JST)</option>
                  <option value="Asia/Kuala_Lumpur">Kuala Lumpur (MYT)</option>
                </select>
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Max Users (optional)
                </label>
                <input
                  type="number"
                  value={maxUsers}
                  onChange={(e) => setMaxUsers(e.target.value)}
                  placeholder="50"
                  min={1}
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>
            </div>
          )}

          {/* Step 3: Review */}
          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sm text-text-muted">
                Review the details below and confirm provisioning.
              </p>

              <div className="rounded-card border border-border bg-bg-elevated p-4">
                <dl className="space-y-3">
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Name
                    </dt>
                    <dd className="text-sm text-text-primary">{name}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Slug
                    </dt>
                    <dd className="font-mono text-sm text-text-muted">
                      {slug || slugify(name)}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Plan
                    </dt>
                    <dd className="font-mono text-sm capitalize text-text-primary">
                      {plan}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                      Contact
                    </dt>
                    <dd className="font-mono text-sm text-text-muted">
                      {contactEmail}
                    </dd>
                  </div>
                  {timezone !== "UTC" && (
                    <div className="flex justify-between">
                      <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                        Timezone
                      </dt>
                      <dd className="font-mono text-sm text-text-muted">
                        {timezone}
                      </dd>
                    </div>
                  )}
                  {maxUsers && (
                    <div className="flex justify-between">
                      <dt className="text-[11px] uppercase tracking-wider text-text-faint">
                        Max Users
                      </dt>
                      <dd className="font-mono text-sm text-text-primary">
                        {maxUsers}
                      </dd>
                    </div>
                  )}
                </dl>
              </div>

              {createMutation.isError && (
                <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
                  <p className="text-xs text-alert">
                    {createMutation.error instanceof Error
                      ? createMutation.error.message
                      : "Failed to provision tenant"}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between border-t border-border px-5 py-3">
          <div>
            {step > 1 && (
              <button
                type="button"
                onClick={handleBack}
                disabled={createMutation.isPending}
                className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated disabled:opacity-30"
              >
                <ChevronLeft size={14} />
                Back
              </button>
            )}
          </div>

          <div className="flex gap-2">
            {step === 1 && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
              >
                Cancel
              </button>
            )}

            {step < 3 && (
              <button
                type="button"
                onClick={handleNext}
                disabled={step === 1 && !canProceedStep1}
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                Next
                <ChevronRight size={14} />
              </button>
            )}

            {step === 3 && (
              <button
                type="button"
                onClick={handleProvision}
                disabled={createMutation.isPending}
                className="flex items-center gap-1 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                {createMutation.isPending ? (
                  "Provisioning..."
                ) : (
                  <>
                    <Check size={14} />
                    Provision
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
