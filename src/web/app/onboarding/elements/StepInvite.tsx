"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { apiPost } from "@/lib/api";

interface StepInviteProps {
  onNext: () => void;
  onBack: () => void;
  onSkip?: () => void;
}

export function StepInvite({ onNext, onBack, onSkip }: StepInviteProps) {
  const [email, setEmail] = useState("");
  const [sentEmails, setSentEmails] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const canSend = emailRegex.test(email.trim()) && !sending;

  async function handleSendInvite() {
    const trimmed = email.trim();
    if (!emailRegex.test(trimmed)) return;

    setSending(true);
    setErrorMsg("");
    try {
      await apiPost("/api/v1/users/invite", {
        email: trimmed,
        role: "user",
      });
      setSentEmails((prev) => [...prev, trimmed]);
      setEmail("");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to send invite");
    } finally {
      setSending(false);
    }
  }

  function handleRemoveChip(emailToRemove: string) {
    setSentEmails((prev) => prev.filter((e) => e !== emailToRemove));
  }

  return (
    <div className="space-y-6 py-4">
      <div>
        <h2 className="text-section-heading text-text-primary">
          Invite Team Members
        </h2>
        <p className="mt-1 text-body-default text-text-muted">
          Bring your colleagues on board. You can always invite more people
          later.
        </p>
      </div>

      {/* Email input + send */}
      <div className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canSend) handleSendInvite();
          }}
          placeholder="colleague@company.com"
          className="flex-1 rounded-control border border-border bg-bg-elevated px-3 py-2 text-body-default text-text-primary placeholder:text-text-faint focus:border-accent focus:outline-none"
        />
        <button
          onClick={handleSendInvite}
          disabled={!canSend}
          className="inline-flex items-center gap-1.5 rounded-control bg-accent px-4 py-2 text-body-default font-semibold text-bg-base transition-opacity disabled:opacity-30"
        >
          {sending && <Loader2 size={12} className="animate-spin" />}
          Send Invite
        </button>
      </div>

      {errorMsg && <p className="text-xs text-alert">{errorMsg}</p>}

      {/* Sent invites as chips */}
      {sentEmails.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {sentEmails.map((sentEmail) => (
            <span
              key={sentEmail}
              className="inline-flex items-center gap-1.5 rounded-control bg-accent-dim px-2.5 py-1 text-xs text-accent"
            >
              <span className="font-mono">{sentEmail}</span>
              <button
                onClick={() => handleRemoveChip(sentEmail)}
                className="text-accent/60 transition-colors hover:text-accent"
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex justify-between pt-2">
        <button
          onClick={onBack}
          className="rounded-control border border-border px-3 py-1.5 text-body-default text-text-muted transition-colors hover:bg-bg-elevated"
        >
          Back
        </button>
        <div className="flex items-center gap-3">
          <button
            onClick={onSkip ?? onNext}
            className="text-body-default text-text-faint transition-colors hover:text-text-muted"
          >
            Skip
          </button>
          <button
            onClick={onNext}
            className="rounded-control bg-accent px-4 py-1.5 text-body-default font-semibold text-bg-base transition-opacity hover:opacity-90"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
