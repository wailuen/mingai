"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const claims = await login({ email, password });
      if (claims.scope === "platform") {
        router.push("/admin/tenants");
      } else if (claims.roles.includes("tenant_admin")) {
        router.push("/settings/dashboard");
      } else {
        router.push("/chat");
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Login failed. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-base px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-card bg-accent text-lg font-bold text-bg-base">
            m
          </div>
          <h1 className="text-page-title text-text-primary">mingai</h1>
          <p className="mt-1 text-sm text-text-muted">
            Enterprise RAG Platform
          </p>
        </div>

        {/* Login form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="email"
              className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="sarah@acmecorp.com"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="mb-1.5 block text-label-nav uppercase tracking-wider text-text-faint"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              className="w-full rounded-control border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint transition-colors focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent-ring"
            />
          </div>

          {error && (
            <div className="rounded-control border border-alert-ring bg-alert-dim px-3 py-2 text-sm text-alert">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-control bg-accent px-4 py-2.5 text-sm font-semibold text-bg-base transition-colors hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-text-faint">
          Phase 1: Local JWT authentication
        </p>
      </div>
    </div>
  );
}
