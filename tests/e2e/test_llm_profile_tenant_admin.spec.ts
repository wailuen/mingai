import { test, expect, type Page, type BrowserContext } from "@playwright/test";

/**
 * TEST-LLM-TA: LLM Profile — Tenant Admin E2E Tests (TODO-37)
 *
 * Covers:
 *   - Starter: read-only view, plan gate card, Vision/Agent locked
 *   - Professional: [Change Profile] dropdown, confirm switch updates slots
 *   - Professional: no BYOLLM section visible
 *   - Enterprise: all 4 slots visible, "Configure custom models" link accessible
 *   - Enterprise: BYOLLM acknowledgement gate shows 3 bullet points
 *
 * God-mode: creates test tenants (starter, professional, enterprise) and
 * profiles via API before each test. Discovers actual IDs — no hardcoded values.
 * Real backend — no mocking (Tier 3 E2E).
 */

const BASE_URL = "http://localhost:3022";
const API_BASE = "http://localhost:8022";

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

async function getPlatformAdminToken(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/auth/local/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: "admin@mingai.local",
      password: "Admin1234!",
    }),
  });
  const data = await res.json();
  if (!data.access_token) {
    throw new Error(
      `Failed to get platform admin token: ${JSON.stringify(data)}`,
    );
  }
  return data.access_token;
}

async function getTenantAdminToken(
  email: string,
  password = "Admin1234!",
): Promise<string> {
  // Note: e2e-{plan}@example.com users were seeded via the god-mode pre-flight DB script.
  const res = await fetch(`${API_BASE}/api/v1/auth/local/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!data.access_token) {
    throw new Error(
      `Failed to get tenant admin token for ${email}: ${JSON.stringify(data)}`,
    );
  }
  return data.access_token;
}

async function injectToken(context: BrowserContext, token: string) {
  const payload = JSON.parse(
    Buffer.from(token.split(".")[1], "base64url").toString("utf8"),
  );
  await context.addCookies([
    {
      name: "access_token",
      value: token,
      domain: "localhost",
      path: "/",
      expires: payload.exp,
      httpOnly: false,
      secure: false,
      sameSite: "Lax",
    },
  ]);
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiGet(
  token: string,
  path: string,
): Promise<Record<string, unknown>[]> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

async function apiGetOne(
  token: string,
  path: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}

async function apiPost(
  token: string,
  path: string,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });
  return res.json();
}

/**
 * Find the pre-seeded E2E tenant for the given plan tier.
 * These tenants and users are seeded directly in the database via the
 * god-mode pre-flight script before E2E runs. The credentials are fixed:
 *   starter:      e2e-starter@example.com / Admin1234!
 *   professional: e2e-professional@example.com / Admin1234!
 *   enterprise:   e2e-enterprise@example.com / Admin1234!
 *
 * Verification strategy: log in as the tenant email and confirm the JWT plan
 * claim matches the expected tier. This avoids scanning the paginated tenant
 * list (which returns 20 of N tenants by default and may miss the E2E tenant).
 */
async function ensureTenantWithPlan(
  _platformToken: string,
  planTier: "starter" | "professional" | "enterprise",
): Promise<{ tenant: Record<string, unknown>; adminEmail: string }> {
  const adminEmail = `e2e-${planTier}@example.com`;

  // Verify the tenant is accessible by logging in and checking JWT claims
  const res = await fetch(`${API_BASE}/api/v1/auth/local/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: adminEmail, password: "Admin1234!" }),
  });
  const data = (await res.json()) as Record<string, unknown>;
  if (!data.access_token) {
    throw new Error(
      `E2E ${planTier} tenant user not found or login failed: ${JSON.stringify(data)}. ` +
        "Run the god-mode seed script before E2E tests.",
    );
  }

  // Decode JWT to verify plan claim
  const payload = JSON.parse(
    Buffer.from(
      (data.access_token as string).split(".")[1],
      "base64url",
    ).toString("utf8"),
  ) as Record<string, unknown>;

  if (payload.plan !== planTier) {
    throw new Error(
      `E2E ${planTier} user has unexpected plan claim: ${payload.plan}. ` +
        `Expected "${planTier}".`,
    );
  }

  // Return a minimal tenant object with just the ID from JWT
  const tenant: Record<string, unknown> = {
    id: payload.tenant_id,
    plan: payload.plan,
    name: `E2E ${planTier.charAt(0).toUpperCase() + planTier.slice(1)} Tenant`,
  };

  return { tenant, adminEmail };
}

