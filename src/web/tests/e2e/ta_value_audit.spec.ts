import { test, expect, Page } from "@playwright/test";

const BASE_URL = "http://localhost:3022";
const TA = { email: "admin@tpcgroup.test", pass: "Admin1234!" };
const SCREENSHOT_DIR = "playwright-report/ta-audit";

async function login(page: Page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(1500);
  const emailInput = page.locator('input[type="email"], input[name="email"]');
  if ((await emailInput.count()) > 0) await emailInput.fill(TA.email);
  const passInput = page.locator(
    'input[type="password"], input[name="password"]',
  );
  if ((await passInput.count()) > 0) await passInput.fill(TA.pass);
  const submitBtn = page.locator('button[type="submit"]');
  if ((await submitBtn.count()) > 0) await submitBtn.click();
  await page.waitForTimeout(3000);
}

async function ss(page: Page, name: string) {
  await page.screenshot({
    path: `${SCREENSHOT_DIR}/${name}.png`,
    fullPage: true,
  });
}

test.describe("Tenant Admin Value Audit", () => {
  test.setTimeout(120000);

  // ===== 1. LOGIN + DASHBOARD =====
  test("TA-01: Login and Dashboard", async ({ page }) => {
    await login(page);
    // Should redirect to dashboard or a default page
    await ss(page, "01-post-login");

    // Navigate to dashboard explicitly
    await page.goto(`${BASE_URL}/settings/dashboard`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "01-dashboard");

    // Check sidebar sections
    const sidebarText = await page
      .locator("aside")
      .first()
      .textContent()
      .catch(() => "");
    console.log("SIDEBAR TEXT:", sidebarText);

    // Check for KPI cards or dashboard content
    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("MAIN CONTENT (first 500):", mainContent?.slice(0, 500));
  });

  // ===== 2. USER MANAGEMENT =====
  test("TA-02: User Management", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/users`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "02-users-list");

    // Check for user table
    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("USERS PAGE:", mainContent?.slice(0, 500));

    // Try invite button
    const inviteBtn = page.locator(
      'button:has-text("Invite"), button:has-text("invite"), button:has-text("Add")',
    );
    if ((await inviteBtn.count()) > 0) {
      await inviteBtn.first().click();
      await page.waitForTimeout(1500);
      await ss(page, "02-invite-modal");
      console.log("INVITE MODAL OPENED: YES");
    } else {
      console.log("INVITE MODAL OPENED: NO - button not found");
    }
  });

  // ===== 3. DOCUMENTS / KNOWLEDGE BASE =====
  test("TA-03: Documents / Knowledge Base", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/knowledge-base`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "03-documents");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("DOCUMENTS PAGE:", mainContent?.slice(0, 500));
  });

  // ===== 4. SSO SETTINGS =====
  test("TA-04: SSO Settings", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/sso`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "04-sso");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("SSO PAGE:", mainContent?.slice(0, 800));

    // Check for SSO toggle, group mapping table, group sync config
    const toggles = await page.locator('button[role="switch"]').count();
    console.log("SSO TOGGLES FOUND:", toggles);

    // Look for group mapping table
    const tableRows = await page.locator("table tbody tr").count();
    console.log("GROUP MAPPING TABLE ROWS:", tableRows);

    // Check for configure button
    const configBtn = page.locator(
      'button:has-text("Configure"), button:has-text("configure")',
    );
    console.log("CONFIGURE SSO BUTTON:", await configBtn.count());
  });

  // ===== 5. GLOSSARY =====
  test("TA-05: Glossary", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/glossary`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "05-glossary");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("GLOSSARY PAGE:", mainContent?.slice(0, 500));

    // Try adding a term
    const addBtn = page.locator(
      'button:has-text("Add Term"), button:has-text("add term"), button:has-text("Add"), button:has-text("New")',
    );
    if ((await addBtn.count()) > 0) {
      await addBtn.first().click();
      await page.waitForTimeout(1500);
      await ss(page, "05-glossary-add-form");

      // Fill in term
      const termInput = page.locator(
        'input[name="term"], input[placeholder*="term"], input[placeholder*="Term"]',
      );
      if ((await termInput.count()) > 0) {
        await termInput.first().fill("APAC");
      }

      const fullFormInput = page.locator(
        'input[name="full_form"], input[name="fullForm"], input[placeholder*="full"]',
      );
      if ((await fullFormInput.count()) > 0) {
        await fullFormInput.first().fill("Asia-Pacific");
      }

      const defInput = page.locator(
        'textarea[name="definition"], textarea[placeholder*="definition"], textarea[placeholder*="Definition"]',
      );
      if ((await defInput.count()) > 0) {
        await defInput
          .first()
          .fill(
            "Our secondary revenue region, covering Japan, China, Southeast Asia, Australia, and India.",
          );
      }

      await ss(page, "05-glossary-form-filled");

      // Save
      const saveBtn = page.locator(
        'button:has-text("Save"), button[type="submit"]',
      );
      if ((await saveBtn.count()) > 0) {
        await saveBtn.first().click();
        await page.waitForTimeout(2000);
        await ss(page, "05-glossary-after-save");
        console.log("GLOSSARY TERM SAVED: attempted");
      }
    } else {
      console.log("ADD TERM BUTTON NOT FOUND");
    }
  });

  // ===== 6. ANALYTICS =====
  test("TA-06: Analytics", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/admin/analytics`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "06-analytics");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("ANALYTICS PAGE:", mainContent?.slice(0, 500));

    // Check for charts
    const svgs = await page.locator("svg.recharts-surface").count();
    console.log("RECHARTS SVG FOUND:", svgs);
  });

  // ===== 7. ISSUES =====
  test("TA-07: Issues", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/engineering-issues`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "07-issues");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("ISSUES PAGE:", mainContent?.slice(0, 500));

    // Check filter tabs
    const tabs = await page
      .locator('button[role="tab"], [data-state]')
      .count();
    console.log("FILTER TABS:", tabs);
  });

  // ===== 8. WORKSPACE SETTINGS =====
  test("TA-08: Workspace Settings", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/workspace`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "08-workspace-settings");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("WORKSPACE SETTINGS PAGE:", mainContent?.slice(0, 500));
  });

  // ===== 9. AGENTS =====
  test("TA-09: Agents", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/admin/agents`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "09-agents");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("AGENTS PAGE:", mainContent?.slice(0, 500));
  });

  // ===== 10. LLM SETTINGS =====
  test("TA-10: LLM Settings", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/admin/settings/llm`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "10-llm-settings");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("LLM SETTINGS PAGE:", mainContent?.slice(0, 500));
  });

  // ===== 11. SYNC / DOCUMENTS SYNC TAB =====
  test("TA-11: Document Sync Status", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/admin/sync`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "11-sync-status");

    const mainContent = await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "");
    console.log("SYNC PAGE:", mainContent?.slice(0, 500));
  });
});
