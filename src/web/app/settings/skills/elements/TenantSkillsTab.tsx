"use client";

import { useState } from "react";
import { Plus, Edit2, Trash2, Lock, ChevronDown, Loader2 } from "lucide-react";
import {
  usePlatformSkills,
  useTenantSkills,
  useUnadoptSkill,
  usePinSkillVersion,
  useDeleteSkill,
} from "@/lib/hooks/useSkills";
import type { TenantSkill } from "@/lib/hooks/useSkills";
import { TenantSkillAuthoringPanel } from "./TenantSkillAuthoringPanel";
import { cn } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  draft: "text-warn bg-warn-dim border-warn/30",
  published: "text-accent bg-accent-dim border-accent/30",
  deprecated: "text-text-faint bg-bg-elevated border-border",
};

export function TenantSkillsTab() {
  const [panelSkill, setPanelSkill] = useState<TenantSkill | null | "new">(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<TenantSkill | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data: platformData, isPending: loadingPlatform } =
    usePlatformSkills();
  const {
    data: tenantData,
    isPending: loadingTenant,
    refetch,
  } = useTenantSkills();
  const { mutate: unadopt } = useUnadoptSkill();
  const { mutate: pin } = usePinSkillVersion();
  const { mutate: deleteSkill, isPending: isDeleting } = useDeleteSkill();

  const adoptedPlatformSkills = (platformData?.items ?? []).filter(
    (s) => s.adopted,
  );
  const tenantSkills = tenantData?.items ?? [];

  function handlePanelClose() {
    setPanelSkill(null);
    refetch();
  }

  function handleUnadopt(skillId: string) {
    unadopt(skillId);
  }

  function handlePin(skillId: string, version: string | null) {
    pin({ skillId, payload: { pinned_version: version } });
  }

  function handleDelete(skill: TenantSkill) {
    setDeleteTarget(skill);
    setConfirmDelete(true);
  }

  function confirmDeleteSkill() {
    if (!deleteTarget) return;
    deleteSkill(deleteTarget.id, {
      onSuccess: () => {
        setConfirmDelete(false);
        setDeleteTarget(null);
        refetch();
      },
    });
  }

  const isLoading = loadingPlatform || loadingTenant;

  return (
    <>
      <div className="space-y-8">
        {/* Loading state */}
        {isLoading && (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-14 animate-pulse rounded-card border border-border bg-bg-surface"
              />
            ))}
          </div>
        )}

        {/* Adopted Platform Skills section */}
        {!isLoading && (
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-section-heading text-text-primary">
                Adopted Platform Skills
              </h2>
              <span className="font-mono text-data-value text-text-faint">
                {adoptedPlatformSkills.length}
              </span>
            </div>

            {adoptedPlatformSkills.length === 0 ? (
              <div className="rounded-card border border-border bg-bg-surface px-4 py-8 text-center">
                <p className="text-body-default text-text-faint">
                  No platform skills adopted yet. Go to the Platform Skills tab
                  to adopt skills.
                </p>
              </div>
            ) : (
              <div className="rounded-card border border-border bg-bg-surface">
                {adoptedPlatformSkills.map((skill, idx) => (
                  <div
                    key={skill.id}
                    className={cn(
                      "flex items-center gap-4 px-4 py-3",
                      idx < adoptedPlatformSkills.length - 1
                        ? "border-b border-border-faint"
                        : "",
                    )}
                  >
                    {/* Name */}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-body-default font-medium text-text-primary">
                        {skill.name}
                      </p>
                      {skill.category && (
                        <p className="font-mono text-data-value text-text-faint">
                          {skill.category}
                        </p>
                      )}
                    </div>

                    {/* Version + pin dropdown */}
                    <AdoptedVersionDropdown
                      version={skill.version}
                      pinnedVersion={skill.pinned_version ?? null}
                      onPin={(v) => handlePin(skill.id, v)}
                    />

                    {/* Remove button (disabled if mandatory) */}
                    {skill.is_mandatory ? (
                      <div className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-body-default text-text-faint">
                        <Lock size={12} />
                        Required
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleUnadopt(skill.id)}
                        className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-body-default text-text-muted transition-colors hover:border-alert/40 hover:text-alert"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* My Skills section */}
        {!isLoading && (
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-section-heading text-text-primary">
                My Skills
              </h2>
              <button
                type="button"
                onClick={() => setPanelSkill("new")}
                className="flex items-center gap-2 rounded-control bg-accent px-3 py-1.5 text-body-default font-medium text-bg-base transition-colors hover:bg-accent/90"
              >
                <Plus size={14} />
                New Skill
              </button>
            </div>

            {tenantSkills.length === 0 ? (
              <div className="rounded-card border border-border bg-bg-surface px-4 py-8 text-center">
                <p className="text-body-default text-text-faint">
                  No tenant skills created yet.
                </p>
                <button
                  type="button"
                  onClick={() => setPanelSkill("new")}
                  className="mt-2 text-body-default text-accent hover:underline"
                >
                  Create your first skill
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {tenantSkills.map((skill) => (
                  <div
                    key={skill.id}
                    className="flex items-start gap-4 rounded-card border border-border bg-bg-surface p-4"
                  >
                    {/* Content */}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-body-default font-medium text-text-primary">
                          {skill.name}
                        </span>

                        {/* Status badge */}
                        <span
                          className={cn(
                            "rounded-badge border px-2 py-0.5 font-mono text-data-value uppercase",
                            STATUS_COLORS[skill.status] ??
                              "text-text-faint bg-bg-elevated border-border",
                          )}
                        >
                          {skill.status}
                        </span>

                        {/* Category */}
                        {skill.category && (
                          <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                            {skill.category}
                          </span>
                        )}

                        {/* Version */}
                        <span className="font-mono text-data-value text-text-faint">
                          v{skill.version}
                        </span>
                      </div>

                      {skill.description && (
                        <p className="mt-1 line-clamp-2 text-body-default text-text-muted">
                          {skill.description}
                        </p>
                      )}

                      {skill.updated_at && (
                        <p className="mt-1 font-mono text-data-value text-text-faint">
                          Updated{" "}
                          {new Date(skill.updated_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setPanelSkill(skill)}
                        className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
                      >
                        <Edit2 size={13} />
                        Edit
                      </button>

                      {/* Can only delete drafts */}
                      {skill.status === "draft" && (
                        <button
                          type="button"
                          onClick={() => handleDelete(skill)}
                          className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-body-default text-text-muted transition-colors hover:border-alert/40 hover:text-alert"
                        >
                          <Trash2 size={13} />
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      {/* Authoring panel */}
      {panelSkill !== null && (
        <TenantSkillAuthoringPanel
          skill={panelSkill === "new" ? null : panelSkill}
          onClose={handlePanelClose}
          onSaved={handlePanelClose}
        />
      )}

      {/* Delete confirmation dialog */}
      {confirmDelete && deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setConfirmDelete(false)}
            aria-hidden
          />
          <div className="relative z-10 w-full max-w-sm rounded-card border border-border bg-bg-surface p-6">
            <h3 className="text-section-heading text-text-primary">
              Delete Skill
            </h3>
            <p className="mt-2 text-body-default text-text-muted">
              Are you sure you want to delete{" "}
              <span className="font-medium text-text-primary">
                {deleteTarget.name}
              </span>
              ? This action cannot be undone.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDeleteSkill}
                disabled={isDeleting}
                className="flex items-center gap-2 rounded-control bg-alert px-4 py-2 text-body-default font-medium text-white transition-colors hover:bg-alert/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isDeleting && <Loader2 size={13} className="animate-spin" />}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Version dropdown for adopted platform skills
// ---------------------------------------------------------------------------

function AdoptedVersionDropdown({
  version,
  pinnedVersion,
  onPin,
}: {
  version: number;
  pinnedVersion: string | null;
  onPin: (version: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  const versions: string[] = [];
  for (let v = version; v >= Math.max(1, version - 4); v--) {
    versions.push(String(v));
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
      >
        <span className="font-mono text-data-value">
          {pinnedVersion ? `v${pinnedVersion}` : "Latest"}
        </span>
        <ChevronDown size={12} />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div className="absolute right-0 top-full z-20 mt-1 w-36 overflow-hidden rounded-card border border-border bg-bg-surface shadow-lg">
            <button
              type="button"
              onClick={() => {
                onPin(null);
                setOpen(false);
              }}
              className={cn(
                "w-full px-3 py-2 text-left text-body-default transition-colors hover:bg-bg-elevated",
                !pinnedVersion ? "text-accent" : "text-text-muted",
              )}
            >
              Always Latest
            </button>
            {versions.map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => {
                  onPin(v);
                  setOpen(false);
                }}
                className={cn(
                  "w-full px-3 py-2 text-left font-mono text-data-value transition-colors hover:bg-bg-elevated",
                  pinnedVersion === v ? "text-accent" : "text-text-muted",
                )}
              >
                v{v}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
