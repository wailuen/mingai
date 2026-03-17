import { test, expect, Page } from "@playwright/test";

const BASE_URL = "http://localhost:3022";
const SCREENSHOT_DIR = "playwright-report/red-team";

const PLATFORM_ADMIN = { email: "admin@mingai.test", pass: "Admin1234!" };
const TENANT_ADMIN = { email: "tenant_admin@mingai.test", pass: "TenantAdmin1234!" };
const END_USER = { email: "user@mingai.test", pass: "User1234!" };

test.use({ actionTimeout: 10000 });

async function login(page: Page, email: string, pass: string): Promise<string> {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);

  const emailInput = page.locator('input[type="email"], input[name="email"]');
  if ((await emailInput.count()) > 0) {
    await emailInput.fill(email);
  } else {
    return `FAIL: No email input found`;
  }

  const passInput = page.locator('input[type="password"], input[name="password"]');
  if ((await passInput.count()) > 0) {
    await passInput.fill(pass);
  } else {
    return `FAIL: No password input found`;
  }

  const submitBtn = page.locator('button[type="submit"]');
  if ((await submitBtn.count()) > 0) {
    await submitBtn.click();
  }

  await page.waitForTimeout(3000);
  return page.url();
}

async function getBodyText(page: Page): Promise<string> {
  try {
    const text = await page.innerText("body");
    return text || "";
  } catch {
    return "";
  }
}

async function ss(page: Page, name: string): Promise<void> {
  try {
    await page.screenshot({ path: `${SCREENSHOT_DIR}/${name}.png`, fullPage: true });
  } catch { /* ignore */ }
}

