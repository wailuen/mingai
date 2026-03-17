import { test, expect, Page } from "@playwright/test";

const BASE_URL = "http://localhost:3022";
const TA = { email: "admin@tpcgroup.test", pass: "Admin1234!" };
const SCREENSHOT_DIR = "tests/e2e/screenshots/ta-redteam";

function log(msg: string) {
  console.log(msg);
}

async function login(page: Page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(2000);
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

async function getMainText(page: Page): Promise<string> {
  return (
    (await page
      .locator("main")
      .first()
      .textContent()
      .catch(() => "")) || ""
  );
}

test.describe("TA Red-Team Part 2", () => {
  test.setTimeout(120000);

  test("FLOW-2b: Invite User Modal", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/users`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);

    // Click Invite User button
    const inviteBtn = page.locator('button:has-text("Invite User")');
    log(`[FLOW-2b] Invite button count: ${await inviteBtn.count()}`);
    if ((await inviteBtn.count()) > 0) {
      await inviteBtn.first().click();
      await page.waitForTimeout(1500);
      await ss(page, "02b-invite-modal");

      const modalText = await page
        .locator('[role="dialog"], [class*="modal"], [class*="dialog"]')
        .first()
        .textContent()
        .catch(() => "NOT FOUND");
      log(`[FLOW-2b] Invite modal content: ${modalText?.slice(0, 400)}`);

      // Try filling invite form
      const emailInputs = page.locator(
        'input[type="email"], input[placeholder*="email" i]',
      );
      log(`[FLOW-2b] Email inputs in modal: ${await emailInputs.count()}`);
    }
  });

  test("FLOW-2c: User Row Click Detail", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/users`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);

    // Click the three-dot menu on first user row
    const menuBtn = page
      .locator(
        'table tbody tr:first-child button, table tbody tr:first-child [class*="menu"]',
      )
      .first();
    if ((await menuBtn.count()) > 0) {
      await menuBtn.click();
      await page.waitForTimeout(1000);
      await ss(page, "02c-user-menu");
      const menuText = await page
        .locator('[role="menu"], [class*="dropdown"], [class*="popover"]')
        .first()
        .textContent()
        .catch(() => "NOT FOUND");
      log(`[FLOW-2c] User context menu: ${menuText?.slice(0, 300)}`);
    } else {
      log("[FLOW-2c] No context menu button found on user row");
    }
  });

  test("FLOW-3: Documents", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/knowledge-base`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "03-documents");

    const text = await getMainText(page);
    log(`[FLOW-3] Documents: ${text.slice(0, 500)}`);

    // Also try /settings/documents
    await page.goto(`${BASE_URL}/settings/documents`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    const text2 = await getMainText(page);
    log(`[FLOW-3] /settings/documents: ${text2.slice(0, 500)}`);
    await ss(page, "03-documents-alt");
  });

  test("FLOW-4: Agents", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/agents`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "04-agents");

    const text = await getMainText(page);
    log(`[FLOW-4] Agents: ${text.slice(0, 600)}`);

    // Check for template cards
    const cards = await page.locator('[class*="card"]').count();
    log(`[FLOW-4] Cards: ${cards}`);

    // Try clicking Preview or Deploy
    const previewBtn = page.locator('button:has-text("Preview")');
    const deployBtn = page.locator('button:has-text("Deploy")');
    log(
      `[FLOW-4] Preview buttons: ${await previewBtn.count()}, Deploy buttons: ${await deployBtn.count()}`,
    );
  });

  test("FLOW-5: Glossary", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/glossary`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "05-glossary");

    const text = await getMainText(page);
    log(`[FLOW-5] Glossary: ${text.slice(0, 500)}`);

    // Click Add Term
    const addBtn = page.locator('button:has-text("Add Term")');
    if ((await addBtn.count()) > 0) {
      await addBtn.first().click();
      await page.waitForTimeout(1500);
      await ss(page, "05-glossary-add-modal");

      const modalText = await page
        .locator('[role="dialog"], [class*="modal"], [class*="dialog"]')
        .first()
        .textContent()
        .catch(() => "NOT FOUND");
      log(`[FLOW-5] Add Term modal: ${modalText?.slice(0, 400)}`);

      // Fill and save
      const termInput = page.locator(
        'input[name="term"], input[placeholder*="term" i]',
      );
      if ((await termInput.count()) > 0) {
        await termInput.first().fill("APAC");
      }

      const defInput = page.locator('textarea, input[name="definition"]');
      if ((await defInput.count()) > 0) {
        await defInput
          .first()
          .fill(
            "Asia-Pacific region covering ASEAN, Japan, Australia and India",
          );
      }

      await ss(page, "05-glossary-filled");

      const saveBtn = page.locator(
        'button:has-text("Save"), button:has-text("Create"), button[type="submit"]',
      );
      if ((await saveBtn.count()) > 0) {
        await saveBtn.first().click();
        await page.waitForTimeout(2000);
        await ss(page, "05-glossary-saved");
        const afterText = await getMainText(page);
        log(
          `[FLOW-5] After save: ${afterText.includes("APAC") ? "APAC VISIBLE" : "APAC NOT VISIBLE"}`,
        );
        log(`[FLOW-5] After save content: ${afterText.slice(0, 300)}`);
      }
    } else {
      log("[FLOW-5] FAIL: Add Term button not found");
    }
  });

  test("FLOW-6: Analytics", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/admin/analytics`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(3000);
    await ss(page, "06-analytics");

    const text = await getMainText(page);
    log(`[FLOW-6] Analytics: ${text.slice(0, 600)}`);

    const svgs = await page.locator("svg.recharts-surface").count();
    log(`[FLOW-6] Recharts SVGs: ${svgs}`);
  });

  test("FLOW-7: Issues", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/engineering-issues`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "07-issues");

    const text = await getMainText(page);
    log(`[FLOW-7] Issues: ${text.slice(0, 600)}`);

    const tabs = await page.locator('button[role="tab"]').count();
    log(`[FLOW-7] Tabs: ${tabs}`);

    const rows = await page.locator("table tbody tr").count();
    log(`[FLOW-7] Issue rows: ${rows}`);
  });

  test("FLOW-8: Workspace Settings", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/workspace`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "08-workspace");

    const text = await getMainText(page);
    log(`[FLOW-8] Workspace: ${text.slice(0, 600)}`);

    const inputs = await page.locator("input, textarea, select").count();
    log(`[FLOW-8] Input fields: ${inputs}`);

    const saveBtn = page.locator('button:has-text("Save")');
    log(
      `[FLOW-8] Save button: ${(await saveBtn.count()) > 0 ? "FOUND" : "MISSING"}`,
    );
  });

  test("FLOW-9: SSO Settings", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/settings/sso`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "09-sso");

    const text = await getMainText(page);
    log(`[FLOW-9] SSO: ${text.slice(0, 600)}`);

    const toggles = await page.locator('button[role="switch"]').count();
    log(`[FLOW-9] Toggles: ${toggles}`);

    const tables = await page.locator("table").count();
    log(`[FLOW-9] Tables: ${tables}`);
  });

  test("FLOW-10: LLM Settings", async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/admin/settings/llm`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "10-llm");

    const text = await getMainText(page);
    log(`[FLOW-10] LLM: ${text.slice(0, 600)}`);

    // Also try settings/llm
    if (text.length < 50) {
      await page.goto(`${BASE_URL}/settings/llm`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);
      const text2 = await getMainText(page);
      log(`[FLOW-10] /settings/llm: ${text2.slice(0, 600)}`);
      await ss(page, "10-llm-alt");
    }
  });

  test("FLOW-11: Document Sync", async ({ page }) => {
    await login(page);

    for (const route of [
      "/admin/sync",
      "/settings/sync",
      "/settings/document-sync",
    ]) {
      await page.goto(`${BASE_URL}${route}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);
      const text = await getMainText(page);
      if (text.length > 50 && !text.toLowerCase().includes("not found")) {
        log(`[FLOW-11] Sync at ${route}: ${text.slice(0, 400)}`);
        await ss(page, "11-sync");
        break;
      } else {
        log(
          `[FLOW-11] ${route}: ${text.length < 50 ? "EMPTY" : text.slice(0, 100)}`,
        );
      }
    }
  });
});
