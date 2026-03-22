"use client";

import { useState } from "react";
import { X, Link, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useRegisterPlatformA2AAgent,
  type RegisterPlatformA2APayload,
} from "@/lib/hooks/usePlatformA2ARegistry";

interface PAA2ARegistrationPanelProps {
  onClose: () => void;
}

const PLAN_OPTIONS = [
  { value: "", label: "All plans" },
  { value: "starter", label: "Starter+" },
  { value: "professional", label: "Professional+" },
  { value: "enterprise", label: "Enterprise only" },
];

export function PAA2ARegistrationPanel({
  onClose,
}: PAA2ARegistrationPanelProps) {
  const [cardUrl, setCardUrl] = useState("");
  const [nameOverride, setNameOverride] = useState("");
  const [descOverride, setDescOverride] = useState("");
  const [planRequired, setPlanRequired] = useState("");
  const [assignAll, setAssignAll] = useState(true);
  const [tenantIds, setTenantIds] = useState("");
  const [blockedTopics, setBlockedTopics] = useState("");
  const [piiMasking, setPiiMasking] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);

  const registerMutation = useRegisterPlatformA2AAgent();

  function validateUrl(value: string): boolean {
    try {
      const u = new URL(value);
      if (!["https:"].includes(u.protocol)) {
        setUrlError("Card URL must use HTTPS");
        return false;
      }
      setUrlError(null);
      return true;
    } catch {
      setUrlError("Invalid URL format");
      return false;
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validateUrl(cardUrl)) return;

    const assignedTenants = assignAll
      ? []
      : tenantIds
          .split(/[\n,]+/)
          .map((s) => s.trim())
          .filter(Boolean);

    const blocked = blockedTopics
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    const guardrail_overlay: Record<string, unknown> = {};
    if (blocked.length > 0) guardrail_overlay.blocked_topics = blocked;
    if (piiMasking) guardrail_overlay.pii_masking = true;

    const payload: RegisterPlatformA2APayload = {
      source_card_url: cardUrl,
      plan_required: planRequired || null,
      assigned_tenants: assignedTenants,
      guardrail_overlay,
    };
    if (nameOverride.trim()) payload.name_override = nameOverride.trim();
    if (descOverride.trim()) payload.description_override = descOverride.trim();

    await registerMutation.mutateAsync(payload);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="flex-1 bg-bg-base/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div className="flex h-full w-[480px] flex-col border-l border-border bg-bg-surface shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Register Platform A2A Agent
            </h2>
            <p className="mt-0.5 text-body-default text-text-faint">
              Platform-scope — available to eligible tenants
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-faint transition-colors hover:text-text-muted"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <form
          id="pa-a2a-form"
          onSubmit={handleSubmit}
          className="flex-1 space-y-5 overflow-y-auto px-5 py-5"
        >
          {/* Card URL */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Agent Card URL <span className="text-alert">*</span>
            </label>
            <div className="relative">
              <Link
                size={13}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-text-faint"
              />
              <input
                type="url"
                required
                value={cardUrl}
                onChange={(e) => setCardUrl(e.target.value)}
                onBlur={(e) => validateUrl(e.target.value)}
                placeholder="https://agent.example.com/.well-known/agent.json"
                className={cn(
                  "w-full rounded-control border bg-bg-elevated py-2 pl-8 pr-3 text-body-default text-text-primary placeholder:text-text-faint outline-none",
                  urlError
                    ? "border-alert focus:border-alert"
                    : "border-border focus:border-accent-ring",
                )}
              />
            </div>
            {urlError && (
              <p className="mt-1 text-body-default text-alert">{urlError}</p>
            )}
          </div>

          {/* Name & Description overrides */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Display Name Override
            </label>
            <input
              type="text"
              value={nameOverride}
              onChange={(e) => setNameOverride(e.target.value)}
              maxLength={255}
              placeholder="Leave blank to use name from agent card"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Description Override
            </label>
            <textarea
              rows={3}
              value={descOverride}
              onChange={(e) => setDescOverride(e.target.value)}
              maxLength={2000}
              placeholder="Leave blank to use description from agent card"
              className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
            />
          </div>

          {/* Platform Config */}
          <div className="border-t border-border-faint pt-4">
            <p className="mb-3 text-label-nav uppercase tracking-wider text-text-faint">
              Platform Configuration
            </p>

            <div className="mb-4">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Plan Gate
              </label>
              <select
                value={planRequired}
                onChange={(e) => setPlanRequired(e.target.value)}
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary outline-none focus:border-accent-ring"
              >
                {PLAN_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Assignment Scope
              </label>
              <div className="space-y-2">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="radio"
                    checked={assignAll}
                    onChange={() => setAssignAll(true)}
                    className="accent-accent"
                  />
                  <span className="text-body-default text-text-primary">
                    All eligible tenants
                  </span>
                </label>
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="radio"
                    checked={!assignAll}
                    onChange={() => setAssignAll(false)}
                    className="accent-accent"
                  />
                  <span className="text-body-default text-text-primary">
                    Specific tenants only
                  </span>
                </label>
              </div>

              {!assignAll && (
                <div className="mt-2">
                  <textarea
                    rows={3}
                    value={tenantIds}
                    onChange={(e) => setTenantIds(e.target.value)}
                    placeholder="One tenant ID per line, or comma-separated"
                    className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
                  />
                </div>
              )}
            </div>
          </div>

          {/* Guardrail Overlay */}
          <div className="border-t border-border-faint pt-4">
            <div className="mb-3 flex items-start gap-2">
              <ShieldAlert size={14} className="mt-0.5 shrink-0 text-warn" />
              <div>
                <p className="text-label-nav uppercase tracking-wider text-text-faint">
                  Guardrail Overlay
                </p>
                <p className="mt-0.5 text-body-default text-text-faint">
                  Applies on top of external agent output — tenants cannot
                  remove
                </p>
              </div>
            </div>

            <div className="mb-3">
              <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                Blocked Topics
              </label>
              <textarea
                rows={3}
                value={blockedTopics}
                onChange={(e) => setBlockedTopics(e.target.value)}
                placeholder="One topic per line or comma-separated"
                className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint outline-none focus:border-accent-ring"
              />
            </div>

            <label className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={piiMasking}
                onChange={(e) => setPiiMasking(e.target.checked)}
                className="accent-accent"
              />
              <span className="text-body-default text-text-primary">
                Enable PII masking on agent output
              </span>
            </label>
          </div>
        </form>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-border px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="submit"
            form="pa-a2a-form"
            disabled={registerMutation.isPending}
            className="rounded-control bg-accent px-4 py-2 text-body-default font-medium text-bg-base transition-opacity disabled:opacity-50"
          >
            {registerMutation.isPending ? "Registering…" : "Register Agent"}
          </button>
        </div>
      </div>
    </div>
  );
}
