"use client";

import {
  useState,
  useRef,
  useEffect,
  useCallback,
} from "react";
import { Eye, EyeOff, Info, AlertTriangle, Trash2, Loader2, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useTemplateCredentials,
  useCredentialHealth,
  useStoreCredential,
  useRotateCredential,
  useDeleteCredential,
  type CredentialMetadata,
  type CredentialStatus,
} from "@/lib/hooks/useAgentTemplatesAdmin";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CredentialsTabProps {
  templateId: string;
  authMode: string;
  requiredCredentials: string[];
  onSwitchToTab?: (tab: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const date = new Date(iso);
  if (isNaN(date.getTime())) return "Never";
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);
  if (diffDays < 30) {
    const diffHours = diffMs / (1000 * 60 * 60);
    if (diffHours < 1) {
      const diffMins = Math.round(diffMs / (1000 * 60));
      return `${diffMins}m ago`;
    }
    if (diffHours < 24) {
      return `${Math.round(diffHours)}h ago`;
    }
    return `${Math.round(diffDays)}d ago`;
  }
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function statusOrder(status: CredentialStatus | "missing"): number {
  if (status === "missing") return 0;
  if (status === "stored") return 1;
  if (status === "revoked") return 2;
  return 3;
}

// ---------------------------------------------------------------------------
// CompletenessHeader
// ---------------------------------------------------------------------------

interface CompletenessHeaderProps {
  totalRequired: number;
  storedCount: number;
  healthStatus: "complete" | "incomplete" | "not_required" | undefined;
}

function CompletenessHeader({
  totalRequired,
  storedCount,
  healthStatus,
}: CompletenessHeaderProps) {
  let badge: React.ReactNode = null;

  if (healthStatus && healthStatus !== "not_required" && totalRequired > 0) {
    const isComplete = healthStatus === "complete";
    const isNone = storedCount === 0;

    const badgeClass = isComplete
      ? "bg-accent-dim text-accent"
      : isNone
        ? "bg-alert-dim text-alert"
        : "bg-warn-dim text-warn";

    const badgeLabel = isComplete
      ? "All configured"
      : isNone
        ? "Unconfigured"
        : `${storedCount}/${totalRequired} configured`;

    badge = (
      <span
        role="status"
        aria-live="polite"
        className={cn(
          "rounded-badge px-[10px] py-[4px] font-mono text-[11px] font-medium uppercase tracking-[0.06em]",
          badgeClass,
        )}
      >
        {badgeLabel}
      </span>
    );
  }

  return (
    <div className="flex items-start justify-between">
      <div>
        <p className="text-[15px] font-semibold text-text-primary">
          Required Credentials
        </p>
        <p className="text-[13px] text-text-muted">
          Credentials needed for agents using this template
        </p>
      </div>
      {badge}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PasswordInput (show/hide toggle)
// ---------------------------------------------------------------------------

interface PasswordInputProps {
  value: string;
  onChange: (v: string) => void;
  credKey: string;
  disabled?: boolean;
}

function PasswordInput({
  value,
  onChange,
  credKey,
  disabled,
}: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <input
        type={visible ? "text" : "password"}
        autoComplete="off"
        data-lpignore="true"
        aria-label={`Credential value for ${credKey}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={cn(
          "h-[40px] w-full rounded-[7px] border border-[var(--border)] bg-[var(--bg-elevated)] pr-10 pl-3 font-mono text-[13px] text-text-primary placeholder:text-text-faint",
          "focus:border-accent focus:shadow-[0_0_0_2px_var(--accent-ring)] focus:outline-none",
          disabled && "opacity-50 cursor-not-allowed",
        )}
        placeholder="••••••••"
      />
      <button
        type="button"
        aria-label={visible ? "Hide credential value" : "Show credential value"}
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-text-faint hover:text-text-muted focus-visible:outline-2 focus-visible:outline-accent"
      >
        {visible ? <EyeOff size={15} /> : <Eye size={15} />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// InjectionMethodSelector
// ---------------------------------------------------------------------------

type InjectionType = "bearer" | "header" | "query_param" | "basic_auth";

interface InjectionConfig {
  type: InjectionType;
  header_name?: string;
  header_format?: string;
  param_name?: string;
}

const INJECTION_LABELS: Record<InjectionType, string> = {
  bearer: "Bearer token",
  header: "Custom header",
  query_param: "Query parameter",
  basic_auth: "Basic Auth",
};

const INJECTION_HINTS: Record<InjectionType, string> = {
  bearer: "Authorization: Bearer <value>",
  header: "",
  query_param: "",
  basic_auth: "Authorization: Basic <base64(value)>",
};

interface InjectionMethodSelectorProps {
  value: InjectionConfig;
  onChange: (cfg: InjectionConfig) => void;
  disabled?: boolean;
}

function InjectionMethodSelector({
  value,
  onChange,
  disabled,
}: InjectionMethodSelectorProps) {
  const types: InjectionType[] = ["bearer", "header", "query_param", "basic_auth"];

  function setType(t: InjectionType) {
    onChange({ type: t });
  }

  return (
    <div
      className="mt-[14px] rounded-[4px] border border-[var(--border-faint)] bg-[var(--bg-elevated)] p-[12px]"
    >
      <p className="mb-[10px] text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
        Injection method
      </p>

      <div className="space-y-[8px]">
        {types.map((t) => {
          const isSelected = value.type === t;
          return (
            <label
              key={t}
              className={cn(
                "flex cursor-pointer items-start gap-[10px]",
                disabled && "opacity-50 cursor-not-allowed",
              )}
            >
              <input
                type="radio"
                name="injection_type"
                value={t}
                checked={isSelected}
                disabled={disabled}
                onChange={() => setType(t)}
                className="mt-[2px] accent-[var(--accent)]"
              />
              <span className={cn("text-[13px]", isSelected ? "text-text-primary" : "text-text-muted")}>
                {INJECTION_LABELS[t]}
                {INJECTION_HINTS[t] && (
                  <span className="ml-2 font-mono text-[11px] text-text-faint">
                    → {INJECTION_HINTS[t]}
                  </span>
                )}
              </span>
            </label>
          );
        })}
      </div>

      {/* Conditional inputs — revealed with opacity transition, not display:none */}
      <div
        style={{
          opacity: value.type === "header" ? 1 : 0,
          pointerEvents: value.type === "header" ? "auto" : "none",
          transition: "opacity 220ms ease",
          height: value.type === "header" ? "auto" : 0,
          overflow: "hidden",
        }}
        aria-hidden={value.type !== "header"}
      >
        <div className="mt-[10px] space-y-[8px]">
          <div>
            <label className="mb-[4px] block text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
              Header name
            </label>
            <input
              type="text"
              tabIndex={value.type === "header" ? 0 : -1}
              placeholder="e.g. X-Api-Key"
              disabled={disabled}
              value={value.header_name ?? ""}
              onChange={(e) =>
                onChange({ ...value, header_name: e.target.value })
              }
              className="h-[34px] w-full rounded-[7px] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 font-mono text-[13px] text-text-primary placeholder:text-text-faint focus:border-accent focus:shadow-[0_0_0_2px_var(--accent-ring)] focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-[4px] block text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
              Value format <span className="text-text-faint font-normal normal-case">(optional, use <span className="font-mono">{"{value}"}</span> as placeholder)</span>
            </label>
            <input
              type="text"
              tabIndex={value.type === "header" ? 0 : -1}
              placeholder="e.g. ApiKey {value}"
              disabled={disabled}
              value={value.header_format ?? ""}
              onChange={(e) =>
                onChange({ ...value, header_format: e.target.value || undefined })
              }
              className="h-[34px] w-full rounded-[7px] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 font-mono text-[13px] text-text-primary placeholder:text-text-faint focus:border-accent focus:shadow-[0_0_0_2px_var(--accent-ring)] focus:outline-none"
            />
          </div>
        </div>
      </div>

      <div
        style={{
          opacity: value.type === "query_param" ? 1 : 0,
          pointerEvents: value.type === "query_param" ? "auto" : "none",
          transition: "opacity 220ms ease",
          height: value.type === "query_param" ? "auto" : 0,
          overflow: "hidden",
        }}
        aria-hidden={value.type !== "query_param"}
      >
        <div className="mt-[10px]">
          <label className="mb-[4px] block text-[11px] font-medium uppercase tracking-[0.06em] text-text-faint">
            Parameter name
          </label>
          <input
            type="text"
            tabIndex={value.type === "query_param" ? 0 : -1}
            placeholder="e.g. api_key"
            disabled={disabled}
            value={value.param_name ?? ""}
            onChange={(e) =>
              onChange({ ...value, param_name: e.target.value })
            }
            className="h-[34px] w-full rounded-[7px] border border-[var(--border)] bg-[var(--bg-elevated)] px-3 font-mono text-[13px] text-text-primary placeholder:text-text-faint focus:border-accent focus:shadow-[0_0_0_2px_var(--accent-ring)] focus:outline-none"
          />
          <p className="mt-[4px] font-mono text-[11px] text-text-faint">
            → ?{value.param_name || "param"}=&lt;value&gt;
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CredentialInlineForm
// ---------------------------------------------------------------------------

type FormMode = "add" | "rotate";

interface CredentialInlineFormProps {
  credKey: string;
  mode: FormMode;
  version?: number;
  templateId: string;
  onClose: () => void;
  triggerRef: React.RefObject<HTMLButtonElement>;
}

function CredentialInlineForm({
  credKey,
  mode,
  version,
  templateId,
  onClose,
  triggerRef,
}: CredentialInlineFormProps) {
  const [value, setValue] = useState("");
  const [injectionConfig, setInjectionConfig] = useState<InjectionConfig>({
    type: "bearer",
  });
  const [formState, setFormState] = useState<
    "idle" | "submitting" | "success" | "error"
  >("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const storeMutation = useStoreCredential();
  const rotateMutation = useRotateCredential();

  const formContainerRef = useRef<HTMLDivElement>(null);

  // Auto-focus password input on mount
  useEffect(() => {
    const el = formContainerRef.current?.querySelector<HTMLInputElement>("input[type='password'],input[type='text']");
    el?.focus();
  }, []);

  // Escape collapses, returns focus to trigger
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, triggerRef]);

  const handleSubmit = useCallback(async () => {
    if (!value.trim()) return;
    setFormState("submitting");
    setErrorMsg(null);
    // Build injection_config payload — omit optional fields if empty
    const injection: Record<string, unknown> = { type: injectionConfig.type };
    if (injectionConfig.type === "header") {
      if (injectionConfig.header_name) injection.header_name = injectionConfig.header_name;
      if (injectionConfig.header_format) injection.header_format = injectionConfig.header_format;
    } else if (injectionConfig.type === "query_param") {
      if (injectionConfig.param_name) injection.param_name = injectionConfig.param_name;
    }
    try {
      if (mode === "add") {
        await storeMutation.mutateAsync({
          templateId,
          key: credKey,
          value: value.trim(),
          allowed_domains: [],
          injection_config: injection,
        });
      } else {
        await rotateMutation.mutateAsync({
          templateId,
          key: credKey,
          value: value.trim(),
          version: version ?? 1,
        });
      }
      setFormState("success");
      // Hold 600ms then collapse
      setTimeout(() => {
        onClose();
      }, 600);
    } catch (err) {
      setFormState("error");
      setErrorMsg(err instanceof Error ? err.message : "Save failed");
    }
  }, [value, injectionConfig, mode, templateId, credKey, version, storeMutation, rotateMutation, onClose]);

  const isSubmitting = formState === "submitting";
  const isSuccess = formState === "success";
  const isError = formState === "error";
  const canSave = value.trim().length > 0 && !isSubmitting && !isSuccess;

  return (
    <div
      ref={formContainerRef}
      className="mt-[8px] rounded-[7px] border border-[var(--border-faint)] bg-[var(--bg-deep)] p-[16px]"
      style={{ animation: "credFormExpand 220ms ease forwards" }}
    >
      <style>{`
        @keyframes credFormExpand {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <PasswordInput
        value={value}
        onChange={setValue}
        credKey={credKey}
        disabled={isSubmitting || isSuccess}
      />

      {/* Injection method selector — only shown when adding (not rotating) */}
      {mode === "add" && (
        <InjectionMethodSelector
          value={injectionConfig}
          onChange={setInjectionConfig}
          disabled={isSubmitting || isSuccess}
        />
      )}

      {isError && errorMsg && (
        <p className="mt-[8px] text-[13px] text-alert">{errorMsg}</p>
      )}

      {/* Encryption notice */}
      <div className="mt-[10px] flex items-start gap-2">
        <Info size={13} className="mt-0.5 flex-shrink-0 text-text-muted" />
        <p className="text-[13px] text-text-muted">
          Stored encrypted. You cannot retrieve this value after saving — only rotate or delete.
        </p>
      </div>

      {/* Rotation impact notice */}
      {mode === "rotate" && (
        <div className="mt-[8px] flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 flex-shrink-0 text-warn" />
          <p className="text-[13px] text-warn">
            Rotating will update all agents (within 5 min).
          </p>
        </div>
      )}

      <div className="mt-[12px] flex items-center gap-3">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSave}
          className={cn(
            "flex h-[36px] items-center gap-2 rounded-[7px] px-4 text-[13px] font-semibold text-bg-base transition-opacity",
            isSuccess ? "bg-accent" : "bg-accent",
            !canSave && "opacity-30 cursor-not-allowed",
          )}
        >
          {isSubmitting && <Loader2 size={13} className="animate-spin" />}
          {isSuccess && <Check size={13} />}
          {isSubmitting ? "Saving…" : isSuccess ? "Saved" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => {
            onClose();
            triggerRef.current?.focus();
          }}
          className="text-[13px] text-text-muted hover:text-text-primary"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DeleteConfirmation
// ---------------------------------------------------------------------------

interface DeleteConfirmationProps {
  credKey: string;
  templateId: string;
  onClose: () => void;
  onDeleted: () => void;
  cancelRef: React.RefObject<HTMLButtonElement>;
}

function DeleteConfirmation({
  credKey,
  templateId,
  onClose,
  onDeleted,
  cancelRef,
}: DeleteConfirmationProps) {
  const [impactLoaded, setImpactLoaded] = useState(false);
  const [affectedCount, setAffectedCount] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const descId = `delete-impact-${credKey}`;

  const deleteMutation = useDeleteCredential();

  // Probe impact on mount using force=false
  useEffect(() => {
    let cancelled = false;
    async function probe() {
      try {
        const result = await deleteMutation.mutateAsync({
          templateId,
          key: credKey,
          force: false,
        });
        if (cancelled) return;
        if (result.conflict) {
          setAffectedCount(result.body.affected_agent_count ?? 0);
          setImpactLoaded(true);
        } else {
          // Deletion succeeded with force=false (0 agents affected)
          onDeleted();
        }
      } catch {
        if (!cancelled) {
          setImpactLoaded(true);
          setAffectedCount(0);
        }
      }
    }
    probe();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Focus cancel on mount
  useEffect(() => {
    cancelRef.current?.focus();
  }, [cancelRef]);

  // Escape closes
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  async function handleDelete() {
    setDeleting(true);
    setErrorMsg(null);
    try {
      await deleteMutation.mutateAsync({
        templateId,
        key: credKey,
        force: true,
      });
      onDeleted();
    } catch (err) {
      setDeleting(false);
      setErrorMsg(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div
      role="alertdialog"
      aria-describedby={descId}
      className="mt-[8px] rounded-[7px] border border-alert/20 bg-alert-dim p-[14px_16px]"
      style={{ animation: "credFormExpand 220ms ease forwards" }}
    >
      <p className="text-[13px] font-semibold text-text-primary">
        Delete{" "}
        <span className="font-mono text-alert">{credKey}</span>?
      </p>

      <div id={descId} className="mt-[6px]">
        {!impactLoaded ? (
          <div className="h-4 w-48 animate-pulse rounded-badge bg-bg-elevated" />
        ) : affectedCount === 0 ? (
          <p className="text-[13px] text-text-muted">
            No active agents affected.
          </p>
        ) : (
          <p className="text-[13px] text-alert">
            <span className="font-mono font-semibold">{affectedCount}</span> agent
            {affectedCount !== 1 ? "s" : ""} will lose access.
          </p>
        )}
      </div>

      {errorMsg && (
        <p className="mt-[8px] text-[13px] text-alert">{errorMsg}</p>
      )}

      <div className="mt-[12px] flex items-center gap-3">
        <button
          type="button"
          onClick={handleDelete}
          disabled={!impactLoaded || deleting}
          className="flex h-[36px] items-center gap-2 rounded-[7px] bg-alert px-4 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {deleting && <Loader2 size={13} className="animate-spin" />}
          {deleting ? "Deleting…" : "Delete"}
        </button>
        <button
          ref={cancelRef}
          type="button"
          onClick={onClose}
          className="text-[13px] text-text-muted hover:text-text-primary"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CredentialRow
// ---------------------------------------------------------------------------

interface CredentialRowProps {
  credKey: string;
  meta: CredentialMetadata | undefined;
  status: CredentialStatus | "missing";
  templateId: string;
  activeKey: string | null;
  activeMode: "add" | "rotate" | "delete" | null;
  onOpenForm: (key: string, mode: "add" | "rotate" | "delete") => void;
  onCloseForm: () => void;
}

function CredentialRow({
  credKey,
  meta,
  status,
  templateId,
  activeKey,
  activeMode,
  onOpenForm,
  onCloseForm,
}: CredentialRowProps) {
  const isActive = activeKey === credKey;
  const isDeleting = isActive && activeMode === "delete";
  const isForming = isActive && (activeMode === "add" || activeMode === "rotate");

  const addTriggerRef = useRef<HTMLButtonElement>(null);
  const rotateTriggerRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const activeTriggerRef =
    activeMode === "rotate" ? rotateTriggerRef : addTriggerRef;

  const description = meta?.description ?? null;
  const truncatedDesc =
    description && description.length > 80
      ? description.slice(0, 80) + "…"
      : description;

  const updatedAt = meta?.updated_at ?? null;
  const relativeTime = formatRelativeTime(updatedAt);
  const isoTime = updatedAt ?? "";

  const statusBadgeClass =
    status === "stored"
      ? "bg-accent-dim text-accent"
      : status === "missing"
        ? "bg-alert-dim text-alert"
        : "bg-bg-elevated text-text-faint";

  const statusLabel =
    status === "stored" ? "Stored" : status === "missing" ? "Missing" : "Revoked";

  const rowIsRevoked = status === "revoked";

  return (
    <div
      className={cn(
        "border-b border-[var(--border-faint)] py-[14px]",
        rowIsRevoked && "opacity-50",
        "last:border-0",
      )}
    >
      {/* Summary line */}
      <div className="flex items-center gap-3">
        {/* Key name */}
        <span className="flex-1 min-w-0 font-mono text-[13px] font-medium text-text-primary truncate">
          {credKey}
        </span>

        {/* Status badge */}
        <span
          role="status"
          className={cn(
            "flex-shrink-0 rounded-[4px] px-[8px] py-[3px] font-mono text-[10px] font-medium uppercase tracking-[0.06em]",
            statusBadgeClass,
          )}
        >
          {statusLabel}
        </span>

        {/* Timestamp */}
        <span
          title={isoTime}
          className="flex-shrink-0 font-mono text-[11px] text-text-faint"
        >
          {updatedAt ? relativeTime : "Never"}
        </span>

        {/* Actions (hidden while delete confirmation open) */}
        {!isDeleting && (
          <div className="flex flex-shrink-0 items-center gap-1.5">
            {(status === "missing" || status === "revoked") && (
              <button
                ref={addTriggerRef}
                type="button"
                onClick={() => onOpenForm(credKey, "add")}
                className="rounded-[7px] border border-accent/30 px-[12px] py-[6px] text-[13px] text-accent transition-colors hover:bg-bg-elevated focus-visible:outline-2 focus-visible:outline-accent"
              >
                Add
              </button>
            )}
            {status === "stored" && (
              <>
                <button
                  ref={rotateTriggerRef}
                  type="button"
                  onClick={() => onOpenForm(credKey, "rotate")}
                  className="rounded-[7px] border border-[var(--border)] px-[12px] py-[6px] text-[13px] text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary focus-visible:outline-2 focus-visible:outline-accent"
                >
                  Rotate
                </button>
                <button
                  type="button"
                  aria-label={`Delete credential ${credKey}`}
                  onClick={() => onOpenForm(credKey, "delete")}
                  className="flex h-[30px] w-[30px] items-center justify-center rounded-[7px] text-text-faint transition-colors hover:text-alert focus-visible:outline-2 focus-visible:outline-accent"
                >
                  <Trash2 size={15} />
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Description */}
      {truncatedDesc && (
        <p className="mt-[4px] text-[13px] text-text-muted">
          {truncatedDesc}
        </p>
      )}

      {/* Inline form */}
      {isForming && (
        <CredentialInlineForm
          credKey={credKey}
          mode={activeMode as "add" | "rotate"}
          version={meta?.version}
          templateId={templateId}
          onClose={onCloseForm}
          triggerRef={activeTriggerRef}
        />
      )}

      {/* Delete confirmation */}
      {isDeleting && (
        <DeleteConfirmation
          credKey={credKey}
          templateId={templateId}
          onClose={onCloseForm}
          onDeleted={() => {
            onCloseForm();
          }}
          cancelRef={cancelRef}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CredentialsTab
// ---------------------------------------------------------------------------

export function CredentialsTab({
  templateId,
  authMode,
  requiredCredentials,
  onSwitchToTab: _onSwitchToTab,
}: CredentialsTabProps) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [activeMode, setActiveMode] = useState<"add" | "rotate" | "delete" | null>(null);

  const { data: credsData } = useTemplateCredentials(templateId);
  const { data: healthData } = useCredentialHealth(templateId);

  const credMap = new Map<string, CredentialMetadata>(
    (credsData?.credentials ?? []).map((c) => [c.key, c]),
  );

  const healthKeys = healthData?.keys ?? {};
  const healthStatus = healthData?.status;

  // Sort: missing first → stored alphabetical → revoked last
  const sortedKeys = [...requiredCredentials].sort((a, b) => {
    const sa = (healthKeys[a] as CredentialStatus | undefined) ?? "missing";
    const sb = (healthKeys[b] as CredentialStatus | undefined) ?? "missing";
    const oa = statusOrder(sa);
    const ob = statusOrder(sb);
    if (oa !== ob) return oa - ob;
    return a.localeCompare(b);
  });

  const storedCount = Object.values(healthKeys).filter(
    (s) => s === "stored",
  ).length;

  function handleOpenForm(key: string, mode: "add" | "rotate" | "delete") {
    setActiveKey(key);
    setActiveMode(mode);
  }

  function handleCloseForm() {
    setActiveKey(null);
    setActiveMode(null);
  }

  if (requiredCredentials.length === 0) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-[13px] text-text-muted">
          No credentials required for this template.
        </p>
      </div>
    );
  }

  // Only show the credential vault UI for platform_credentials mode
  if (authMode !== "platform_credentials") {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-[13px] text-text-muted">
          Credential vault is only available for Platform Credentials auth mode.
        </p>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-5">
      <CompletenessHeader
        totalRequired={requiredCredentials.length}
        storedCount={storedCount}
        healthStatus={healthStatus}
      />

      <div>
        {sortedKeys.map((key) => {
          const meta = credMap.get(key);
          const status: CredentialStatus | "missing" =
            (healthKeys[key] as CredentialStatus | undefined) ?? "missing";

          return (
            <CredentialRow
              key={key}
              credKey={key}
              meta={meta}
              status={status}
              templateId={templateId}
              activeKey={activeKey}
              activeMode={activeMode}
              onOpenForm={handleOpenForm}
              onCloseForm={handleCloseForm}
            />
          );
        })}
      </div>
    </div>
  );
}
