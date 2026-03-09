"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";

interface GitHubIssueButtonProps {
  issueId: string;
  issueTitle: string;
  issueDescription: string;
  githubUrl?: string;
}

interface GitHubCreateResponse {
  github_url: string;
}

function GitHubIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
      />
    </svg>
  );
}

export function GitHubIssueButton({
  issueId,
  issueTitle,
  issueDescription,
  githubUrl,
}: GitHubIssueButtonProps) {
  const [showDialog, setShowDialog] = useState(false);
  const [title, setTitle] = useState(issueTitle);
  const [body, setBody] = useState(issueDescription);

  const createMutation = useMutation({
    mutationFn: () =>
      apiPost<GitHubCreateResponse>(
        `/api/v1/platform/issues/${issueId}/github`,
        { title, body },
      ),
    onSuccess: () => {
      setShowDialog(false);
    },
    onError: (err) => {
      console.error(
        `Failed to create GitHub issue for ${issueId}:`,
        err instanceof Error ? err.message : err,
      );
    },
  });

  const isLinked = !!githubUrl;

  return (
    <>
      {/* Trigger button */}
      <button
        type="button"
        disabled={isLinked}
        onClick={() => {
          setTitle(issueTitle);
          setBody(issueDescription);
          setShowDialog(true);
        }}
        className={cn(
          "flex items-center gap-1.5 rounded-control border px-3 py-1.5 text-[13px] transition-colors",
          isLinked
            ? "cursor-default border-accent-ring bg-accent-dim text-accent"
            : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
        )}
      >
        <GitHubIcon size={14} />
        {isLinked ? (
          <a
            href={githubUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-accent"
            onClick={(e) => e.stopPropagation()}
          >
            View in GitHub
            <ExternalLink size={12} />
          </a>
        ) : (
          "File in GitHub"
        )}
      </button>

      {/* Dialog */}
      {showDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
          <div className="w-full max-w-[540px] rounded-card border border-border bg-bg-surface">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <div className="flex items-center gap-2">
                <GitHubIcon size={18} />
                <h2 className="text-section-heading text-text-primary">
                  File GitHub Issue
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setShowDialog(false)}
                className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
              >
                <X size={16} />
              </button>
            </div>

            {/* Body */}
            <div className="space-y-4 p-5">
              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Title
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] uppercase tracking-wider text-text-faint">
                  Description
                </label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={6}
                  className="w-full resize-y rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />
              </div>

              {createMutation.isError && (
                <div className="rounded-control border border-alert/30 bg-alert-dim p-3">
                  <p className="text-xs text-alert">
                    {createMutation.error instanceof Error
                      ? createMutation.error.message
                      : "Failed to create GitHub issue"}
                  </p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
              <button
                type="button"
                onClick={() => setShowDialog(false)}
                className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => createMutation.mutate()}
                disabled={createMutation.isPending || !title.trim()}
                className="flex items-center gap-1.5 rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
              >
                <GitHubIcon size={14} />
                {createMutation.isPending ? "Creating..." : "Create Issue"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
