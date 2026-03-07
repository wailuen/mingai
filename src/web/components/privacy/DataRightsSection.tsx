"use client";

import { useState } from "react";
import { Download, Trash2, AlertTriangle } from "lucide-react";
import { apiRequest, apiDelete } from "@/lib/api";

/**
 * FE-020: Data rights section - export + clear all data.
 * GDPR compliance: export all profile data + full erasure option.
 */
export function DataRightsSection() {
  const [exporting, setExporting] = useState(false);
  const [confirmErase, setConfirmErase] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [eraseConfirmText, setEraseConfirmText] = useState("");

  async function handleExport() {
    setExporting(true);
    try {
      const data = await apiRequest<Record<string, unknown>>(
        "/api/v1/me/profile/export",
      );
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mingai-profile-export-${new Date().toISOString().split("T")[0]}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // Error handled silently
    } finally {
      setExporting(false);
    }
  }

  async function handleErase() {
    if (eraseConfirmText !== "DELETE") return;
    setErasing(true);
    try {
      await apiDelete("/api/v1/me/profile/data");
      // Redirect to login after erasure
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    } catch {
      // Error handled silently
    } finally {
      setErasing(false);
    }
  }

  return (
    <div className="rounded-card border border-border bg-bg-surface p-5">
      <h3 className="mb-4 text-section-heading text-text-primary">
        Your Data Rights
      </h3>

      <div className="space-y-4">
        {/* Export */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-text-primary">
              Export your data
            </p>
            <p className="text-xs text-text-muted">
              Download all your profile data, memory notes, and preferences as
              JSON
            </p>
          </div>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary disabled:opacity-50"
          >
            <Download size={14} />
            {exporting ? "Exporting..." : "Export"}
          </button>
        </div>

        {/* Erasure */}
        <div className="border-t border-border-faint pt-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-alert">
                Delete all your data
              </p>
              <p className="text-xs text-text-muted">
                Permanently removes your profile, memory notes, working memory,
                and all cached data. This action cannot be undone.
              </p>
            </div>
            {!confirmErase ? (
              <button
                onClick={() => setConfirmErase(true)}
                className="flex items-center gap-1.5 rounded-control border border-alert px-3 py-1.5 text-sm text-alert transition-colors hover:bg-alert-dim"
              >
                <Trash2 size={14} />
                Delete
              </button>
            ) : null}
          </div>

          {confirmErase && (
            <div className="mt-3 rounded-control border border-alert-ring bg-alert-dim p-3">
              <div className="mb-2 flex items-center gap-2">
                <AlertTriangle size={14} className="text-alert" />
                <span className="text-sm font-medium text-alert">
                  This is permanent
                </span>
              </div>
              <p className="mb-3 text-xs text-text-muted">
                Type <strong className="text-text-primary">DELETE</strong> to
                confirm erasure of all your data.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={eraseConfirmText}
                  onChange={(e) => setEraseConfirmText(e.target.value)}
                  placeholder="Type DELETE"
                  className="flex-1 rounded-control border border-border bg-bg-elevated px-3 py-1.5 text-sm text-text-primary placeholder:text-text-faint focus:border-alert focus:outline-none"
                />
                <button
                  onClick={handleErase}
                  disabled={eraseConfirmText !== "DELETE" || erasing}
                  className="rounded-control bg-alert px-3 py-1.5 text-sm font-medium text-white transition-opacity disabled:opacity-30"
                >
                  {erasing ? "Deleting..." : "Confirm Delete"}
                </button>
                <button
                  onClick={() => {
                    setConfirmErase(false);
                    setEraseConfirmText("");
                  }}
                  className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
