"use client";

import { useState, useEffect } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCreateTerm,
  useUpdateTerm,
  type GlossaryTerm,
  type CreateTermPayload,
  type UpdateTermPayload,
} from "@/lib/hooks/useGlossary";

interface TermFormProps {
  term: GlossaryTerm | null;
  onClose: () => void;
}

const MAX_DEFINITION_LENGTH = 200;
const WARN_THRESHOLD = 180;

export function TermForm({ term, onClose }: TermFormProps) {
  const isEdit = term !== null;

  const [termValue, setTermValue] = useState(term?.term ?? "");
  const [fullForm, setFullForm] = useState(term?.full_form ?? "");
  const [definition, setDefinition] = useState(term?.definition ?? "");
  const [aliasInput, setAliasInput] = useState("");
  const [aliases, setAliases] = useState<string[]>(term?.aliases ?? []);
  const [error, setError] = useState("");

  const createMutation = useCreateTerm();
  const updateMutation = useUpdateTerm();
  const isPending = createMutation.isPending || updateMutation.isPending;

  useEffect(() => {
    if (term) {
      setTermValue(term.term);
      setFullForm(term.full_form ?? "");
      setDefinition(term.definition);
      setAliases(term.aliases ?? []);
    }
  }, [term]);

  function handleAliasKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const value = aliasInput.trim().replace(/,$/g, "");
      if (value && !aliases.includes(value)) {
        setAliases((prev) => [...prev, value]);
      }
      setAliasInput("");
    }
  }

  function removeAlias(alias: string) {
    setAliases((prev) => prev.filter((a) => a !== alias));
  }

  function handleDefinitionChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    if (val.length <= MAX_DEFINITION_LENGTH) {
      setDefinition(val);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!termValue.trim()) {
      setError("Term is required");
      return;
    }
    if (!definition.trim()) {
      setError("Definition is required");
      return;
    }

    const payload: CreateTermPayload = {
      term: termValue.trim(),
      definition: definition.trim(),
    };
    if (fullForm.trim()) {
      payload.full_form = fullForm.trim();
    }
    if (aliases.length > 0) {
      payload.aliases = aliases;
    }

    try {
      if (isEdit && term) {
        const updatePayload: UpdateTermPayload = { ...payload };
        await updateMutation.mutateAsync({
          id: term.id,
          payload: updatePayload,
        });
      } else {
        await createMutation.mutateAsync(payload);
      }
      onClose();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Failed to save term");
      }
    }
  }

  const defLength = definition.length;
  const charCountColor =
    defLength >= MAX_DEFINITION_LENGTH
      ? "text-alert"
      : defLength >= WARN_THRESHOLD
        ? "text-warn"
        : "text-text-faint";

  const canSubmit =
    termValue.trim().length > 0 &&
    definition.trim().length > 0 &&
    defLength <= MAX_DEFINITION_LENGTH &&
    !isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70">
      <div className="w-full max-w-lg rounded-card border border-border bg-bg-surface">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-section-heading text-text-primary">
            {isEdit ? "Edit Term" : "Add Term"}
          </h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-control text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-sm text-alert">
              {error}
            </div>
          )}

          {/* Term */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Term <span className="text-alert">*</span>
            </label>
            <input
              type="text"
              value={termValue}
              onChange={(e) => setTermValue(e.target.value.slice(0, 100))}
              maxLength={100}
              placeholder="e.g. API"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Full Form */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Full Form
            </label>
            <input
              type="text"
              value={fullForm}
              onChange={(e) => setFullForm(e.target.value)}
              placeholder="e.g. Application Programming Interface"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {/* Definition */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Definition <span className="text-alert">*</span>
            </label>
            <textarea
              value={definition}
              onChange={handleDefinitionChange}
              placeholder="Provide a clear definition for the AI to use..."
              rows={3}
              className="w-full resize-none rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none"
            />
            <div className="mt-1 flex justify-end">
              <span className={cn("font-mono text-xs", charCountColor)}>
                {defLength}/{MAX_DEFINITION_LENGTH}
              </span>
            </div>
          </div>

          {/* Aliases */}
          <div>
            <label className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint">
              Aliases
            </label>
            <div className="flex flex-wrap gap-1.5 rounded-control border border-border bg-bg-elevated px-2 py-1.5">
              {aliases.map((alias) => (
                <span
                  key={alias}
                  className="flex items-center gap-1 rounded-badge border border-border bg-bg-surface px-2 py-0.5 text-xs text-text-muted"
                >
                  {alias}
                  <button
                    type="button"
                    onClick={() => removeAlias(alias)}
                    className="ml-0.5 text-text-faint transition-colors hover:text-alert"
                  >
                    <X size={10} />
                  </button>
                </span>
              ))}
              <input
                type="text"
                value={aliasInput}
                onChange={(e) => setAliasInput(e.target.value)}
                onKeyDown={handleAliasKeyDown}
                placeholder={
                  aliases.length === 0 ? "Type and press Enter or comma..." : ""
                }
                className="min-w-[120px] flex-1 border-none bg-transparent py-0.5 text-sm text-text-primary placeholder:text-text-faint focus:outline-none"
              />
            </div>
            <p className="mt-1 text-xs text-text-faint">
              Press Enter or comma to add an alias
            </p>
          </div>
        </form>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-control border border-border px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-bg-elevated"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="rounded-control bg-accent px-4 py-1.5 text-sm font-semibold text-bg-base transition-opacity disabled:opacity-30"
          >
            {isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
