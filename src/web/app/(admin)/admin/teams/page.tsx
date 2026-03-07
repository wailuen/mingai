"use client";

import { useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TeamList } from "./elements/TeamList";
import { TeamForm } from "./elements/TeamForm";
import { TeamDetail } from "./elements/TeamDetail";
import { AddMemberDialog } from "./elements/AddMemberDialog";
import { Plus } from "lucide-react";
import type { Team } from "@/lib/hooks/useTeams";

/**
 * FE-039: Teams Management page (Tenant Admin).
 * Orchestrator only -- business logic lives in elements/.
 */
export default function TeamsPage() {
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [selectedTeamName, setSelectedTeamName] = useState("");
  const [showTeamForm, setShowTeamForm] = useState(false);
  const [editingTeam, setEditingTeam] = useState<Team | null>(null);
  const [showAddMember, setShowAddMember] = useState(false);

  function handleEdit(team: Team) {
    setEditingTeam(team);
    setShowTeamForm(true);
  }

  function handleCloseForm() {
    setShowTeamForm(false);
    setEditingTeam(null);
  }

  function handleSelect(teamId: string, teamName: string) {
    setSelectedTeamId(teamId);
    setSelectedTeamName(teamName);
  }

  function handleCloseDetail() {
    setSelectedTeamId(null);
    setSelectedTeamName("");
  }

  return (
    <AppShell>
      <div className="p-7">
        {/* Page header */}
        <div className="mb-1">
          <h1 className="text-page-title text-text-primary">Teams</h1>
          <p className="mt-1 text-sm text-text-muted">
            Manage team memberships and working memory
          </p>
        </div>

        {/* Action bar */}
        <div className="mb-4 mt-5 flex items-center">
          <div className="flex-1" />
          <button
            onClick={() => {
              setEditingTeam(null);
              setShowTeamForm(true);
            }}
            className="flex items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-sm font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            <Plus size={14} />
            New Team
          </button>
        </div>

        {/* Team list */}
        <ErrorBoundary>
          <TeamList onEdit={handleEdit} onSelect={handleSelect} />
        </ErrorBoundary>

        {/* Detail panel */}
        {selectedTeamId && (
          <TeamDetail
            teamId={selectedTeamId}
            onClose={handleCloseDetail}
            onAddMember={() => setShowAddMember(true)}
          />
        )}

        {/* Modals */}
        {showTeamForm && (
          <TeamForm team={editingTeam} onClose={handleCloseForm} />
        )}
        {showAddMember && selectedTeamId && (
          <AddMemberDialog
            teamId={selectedTeamId}
            teamName={selectedTeamName}
            onClose={() => setShowAddMember(false)}
          />
        )}
      </div>
    </AppShell>
  );
}