async function navTo(page: Page, path: string): Promise<void> {
  await page.goto(`${BASE_URL}${path}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
}

async function getNavItems(page: Page): Promise<string[]> {
  const items: string[] = [];
  const links = page.locator("nav a, aside a, [role='navigation'] a, [class*='sidebar'] a, [class*='Sidebar'] a, [class*='nav'] a");
  const count = await links.count();
  for (let i = 0; i < count && i < 40; i++) {
    try {
      const text = await links.nth(i).innerText();
      if (text?.trim()) items.push(text.trim());
    } catch { /* skip */ }
  }
  return items;
}

// ===================== END USER AUDIT =====================
test.describe("RED TEAM: End User", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, END_USER.email, END_USER.pass);
  });

  test("EU-01: Login and landing", async ({ page }) => {
    const url = page.url();
    console.log(`[EU-01] URL: ${url}`);
    await ss(page, "eu-01-landing");

    const body = await getBodyText(page);
    console.log(`[EU-01] Body (500): ${body.substring(0, 500)}`);

    expect(url).not.toContain("/admin");
  });

  test("EU-02: Chat empty state", async ({ page }) => {
    await navTo(page, "/chat");
    await ss(page, "eu-02-chat");

    const body = await getBodyText(page);
    console.log(`[EU-02] URL: ${page.url()}`);
    console.log(`[EU-02] Body (500): ${body.substring(0, 500)}`);

    const hasInput = (await page.locator("textarea").count()) > 0;
    console.log(`[EU-02] Has textarea: ${hasInput}`);
  });

  test("EU-03: Send message", async ({ page }) => {
    await navTo(page, "/chat");

    const textarea = page.locator("textarea").first();
    if ((await textarea.count()) > 0) {
      await textarea.fill("What is our travel policy?");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(5000);
      await ss(page, "eu-03-after-send");
      const body = await getBodyText(page);
      console.log(`[EU-03] After send (500): ${body.substring(0, 500)}`);
    } else {
      console.log("[EU-03] No textarea found");
    }
  });

  test("EU-04: Sidebar check", async ({ page }) => {
    await navTo(page, "/chat");
    const navItems = await getNavItems(page);
    console.log(`[EU-04] Nav items: ${JSON.stringify(navItems)}`);

    const body = await getBodyText(page);
    const hasHistory = body.includes("History") || body.includes("New Chat") || body.includes("New chat");
    console.log(`[EU-04] Has history: ${hasHistory}`);

    const hasAdminNav = navItems.some(item =>
      ["Dashboard", "Users", "Agents", "Documents", "Glossary", "Settings"].some(a => item.includes(a))
    );
    console.log(`[EU-04] Has admin nav (should be false): ${hasAdminNav}`);
    await ss(page, "eu-04-sidebar");
  });

  test("EU-05: Settings pages", async ({ page }) => {
    for (const path of ["/settings", "/settings/profile", "/profile"]) {
      await navTo(page, path);
      const url = page.url();
      if (!url.includes("/login")) {
        console.log(`[EU-05] Settings at: ${url}`);
        await ss(page, "eu-05-settings");
        const body = await getBodyText(page);
        console.log(`[EU-05] Body (300): ${body.substring(0, 300)}`);
        break;
      }
    }
  });

  test("EU-06: Privacy page", async ({ page }) => {
    await navTo(page, "/settings/privacy");
    await ss(page, "eu-06-privacy");
    console.log(`[EU-06] URL: ${page.url()}`);
    const body = await getBodyText(page);
    console.log(`[EU-06] Body (300): ${body.substring(0, 300)}`);
  });

  test("EU-07: Memory notes", async ({ page }) => {
    await navTo(page, "/settings/memory");
    await ss(page, "eu-07-memory");
    console.log(`[EU-07] URL: ${page.url()}`);
    const body = await getBodyText(page);
    console.log(`[EU-07] Body (300): ${body.substring(0, 300)}`);
  });
});

// ===================== TENANT ADMIN AUDIT =====================
test.describe("RED TEAM: Tenant Admin", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
  });

  test("TA-01: Login and dashboard", async ({ page }) => {
    const url = page.url();
    console.log(`[TA-01] URL: ${url}`);
    await ss(page, "ta-01-landing");
    const body = await getBodyText(page);
    console.log(`[TA-01] Body (500): ${body.substring(0, 500)}`);
    const navItems = await getNavItems(page);
    console.log(`[TA-01] Nav: ${JSON.stringify(navItems)}`);
  });

  test("TA-02: Dashboard KPIs", async ({ page }) => {
    await navTo(page, "/admin");
    await ss(page, "ta-02-dashboard");
    const body = await getBodyText(page);
    console.log(`[TA-02] URL: ${page.url()}`);
    console.log(`[TA-02] Body (600): ${body.substring(0, 600)}`);
  });

  test("TA-03: Users page", async ({ page }) => {
    await navTo(page, "/admin/users");
    await ss(page, "ta-03-users");
    const body = await getBodyText(page);
    console.log(`[TA-03] URL: ${page.url()}`);
    console.log(`[TA-03] Body (500): ${body.substring(0, 500)}`);
    const hasTable = (await page.locator("table").count()) > 0;
    console.log(`[TA-03] Has table: ${hasTable}`);
  });

  test("TA-04: Knowledge Base", async ({ page }) => {
    for (const p of ["/admin/knowledge-base", "/admin/documents", "/admin/kb"]) {
      await navTo(page, p);
      const url = page.url();
      if (!url.includes("/login")) {
        console.log(`[TA-04] KB at: ${url}`);
        await ss(page, "ta-04-kb");
        const body = await getBodyText(page);
        console.log(`[TA-04] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });

  test("TA-05: Agents page", async ({ page }) => {
    await navTo(page, "/admin/agents");
    await ss(page, "ta-05-agents");
    const body = await getBodyText(page);
    console.log(`[TA-05] URL: ${page.url()}`);
    console.log(`[TA-05] Body (500): ${body.substring(0, 500)}`);
  });

  test("TA-06: Glossary page", async ({ page }) => {
    for (const p of ["/admin/glossary", "/settings/glossary", "/admin/settings/glossary"]) {
      await navTo(page, p);
      const url = page.url();
      if (!url.includes("/login")) {
        console.log(`[TA-06] Glossary at: ${url}`);
        await ss(page, "ta-06-glossary");
        const body = await getBodyText(page);
        console.log(`[TA-06] Body (500): ${body.substring(0, 500)}`);
        const hasAddTerm = body.includes("Add Term") || body.includes("New Term");
        console.log(`[TA-06] Has Add Term: ${hasAddTerm}`);
        break;
      }
    }
  });

  test("TA-07: Glossary CRUD", async ({ page }) => {
    await navTo(page, "/admin/glossary");
    const addBtn = page.locator('button:has-text("Add Term"), button:has-text("New Term"), button:has-text("Add")').first();
    if ((await addBtn.count()) > 0) {
      await addBtn.click();
      await page.waitForTimeout(1000);
      await ss(page, "ta-07-glossary-form");
      const body = await getBodyText(page);
      console.log(`[TA-07] Form body (500): ${body.substring(0, 500)}`);

      // Try to fill
      const termInput = page.locator('input[name="term"], input[placeholder*="term" i], input[id*="term" i]').first();
      if ((await termInput.count()) > 0) {
        await termInput.fill("LTV");
        console.log("[TA-07] Filled term");
      }

      const fullFormInput = page.locator('input[name="full_form"], input[name="fullForm"], input[placeholder*="full" i]').first();
      if ((await fullFormInput.count()) > 0) {
        await fullFormInput.fill("Loan-to-Value");
        console.log("[TA-07] Filled full_form");
      }

      const defInput = page.locator('textarea[name="definition"], textarea, input[name="definition"]').first();
      if ((await defInput.count()) > 0) {
        await defInput.fill("The ratio of a loan amount to the appraised value");
        console.log("[TA-07] Filled definition");
      }

      await ss(page, "ta-07-glossary-filled");

      // Try to save
      const saveBtn = page.locator('button:has-text("Save"), button:has-text("Create"), button:has-text("Publish"), button[type="submit"]').first();
      if ((await saveBtn.count()) > 0) {
        await saveBtn.click();
        await page.waitForTimeout(2000);
        await ss(page, "ta-07-glossary-saved");
        console.log(`[TA-07] After save URL: ${page.url()}`);
        const body2 = await getBodyText(page);
        const hasLTV = body2.includes("LTV");
        console.log(`[TA-07] LTV visible after save: ${hasLTV}`);
      }
    } else {
      console.log("[TA-07] No Add Term button found");
    }
  });

  test("TA-08: Analytics", async ({ page }) => {
    await navTo(page, "/admin/analytics");
    await ss(page, "ta-08-analytics");
    const body = await getBodyText(page);
    console.log(`[TA-08] URL: ${page.url()}`);
    console.log(`[TA-08] Body (500): ${body.substring(0, 500)}`);
  });

  test("TA-09: Issues", async ({ page }) => {
    await navTo(page, "/admin/issues");
    await ss(page, "ta-09-issues");
    const body = await getBodyText(page);
    console.log(`[TA-09] URL: ${page.url()}`);
    console.log(`[TA-09] Body (500): ${body.substring(0, 500)}`);
  });

  test("TA-10: Settings", async ({ page }) => {
    await navTo(page, "/admin/settings");
    await ss(page, "ta-10-settings");
    const body = await getBodyText(page);
    console.log(`[TA-10] URL: ${page.url()}`);
    console.log(`[TA-10] Body (500): ${body.substring(0, 500)}`);
  });

  test("TA-11: Navigation coherence", async ({ page }) => {
    await navTo(page, "/admin");
    const navItems = await getNavItems(page);
    console.log(`[TA-11] All nav: ${JSON.stringify(navItems)}`);

    const expected = ["Dashboard", "Documents", "Users", "Agents", "Glossary", "Analytics", "Issues", "Settings"];
    const found = expected.filter(e => navItems.some(n => n.includes(e)));
    const missing = expected.filter(e => !navItems.some(n => n.includes(e)));
    console.log(`[TA-11] Found: ${JSON.stringify(found)}`);
    console.log(`[TA-11] Missing: ${JSON.stringify(missing)}`);
  });
});

