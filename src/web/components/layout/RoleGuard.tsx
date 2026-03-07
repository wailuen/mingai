"use client";

import type { ReactNode } from "react";
import type { JWTClaims } from "@/lib/auth";

interface RoleGuardProps {
  claims: JWTClaims | null;
  allowedRoles?: string[];
  allowedScopes?: Array<"platform" | "tenant">;
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * Client-side role check wrapper.
 * Middleware handles hard redirects; this provides in-page gating.
 */
export function RoleGuard({
  claims,
  allowedRoles,
  allowedScopes,
  children,
  fallback,
}: RoleGuardProps) {
  if (!claims) {
    return fallback ?? null;
  }

  if (allowedScopes && !allowedScopes.includes(claims.scope)) {
    return (
      fallback ?? (
        <div className="flex h-full items-center justify-center p-6">
          <p className="text-sm text-text-muted">
            You do not have permission to view this page.
          </p>
        </div>
      )
    );
  }

  if (allowedRoles) {
    const hasRole = claims.roles.some((r) => allowedRoles.includes(r));
    if (!hasRole) {
      return (
        fallback ?? (
          <div className="flex h-full items-center justify-center p-6">
            <p className="text-sm text-text-muted">
              You do not have permission to view this page.
            </p>
          </div>
        )
      );
    }
  }

  return <>{children}</>;
}
