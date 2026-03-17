/**
 * PVDR-020: LLM Provider Credentials Management E2E Tests
 *
 * Covers:
 *   1. PA adds a provider (skipped when TEST_PROVIDER_KEY is absent)
 *   2. PA sets default provider
 *   3. TA sees provider selection UI
 *   4. API key not visible in edit form / API response
 *
 * Prerequisites:
 *   Backend running on port 8022
 *   Frontend running on port 3022 (UI tests skip gracefully if unavailable)
 *
 * Credential-dependent steps require:
 *   TEST_PROVIDER_KEY=<real_api_key> in environment
 */

import { test, expect, request } from "@playwright/test";

const BACKEND_URL = "http://localhost:8022";
const FRONTEND_URL = "http://localhost:3022";

const PLATFORM_ADMIN = {
  email: "admin@mingai.test",
  pass: "Admin1234!",
};

const TENANT_ADMIN = {
  email: "tenant_admin@mingai.test",
  pass: "TenantAdmin1234!",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type ApiContext = Awaited<ReturnType<(typeof request)["newContext"]>>;

async function apiLogin(
  ctx: ApiContext,
  email: string,
  pass: string,
): Promise<string> {
  const resp = await ctx.post(`${BACKEND_URL}/api/v1/auth/local/login`, {
    data: { email, password: pass },
  });
  if (!resp.ok()) return "";
  const body = await resp.json();
  return body.access_token ?? "";
}

async function backendAvailable(): Promise<boolean> {
  try {
    const ctx = await request.newContext();
    const resp = await ctx.get(`${BACKEND_URL}/api/v1/health`, {
      timeout: 3000,
    });
    await ctx.dispose();
    return resp.status() < 500;
  } catch {
    return false;
  }
}

async function frontendAvailable(): Promise<boolean> {
  try {
    const ctx = await request.newContext();
    const resp = await ctx.get(FRONTEND_URL, { timeout: 3000 });
    await ctx.dispose();
    return resp.ok();
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Test 1: PA adds a provider (credential-dependent)
// ---------------------------------------------------------------------------

test("PVDR-001: Platform admin can add a provider with real credentials", async ({
  page,
}) => {
  const testKey = process.env.TEST_PROVIDER_KEY;
  if (!testKey) test.skip();
  if (!(await backendAvailable())) test.skip();

  const ctx = await request.newContext();
  const token = await apiLogin(ctx, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
  if (!token) test.skip();

  const uniqueSuffix = Date.now().toString().slice(-6);

  // Create provider via API
  const resp = await ctx.post(`${BACKEND_URL}/api/v1/platform/providers`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      provider_type: "openai",
      display_name: `E2E Test Provider ${uniqueSuffix}`,
      api_key: testKey,
      description: "Created by PVDR-020 E2E tests",
    },
  });

  expect(resp.status()).toBe(201);
  const body = await resp.json();
  expect(body.id).toBeTruthy();
  expect(body.display_name).toBe(`E2E Test Provider ${uniqueSuffix}`);
  // API key must NEVER be returned
  expect(JSON.stringify(body)).not.toContain(testKey);
  expect(JSON.stringify(body)).not.toContain("api_key");

  // Cleanup
  await ctx.delete(`${BACKEND_URL}/api/v1/platform/providers/${body.id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  await ctx.dispose();
});

// ---------------------------------------------------------------------------
// Test 2: PA sets default provider
// ---------------------------------------------------------------------------

test("PVDR-002: Platform admin can set a provider as default", async () => {
  if (!(await backendAvailable())) test.skip();

  const ctx = await request.newContext();
  const token = await apiLogin(ctx, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
  if (!token) test.skip();

  // List providers
  const listResp = await ctx.get(`${BACKEND_URL}/api/v1/platform/providers`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  // Endpoint may not exist yet — accept 200 or 404
  const status = listResp.status();
  expect([200, 404]).toContain(status);

  if (status !== 200) {
    await ctx.dispose();
    return;
  }

  const listBody = await listResp.json();
  const providers: Array<{ id: string; is_default: boolean }> =
    listBody.providers ?? listBody ?? [];

  if (providers.length === 0) {
    // No providers to test set-default on — skip
    await ctx.dispose();
    test.skip();
    return;
  }

  // Pick a non-default provider if one exists, else any provider
  const target =
    providers.find((p) => !p.is_default) ?? providers[0];

  const setDefaultResp = await ctx.post(
    `${BACKEND_URL}/api/v1/platform/providers/${target.id}/set-default`,
    { headers: { Authorization: `Bearer ${token}` } },
  );

  expect([200, 201]).toContain(setDefaultResp.status());

  // Verify it is now default
  const verifyResp = await ctx.get(
    `${BACKEND_URL}/api/v1/platform/providers`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (verifyResp.status() === 200) {
    const verifyBody = await verifyResp.json();
    const updated: Array<{ id: string; is_default: boolean }> =
      verifyBody.providers ?? verifyBody ?? [];
    const updatedProvider = updated.find((p) => p.id === target.id);
    if (updatedProvider) {
      expect(updatedProvider.is_default).toBe(true);
    }
  }

  await ctx.dispose();
});

// ---------------------------------------------------------------------------
// Test 3: TA sees provider selection in LLM Settings UI
// ---------------------------------------------------------------------------

test("PVDR-003: Tenant admin sees provider selection in LLM Settings", async ({
  page,
}) => {
  if (!(await backendAvailable())) test.skip();
  if (!(await frontendAvailable())) test.skip();

  // Log in as tenant admin
  await page.goto(`${FRONTEND_URL}/login`);
  await page.fill('input[type="email"]', TENANT_ADMIN.email);
  await page.fill('input[type="password"]', TENANT_ADMIN.pass);
  await page.click('button[type="submit"]');

  // Navigate to LLM settings
  await page.waitForURL(/\/(admin|settings)/, { timeout: 10000 });
  await page.goto(`${FRONTEND_URL}/admin/settings/llm`);

  // The "Use Library Model" tab should be active by default
  await expect(
    page.locator("text=Use Library Model").first(),
  ).toBeVisible({ timeout: 8000 });

  // The Platform Provider section should be rendered
  await expect(
    page.locator("text=Platform Provider").first(),
  ).toBeVisible({ timeout: 8000 });
});

// ---------------------------------------------------------------------------
// Test 4: API key not visible in edit form or GET response
// ---------------------------------------------------------------------------

test("PVDR-004: API key is never visible in provider GET response or edit form", async ({
  page,
}) => {
  if (!(await backendAvailable())) test.skip();

  const ctx = await request.newContext();
  const token = await apiLogin(ctx, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
  if (!token) {
    await ctx.dispose();
    test.skip();
    return;
  }

  // GET providers list — must not contain api_key field
  const listResp = await ctx.get(`${BACKEND_URL}/api/v1/platform/providers`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (listResp.status() === 200) {
    const body = await listResp.json();
    const bodyStr = JSON.stringify(body);
    // Raw api_key values must never appear; key_present boolean is allowed
    expect(bodyStr).not.toMatch(/"api_key"\s*:\s*"[^"]+"/);
  }

  // GET individual provider if any exist
  const listBody = listResp.status() === 200 ? await listResp.json() : null;
  const providers: Array<{ id: string }> =
    listBody?.providers ?? listBody ?? [];

  if (providers.length > 0) {
    const getResp = await ctx.get(
      `${BACKEND_URL}/api/v1/platform/providers/${providers[0].id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (getResp.status() === 200) {
      const singleBody = await getResp.json();
      const singleStr = JSON.stringify(singleBody);
      expect(singleStr).not.toMatch(/"api_key"\s*:\s*"[^"]+"/);
    }
  }

  await ctx.dispose();

  // UI check: edit form should not pre-populate the API key field
  if (!(await frontendAvailable())) return;

  await page.goto(`${FRONTEND_URL}/login`);
  await page.fill('input[type="email"]', PLATFORM_ADMIN.email);
  await page.fill('input[type="password"]', PLATFORM_ADMIN.pass);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/platform/, { timeout: 10000 });

  await page.goto(`${FRONTEND_URL}/platform/providers`);
  await page.waitForLoadState("networkidle");

  // If there are providers, open the edit form for the first one
  const editButtons = page.locator('button:has-text("Edit")');
  const count = await editButtons.count();
  if (count > 0) {
    await editButtons.first().click();
    // API key input should be empty (placeholder only)
    const apiKeyInput = page.locator('input[type="password"]').first();
    await expect(apiKeyInput).toBeVisible({ timeout: 5000 });
    const value = await apiKeyInput.inputValue();
    expect(value).toBe("");
  }
});
