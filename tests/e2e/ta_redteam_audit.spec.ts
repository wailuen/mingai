import { test, expect, Page } from "@playwright/test";

const BASE_URL = "http://localhost:3022";
const TA = { email: "admin@tpcgroup.test", pass: "Admin1234!" };
const SCREENSHOT_DIR = "tests/e2e/screenshots/ta-redteam";

// Logging helper
const findings: string[] = [];
function log(msg: string) {
  findings.push(msg);
  console.log(msg);
}

async function login(page: Page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(2000);

  const emailInput = page.locator('input[type="email"], input[name="email"]');
  if ((await emailInput.count()) > 0) await emailInput.fill(TA.email);
  else {
    log("[LOGIN] FAIL: No email input found on /login");
    return false;
  }

  const passInput = page.locator(
    'input[type="password"], input[name="password"]',
  );
  if ((await passInput.count()) > 0) await passInput.fill(TA.pass);
  else {
    log("[LOGIN] FAIL: No password input found");
    return false;
  }

  const submitBtn = page.locator('button[type="submit"]');
  if ((await submitBtn.count()) > 0) await submitBtn.click();
  else {
    log("[LOGIN] FAIL: No submit button found");
    return false;
  }

  await page.waitForTimeout(3000);
  const url = page.url();
  log(`[LOGIN] Post-login URL: ${url}`);
  return true;
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

async function getSidebarText(page: Page): Promise<string> {
  return (
    (await page
      .locator("aside, nav, [class*=sidebar], [class*=Sidebar]")
      .first()
      .textContent()
      .catch(() => "")) || ""
  );
}

test.describe("TA Red-Team Value Audit", () => {
  test.setTimeout(180000);

  test("FULL AUDIT: All TA Flows", async ({ page }) => {
    // ===== TA-FLOW-1: LOGIN & DASHBOARD =====
    log("\n===== TA-FLOW-1: LOGIN & DASHBOARD =====");

    const loginOk = await login(page);
    await ss(page, "01-post-login");
    const postLoginUrl = page.url();
    log(`[FLOW-1] Post-login redirect: ${postLoginUrl}`);

    // Navigate to dashboard
    await page.goto(`${BASE_URL}/settings/dashboard`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "01-dashboard");

    const dashMainText = await getMainText(page);
    log(
      `[FLOW-1] Dashboard content (first 300): ${dashMainText.slice(0, 300)}`,
    );

    // Check sidebar navigation
    const sidebarText = await getSidebarText(page);
    log(`[FLOW-1] Sidebar text: ${sidebarText.slice(0, 400)}`);

    // Check for expected nav items
    const expectedNav = [
      "Dashboard",
      "Documents",
      "Users",
      "Agents",
      "Glossary",
      "Analytics",
      "Issues",
      "Settings",
    ];
    for (const item of expectedNav) {
      const found = sidebarText.toLowerCase().includes(item.toLowerCase());
      log(`[FLOW-1] Nav item '${item}': ${found ? "FOUND" : "MISSING"}`);
    }

    // Check for KPI cards
    const kpiKeywords = [
      "users",
      "agents",
      "documents",
      "queries",
      "satisfaction",
    ];
    for (const kw of kpiKeywords) {
      const found = dashMainText.toLowerCase().includes(kw);
      log(`[FLOW-1] Dashboard KPI '${kw}': ${found ? "FOUND" : "MISSING"}`);
    }

    // ===== TA-FLOW-2: USER MANAGEMENT =====
    log("\n===== TA-FLOW-2: USER MANAGEMENT =====");
    await page.goto(`${BASE_URL}/settings/users`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "02-users-list");

    const usersText = await getMainText(page);
    log(`[FLOW-2] Users page content (first 400): ${usersText.slice(0, 400)}`);

    // Check for user table
    const userTableRows = await page
      .locator("table tbody tr, [class*=table] [class*=row]")
      .count();
    log(`[FLOW-2] User table rows: ${userTableRows}`);

    // Check for search
    const searchInput = page.locator(
      'input[placeholder*="search" i], input[placeholder*="filter" i], input[type="search"]',
    );
    const searchExists = (await searchInput.count()) > 0;
    log(`[FLOW-2] Search input: ${searchExists ? "FOUND" : "MISSING"}`);

    // Test search if exists
    if (searchExists) {
      await searchInput.first().fill("admin");
      await page.waitForTimeout(1000);
      const filteredRows = await page.locator("table tbody tr").count();
      log(`[FLOW-2] Filtered rows after search 'admin': ${filteredRows}`);
      await searchInput.first().clear();
      await page.waitForTimeout(500);
    }

    // Test click on a user row for detail panel
    const firstUserRow = page.locator("table tbody tr").first();
    if ((await firstUserRow.count()) > 0) {
      await firstUserRow.click();
      await page.waitForTimeout(1500);
      await ss(page, "02-user-detail-panel");
      const detailPanelText = await page
        .locator(
          '[class*="slide"], [class*="panel"], [class*="drawer"], [class*="detail"], [role="dialog"]',
        )
        .first()
        .textContent()
        .catch(() => "NOT FOUND");
      log(
        `[FLOW-2] User detail panel: ${detailPanelText?.slice(0, 300) || "NOT FOUND"}`,
      );
    }

    // Test invite button
    const inviteBtn = page.locator(
      'button:has-text("Invite"), button:has-text("Add User"), button:has-text("invite")',
    );
    if ((await inviteBtn.count()) > 0) {
      await inviteBtn.first().click();
      await page.waitForTimeout(1500);
      await ss(page, "02-invite-modal");

      // Check invite form fields
      const inviteEmailInput = page.locator(
        'input[placeholder*="email" i], input[type="email"]',
      );
      const roleDropdown = page.locator(
        'select, [role="listbox"], [class*="select"]',
      );
      log(
        `[FLOW-2] Invite modal: email input=${(await inviteEmailInput.count()) > 0}, role dropdown=${(await roleDropdown.count()) > 0}`,
      );

      // Close modal
      const closeBtn = page.locator(
        'button:has-text("Cancel"), button:has-text("Close"), button[aria-label="Close"], [class*="close"]',
      );
      if ((await closeBtn.count()) > 0) await closeBtn.first().click();
      await page.waitForTimeout(500);
    } else {
      log("[FLOW-2] FAIL: Invite button NOT FOUND");
    }

    // ===== TA-FLOW-3: DOCUMENTS / KNOWLEDGE BASE =====
    log("\n===== TA-FLOW-3: DOCUMENTS / KNOWLEDGE BASE =====");
    await page.goto(`${BASE_URL}/settings/knowledge-base`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "03-documents");

    const docsText = await getMainText(page);
    log(`[FLOW-3] Documents page (first 400): ${docsText.slice(0, 400)}`);

    // Check for document sources or empty state
    const hasSharePoint = docsText.toLowerCase().includes("sharepoint");
    const hasGoogleDrive = docsText.toLowerCase().includes("google drive");
    const hasEmptyState =
      docsText.toLowerCase().includes("no documents") ||
      docsText.toLowerCase().includes("connect") ||
      docsText.toLowerCase().includes("get started");
    log(
      `[FLOW-3] SharePoint: ${hasSharePoint}, Google Drive: ${hasGoogleDrive}, Empty state: ${hasEmptyState}`,
    );

    // ===== TA-FLOW-4: AGENTS =====
    log("\n===== TA-FLOW-4: AGENTS =====");

    // Try multiple possible routes
    for (const route of [
      "/admin/agents",
      "/settings/agents",
      "/settings/agent-library",
    ]) {
      await page.goto(`${BASE_URL}${route}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);
      const agentsText = await getMainText(page);
      if (
        agentsText.length > 50 &&
        !agentsText.toLowerCase().includes("not found")
      ) {
        log(`[FLOW-4] Agents found at route: ${route}`);
        log(`[FLOW-4] Agents page (first 400): ${agentsText.slice(0, 400)}`);
        break;
      } else {
        log(
          `[FLOW-4] Route ${route}: ${agentsText.length < 50 ? "EMPTY/404" : agentsText.slice(0, 100)}`,
        );
      }
    }
    await ss(page, "04-agents");

    // Check for agent template cards
    const agentCards = page.locator(
      '[class*="card"], [class*="template"], [class*="agent-item"]',
    );
    log(`[FLOW-4] Agent cards/templates count: ${await agentCards.count()}`);

    // Check for categories
    const agentsMainText = await getMainText(page);
    const categories = ["HR", "IT", "Finance", "Procurement"];
    for (const cat of categories) {
      log(
        `[FLOW-4] Category '${cat}': ${agentsMainText.includes(cat) ? "FOUND" : "MISSING"}`,
      );
    }

    // ===== TA-FLOW-5: GLOSSARY =====
    log("\n===== TA-FLOW-5: GLOSSARY =====");
    await page.goto(`${BASE_URL}/settings/glossary`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "05-glossary");

    const glossaryText = await getMainText(page);
    log(`[FLOW-5] Glossary page (first 400): ${glossaryText.slice(0, 400)}`);

    // Try adding a term
    const addTermBtn = page.locator(
      'button:has-text("Add Term"), button:has-text("New Term"), button:has-text("Add")',
    );
    if ((await addTermBtn.count()) > 0) {
      log("[FLOW-5] Add Term button: FOUND");
      await addTermBtn.first().click();
      await page.waitForTimeout(1500);
      await ss(page, "05-glossary-add-form");

      // Fill term
      const termInput = page.locator(
        'input[name="term"], input[placeholder*="term" i], input[placeholder*="Term"]',
      );
      if ((await termInput.count()) > 0) {
        await termInput.first().fill("APAC");
        log("[FLOW-5] Term input filled: APAC");
      } else {
        log("[FLOW-5] FAIL: Term input not found in form");
      }

      // Fill full form
      const fullFormInput = page.locator(
        'input[name="full_form"], input[name="fullForm"], input[placeholder*="full" i], input[placeholder*="expansion" i]',
      );
      if ((await fullFormInput.count()) > 0) {
        await fullFormInput.first().fill("Asia-Pacific");
        log("[FLOW-5] Full form input filled: Asia-Pacific");
      } else {
        log("[FLOW-5] Full form input: NOT FOUND (may be optional)");
      }

      // Fill definition
      const defInput = page.locator(
        'textarea[name="definition"], textarea[placeholder*="definition" i], textarea, input[name="definition"]',
      );
      if ((await defInput.count()) > 0) {
        await defInput
          .first()
          .fill(
            "Our secondary revenue region, covering Japan, China, Southeast Asia, Australia, and India.",
          );
        log("[FLOW-5] Definition filled");
      } else {
        log("[FLOW-5] FAIL: Definition input not found");
      }

      await ss(page, "05-glossary-form-filled");

      // Save
      const saveBtn = page.locator(
        'button:has-text("Save"), button:has-text("Create"), button[type="submit"]',
      );
      if ((await saveBtn.count()) > 0) {
        await saveBtn.first().click();
        await page.waitForTimeout(2000);
        await ss(page, "05-glossary-after-save");

        // Check if term appears in list
        const afterSaveText = await getMainText(page);
        const termSaved = afterSaveText.includes("APAC");
        log(`[FLOW-5] Term 'APAC' visible after save: ${termSaved}`);
      } else {
        log("[FLOW-5] FAIL: Save button not found");
      }
    } else {
      log("[FLOW-5] FAIL: Add Term button NOT FOUND");
    }

    // Check for Miss Signals section
    const hasMissSignals =
      glossaryText.toLowerCase().includes("miss") ||
      glossaryText.toLowerCase().includes("suggestion") ||
      glossaryText.toLowerCase().includes("unrecognized");
    log(
      `[FLOW-5] Miss Signals section: ${hasMissSignals ? "FOUND" : "MISSING"}`,
    );

    // ===== TA-FLOW-6: ANALYTICS =====
    log("\n===== TA-FLOW-6: ANALYTICS =====");

    for (const route of ["/admin/analytics", "/settings/analytics"]) {
      await page.goto(`${BASE_URL}${route}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);
      const analyticsText = await getMainText(page);
      if (
        analyticsText.length > 50 &&
        !analyticsText.toLowerCase().includes("not found")
      ) {
        log(`[FLOW-6] Analytics found at route: ${route}`);
        log(
          `[FLOW-6] Analytics page (first 500): ${analyticsText.slice(0, 500)}`,
        );
        break;
      } else {
        log(
          `[FLOW-6] Route ${route}: ${analyticsText.length < 50 ? "EMPTY/404" : analyticsText.slice(0, 100)}`,
        );
      }
    }
    await ss(page, "06-analytics");

    // Check for satisfaction gauge
    const analyticsMainText = await getMainText(page);
    const hasSatisfaction =
      analyticsMainText.toLowerCase().includes("satisfaction") ||
      analyticsMainText.toLowerCase().includes("collecting");
    log(
      `[FLOW-6] Satisfaction section: ${hasSatisfaction ? "FOUND" : "MISSING"}`,
    );

    // Check for Recharts SVG
    const rechartsCount = await page
      .locator("svg.recharts-surface, svg[class*='recharts']")
      .count();
    log(`[FLOW-6] Recharts SVG elements: ${rechartsCount}`);

    // Check for agent breakdown
    const hasAgentBreakdown =
      analyticsMainText.toLowerCase().includes("agent") &&
      analyticsMainText.toLowerCase().includes("breakdown");
    log(`[FLOW-6] Agent Breakdown: ${hasAgentBreakdown ? "FOUND" : "MISSING"}`);

    // Check for issue queue section
    const hasIssueQueue =
      analyticsMainText.toLowerCase().includes("issue") ||
      analyticsMainText.toLowerCase().includes("queue");
    log(`[FLOW-6] Issue Queue section: ${hasIssueQueue ? "FOUND" : "MISSING"}`);

    // ===== TA-FLOW-7: ISSUES =====
    log("\n===== TA-FLOW-7: ISSUES =====");

    for (const route of [
      "/settings/engineering-issues",
      "/settings/issues",
      "/admin/issues",
    ]) {
      await page.goto(`${BASE_URL}${route}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);
      const issuesText = await getMainText(page);
      if (
        issuesText.length > 50 &&
        !issuesText.toLowerCase().includes("not found")
      ) {
        log(`[FLOW-7] Issues found at route: ${route}`);
        log(`[FLOW-7] Issues page (first 400): ${issuesText.slice(0, 400)}`);
        break;
      } else {
        log(
          `[FLOW-7] Route ${route}: ${issuesText.length < 50 ? "EMPTY/404" : issuesText.slice(0, 100)}`,
        );
      }
    }
    await ss(page, "07-issues");

    // Check filter tabs
    const issuesTabs = await page
      .locator(
        'button[role="tab"], [data-state="active"], [class*="tab-trigger"]',
      )
      .count();
    log(`[FLOW-7] Filter tabs: ${issuesTabs}`);

    // Check issue rows
    const issueRows = await page
      .locator("table tbody tr, [class*='issue-row']")
      .count();
    log(`[FLOW-7] Issue rows: ${issueRows}`);

    // Try clicking on an issue
    const firstIssueRow = page.locator("table tbody tr").first();
    if ((await firstIssueRow.count()) > 0 && issueRows > 0) {
      await firstIssueRow.click();
      await page.waitForTimeout(1500);
      await ss(page, "07-issue-detail");
      const issueDetailText = await page
        .locator(
          '[class*="slide"], [class*="panel"], [class*="drawer"], [role="dialog"]',
        )
        .first()
        .textContent()
        .catch(() => "NOT FOUND");
      log(
        `[FLOW-7] Issue detail: ${issueDetailText?.slice(0, 300) || "NO DETAIL PANEL"}`,
      );
    }

    // ===== TA-FLOW-8: WORKSPACE SETTINGS =====
    log("\n===== TA-FLOW-8: WORKSPACE SETTINGS =====");
    await page.goto(`${BASE_URL}/settings/workspace`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "08-workspace");

    const workspaceText = await getMainText(page);
    log(
      `[FLOW-8] Workspace settings (first 400): ${workspaceText.slice(0, 400)}`,
    );

    // Check for expected fields
    const wsFields = ["name", "slug", "timezone", "locale", "welcome"];
    for (const field of wsFields) {
      log(
        `[FLOW-8] Field '${field}': ${workspaceText.toLowerCase().includes(field) ? "FOUND" : "MISSING"}`,
      );
    }

    // Check save button
    const wsSaveBtn = page.locator(
      'button:has-text("Save"), button[type="submit"]',
    );
    log(
      `[FLOW-8] Save button: ${(await wsSaveBtn.count()) > 0 ? "FOUND" : "MISSING"}`,
    );

    // ===== TA-FLOW-9: SSO SETTINGS =====
    log("\n===== TA-FLOW-9: SSO SETTINGS =====");
    await page.goto(`${BASE_URL}/settings/sso`);
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);
    await ss(page, "09-sso");

    const ssoText = await getMainText(page);
    log(`[FLOW-9] SSO page (first 500): ${ssoText.slice(0, 500)}`);

    // Check for SSO toggle
    const ssoToggles = await page.locator('button[role="switch"]').count();
    log(`[FLOW-9] SSO toggles: ${ssoToggles}`);

    // Check for group sync config
    const hasGroupSync =
      ssoText.toLowerCase().includes("group") &&
      (ssoText.toLowerCase().includes("sync") ||
        ssoText.toLowerCase().includes("mapping"));
    log(`[FLOW-9] Group sync/mapping: ${hasGroupSync ? "FOUND" : "MISSING"}`);

    // ===== TA-FLOW-10: LLM SETTINGS =====
    log("\n===== TA-FLOW-10: LLM SETTINGS =====");

    for (const route of [
      "/admin/settings/llm",
      "/settings/llm",
      "/settings/llm-settings",
    ]) {
      await page.goto(`${BASE_URL}${route}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);
      const llmText = await getMainText(page);
      if (llmText.length > 50 && !llmText.toLowerCase().includes("not found")) {
        log(`[FLOW-10] LLM Settings found at route: ${route}`);
        log(`[FLOW-10] LLM page (first 400): ${llmText.slice(0, 400)}`);
        break;
      } else {
        log(
          `[FLOW-10] Route ${route}: ${llmText.length < 50 ? "EMPTY/404" : llmText.slice(0, 100)}`,
        );
      }
    }
    await ss(page, "10-llm-settings");

    // ===== TA-FLOW-11: DOCUMENT SYNC =====
    log("\n===== TA-FLOW-11: DOCUMENT SYNC =====");

    for (const route of [
      "/admin/sync",
      "/settings/sync",
      "/settings/document-sync",
    ]) {
      await page.goto(`${BASE_URL}${route}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(2000);
      const syncText = await getMainText(page);
      if (
        syncText.length > 50 &&
        !syncText.toLowerCase().includes("not found")
      ) {
        log(`[FLOW-11] Sync page found at route: ${route}`);
        log(`[FLOW-11] Sync page (first 400): ${syncText.slice(0, 400)}`);
        break;
      } else {
        log(
          `[FLOW-11] Route ${route}: ${syncText.length < 50 ? "EMPTY/404" : syncText.slice(0, 100)}`,
        );
      }
    }
    await ss(page, "11-sync");

    // ===== CONSOLE ERRORS =====
    log("\n===== CONSOLE ERRORS =====");
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    // Navigate to a key page to capture errors
    await page.goto(`${BASE_URL}/settings/dashboard`);
    await page.waitForTimeout(2000);
    for (const err of consoleErrors.slice(0, 10)) {
      log(`[CONSOLE ERROR] ${err.slice(0, 200)}`);
    }

    // ===== FINAL SUMMARY =====
    log("\n===== AUDIT COMPLETE =====");
    log(`Total findings logged: ${findings.length}`);
  });
});
