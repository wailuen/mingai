import { test, expect, Page } from "@playwright/test";

const BASE_URL = "http://localhost:3022";
const PLATFORM_ADMIN = { email: "admin@mingai.test", pass: "Admin1234!" };
const TENANT_ADMIN = {
  email: "tenant_admin@mingai.test",
  pass: "TenantAdmin1234!",
};
const END_USER = { email: "user@mingai.test", pass: "User1234!" };

async function login(page: Page, email: string, pass: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(1000);
  const emailInput = page.locator('input[type="email"], input[name="email"]');
  if ((await emailInput.count()) > 0) {
    await emailInput.fill(email);
  }
  const passInput = page.locator(
    'input[type="password"], input[name="password"]',
  );
  if ((await passInput.count()) > 0) {
    await passInput.fill(pass);
  }
  const submitBtn = page.locator('button[type="submit"]');
  if ((await submitBtn.count()) > 0) {
    await submitBtn.click();
  }
  await page.waitForTimeout(3000);
}

test.describe("Pass 2 - Correct Routes", () => {
  // ===== END USER =====
  test("EU-chat: End user chat page", async ({ page }) => {
    await login(page, END_USER.email, END_USER.pass);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-eu-chat.png",
      fullPage: true,
    });
  });

  test("EU-send: End user sends a message", async ({ page }) => {
    test.setTimeout(60000);
    await login(page, END_USER.email, END_USER.pass);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);

    const chatInput = page.locator("textarea").first();
    if ((await chatInput.count()) > 0) {
      await chatInput.fill("What is the annual leave policy?");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(10000);
    }
    await page.screenshot({
      path: "playwright-report/p2-eu-send-msg.png",
      fullPage: true,
    });
  });

  test("EU-privacy: End user privacy page", async ({ page }) => {
    await login(page, END_USER.email, END_USER.pass);
    await page.goto(`${BASE_URL}/settings/privacy`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-eu-privacy.png",
      fullPage: true,
    });
  });

  test("EU-memory: End user memory page", async ({ page }) => {
    await login(page, END_USER.email, END_USER.pass);
    await page.goto(`${BASE_URL}/settings/memory`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-eu-memory.png",
      fullPage: true,
    });
  });

  // ===== TENANT ADMIN =====
  test("TA-users: Tenant admin users page", async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/users`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-ta-users.png",
      fullPage: true,
    });
  });

  test("TA-glossary: Tenant admin glossary page", async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/glossary`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-ta-glossary.png",
      fullPage: true,
    });
  });

  test("TA-agents: Tenant admin agents page", async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/agents`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-ta-agents.png",
      fullPage: true,
    });
  });

  test("TA-eng-issues: Tenant admin engineering issues", async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/engineering-issues`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-ta-eng-issues.png",
      fullPage: true,
    });
  });

  test("TA-kb: Tenant admin knowledge base page", async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/knowledge-base`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-ta-kb.png",
      fullPage: true,
    });
  });

  test("TA-admin-analytics: Tenant admin analytics", async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
    await page.goto(`${BASE_URL}/admin/analytics`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-ta-analytics.png",
      fullPage: true,
    });
  });

  // ===== PLATFORM ADMIN =====
  test("PA-tenants: Platform admin tenants page", async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/tenants`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-pa-tenants.png",
      fullPage: true,
    });
  });

  test("PA-issue-queue: Platform admin issue queue", async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/issue-queue`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-pa-issue-queue.png",
      fullPage: true,
    });
  });

  test("PA-llm: Platform admin LLM profiles", async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/llm-profiles`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-pa-llm.png",
      fullPage: true,
    });
  });

  test("PA-cost: Platform admin cost analytics", async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
    await page.goto(`${BASE_URL}/settings/cost-analytics`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-pa-cost.png",
      fullPage: true,
    });
  });

  test("PA-platform-issues: Platform issues page", async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
    await page.goto(`${BASE_URL}/platform/issues`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-pa-platform-issues.png",
      fullPage: true,
    });
  });

  test("PA-platform-tenants: Platform tenants page", async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
    await page.goto(`${BASE_URL}/platform/tenants`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-pa-platform-tenants.png",
      fullPage: true,
    });
  });

  test("PA-platform-llm: Platform LLM profiles", async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
    await page.goto(`${BASE_URL}/platform/llm-profiles`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: "playwright-report/p2-pa-platform-llm.png",
      fullPage: true,
    });
  });
});
