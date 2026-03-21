"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { usePublishToRegistry } from "@/lib/hooks/useRegistry";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Static option lists
// ---------------------------------------------------------------------------

const INDUSTRY_OPTIONS = [
  "Finance",
  "Healthcare",
  "Legal",
  "HR",
  "Procurement",
  "Logistics",
  "Insurance",
  "Real Estate",
  "Retail",
  "Technology",
];

const TRANSACTION_TYPE_OPTIONS = [
  "Invoice",
  "Contract",
  "Onboarding",
  "Compliance",
  "Payment",
  "Report",
  "Approval",
  "Audit",
];

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "zh", label: "Chinese" },
  { value: "ms", label: "Malay" },
  { value: "ta", label: "Tamil" },
  { value: "id", label: "Indonesian" },
  { value: "th", label: "Thai" },
  { value: "vi", label: "Vietnamese" },
  { value: "ja", label: "Japanese" },
  { value: "ko", label: "Korean" },
];

// ---------------------------------------------------------------------------
// Multi-select chip group
// ---------------------------------------------------------------------------

interface ChipGroupProps {
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
  label: string;
}

function ChipGroup({ options, selected, onToggle, label }: ChipGroupProps) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-text-muted">
        {label}
      </label>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = selected.includes(opt);
          return (
            <button
              key={opt}
              type="button"
              onClick={() => onToggle(opt)}
              className={cn(
                "rounded-control border px-2.5 py-1 text-xs font-medium transition-colors",
                active
                  ? "border-accent bg-accent-dim text-accent"
                  : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
              )}
            >
              {opt}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

interface PublishToRegistryModalProps {
  agentId: string;
  agentName: string;
  agentDescription: string;
  onClose: () => void;
  onPublished: () => void;
}

export function PublishToRegistryModal({
  agentId: _agentId,
  agentName,
  agentDescription,
  onClose,
  onPublished,
}: PublishToRegistryModalProps) {
  const [a2aEndpoint, setA2aEndpoint] = useState("");
  const [healthCheckUrl, setHealthCheckUrl] = useState("");
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);
  const [selectedTxTypes, setSelectedTxTypes] = useState<string[]>([]);
  const [selectedLanguages, setSelectedLanguages] = useState<string[]>(["en"]);
  const [error, setError] = useState<string | null>(null);

  const publishMutation = usePublishToRegistry();

  function toggleItem(
    list: string[],
    setter: React.Dispatch<React.SetStateAction<string[]>>,
    value: string,
  ) {
    setter(
      list.includes(value) ? list.filter((v) => v !== value) : [...list, value],
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!a2aEndpoint.trim()) {
      setError("A2A endpoint is required.");
      return;
    }
    if (selectedTxTypes.length === 0) {
      setError("Select at least one transaction type.");
      return;
    }
    if (selectedIndustries.length === 0) {
      setError("Select at least one industry.");
      return;
    }

    publishMutation.mutate(
      {
        name: agentName,
        description: agentDescription,
        a2a_endpoint: a2aEndpoint.trim(),
        health_check_url: healthCheckUrl.trim() || undefined,
        transaction_types: selectedTxTypes,
        industries: selectedIndustries,
        languages: selectedLanguages,
      },
      {
        onSuccess: () => {
          onPublished();
          onClose();
        },
        onError: (err) => {
          setError(err.message ?? "Failed to publish agent.");
        },
      },
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg-deep/70 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-card border border-border bg-bg-surface"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-section-heading text-text-primary">
              Publish to Registry
            </h2>
            <p className="mt-0.5 text-xs text-text-faint">{agentName}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-control p-1 text-text-faint hover:bg-bg-elevated hover:text-text-primary"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <div className="space-y-5 px-5 py-5">
            {/* A2A endpoint */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-muted">
                A2A Endpoint <span className="text-alert">*</span>
              </label>
              <input
                type="url"
                value={a2aEndpoint}
                onChange={(e) => setA2aEndpoint(e.target.value)}
                placeholder="https://your-agent.example.com/a2a"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring"
              />
              <p className="mt-1 text-[11px] text-text-faint">
                The HTTPS endpoint that accepts A2A protocol requests.
              </p>
            </div>

            {/* Health check URL */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-muted">
                Health Check URL{" "}
                <span className="text-text-faint">(optional)</span>
              </label>
              <input
                type="url"
                value={healthCheckUrl}
                onChange={(e) => setHealthCheckUrl(e.target.value)}
                placeholder="https://your-agent.example.com/health"
                className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring"
              />
            </div>

            {/* Transaction types */}
            <ChipGroup
              label="Transaction Types *"
              options={TRANSACTION_TYPE_OPTIONS}
              selected={selectedTxTypes}
              onToggle={(v) =>
                toggleItem(selectedTxTypes, setSelectedTxTypes, v)
              }
            />

            {/* Industries */}
            <ChipGroup
              label="Industries *"
              options={INDUSTRY_OPTIONS}
              selected={selectedIndustries}
              onToggle={(v) =>
                toggleItem(selectedIndustries, setSelectedIndustries, v)
              }
            />

            {/* Languages */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-muted">
                Languages
              </label>
              <div className="flex flex-wrap gap-1.5">
                {LANGUAGE_OPTIONS.map(({ value, label }) => {
                  const active = selectedLanguages.includes(value);
                  return (
                    <button
                      key={value}
                      type="button"
                      onClick={() =>
                        toggleItem(
                          selectedLanguages,
                          setSelectedLanguages,
                          value,
                        )
                      }
                      className={cn(
                        "rounded-control border px-2.5 py-1 text-xs font-medium transition-colors",
                        active
                          ? "border-accent bg-accent-dim text-accent"
                          : "border-border bg-bg-elevated text-text-muted hover:border-accent-ring hover:text-text-primary",
                      )}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Error */}
            {error && (
              <p className="rounded-control border border-alert/30 bg-alert-dim px-3 py-2 text-xs text-alert">
                {error}
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-control border border-border px-4 py-2 text-xs font-medium text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={publishMutation.isPending}
              className="rounded-control border border-accent bg-accent-dim px-4 py-2 text-xs font-medium text-accent transition-colors hover:bg-accent/10 disabled:opacity-50"
            >
              {publishMutation.isPending
                ? "Publishing..."
                : "Publish to Registry"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
