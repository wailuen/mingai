"use client";

import Link from "next/link";
import { AppShell } from "@/components/layout/AppShell";
import { BarChart3, DollarSign, AlertCircle, Zap } from "lucide-react";

const ANALYTICS_SECTIONS = [
  {
    title: "Cost Analytics",
    description: "LLM costs, infrastructure spend, gross margin per tenant.",
    href: "/platform/analytics/cost",
    icon: DollarSign,
  },
  {
    title: "Issue Analytics",
    description: "Cross-tenant issue trends, resolution rates, SLA adherence.",
    href: "/platform/analytics/issues",
    icon: AlertCircle,
  },
  {
    title: "Cache Analytics",
    description: "Semantic cache hit rates, cost savings, latency improvements.",
    href: "/platform/analytics/cache",
    icon: Zap,
  },
];

export default function PlatformAnalyticsPage() {
  return (
    <AppShell>
      <div className="px-8 py-7">
        <div className="mb-6">
          <div className="flex items-center gap-2.5 mb-1">
            <BarChart3 size={18} className="text-accent" />
            <h1 className="text-page-title text-text-primary">Analytics</h1>
          </div>
          <p className="text-sm text-text-muted">
            Platform-wide intelligence across all tenants.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {ANALYTICS_SECTIONS.map((section) => {
            const Icon = section.icon;
            return (
              <Link
                key={section.href}
                href={section.href}
                className="block rounded-card border border-border bg-bg-surface p-5 transition-colors hover:border-accent-ring hover:bg-bg-elevated"
              >
                <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-control bg-accent-dim">
                  <Icon size={16} className="text-accent" />
                </div>
                <h2 className="mb-1 text-section-heading text-text-primary">
                  {section.title}
                </h2>
                <p className="text-sm text-text-muted">{section.description}</p>
              </Link>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
