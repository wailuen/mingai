import { type BrowserContext } from "@playwright/test";

/**
 * Build a minimal JWT (header.payload.signature) that the Next.js middleware
 * can decode with jwt-decode (which does NOT verify signatures).
 *
 * This lets us pass middleware auth checks without a running auth server.
 */
function buildTestJWT(claims: Record<string, unknown>): string {
  const header = { alg: "none", typ: "JWT" };
  const encode = (obj: unknown): string =>
    Buffer.from(JSON.stringify(obj)).toString("base64url");
  return `${encode(header)}.${encode(claims)}.test-signature`;
}

interface InjectAuthOptions {
  /** JWT sub (user id). Default: "test-user-001" */
  sub?: string;
  /** Tenant id. Default: "tenant-001" */
  tenantId?: string;
  /** User roles. Default: ["user"] */
  roles?: string[];
  /** Scope: "tenant" or "platform". Default: "tenant" */
  scope?: "tenant" | "platform";
  /** Plan name. Default: "enterprise" */
  plan?: string;
  /** Email claim for display name derivation. Default: "testuser@mingai.test" */
  email?: string;
}

/**
 * Inject a test access_token cookie into the browser context.
 * The JWT is unsigned but structurally valid for jwt-decode.
 */
export async function injectAuth(
  context: BrowserContext,
  options: InjectAuthOptions = {},
): Promise<void> {
  const {
    sub = "test-user-001",
    tenantId = "tenant-001",
    roles = ["user"],
    scope = "tenant",
    plan = "enterprise",
    email = "testuser@mingai.test",
  } = options;

  const token = buildTestJWT({
    sub,
    tenant_id: tenantId,
    roles,
    scope,
    plan,
    email,
    exp: Math.floor(Date.now() / 1000) + 3600, // 1 hour from now
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
 * Inject a tenant admin access_token cookie.
 */
export async function injectTenantAdmin(
  context: BrowserContext,
): Promise<void> {
  await injectAuth(context, {
    sub: "admin-user-001",
    roles: ["tenant_admin"],
    scope: "tenant",
    email: "admin@mingai.test",
  });
}

/**
 * Inject a platform admin access_token cookie.
 */
export async function injectPlatformAdmin(
  context: BrowserContext,
): Promise<void> {
  await injectAuth(context, {
    sub: "platform-admin-001",
    roles: ["platform_admin"],
    scope: "platform",
    email: "platform@mingai.test",
  });
}
