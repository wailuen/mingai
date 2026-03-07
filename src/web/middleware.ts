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

  // Platform admin routes: require scope=platform
  if (request.nextUrl.pathname.startsWith("/admin")) {
    if (claims.scope !== "platform") {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
  }

  // Tenant admin settings routes: require tenant_admin role
  const adminSettingsRoutes = [
    "/settings/workspace",
    "/settings/users",
    "/settings/knowledge-base",
    "/settings/glossary",
    "/settings/agents",
    "/settings/teams",
    "/settings/memory-policy",
    "/settings/analytics",
  ];

  const isAdminRoute = adminSettingsRoutes.some((route) =>
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
  matcher: ["/chat/:path*", "/admin/:path*", "/settings/:path*", "/login"],
};
