"use client";

import type { WizardFormData } from "../AgentDeployWizard";

interface WizardStep3AccessProps {
  formData: WizardFormData;
  onChange: (data: Partial<WizardFormData>) => void;
}

type AccessMode = WizardFormData["accessMode"];

const ACCESS_OPTIONS: {
  value: AccessMode;
  label: string;
  desc: string;
}[] = [
  {
    value: "workspace_wide",
    label: "All workspace members",
    desc: "Every user in the workspace can access this agent.",
  },
  {
    value: "role_restricted",
    label: "Specific roles",
    desc: "Only users with the specified roles can access this agent.",
  },
  {
    value: "user_specific",
    label: "Specific users",
    desc: "Only the listed users can access this agent.",
  },
];

export function WizardStep3Access({
  formData,
  onChange,
}: WizardStep3AccessProps) {
  return (
    <div className="flex flex-col gap-6">
      <p className="text-section-heading text-text-primary">Access Control</p>

      {/* Access mode radio group */}
      <div className="flex flex-col gap-2">
        {ACCESS_OPTIONS.map((opt) => (
          <label
            key={opt.value}
            className="flex cursor-pointer items-start gap-3 rounded-control border border-border bg-bg-elevated px-3 py-3 transition-colors hover:border-accent-ring"
          >
            <input
              type="radio"
              name="accessMode"
              value={opt.value}
              checked={formData.accessMode === opt.value}
              onChange={() => onChange({ accessMode: opt.value })}
              className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
            />
            <div>
              <p className="text-body-default font-medium text-text-primary">
                {opt.label}
              </p>
              <p className="text-[11px] text-text-muted">{opt.desc}</p>
            </div>
          </label>
        ))}
      </div>

      {/* Conditional: roles input */}
      {formData.accessMode === "role_restricted" && (
        <div>
          <label className="mb-1.5 block text-body-default font-medium text-text-primary">
            Allowed Roles
            <span className="ml-0.5 text-alert">*</span>
          </label>
          <input
            type="text"
            value={formData.allowedRoles.join(", ")}
            onChange={(e) =>
              onChange({
                allowedRoles: e.target.value
                  .split(",")
                  .map((r) => r.trim())
                  .filter(Boolean),
              })
            }
            placeholder="admin, manager, analyst"
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
          <p className="mt-1 text-[11px] text-text-muted">
            Comma-separated list of role names.
          </p>
        </div>
      )}

      {/* Conditional: user IDs input */}
      {formData.accessMode === "user_specific" && (
        <div>
          <label className="mb-1.5 block text-body-default font-medium text-text-primary">
            Allowed Users
            <span className="ml-0.5 text-alert">*</span>
          </label>
          <input
            type="text"
            value={formData.allowedUserIds.join(", ")}
            onChange={(e) =>
              onChange({
                allowedUserIds: e.target.value
                  .split(",")
                  .map((id) => id.trim())
                  .filter(Boolean),
              })
            }
            placeholder="user-id-1, user-id-2"
            className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
          />
          <p className="mt-1 text-[11px] text-text-muted">
            Comma-separated list of user IDs.
          </p>
        </div>
      )}

      {/* Rate limit */}
      <div>
        <label className="mb-1.5 block text-body-default font-medium text-text-primary">
          Rate Limit{" "}
          <span className="font-normal text-text-muted">(optional)</span>
        </label>
        <p className="mb-1.5 text-[11px] text-text-muted">
          Max requests per user per minute. Leave blank for no limit.
        </p>
        <input
          type="number"
          min={1}
          value={formData.rateLimitPerMinute ?? ""}
          onChange={(e) => {
            const raw = e.target.value;
            onChange({
              rateLimitPerMinute:
                raw === "" ? null : Math.max(1, parseInt(raw, 10)),
            });
          }}
          placeholder="e.g. 20"
          className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 font-mono text-data-value text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
        />
      </div>
    </div>
  );
}
