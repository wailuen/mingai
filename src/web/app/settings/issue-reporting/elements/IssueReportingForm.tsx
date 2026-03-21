"use client";

import { useCallback, useEffect, useState } from "react";
import {
  useIssueReportingConfig,
  useUpdateIssueReportingConfig,
  type IssueReportingConfig,
} from "@/lib/hooks/useIssueReporting";
import { cn } from "@/lib/utils";

function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      disabled={disabled}
      className={cn(
        "relative h-5 w-9 flex-shrink-0 rounded-full transition-colors",
        checked ? "bg-accent" : "bg-bg-elevated",
        disabled && "opacity-50",
      )}
      role="switch"
      aria-checked={checked}
      aria-label={label}
    >
      <span
        className={cn(
          "absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
          checked ? "translate-x-4" : "translate-x-0",
        )}
      />
    </button>
  );
}

/**
 * FE-053: Issue reporting configuration form.
 * Manages toggles, email, escalation settings, and Slack webhook.
 */
export function IssueReportingForm() {
  const { data: config, isPending, error } = useIssueReportingConfig();
  const updateMutation = useUpdateIssueReportingConfig();

  const [local, setLocal] = useState<IssueReportingConfig>({
    enabled: false,
    notify_email: "",
    auto_escalate_p0: true,
    auto_escalate_p1: false,
    escalation_threshold_hours: 4,
    slack_webhook_url: "",
  });

  const [emailError, setEmailError] = useState<string | null>(null);
  const [webhookError, setWebhookError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">(
    "idle",
  );

  useEffect(() => {
    if (config) {
      setLocal(config);
    }
  }, [config]);

  const validate = useCallback((): boolean => {
    let valid = true;

    if (local.enabled && local.notify_email) {
      const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailPattern.test(local.notify_email)) {
        setEmailError("Please enter a valid email address");
        valid = false;
      } else {
        setEmailError(null);
      }
    } else {
      setEmailError(null);
    }

    if (local.slack_webhook_url && local.slack_webhook_url.length > 0) {
      // Restrict to Slack's webhook domain to prevent SSRF via arbitrary URLs
      if (
        !local.slack_webhook_url.startsWith("https://hooks.slack.com/services/")
      ) {
        setWebhookError(
          "URL must be a Slack webhook (https://hooks.slack.com/services/...)",
        );
        valid = false;
      } else {
        setWebhookError(null);
      }
    } else {
      setWebhookError(null);
    }

    return valid;
  }, [local]);

  function handleSave() {
    if (!validate()) return;

    setSaveStatus("idle");
    updateMutation.mutate(local, {
      onSuccess: () => setSaveStatus("success"),
      onError: () => setSaveStatus("error"),
    });
  }

  const showEscalationThreshold =
    local.auto_escalate_p0 || local.auto_escalate_p1;

  if (isPending) {
    return (
      <div className="space-y-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-16 animate-pulse rounded-card border border-border bg-bg-surface"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-body-default text-alert">
        Failed to load issue reporting settings: {error.message}
      </p>
    );
  }

  return (
    <div className="space-y-5">
      {/* Enable toggle */}
      <div className="flex items-center justify-between rounded-card border border-border bg-bg-surface p-5">
        <div>
          <p className="text-body-default font-medium text-text-primary">
            Enable Issue Reporting
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Allow workspace users to report issues and receive escalation
            notifications.
          </p>
        </div>
        <Toggle
          checked={local.enabled}
          onChange={(v) => setLocal({ ...local, enabled: v })}
          disabled={updateMutation.isPending}
          label="Toggle issue reporting"
        />
      </div>

      {/* Notify email */}
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <label className="block text-body-default font-medium text-text-primary">
          Notification Email
        </label>
        <p className="mt-0.5 text-xs text-text-muted">
          Email address for issue notifications
        </p>
        <input
          type="email"
          value={local.notify_email}
          onChange={(e) => setLocal({ ...local, notify_email: e.target.value })}
          placeholder="admin@company.com"
          className={cn(
            "mt-2 w-full rounded-control border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring",
            emailError ? "border-alert" : "border-border",
          )}
        />
        {emailError && <p className="mt-1 text-xs text-alert">{emailError}</p>}
      </div>

      {/* Auto-escalate P0 */}
      <div className="flex items-center justify-between rounded-card border border-border bg-bg-surface p-5">
        <div>
          <p className="text-body-default font-medium text-text-primary">
            Auto-escalate P0 Issues
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Automatically escalate critical (P0) issues when threshold is
            exceeded.
          </p>
        </div>
        <Toggle
          checked={local.auto_escalate_p0}
          onChange={(v) => setLocal({ ...local, auto_escalate_p0: v })}
          disabled={updateMutation.isPending}
          label="Toggle auto-escalate P0"
        />
      </div>

      {/* Auto-escalate P1 */}
      <div className="flex items-center justify-between rounded-card border border-border bg-bg-surface p-5">
        <div>
          <p className="text-body-default font-medium text-text-primary">
            Auto-escalate P1 Issues
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Automatically escalate high priority (P1) issues when threshold is
            exceeded.
          </p>
        </div>
        <Toggle
          checked={local.auto_escalate_p1}
          onChange={(v) => setLocal({ ...local, auto_escalate_p1: v })}
          disabled={updateMutation.isPending}
          label="Toggle auto-escalate P1"
        />
      </div>

      {/* Escalation threshold hours */}
      {showEscalationThreshold && (
        <div className="rounded-card border border-border bg-bg-surface p-5">
          <label className="block text-body-default font-medium text-text-primary">
            Escalation Threshold (hours)
          </label>
          <p className="mt-0.5 text-xs text-text-muted">
            Hours before an unresolved issue is automatically escalated
          </p>
          <input
            type="number"
            min={1}
            max={168}
            value={local.escalation_threshold_hours}
            onChange={(e) =>
              setLocal({
                ...local,
                escalation_threshold_hours: parseInt(e.target.value, 10) || 1,
              })
            }
            className="mt-2 w-32 rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-body-default text-text-primary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring"
          />
        </div>
      )}

      {/* Slack webhook */}
      <div className="rounded-card border border-border bg-bg-surface p-5">
        <label className="block text-body-default font-medium text-text-primary">
          Slack Webhook URL
          <span className="ml-1 text-xs font-normal text-text-faint">
            (optional)
          </span>
        </label>
        <p className="mt-0.5 text-xs text-text-muted">
          Send issue notifications to a Slack channel
        </p>
        <input
          type="url"
          value={local.slack_webhook_url ?? ""}
          onChange={(e) =>
            setLocal({ ...local, slack_webhook_url: e.target.value })
          }
          placeholder="https://hooks.slack.com/services/..."
          className={cn(
            "mt-2 w-full rounded-control border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring",
            webhookError ? "border-alert" : "border-border",
          )}
        />
        {webhookError && (
          <p className="mt-1 text-xs text-alert">{webhookError}</p>
        )}
      </div>

      {/* Save button and status */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={updateMutation.isPending}
          className={cn(
            "rounded-control bg-accent px-5 py-2 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90",
            updateMutation.isPending && "opacity-50",
          )}
        >
          {updateMutation.isPending ? "Saving..." : "Save Changes"}
        </button>
        {saveStatus === "success" && (
          <span className="text-xs text-accent">Settings saved</span>
        )}
        {saveStatus === "error" && (
          <span className="text-xs text-alert">Failed to save settings</span>
        )}
      </div>
    </div>
  );
}
