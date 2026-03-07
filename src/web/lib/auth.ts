import { jwtDecode } from "jwt-decode";

export interface JWTClaims {
  sub: string;
  tenant_id: string;
  roles: string[];
  scope: "platform" | "tenant";
  plan: string;
  email?: string;
  exp: number;
}

/**
 * Read access token from cookie.
 *
 * Phase 1: stored in a regular cookie for client-side access.
 * Phase 2 (Auth0): switch to httpOnly cookies sent automatically by browser.
 * Tokens are NEVER stored in localStorage (XSS risk).
 */
export function getStoredToken(): string | null {
  if (typeof document === "undefined") return null;
  return (() => {
    const row = document.cookie
      .split("; ")
      .find((r) => r.startsWith("access_token="));
    if (!row) return null;
    // Use substring to preserve any '=' padding characters in the JWT value
    return row.substring("access_token=".length);
  })();
}

export function decodeToken(token: string): JWTClaims {
  return jwtDecode<JWTClaims>(token);
}

export function isTokenExpired(token: string): boolean {
  try {
    const claims = decodeToken(token);
    return claims.exp * 1000 < Date.now();
  } catch {
    return true;
  }
}

export function setTokenCookie(token: string): void {
  if (typeof document === "undefined") return;
  const claims = decodeToken(token);
  const expires = new Date(claims.exp * 1000);
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `access_token=${token}; path=/; expires=${expires.toUTCString()}; SameSite=Lax${secure}`;
}

export function clearTokenCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie =
    "access_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
}

export function hasRole(claims: JWTClaims, role: string): boolean {
  return claims.roles.includes(role);
}

export function isPlatformAdmin(claims: JWTClaims): boolean {
  return claims.scope === "platform";
}

export function isTenantAdmin(claims: JWTClaims): boolean {
  return claims.scope === "tenant" && hasRole(claims, "tenant_admin");
}