// ===================== PLATFORM ADMIN AUDIT =====================
test.describe("RED TEAM: Platform Admin", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, PLATFORM_ADMIN.email, PLATFORM_ADMIN.pass);
  });

  test("PA-01: Login and landing", async ({ page }) => {
    const url = page.url();
    console.log(`[PA-01] URL: ${url}`);
    await ss(page, "pa-01-landing");
    const body = await getBodyText(page);
    console.log(`[PA-01] Body (500): ${body.substring(0, 500)}`);
    const navItems = await getNavItems(page);
    console.log(`[PA-01] Nav: ${JSON.stringify(navItems)}`);
  });

  test("PA-02: Platform Dashboard", async ({ page }) => {
    for (const p of ["/admin/platform", "/admin/platform/dashboard", "/admin"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-02] Dashboard at: ${page.url()}`);
        await ss(page, "pa-02-dashboard");
        const body = await getBodyText(page);
        console.log(`[PA-02] Body (600): ${body.substring(0, 600)}`);
        break;
      }
    }
  });

  test("PA-03: Tenants", async ({ page }) => {
    for (const p of ["/admin/platform/tenants", "/admin/tenants"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-03] Tenants at: ${page.url()}`);
        await ss(page, "pa-03-tenants");
        const body = await getBodyText(page);
        console.log(`[PA-03] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });

  test("PA-04: LLM Profiles", async ({ page }) => {
    for (const p of ["/admin/platform/llm-profiles", "/admin/llm-profiles"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-04] LLM at: ${page.url()}`);
        await ss(page, "pa-04-llm");
        const body = await getBodyText(page);
        console.log(`[PA-04] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });

  test("PA-05: Cost Analytics", async ({ page }) => {
    for (const p of ["/admin/platform/cost", "/admin/platform/cost-analytics", "/admin/cost"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-05] Cost at: ${page.url()}`);
        await ss(page, "pa-05-cost");
        const body = await getBodyText(page);
        console.log(`[PA-05] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });

  test("PA-06: Issue Queue", async ({ page }) => {
    for (const p of ["/admin/platform/issues", "/admin/issues"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-06] Issues at: ${page.url()}`);
        await ss(page, "pa-06-issues");
        const body = await getBodyText(page);
        console.log(`[PA-06] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });

  test("PA-07: Agent Templates", async ({ page }) => {
    for (const p of ["/admin/platform/agent-templates", "/admin/agent-templates"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-07] Agents at: ${page.url()}`);
        await ss(page, "pa-07-agents");
        const body = await getBodyText(page);
        console.log(`[PA-07] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });

  test("PA-08: Tool Catalog", async ({ page }) => {
    for (const p of ["/admin/platform/tool-catalog", "/admin/tool-catalog"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-08] Tools at: ${page.url()}`);
        await ss(page, "pa-08-tools");
        const body = await getBodyText(page);
        console.log(`[PA-08] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });

  test("PA-09: Navigation coherence", async ({ page }) => {
    await navTo(page, "/admin/platform");
    const navItems = await getNavItems(page);
    console.log(`[PA-09] Nav: ${JSON.stringify(navItems)}`);

    const expected = ["Dashboard", "Tenants", "Issue", "LLM", "Agent", "Analytics", "Tool", "Cost"];
    const found = expected.filter(e => navItems.some(n => n.toLowerCase().includes(e.toLowerCase())));
    const missing = expected.filter(e => !navItems.some(n => n.toLowerCase().includes(e.toLowerCase())));
    console.log(`[PA-09] Found: ${JSON.stringify(found)}`);
    console.log(`[PA-09] Missing: ${JSON.stringify(missing)}`);
  });

  test("PA-10: Platform Analytics", async ({ page }) => {
    for (const p of ["/admin/platform/analytics", "/admin/analytics"]) {
      await navTo(page, p);
      if (!page.url().includes("/login")) {
        console.log(`[PA-10] Analytics at: ${page.url()}`);
        await ss(page, "pa-10-analytics");
        const body = await getBodyText(page);
        console.log(`[PA-10] Body (500): ${body.substring(0, 500)}`);
        break;
      }
    }
  });
});

// ===================== CROSS-ROLE ISOLATION =====================
test.describe("RED TEAM: Isolation", () => {
  test("ISO-01: End user blocked from admin", async ({ page }) => {
    await login(page, END_USER.email, END_USER.pass);
    for (const p of ["/admin", "/admin/users", "/admin/platform"]) {
      await navTo(page, p);
      const url = page.url();
      console.log(`[ISO-01] ${p} => ${url}`);
    }
    await ss(page, "iso-01");
  });

  test("ISO-02: Tenant admin blocked from platform", async ({ page }) => {
    await login(page, TENANT_ADMIN.email, TENANT_ADMIN.pass);
    for (const p of ["/admin/platform", "/admin/platform/tenants"]) {
      await navTo(page, p);
      const url = page.url();
      console.log(`[ISO-02] ${p} => ${url}`);
    }
    await ss(page, "iso-02");
  });
});
