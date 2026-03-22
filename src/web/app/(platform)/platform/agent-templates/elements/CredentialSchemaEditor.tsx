"use client";

import { Plus, Trash2 } from "lucide-react";
import type { CredentialSchema } from "@/lib/hooks/useAgentTemplatesAdmin";

interface CredentialSchemaEditorProps {
  rows: CredentialSchema[];
  onChange: (rows: CredentialSchema[]) => void;
}

function labelToKey(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_]/g, "");
}

/**
 * Inline editable table for credential schema.
 * Key is auto-generated from label on first creation and read-only thereafter.
 */
export function CredentialSchemaEditor({
  rows,
  onChange,
}: CredentialSchemaEditorProps) {
  function handleAdd() {
    onChange([
      ...rows,
      { key: "", label: "", type: "string", sensitive: false },
    ]);
  }

  function handleRemove(index: number) {
    onChange(rows.filter((_, i) => i !== index));
  }

  function handleChange(
    index: number,
    field: keyof CredentialSchema,
    value: string | boolean,
  ) {
    const updated = rows.map((row, i) => {
      if (i !== index) return row;
      const next = { ...row, [field]: value };
      // Auto-generate key from label if key is still empty
      if (field === "label" && !row.key) {
        next.key = labelToKey(value as string);
      }
      return next;
    });
    onChange(updated);
  }

  return (
    <div className="space-y-2">
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-bg-elevated">
                <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Key
                </th>
                <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Label
                </th>
                <th className="px-3 py-2 text-left text-label-nav uppercase tracking-wider text-text-faint">
                  Type
                </th>
                <th className="px-3 py-2 text-center text-label-nav uppercase tracking-wider text-text-faint">
                  Sensitive
                </th>
                <th className="w-8 px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b border-border-faint last:border-0">
                  <td className="px-3 py-2">
                    <span className="font-mono text-data-value text-text-muted">
                      {row.key || (
                        <span className="text-text-faint">auto</span>
                      )}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <input
                      type="text"
                      value={row.label}
                      onChange={(e) => handleChange(i, "label", e.target.value)}
                      placeholder="e.g. API Key"
                      className="w-full rounded-control border border-border bg-bg-elevated px-2 py-1 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <select
                      value={row.type}
                      onChange={(e) =>
                        handleChange(
                          i,
                          "type",
                          e.target.value as "string" | "secret",
                        )
                      }
                      className="rounded-control border border-border bg-bg-elevated px-2 py-1 text-body-default text-text-primary focus:border-accent focus:outline-none"
                    >
                      <option value="string">String</option>
                      <option value="secret">Secret</option>
                    </select>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={row.sensitive}
                      onChange={(e) => handleChange(i, "sensitive", e.target.checked)}
                      className="accent-accent"
                    />
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => handleRemove(i)}
                      title="Remove credential"
                      className="flex h-6 w-6 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <button
        type="button"
        onClick={handleAdd}
        className="flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
      >
        <Plus size={13} />
        Add Credential Field
      </button>
    </div>
  );
}
