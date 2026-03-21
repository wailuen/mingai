"use client";

import { useState } from "react";
import { X, UserPlus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/shared/LoadingState";
import { useTeam, useTeamMemory, useRemoveMember } from "@/lib/hooks/useTeams";
import { Auth0SyncSettings } from "./Auth0SyncSettings";
import { TeamMemoryControls } from "./TeamMemoryControls";
import { MembershipAuditLog } from "./MembershipAuditLog";

interface TeamDetailProps {
  teamId: string;
  onClose: () => void;
  onAddMember: () => void;
}

type DetailTab = "members" | "memory" | "sync" | "audit";

const TAB_LABELS: Record<DetailTab, string> = {
  members: "Members",
  memory: "Memory",
  sync: "Auth0 Sync",
  audit: "Audit Log",
};

export function TeamDetail({ teamId, onClose, onAddMember }: TeamDetailProps) {
  const [activeTab, setActiveTab] = useState<DetailTab>("members");
  const { data: team, isLoading: teamLoading } = useTeam(teamId);
  const { data: memory, isLoading: memoryLoading } = useTeamMemory(
    activeTab === "memory" ? teamId : null,
  );
  const removeMutation = useRemoveMember();

  function handleRemoveMember(userId: string) {
    removeMutation.mutate({ teamId, userId });
  }

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border bg-bg-surface animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <div className="min-w-0 flex-1">
          {teamLoading ? (
            <Skeleton className="h-5 w-40" />
          ) : (
            <>
              <h2 className="truncate text-section-heading text-text-primary">
                {team?.name}
              </h2>
              <p className="mt-0.5 font-mono text-xs text-text-faint">
                {team?.member_count ?? 0} members
              </p>
            </>
          )}
        </div>
        <button
          onClick={onClose}
          className="ml-3 flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          <X size={16} />
        </button>
      </div>

      {/* Description */}
      {team?.description && (
        <div className="border-b border-border-faint px-5 py-3">
          <p className="text-body-default text-text-muted">{team.description}</p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex overflow-x-auto border-b border-border px-5">
        {(["members", "memory", "sync", "audit"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium transition-colors",
              activeTab === tab
                ? "border-accent text-text-primary"
                : "border-transparent text-text-faint hover:text-text-muted",
            )}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {activeTab === "members" && (
          <MembersTab
            teamId={teamId}
            memberCount={team?.member_count ?? 0}
            onAddMember={onAddMember}
            onRemoveMember={handleRemoveMember}
            isRemoving={removeMutation.isPending}
          />
        )}
        {activeTab === "memory" && (
          <>
            <TeamMemoryControls
              teamId={teamId}
              memberCount={team?.member_count ?? 0}
            />
            <div className="mt-6 border-t border-border-faint pt-4">
              <MemoryTab memory={memory} isLoading={memoryLoading} />
            </div>
          </>
        )}
        {activeTab === "sync" && <Auth0SyncSettings teamId={teamId} />}
        {activeTab === "audit" && <MembershipAuditLog teamId={teamId} />}
      </div>

      {/* Created at */}
      {team?.created_at && (
        <div className="border-t border-border-faint px-5 py-3">
          <span className="text-xs text-text-faint">Created </span>
          <span className="font-mono text-xs text-text-faint">
            {new Date(team.created_at).toLocaleDateString()}
          </span>
        </div>
      )}
    </div>
  );
}

function MembersTab({
  teamId,
  memberCount,
  onAddMember,
  onRemoveMember,
  isRemoving,
}: {
  teamId: string;
  memberCount: number;
  onAddMember: () => void;
  onRemoveMember: (userId: string) => void;
  isRemoving: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-body-default text-text-muted">
          {memberCount} member{memberCount !== 1 ? "s" : ""}
        </span>
        <button
          onClick={onAddMember}
          className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-xs font-semibold text-bg-base transition-opacity hover:opacity-90"
        >
          <UserPlus size={12} />
          Add Member
        </button>
      </div>

      {memberCount === 0 ? (
        <p className="py-8 text-center text-body-default text-text-faint">
          No members yet. Add the first member to this team.
        </p>
      ) : (
        <p className="py-4 text-center text-xs text-text-faint">
          Member details are available via the Users directory. Use the team ID{" "}
          <span className="font-mono text-text-muted">{teamId}</span> to manage
          memberships.
        </p>
      )}
    </div>
  );
}

function MemoryTab({
  memory,
  isLoading,
}: {
  memory:
    | { team_id: string; topics: string[]; recent_queries: string[] }
    | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }

  const hasTopics = (memory?.topics?.length ?? 0) > 0;
  const hasQueries = (memory?.recent_queries?.length ?? 0) > 0;

  if (!hasTopics && !hasQueries) {
    return (
      <p className="py-8 text-center text-body-default text-text-faint">
        No working memory stored for this team yet.
      </p>
    );
  }

  return (
    <div className="space-y-5">
      {hasTopics && (
        <div>
          <h4 className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
            Topics
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {memory?.topics.map((topic, i) => (
              <span
                key={i}
                className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 text-xs text-text-muted"
              >
                {topic}
              </span>
            ))}
          </div>
        </div>
      )}

      {hasQueries && (
        <div>
          <h4 className="mb-2 text-label-nav uppercase tracking-wider text-text-faint">
            Recent Queries
          </h4>
          <div className="space-y-1.5">
            {memory?.recent_queries.map((query, i) => (
              <p key={i} className="text-body-default text-text-muted">
                {query}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
