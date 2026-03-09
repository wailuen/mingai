"use client";

import { AppShell } from "@/components/layout/AppShell";

export default function AgentsPage() {
  return (
    <AppShell>
      <div className="flex flex-col gap-6 p-8">
        <h1 className="text-2xl font-bold text-text-primary">Agents</h1>
        <p className="text-text-muted">
          Agent management is coming in a future phase.
        </p>
      </div>
    </AppShell>
  );
}
