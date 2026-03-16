import { test, expect, Page } from "@playwright/test";

const BASE_URL = "http://localhost:3022";

// Test accounts
const PLATFORM_ADMIN = { email: "admin@mingai.test", pass: "Admin1234!" };
const TENANT_ADMIN = {
  email: "tenant_admin@mingai.test",
  pass: "TenantAdmin1234!",
};
const END_USER = { email: "user@mingai.test", pass: "User1234!" };

async function login(page: Page, email: string, pass: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("networkidle");
  // Fill email
  const emailInput = page.locator('input[type="email"], input[name="email"]');
  if ((await emailInput.count()) > 0) {
    await emailInput.fill(email);
  }
  // Fill password
  const passInput = page.locator(
    'input[type="password"], input[name="password"]',
  );
  if ((await passInput.count()) > 0) {
    await passInput.fill(pass);
  }
  // Click submit
  const submitBtn = page.locator('button[type="submit"]');
  if ((await submitBtn.count()) > 0) {
    await submitBtn.click();
  }
  await page.waitForTimeout(2000);
  await page.waitForLoadState("networkidle");
}

// ===== END USER FLOWS =====
test.describe("End User Flows", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, END_USER.email, END_USER.pass);
  });

  test("EU-01: Login and landing page", async ({ page }) => {
    await page.screenshot({
      path: "playwright-report/eu-01-landing.png",
      fullPage: true,
    });
    // Should land on chat page, not admin
    const url = page.url();
    console.log(`[EU-01] Landed at: ${url}`);
    // Check for chat-related elements
    const body = await page.textContent("body");
    console.log(`[EU-01] Page content preview: ${body?.substring(0, 500)}`);
  });

  test("EU-02: Chat empty state", async ({ page }) => {
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/eu-02-chat-empty.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[EU-02] Chat page content: ${body?.substring(0, 500)}`);
  });

  test("EU-03: Send first message", async ({ page }) => {
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);

    // Find chat input
    const chatInput = page.locator(
      'textarea, input[placeholder*="Ask"], input[placeholder*="ask"], input[placeholder*="message"], input[placeholder*="Message"]',
    );
    if ((await chatInput.count()) > 0) {
      await chatInput.first().fill("What is our travel reimbursement policy?");
      // Find and click send button
      const sendBtn = page
        .locator(
          'button[aria-label*="send"], button[aria-label*="Send"], button:has(svg)',
        )
        .last();
      if ((await sendBtn.count()) > 0) {
        await sendBtn.click();
      } else {
        await chatInput.first().press("Enter");
      }
      await page.waitForTimeout(5000);
      await page.screenshot({
        path: "playwright-report/eu-03-first-message.png",
        fullPage: true,
      });
      const body = await page.textContent("body");
      console.log(`[EU-03] After send: ${body?.substring(0, 500)}`);
    } else {
      console.log("[EU-03] FAIL: No chat input found");
      await page.screenshot({
        path: "playwright-report/eu-03-no-input.png",
        fullPage: true,
      });
    }
  });

  test("EU-04: Conversation history sidebar", async ({ page }) => {
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    // Check for sidebar with history
    const sidebar = page.locator('[class*="sidebar"], nav, aside');
    await page.screenshot({
      path: "playwright-report/eu-04-sidebar.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[EU-04] Sidebar/history content: ${body?.substring(0, 500)}`);
  });

  test("EU-05: New conversation button", async ({ page }) => {
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    // Look for new chat button
    const newChatBtn = page.locator(
      'button:has-text("New"), button[aria-label*="New"], a:has-text("New Chat")',
    );
    const count = await newChatBtn.count();
    console.log(`[EU-05] New chat buttons found: ${count}`);
    if (count > 0) {
      await newChatBtn.first().click();
      await page.waitForTimeout(1000);
      await page.screenshot({
        path: "playwright-report/eu-05-new-chat.png",
        fullPage: true,
      });
    }
  });

  test("EU-06: Settings page (Profile/Privacy)", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/eu-06-settings.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[EU-06] Settings page: ${body?.substring(0, 500)}`);
  });

  test("EU-07: Privacy/Memory settings", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/privacy`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/eu-07-privacy.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[EU-07] Privacy page: ${body?.substring(0, 500)}`);
  });
});

// ===== TENANT ADMIN FLOWS =====
test.describe("Tenant Admin Flows", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
  });

  test("TA-01: Dashboard landing", async ({ page }) => {
    await page.screenshot({
      path: "playwright-report/ta-01-dashboard.png",
      fullPage: true,
    });
    const url = page.url();
    console.log(`[TA-01] Landed at: ${url}`);
    const body = await page.textContent("body");
    console.log(`[TA-01] Dashboard content: ${body?.substring(0, 500)}`);
  });

  test("TA-02: User management page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/users`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/ta-02-users.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[TA-02] Users page: ${body?.substring(0, 500)}`);
  });

  test("TA-03: Invite user modal", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/users`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    const inviteBtn = page.locator(
      'button:has-text("Invite"), button:has-text("invite"), button:has-text("Add User")',
    );
    const count = await inviteBtn.count();
    console.log(`[TA-03] Invite buttons found: ${count}`);
    if (count > 0) {
      await inviteBtn.first().click();
      await page.waitForTimeout(1000);
      await page.screenshot({
        path: "playwright-report/ta-03-invite-modal.png",
        fullPage: true,
      });
      const body = await page.textContent("body");
      console.log(`[TA-03] Invite modal: ${body?.substring(0, 500)}`);
    }
  });

  test("TA-04: Glossary page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/glossary`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/ta-04-glossary.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[TA-04] Glossary page: ${body?.substring(0, 500)}`);
  });

  test("TA-05: Add glossary term", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/glossary`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    const addBtn = page.locator(
      'button:has-text("Add"), button:has-text("add"), button:has-text("New Term")',
    );
    const count = await addBtn.count();
    console.log(`[TA-05] Add term buttons found: ${count}`);
    if (count > 0) {
      await addBtn.first().click();
      await page.waitForTimeout(1000);
      await page.screenshot({
        path: "playwright-report/ta-05-add-term.png",
        fullPage: true,
      });
    }
  });

  test("TA-06: Documents/SharePoint page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/documents`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/ta-06-documents.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[TA-06] Documents page: ${body?.substring(0, 500)}`);
  });

  test("TA-07: Documents/Google Drive page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/documents/google-drive`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/ta-07-google-drive.png",
      fullPage: true,
    });
    const url = page.url();
    const status = page.url().includes("404") ? "404" : "loaded";
    console.log(`[TA-07] Google Drive page status: ${status}, URL: ${url}`);
    const body = await page.textContent("body");
    console.log(`[TA-07] Google Drive content: ${body?.substring(0, 300)}`);
  });

  test("TA-08: Issues page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/issues`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/ta-08-issues.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[TA-08] Issues page: ${body?.substring(0, 500)}`);
  });

  test("TA-09: Agents page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/agents`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/ta-09-agents.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[TA-09] Agents page: ${body?.substring(0, 500)}`);
  });

  test("TA-10: Analytics page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/analytics`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/ta-10-analytics.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[TA-10] Analytics page: ${body?.substring(0, 500)}`);
  });
});

