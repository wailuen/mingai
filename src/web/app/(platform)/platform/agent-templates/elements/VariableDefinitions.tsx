"use client";

import { Plus, Trash2 } from "lucide-react";
import type { AgentTemplateVariable } from "@/lib/hooks/useAgentTemplatesAdmin";

interface VariableDefinitionsProps {
  variables: AgentTemplateVariable[];
  onChange: (variables: AgentTemplateVariable[]) => void;
}

const TYPE_OPTIONS: { value: AgentTemplateVariable["type"]; label: string }[] =
  [
    { value: "string", label: "String" },
    { value: "number", label: "Number" },
    { value: "boolean", label: "Boolean" },
  ];

export function VariableDefinitions({
  variables,
  onChange,
}: VariableDefinitionsProps) {
  function handleAdd() {
    onChange([
      ...variables,
      { name: "", type: "string", label: "", required: false },
    ]);
  }

  function handleRemove(index: number) {
    onChange(variables.filter((_, i) => i !== index));
  }

  function handleUpdate(
    index: number,
    field: keyof AgentTemplateVariable,
    value: string | boolean,
  ) {
    const updated = variables.map((v, i) =>
      i === index ? { ...v, [field]: value } : v,
    );
    onChange(updated);
  }

  return (
    <div>
      <label className="mb-2 block text-[11px] uppercase tracking-wider text-text-faint">
        Variable Definitions
      </label>

      {variables.length > 0 && (
        <div className="mb-2 space-y-2">
          {variables.map((variable, index) => (
            <div
              key={index}
              className="flex items-start gap-2 rounded-control border border-border bg-bg-elevated p-2"
            >
              <div className="flex flex-1 flex-wrap items-center gap-2">
                <input
                  type="text"
                  value={variable.name}
                  onChange={(e) => handleUpdate(index, "name", e.target.value)}
                  placeholder="variable_name"
                  className="w-28 rounded-control border border-border bg-bg-base px-2 py-1 font-mono text-xs text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />

                <input
                  type="text"
                  value={variable.label}
                  onChange={(e) => handleUpdate(index, "label", e.target.value)}
                  placeholder="Display label"
                  className="w-32 rounded-control border border-border bg-bg-base px-2 py-1 text-xs text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
                />

                <select
                  value={variable.type}
                  onChange={(e) => handleUpdate(index, "type", e.target.value)}
                  className="rounded-control border border-border bg-bg-base px-2 py-1 text-xs text-text-primary focus:border-accent focus:outline-none"
                >
                  {TYPE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>

                <label className="flex items-center gap-1 text-xs text-text-muted">
                  <input
                    type="checkbox"
                    checked={variable.required}
                    onChange={(e) =>
                      handleUpdate(index, "required", e.target.checked)
                    }
                    className="accent-accent"
                  />
                  Required
                </label>
              </div>

              <button
                type="button"
                onClick={() => handleRemove(index)}
                className="mt-1 flex h-6 w-6 items-center justify-center rounded-control text-text-faint transition-colors hover:bg-alert-dim hover:text-alert"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={handleAdd}
        className="flex items-center gap-1 rounded-control border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
      >
        <Plus size={12} />
        Add Variable
      </button>
    </div>
  );
}
