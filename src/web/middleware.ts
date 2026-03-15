import { NextRequest, NextResponse } from "next/server";
import { jwtDecode } from "jwt-decode";

interface JWTClaims {
  sub: string;
  tenant_id: string;
  roles: string[];
  scope: "platform" | "tenant";
  plan: string;
  exp: number;
}

function isExpired(claims: JWTClaims): boolean {
  return claims.exp * 1000 < Date.now();
}

export function middleware(request: NextRequest) {
  const token = request.cookies.get("access_token")?.value;

  // Allow login page without auth
  if (request.nextUrl.pathname === "/login") {
    if (token) {
      try {
        const claims = jwtDecode<JWTClaims>(token);
        if (!isExpired(claims)) {
          return NextResponse.redirect(new URL("/chat", request.url));
        }
      } catch {
        // Invalid token, allow login page
      }
    }
    return NextResponse.next();
  }

  // No token -> redirect to login
  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  let claims: JWTClaims;
  try {
    claims = jwtDecode<JWTClaims>(token);
  } catch {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (isExpired(claims)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Admin routes (/admin/*) are for Tenant Admins. Platform admins also allowed.
  if (request.nextUrl.pathname.startsWith("/admin")) {
    const isTenantAdmin =
      claims.scope === "tenant" && claims.roles.includes("tenant_admin");
    if (!isTenantAdmin && claims.scope !== "platform") {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  // Platform routes (/platform/*) require scope=platform
  if (request.nextUrl.pathname.startsWith("/platform")) {
    if (claims.scope !== "platform") {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  // Settings routes: block end users (viewers) from all settings except /settings/privacy
  if (
    request.nextUrl.pathname.startsWith("/settings") &&
    !request.nextUrl.pathname.startsWith("/settings/privacy")
  ) {
    const isEndUser =
      claims.scope === "tenant" && !claims.roles.includes("tenant_admin");
    if (isEndUser) {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  // Platform-only settings routes: require scope=platform
  const platformOnlyRoutes = [
    "/settings/tenants",
    "/settings/llm-profiles",
    "/settings/issue-queue",
  ];

  const isPlatformRoute = platformOnlyRoutes.some((route) =>
    request.nextUrl.pathname.startsWith(route),
  );

  if (isPlatformRoute) {
    if (claims.scope !== "platform") {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  // Tenant admin settings routes: require tenant_admin role
  const tenantAdminRoutes = [
    "/settings/workspace",
    "/settings/users",
    "/settings/knowledge-base",
    "/settings/glossary",
    "/settings/agents",
    "/settings/teams",
    "/settings/memory-policy",
    "/settings/analytics",
  ];

  const isAdminRoute = tenantAdminRoutes.some((route) =>
    request.nextUrl.pathname.startsWith(route),
  );

  if (isAdminRoute) {
    if (claims.scope !== "tenant" || !claims.roles.includes("tenant_admin")) {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/chat/:path*",
    "/admin/:path*",
    "/settings/:path*",
    "/platform/:path*",
    "/login",
  ],
};