// ===== PLATFORM ADMIN FLOWS =====
test.describe("Platform Admin Flows", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
  });

  test("PA-01: Dashboard landing", async ({ page }) => {
    await page.screenshot({
      path: "playwright-report/pa-01-dashboard.png",
      fullPage: true,
    });
    const url = page.url();
    console.log(`[PA-01] Landed at: ${url}`);
    const body = await page.textContent("body");
    console.log(`[PA-01] Dashboard content: ${body?.substring(0, 500)}`);
  });

  test("PA-02: Tenants page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/tenants`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/pa-02-tenants.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[PA-02] Tenants page: ${body?.substring(0, 500)}`);
  });

  test("PA-03: Issue queue", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/issue-queue`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/pa-03-issue-queue.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[PA-03] Issue queue: ${body?.substring(0, 500)}`);
  });

  test("PA-04: LLM Profiles page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/llm-profiles`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/pa-04-llm-profiles.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[PA-04] LLM Profiles: ${body?.substring(0, 500)}`);
  });

  test("PA-05: Cost analytics page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/cost-analytics`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/pa-05-cost-analytics.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[PA-05] Cost analytics: ${body?.substring(0, 500)}`);
  });

  test("PA-06: Agent templates page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/agent-templates`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/pa-06-agent-templates.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[PA-06] Agent templates: ${body?.substring(0, 500)}`);
  });

  test("PA-07: Analytics page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/analytics`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/pa-07-analytics.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[PA-07] Analytics: ${body?.substring(0, 500)}`);
  });

  test("PA-08: Tool catalog page", async ({ page }) => {
    await page.goto(`${BASE_URL}/settings/tool-catalog`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);
    await page.screenshot({
      path: "playwright-report/pa-08-tool-catalog.png",
      fullPage: true,
    });
    const body = await page.textContent("body");
    console.log(`[PA-08] Tool catalog: ${body?.substring(0, 500)}`);
  });
});