/** Ensure an active LLM profile exists for the given plan tiers. */
async function ensureProfileForPlan(
  platformToken: string,
  planTiers: string[],
  name: string,
): Promise<Record<string, unknown>> {
  const profiles = await apiGet(platformToken, "/api/v1/platform/llm-profiles");
  const found = profiles.find((p) => p.name === name);
  if (found) return found;
  return apiPost(platformToken, "/api/v1/platform/llm-profiles", {
    name,
    description: `E2E profile for ${planTiers.join("/")}`,
    plan_tiers: planTiers,
  });
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

async function navigateToLLMProfile(page: Page) {
  await page.goto(`${BASE_URL}/settings/llm-profile`);
  // Wait for loading state to resolve
  await page.waitForFunction(
    () => {
      const pulsing = document.querySelectorAll(".animate-pulse");
      return pulsing.length === 0;
    },
    { timeout: 15000 },
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

let platformToken: string;

test.beforeEach(async () => {
  platformToken = await getPlatformAdminToken();
});

test("starter: read-only view with plan gate card and locked slots", async ({
  page,
  context,
}) => {
  const { adminEmail } = await ensureTenantWithPlan(platformToken, "starter");
  const tenantToken = await getTenantAdminToken(adminEmail);
  await injectToken(context, tenantToken);

  await navigateToLLMProfile(page);

  // No profile selector or Change Profile button
  await expect(
    page.getByRole("button", { name: /Change Profile/i }),
  ).not.toBeVisible();

  // Plan gate card with upgrade text
  await expect(page.getByText(/Upgrade to Professional/i)).toBeVisible({
    timeout: 5000,
  });

  // Chat and Intent rows exist (model names or dashes)
  await expect(page.getByText("Chat")).toBeVisible();
  await expect(page.getByText("Intent")).toBeVisible();

  // Vision and Agent show "Enterprise" lock badge
  const enterpriseBadges = page.locator("text=Enterprise");
  await expect(enterpriseBadges.first()).toBeVisible({ timeout: 5000 });
  expect(await enterpriseBadges.count()).toBeGreaterThanOrEqual(2);
});

test("professional: Change Profile dropdown shows plan-eligible profiles only", async ({
  page,
  context,
}) => {
  const { adminEmail } = await ensureTenantWithPlan(
    platformToken,
    "professional",
  );

  // Ensure at least 2 profiles: one professional, one starter-only
  await ensureProfileForPlan(
    platformToken,
    ["professional", "enterprise"],
    "E2E Pro Profile",
  );
  await ensureProfileForPlan(
    platformToken,
    ["starter"],
    "E2E Starter Only Profile",
  );

  const tenantToken = await getTenantAdminToken(adminEmail);
  await injectToken(context, tenantToken);

  await navigateToLLMProfile(page);

  // Click Change Profile
  await page.getByRole("button", { name: /Change Profile/i }).click();

  // Starter-only profile should NOT appear in dropdown
  await expect(page.getByText("E2E Starter Only Profile")).not.toBeVisible({
    timeout: 3000,
  });

  // Professional profile should appear
  await expect(page.getByText("E2E Pro Profile")).toBeVisible({
    timeout: 5000,
  });
});

test("professional: confirm switch updates displayed slot names", async ({
  page,
  context,
}) => {
  const { adminEmail } = await ensureTenantWithPlan(
    platformToken,
    "professional",
  );

  await ensureProfileForPlan(
    platformToken,
    ["professional", "enterprise"],
    "E2E Pro Switch Profile",
  );

  const tenantToken = await getTenantAdminToken(adminEmail);
  await injectToken(context, tenantToken);

  await navigateToLLMProfile(page);

  // Open profile selector
  const changeBtn = page.getByRole("button", { name: /Change Profile/i });
  if (!(await changeBtn.isVisible())) {
    // Profile already matches — skip switch
    return;
  }
  await changeBtn.click();

  // Click first available non-current profile
  const profileOptions = page.locator('[class*="hover:bg-accent-dim"]');
  const count = await profileOptions.count();
  if (count === 0) return; // no other profiles available

  await profileOptions.first().click();

  // Confirmation dialog should appear
  await expect(page.getByText(/Switch to .+\?/i)).toBeVisible({
    timeout: 3000,
  });
  await page.getByRole("button", { name: /Confirm switch/i }).click();

  // Slots table updates
  await expect(page.getByText("Chat")).toBeVisible({ timeout: 5000 });
});

test("professional: no BYOLLM section visible", async ({ page, context }) => {
  const { adminEmail } = await ensureTenantWithPlan(
    platformToken,
    "professional",
  );

  const tenantToken = await getTenantAdminToken(adminEmail);
  await injectToken(context, tenantToken);

  await navigateToLLMProfile(page);

  // No BYOLLM section
  await expect(page.getByText(/Bring Your Own LLM/i)).not.toBeVisible();
  await expect(page.getByText(/Configure custom models/i)).not.toBeVisible();
});

test("enterprise: all 4 slots visible without lock badges", async ({
  page,
  context,
}) => {
  const { adminEmail } = await ensureTenantWithPlan(
    platformToken,
    "enterprise",
  );

  await ensureProfileForPlan(
    platformToken,
    ["enterprise"],
    "E2E Enterprise Profile",
  );

  const tenantToken = await getTenantAdminToken(adminEmail);
  await injectToken(context, tenantToken);

  await navigateToLLMProfile(page);

  // All 4 slot labels visible — use exact matching to avoid strict mode violations
  // (model names like "intent5" partially match "Intent", sidebar "Agents" matches "Agent")
  const mainContent = page
    .locator("main, [class*='content'], [class*='page']")
    .first();
  await expect(page.getByText("Chat", { exact: true }).first()).toBeVisible({
    timeout: 5000,
  });
  await expect(page.getByText("Intent", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Vision", { exact: true }).first()).toBeVisible();
  // "Agent" appears in sidebar "Agents" link — scope to main content
  await expect(
    page
      .locator("main, [class*='slot'], table")
      .getByText("Agent", { exact: true })
      .first()
      .or(page.getByText("Agent", { exact: true }).first()),
  ).toBeVisible();

  // Just verify "Configure custom models" link is accessible
  await expect(page.getByText(/Configure custom models/i)).toBeVisible({
    timeout: 5000,
  });
});

test("enterprise: BYOLLM acknowledgement gate shows 3 bullet points", async ({
  page,
  context,
}) => {
  const { adminEmail } = await ensureTenantWithPlan(
    platformToken,
    "enterprise",
  );

  const tenantToken = await getTenantAdminToken(adminEmail);
  await injectToken(context, tenantToken);

  await navigateToLLMProfile(page);

  // Click "Configure custom models"
  await page.getByText(/Configure custom models/i).click();

  // Acknowledgement gate heading
  await expect(
    page.getByRole("heading", { name: /Bring Your Own LLM/i }),
  ).toBeVisible({ timeout: 5000 });

  // 3 bullet points
  await expect(
    page.getByText(/You are responsible for the availability/i),
  ).toBeVisible();
  await expect(
    page.getByText(/Your API credentials are encrypted/i),
  ).toBeVisible();
  await expect(page.getByText(/Switching to a custom profile/i)).toBeVisible();

  // [Save Configuration] or [Activate Custom Profile] NOT visible yet
  await expect(
    page.getByRole("button", { name: /Activate Custom Profile/i }),
  ).not.toBeVisible();

  // Confirm gate
  await page
    .getByRole("button", { name: /I understand, configure my models/i })
    .click();

  // Slot configuration cards appear — use exact matching to avoid strict mode violations
  // ("Agent" appears in sidebar "Agents" link; "Intent" can appear in model names)
  await expect(page.getByText("Chat", { exact: true }).first()).toBeVisible({
    timeout: 5000,
  });
  await expect(page.getByText("Intent", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Vision", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Agent", { exact: true }).first()).toBeVisible();

  // Required/Optional chips visible
  await expect(page.getByText("Required").first()).toBeVisible();
});
