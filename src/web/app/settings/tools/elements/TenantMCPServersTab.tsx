"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Plus,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Pencil,
  Trash2,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  MinusCircle,
  Server,
} from "lucide-react";
import {
  useMCPServers,
  useDeleteMCPServer,
  useReverifyMCPServer,
  useUpdateMCPServer,
} from "@/lib/hooks/useTools";
import type {
  MCPServer,
  MCPTool,
  MCPServerStatus,
  MCPTransport,
  MCPAuthType,
} from "@/lib/hooks/useTools";
import { MCPServerRegistrationPanel } from "./MCPServerRegistrationPanel";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<
  MCPServerStatus,
  { label: string; color: string; Icon: typeof CheckCircle2 }
> = {
  verified: {
    label: "Verified",
    color: "text-accent bg-accent/10 border-accent/30",
    Icon: CheckCircle2,
  },
  error: {
    label: "Error",
    color: "text-alert bg-alert/10 border-alert/30",
    Icon: AlertCircle,
  },
  pending: {
    label: "Pending",
    color: "text-warn bg-warn/10 border-warn/30",
    Icon: Clock,
  },
  inactive: {
    label: "Inactive",
    color: "text-text-faint bg-bg-elevated border-border",
    Icon: MinusCircle,
  },
};

const TRANSPORT_LABELS: Record<MCPTransport, string> = {
  sse: "SSE",
  streamable_http: "Streamable HTTP",
};

const AUTH_LABELS: Record<MCPAuthType, string> = {
  none: "No Auth",
  bearer: "Bearer Token",
  api_key: "API Key",
};

// ---------------------------------------------------------------------------
// Edit modal (inline simple)
// ---------------------------------------------------------------------------

interface EditServerModalProps {
  server: MCPServer;
  onClose: () => void;
}

function EditServerModal({ server, onClose }: EditServerModalProps) {
  const [name, setName] = useState(server.name);
  const [description, setDescription] = useState(server.description ?? "");
  const { mutate: update, isPending } = useUpdateMCPServer();

  function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    update(
      {
        serverId: server.id,
        payload: {
          name: name.trim(),
          description: description.trim() || undefined,
        },
      },
      { onSuccess: onClose },
    );
  }

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-bg-base/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-card border border-border bg-bg-surface p-6 shadow-xl">
        <h2 className="mb-4 text-section-heading text-text-primary">
          Edit Server
        </h2>
        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-body-default font-medium text-text-primary">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary outline-none focus:border-accent-ring"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-body-default font-medium text-text-primary">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary outline-none focus:border-accent-ring"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !name.trim()}
              className="flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-body-default font-medium text-bg-base disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPending && <Loader2 size={13} className="animate-spin" />}
              Save
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Delete confirm modal
// ---------------------------------------------------------------------------

interface DeleteConfirmModalProps {
  server: MCPServer;
  onClose: () => void;
}

function DeleteConfirmModal({ server, onClose }: DeleteConfirmModalProps) {
  const { mutate: del, isPending } = useDeleteMCPServer();

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-bg-base/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div className="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-card border border-border bg-bg-surface p-6 shadow-xl">
        <h2 className="mb-2 text-section-heading text-text-primary">
          Delete MCP Server
        </h2>
        <p className="mb-6 text-body-default text-text-muted">
          Remove{" "}
          <span className="font-medium text-text-primary">{server.name}</span>?
          All tools enumerated from this server will no longer be available to
          agents.
        </p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-4 py-2 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isPending}
            onClick={() => del(server.id, { onSuccess: onClose })}
            className="flex items-center gap-2 rounded-control bg-alert px-4 py-2 text-body-default font-medium text-white transition-colors hover:bg-alert/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isPending && <Loader2 size={13} className="animate-spin" />}
            Delete
          </button>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Tool list in expanded server card
// ---------------------------------------------------------------------------

