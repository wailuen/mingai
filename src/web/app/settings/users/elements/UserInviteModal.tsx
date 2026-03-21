"use client";

import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiPost } from "@/lib/api";
import { X, Upload } from "lucide-react";

interface ParsedCSVRow {
  email: string;
  role: string;
  valid: boolean;
  error: string;
}

/**
 * Invite modal: single email + role, or bulk CSV upload with preview.
 * CSV format: email,role (header required).
 */
export function UserInviteModal({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<"single" | "csv">("single");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"viewer" | "tenant_admin">("viewer");
  const [csvRows, setCsvRows] = useState<ParsedCSVRow[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const queryClient = useQueryClient();

  const handleCSVUpload = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (event) => {
        const text = event.target?.result as string;
        const lines = text.trim().split("\n");
        const rows: ParsedCSVRow[] = [];

        // Skip header
        for (let i = 1; i < lines.length; i++) {
          const parts = lines[i].split(",").map((s) => s.trim());
          const rowEmail = parts[0] ?? "";
          const rowRole = parts[1] ?? "user";

          const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
          const isValidEmail = emailRegex.test(rowEmail);
          const isValidRole = ["user", "tenant_admin"].includes(rowRole);

          rows.push({
            email: rowEmail,
            role: rowRole,
            valid: isValidEmail && isValidRole,
            error: !isValidEmail
              ? "Invalid email"
              : !isValidRole
                ? "Invalid role (use user or tenant_admin)"
                : "",
          });
        }
        setCsvRows(rows);
      };
      reader.readAsText(file);
    },
    [],
  );

  async function handleInvite() {
    setSubmitting(true);
    try {
      if (mode === "single" && email.trim()) {
        await apiPost("/api/v1/admin/users/invite", {
          email: email.trim(),
          role,
        });
      } else if (mode === "csv") {
        // Invite each valid CSV row sequentially via the single invite endpoint
        const validRows = csvRows.filter((r) => r.valid);
        for (const row of validRows) {
          await apiPost("/api/v1/admin/users/invite", {
            email: row.email,
            role: row.role,
          });
        }
      }
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    } catch {
      // Error surfaced by API layer
    } finally {
      setSubmitting(false);
    }
  }

  const validCount = csvRows.filter((r) => r.valid).length;
  const invalidCount = csvRows.filter((r) => !r.valid).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-lg rounded-card border border-border bg-bg-surface">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">
            Invite Users
          </h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5">
          {/* Mode tabs */}
          <div className="mb-4 flex gap-2 border-b border-border pb-2">
            <button
              onClick={() => setMode("single")}
              className={`rounded-control px-3 py-1 text-xs transition-colors ${
                mode === "single"
                  ? "bg-accent-dim text-accent"
                  : "text-text-faint hover:text-text-muted"
              }`}
            >
              Single Email
            </button>
            <button
              onClick={() => setMode("csv")}
              className={`rounded-control px-3 py-1 text-xs transition-colors ${
                mode === "csv"
                  ? "bg-accent-dim text-accent"
                  : "text-text-faint hover:text-text-muted"
              }`}
            >
              CSV Upload
            </button>
          </div>

          {mode === "single" ? (
            <div className="space-y-4">
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="user@company.com"
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
                  Role
                </label>
                <select
                  value={role}
                  onChange={(e) =>
                    setRole(e.target.value as "viewer" | "tenant_admin")
                  }
                  className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary transition-colors focus:border-accent focus:outline-none"
                >
                  <option value="viewer">User</option>
                  <option value="tenant_admin">Admin</option>
                </select>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <label className="block cursor-pointer rounded-control border border-dashed border-border px-4 py-6 text-center text-body-default text-text-faint transition-colors hover:border-accent-ring hover:bg-bg-elevated">
                <Upload size={20} className="mx-auto mb-2" />
                {csvRows.length > 0
                  ? `${csvRows.length} rows parsed`
                  : "Drop CSV file or click to browse"}
                <input
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={handleCSVUpload}
                />
              </label>

              {/* CSV preview */}
              {csvRows.length > 0 && (
                <div className="max-h-48 overflow-y-auto rounded-card border border-border">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                          Email
                        </th>
                        <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                          Role
                        </th>
                        <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {csvRows.map((row, i) => (
                        <tr key={i} className="border-b border-border-faint">
                          <td className="px-3 py-1.5 font-mono text-data-value text-text-muted">
                            {row.email}
                          </td>
                          <td className="px-3 py-1.5 text-xs text-text-muted">
                            {row.role}
                          </td>
                          <td className="px-3 py-1.5 text-xs">
                            {row.valid ? (
                              <span className="text-accent">Valid</span>
                            ) : (
                              <span className="text-alert">{row.error}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="flex gap-3 border-t border-border px-3 py-2">
                    <span className="font-mono text-xs text-accent">
                      {validCount} valid
                    </span>
                    {invalidCount > 0 && (
                      <span className="font-mono text-xs text-alert">
                        {invalidCount} invalid
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            onClick={handleInvite}
            disabled={
              submitting ||
              (mode === "single" && !email.trim()) ||
              (mode === "csv" && validCount === 0)
            }
            className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
          >
            {submitting
              ? "Sending..."
              : mode === "csv"
                ? `Send ${validCount} Invite${validCount !== 1 ? "s" : ""}`
                : "Send Invite"}
          </button>
        </div>
      </div>
    </div>
  );
}
