"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { IconPicker } from "@/components/shared/IconPicker";
import type { AgentIconType } from "@/lib/hooks/useCustomAgentStudio";
import {
  useRegisterA2AAgent,
  type RegisterA2APayload,
} from "@/lib/hooks/useA2AAgents";
import { ApiException } from "@/lib/api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface A2ARegistrationPanelProps {
  onClose: () => void;
  onRegistered?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type AccessMode = "workspace" | "role" | "user";

function isHttps(url: string): boolean {
  return url.trim().toLowerCase().startsWith("https://");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function A2ARegistrationPanel({
  onClose,
  onRegistered,
}: A2ARegistrationPanelProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [cardUrl, setCardUrl] = useState("");
  const [icon, setIcon] = useState<AgentIconType>("custom");
  const [accessMode, setAccessMode] = useState<AccessMode>("workspace");
  const [rolesText, setRolesText] = useState("");
  const [userIdsText, setUserIdsText] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [cardUrlTouched, setCardUrlTouched] = useState(false);

  const register = useRegisterA2AAgent();

  const cardUrlInvalid =
    cardUrlTouched && cardUrl.trim().length > 0 && !isHttps(cardUrl);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);

    if (!name.trim()) {
      setSubmitError("Display name is required.");
      return;
    }
    if (!cardUrl.trim()) {
      setSubmitError("Agent Card URL is required.");
      return;
    }
    if (!isHttps(cardUrl)) {
      setSubmitError("Agent Card URL must use HTTPS.");
      return;
    }

    const payload: RegisterA2APayload = {
      name: name.trim(),
      source_card_url: cardUrl.trim(),
      icon,
    };

    if (description.trim()) {
      payload.description = description.trim();
    }

    if (accessMode === "role") {
      payload.access_control = "role";
      payload.allowed_roles = rolesText
        .split("\n")
        .map((r) => r.trim())
        .filter(Boolean);
    } else if (accessMode === "user") {
      payload.access_control = "user";
      payload.allowed_user_ids = userIdsText
        .split("\n")
        .map((u) => u.trim())
        .filter(Boolean);
    } else {
      payload.access_control = "workspace";
    }

    try {
      await register.mutateAsync(payload);
      onRegistered?.();
      onClose();
    } catch (err) {
      if (err instanceof ApiException) {
        // 422 when card fetch fails — show backend detail
        const detail =
          (err.body as { detail?: string })?.detail ?? err.body?.message;
        setSubmitError(detail ?? "Registration failed. Please try again.");
      } else {
        setSubmitError("Registration failed. Please try again.");
      }
    }
  }

  return (
    /* Overlay */
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-bg-base/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <aside
        className="relative z-10 flex w-full max-w-[480px] flex-col border-l border-border bg-bg-surface"
        aria-label="Register External A2A Agent"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-section-heading text-text-primary">
            Register External A2A Agent
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-faint transition-colors hover:text-text-primary"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form
          onSubmit={handleSubmit}
          className="flex flex-1 flex-col overflow-y-auto"
        >
          <div className="flex-1 space-y-5 px-5 py-5">
            {/* Display name */}
            <div>
              <label
                htmlFor="a2a-name"
                className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
              >
                Display Name <span className="text-alert">*</span>
              </label>
              <input
                id="a2a-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Finance Summariser Agent"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>

            {/* Description */}
            <div>
              <label
                htmlFor="a2a-description"
                className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
              >
                Description
              </label>
              <textarea
                id="a2a-description"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional — describe what this agent does"
                className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
              />
            </div>

            {/* Agent Card URL */}
            <div>
              <label
                htmlFor="a2a-card-url"
                className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
              >
                Agent Card URL <span className="text-alert">*</span>
              </label>
              <input
                id="a2a-card-url"
                type="url"
                value={cardUrl}
                onChange={(e) => {
                  setCardUrl(e.target.value);
                  setCardUrlTouched(true);
                }}
                onBlur={() => setCardUrlTouched(true)}
                placeholder="https://agent.example.com/.well-known/agent.json"
                className={cn(
                  "w-full rounded-control border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:outline-none",
                  cardUrlInvalid
                    ? "border-alert focus:border-alert"
                    : "border-border focus:border-accent",
                )}
              />
              {cardUrlInvalid && (
                <p className="mt-1 text-body-default text-alert">
                  URL must use HTTPS.
                </p>
              )}
            </div>

            {/* Icon picker */}
            <div>
              <p className="mb-1.5 text-label-nav uppercase tracking-wider text-text-faint">
                Icon
              </p>
              <IconPicker value={icon} onChange={setIcon} />
            </div>

            {/* Access control */}
            <div>
              <p className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
                Access Control
              </p>
              <div className="space-y-2">
                {(
                  [
                    { value: "workspace", label: "Workspace-wide" },
                    { value: "role", label: "Role-restricted" },
                    { value: "user", label: "User-specific" },
                  ] as { value: AccessMode; label: string }[]
                ).map((opt) => (
                  <label
                    key={opt.value}
                    className="flex cursor-pointer items-center gap-2.5"
                  >
                    <input
                      type="radio"
                      name="access-mode"
                      value={opt.value}
                      checked={accessMode === opt.value}
                      onChange={() => setAccessMode(opt.value)}
                      className="accent-accent"
                    />
                    <span className="text-body-default text-text-primary">
                      {opt.label}
                    </span>
                  </label>
                ))}
              </div>

              {/* Role list */}
              {accessMode === "role" && (
                <div className="mt-3">
                  <label
                    htmlFor="a2a-roles"
                    className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
                  >
                    Allowed Roles (one per line)
                  </label>
                  <textarea
                    id="a2a-roles"
                    rows={3}
                    value={rolesText}
                    onChange={(e) => setRolesText(e.target.value)}
                    placeholder={"finance_analyst\nhr_manager"}
                    className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                  />
                </div>
              )}

              {/* User ID list */}
              {accessMode === "user" && (
                <div className="mt-3">
                  <label
                    htmlFor="a2a-users"
                    className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
                  >
                    Allowed User IDs (one per line)
                  </label>
                  <textarea
                    id="a2a-users"
                    rows={3}
                    value={userIdsText}
                    onChange={(e) => setUserIdsText(e.target.value)}
                    placeholder={"auth0|abc123\nauth0|def456"}
                    className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                  />
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="border-t border-border px-5 py-4">
            {submitError && (
              <p className="mb-3 text-body-default text-alert">{submitError}</p>
            )}
            <div className="flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={register.isPending}
                className="rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {register.isPending ? "Registering…" : "Register"}
              </button>
            </div>
          </div>
        </form>
      </aside>
    </div>
  );
}
