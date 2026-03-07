import type { BrowserContext } from "@playwright/test";

/**
 * Create a mock JWT token that the Next.js middleware can decode.
 * The middleware uses jwtDecode (client-side decode only, no signature verification),
 * so we just need a properly structured JWT with the right claims.
 */
function createMockJWT(claims: {
  sub: string;
  tenant_id: string;
  roles: string[];
  scope: "platform" | "tenant";
  plan: string;
  exp: number;
}): string {
  const header = { alg: "HS256", typ: "JWT" };
  const encode = (obj: object) =>
    Buffer.from(JSON.stringify(obj)).toString("base64url");

  return `${encode(header)}.${encode(claims)}.mock-signature`;
}

/**
 * Inject a platform admin auth cookie into the browser context.
 * Token expires 24 hours from now.
 */
export async function injectPlatformAdminAuth(context: BrowserContext) {
  const token = createMockJWT({
    sub: "platform-admin-test-user",
    tenant_id: "platform",
    roles: ["platform_admin"],
    scope: "platform",
    plan: "enterprise",
    exp: Math.floor(Date.now() / 1000) + 86400,
  });

  await context.addCookies([
    {
      name: "access_token",
      value: token,
      domain: "localhost",
      path: "/",
    },
  ]);
}

/**
 * Inject a tenant admin auth cookie into the browser context.
 * Token expires 24 hours from now.
 */
export async function injectTenantAdminAuth(context: BrowserContext) {
  const token = createMockJWT({
    sub: "tenant-admin-test-user",
    tenant_id: "test-tenant-001",
    roles: ["tenant_admin"],
    scope: "tenant",
    plan: "professional",
    exp: Math.floor(Date.now() / 1000) + 86400,
  });

  await context.addCookies([
    {
      name: "access_token",
      value: token,
      domain: "localhost",
      path: "/",
    },
  ]);
}

/**
 * Inject an end-user auth cookie into the browser context.
 * Token expires 24 hours from now.
 */
export async function injectEndUserAuth(context: BrowserContext) {
  const token = createMockJWT({
    sub: "end-user-test-user",
    tenant_id: "test-tenant-001",
    roles: ["user"],
    scope: "tenant",
    plan: "professional",
    exp: Math.floor(Date.now() / 1000) + 86400,
  });

  await context.addCookies([
    {
      name: "access_token",
      value: token,
      domain: "localhost",
      path: "/",
    },
  ]);
}