function ToolList({ tools }: { tools: MCPTool[] }) {
  if (tools.length === 0) {
    return (
      <p className="text-body-default text-text-faint">
        No tools enumerated from this server yet.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {tools.map((tool) => (
        <div
          key={tool.id}
          className="rounded-control border border-border bg-bg-base px-3 py-2.5"
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-body-default font-medium text-text-primary">
              {tool.name}
            </span>
            {tool.usage_count != null && (
              <span className="shrink-0 font-mono text-data-value text-text-faint">
                {tool.usage_count} uses
              </span>
            )}
          </div>
          {tool.description && (
            <p className="mt-0.5 text-body-default text-text-muted">
              {tool.description}
            </p>
          )}
          {tool.input_schema && Object.keys(tool.input_schema).length > 0 && (
            <p className="mt-1 font-mono text-data-value text-text-faint">
              {Object.keys(tool.input_schema).length} input param
              {Object.keys(tool.input_schema).length !== 1 ? "s" : ""}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Individual server card
// ---------------------------------------------------------------------------

interface ServerCardProps {
  server: MCPServer;
}

function ServerCard({ server }: ServerCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const { mutate: reverify, isPending: isReverifying } = useReverifyMCPServer();

  const statusCfg = STATUS_CONFIG[server.status];
  const StatusIcon = statusCfg.Icon;

  const toolCount = server.tools?.length ?? 0;

  function handleReverify(e: React.MouseEvent) {
    e.stopPropagation();
    reverify(server.id);
  }

  function handleEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setEditOpen(true);
  }

  function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    setDeleteOpen(true);
  }

  return (
    <>
      <div className="rounded-card border border-border bg-bg-surface overflow-hidden">
        {/* Card header — click to expand */}
        <div
          className="flex cursor-pointer items-start gap-3 px-4 py-4 transition-colors hover:bg-bg-elevated/50"
          onClick={() => setExpanded((p) => !p)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setExpanded((p) => !p);
            }
          }}
          aria-expanded={expanded}
        >
          {/* Expand chevron */}
          <span className="mt-0.5 shrink-0 text-text-faint">
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </span>

          {/* Main info */}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-body-default font-medium text-text-primary">
                {server.name}
              </span>

              {/* Status badge */}
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-badge border px-2 py-0.5 font-mono text-data-value",
                  statusCfg.color,
                )}
              >
                <StatusIcon size={11} />
                {statusCfg.label}
              </span>

              {/* Transport badge */}
              <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                {TRANSPORT_LABELS[server.transport]}
              </span>

              {/* Auth badge */}
              <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                {AUTH_LABELS[server.auth_type]}
              </span>

              {/* Tool count */}
              {toolCount > 0 && (
                <span className="rounded-badge border border-border bg-bg-elevated px-2 py-0.5 font-mono text-data-value text-text-muted">
                  {toolCount} tool{toolCount !== 1 ? "s" : ""}
                </span>
              )}
            </div>

            {/* Endpoint URL */}
            <p className="mt-1 truncate font-mono text-data-value text-text-faint">
              {server.endpoint_url}
            </p>

            {/* Error message */}
            {server.status === "error" && server.last_error && (
              <p className="mt-1.5 text-body-default text-alert">
                {server.last_error}
              </p>
            )}

            {/* Last verified */}
            {server.last_verified_at && server.status === "verified" && (
              <p className="mt-1 font-mono text-data-value text-text-faint">
                Verified{" "}
                {new Date(server.last_verified_at).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </p>
            )}
          </div>

          {/* Actions */}
          <div
            className="flex shrink-0 items-center gap-2"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Re-verify */}
            <button
              type="button"
              onClick={handleReverify}
              disabled={isReverifying}
              title="Re-verify server"
              className="flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1.5 text-body-default text-text-muted transition-colors hover:border-accent-ring hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isReverifying ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RefreshCw size={13} />
              )}
              Re-verify
            </button>

            {/* Edit */}
            <button
              type="button"
              onClick={handleEdit}
              title="Edit server"
              className="rounded-control border border-border p-1.5 text-text-faint transition-colors hover:border-accent-ring hover:text-text-primary"
            >
              <Pencil size={13} />
            </button>

            {/* Delete */}
            <button
              type="button"
              onClick={handleDelete}
              title="Delete server"
              className="rounded-control border border-border p-1.5 text-text-faint transition-colors hover:border-alert/40 hover:text-alert"
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>

        {/* Expanded: tool list */}
        {expanded && (
          <div className="border-t border-border-faint bg-bg-deep px-6 py-4">
            <p className="mb-3 text-label-nav uppercase tracking-wider text-text-faint">
              Tools ({toolCount})
            </p>
            <ToolList tools={server.tools ?? []} />
          </div>
        )}
      </div>

      {editOpen && (
        <EditServerModal server={server} onClose={() => setEditOpen(false)} />
      )}
      {deleteOpen && (
        <DeleteConfirmModal
          server={server}
          onClose={() => setDeleteOpen(false)}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main tab component
// ---------------------------------------------------------------------------

export function TenantMCPServersTab() {
  const [showRegistration, setShowRegistration] = useState(false);
  const { data, isPending, error } = useMCPServers();
  const queryClient = useQueryClient();

  const servers = data?.items ?? [];

  // Poll every 3s while any server is pending
  const hasPending = servers.some((s) => s.status === "pending");

  const doRefetch = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
  }, [queryClient]);

  useEffect(() => {
    if (!hasPending) return;
    const id = setInterval(doRefetch, 3000);
    return () => clearInterval(id);
  }, [hasPending, doRefetch]);

  if (error) {
    return (
      <div className="py-12 text-center">
        <p className="text-body-default text-alert">
          Failed to load MCP servers.{" "}
          {error instanceof Error ? error.message : "Unknown error."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <p className="text-body-default text-text-muted">
          {servers.length > 0
            ? `${servers.length} server${servers.length !== 1 ? "s" : ""} registered`
            : "No MCP servers registered yet"}
        </p>
        <button
          type="button"
          onClick={() => setShowRegistration(true)}
          className="flex items-center gap-2 rounded-control bg-accent px-3 py-2 text-body-default font-medium text-bg-base transition-colors hover:bg-accent/90"
        >
          <Plus size={15} />
          Register MCP Server
        </button>
      </div>

      {/* Loading skeleton */}
      {isPending && (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="h-20 animate-pulse rounded-card border border-border bg-bg-surface"
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isPending && servers.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-card border border-border bg-bg-surface py-16 text-center">
          <Server size={36} className="mb-3 text-text-faint" />
          <p className="text-body-default font-medium text-text-muted">
            No MCP servers registered
          </p>
          <p className="mt-1 text-body-default text-text-faint">
            Register an MCP-compliant server to make its tools available to your
            agents.
          </p>
          <button
            type="button"
            onClick={() => setShowRegistration(true)}
            className="mt-4 flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-body-default font-medium text-bg-base transition-colors hover:bg-accent/90"
          >
            <Plus size={14} />
            Register your first server
          </button>
        </div>
      )}

      {/* Server cards */}
      {!isPending && servers.length > 0 && (
        <div className="space-y-3">
          {servers.map((server) => (
            <ServerCard key={server.id} server={server} />
          ))}
        </div>
      )}

      {/* Pending notice */}
      {hasPending && (
        <div className="flex items-center gap-2 rounded-control border border-warn/30 bg-warn-dim px-4 py-2.5">
          <Loader2 size={14} className="animate-spin text-warn" />
          <p className="text-body-default text-warn">
            Verifying servers — checking every few seconds...
          </p>
        </div>
      )}

      {/* Registration panel */}
      {showRegistration && (
        <MCPServerRegistrationPanel
          onClose={() => setShowRegistration(false)}
        />
      )}
    </div>
  );
}
