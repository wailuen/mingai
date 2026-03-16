/**
 * Value Audit -- Enterprise Demo QA
 * Tests all 7 prioritized scenarios using real login flow.
 */
import { test, expect, type Page, type BrowserContext } from "@playwright/test";

test.setTimeout(90_000);

const SCREENSHOT_DIR = "tests/e2e/screenshots/value-audit";

// --- Helper: login via the UI login page ---
async function loginAs(
  page: Page,
  email: string,
  password: string
): Promise<void> {
  await page.goto("/login");
  await page.waitForLoadState("networkidle").catch(() => {});

  await page.fill('input[id="email"], input[name="email"], input[type="email"]', email);
  await page.fill('input[id="password"], input[name="password"], input[type="password"]', password);
  await page.click('button[type="submit"]');

  // Wait for navigation away from login page
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  });
  await page.waitForLoadState("networkidle").catch(() => {});
}

// --- Helper: collect console errors ---
function collectErrors(page: Page): { errors: string[]; networkErrors: string[] } {
  const errors: string[] = [];
  const networkErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  page.on("response", (resp) => {
    if (resp.status() >= 400) {
      networkErrors.push(`${resp.status()} ${resp.url()}`);
    }
  });
  return { errors, networkErrors };
}

// --- Helper: wait for network idle ---
async function idle(page: Page, ms = 5000) {
  try {
    await page.waitForLoadState("networkidle", { timeout: ms });
  } catch {
    // OK
  }
}

// =============================================================
// TEST 1: End User Chat with Markdown Rendering (CRITICAL)
// =============================================================
test.describe("1. End User Chat -- Markdown Rendering", () => {
  test("Chat loads, sends message, renders markdown", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const { errors } = collectErrors(page);

    await loginAs(page, "user@mingai.test", "User1234!");

    // Navigate to chat (login should redirect here, but be explicit)
    await page.goto("/chat");
    await idle(page);

    // Screenshot: empty state
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/01-chat-empty-state.png`,
      fullPage: true,
    });

    // Verify input exists
    const input = page.locator("textarea").first();
    await expect(input).toBeVisible({ timeout: 10_000 });

    // Check KB hint
    const pageText = await page.textContent("body");
    const kbHintCorrect =
      pageText?.includes("SharePoint") && pageText?.includes("Knowledge base active");
    const kbHintOld = pageText?.includes("2,081 documents indexed");
    console.log(`[AUDIT-1] KB hint correct ("SharePoint...Knowledge base active"): ${kbHintCorrect}`);
    console.log(`[AUDIT-1] KB hint old ("2,081 documents indexed"): ${kbHintOld}`);

    // Send message
    await input.fill("What does LTV mean in finance?");
    // Click send button
    const sendBtn = page.locator('button[type="submit"], button:has(svg)').last();
    await sendBtn.click();

    // Check for streaming status indicators (poll for 5s)
    let statusSeen = false;
    for (let i = 0; i < 10; i++) {
      await page.waitForTimeout(500);
      const txt = (await page.textContent("body")) || "";
      if (
        txt.includes("Detecting intent") ||
        txt.includes("Searching knowledge") ||
        txt.includes("Generating response") ||
        txt.includes("Thinking") ||
        txt.includes("Processing")
      ) {
        statusSeen = true;
        break;
      }
    }
    console.log(`[AUDIT-1] Streaming status indicator seen: ${statusSeen}`);

    // Wait for response to complete (up to 30s)
    // Look for content that indicates a completed AI response
    let responseCompleted = false;
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(1000);
      const txt = (await page.textContent("body")) || "";
      // A completed response typically contains "LTV" or "Lifetime Value" in the AI response
      if (
        (txt.includes("Lifetime Value") || txt.includes("lifetime value")) &&
        !txt.includes("Generating")
      ) {
        responseCompleted = true;
        break;
      }
    }
    console.log(`[AUDIT-1] Response completed with relevant content: ${responseCompleted}`);

    // Screenshot: completed response
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/01-chat-response.png`,
      fullPage: true,
    });

    const finalBody = await page.textContent("body") || "";

    // Check markdown rendering
    const strongCount = await page.locator(".prose strong, .markdown strong, [class*='message'] strong, [class*='chat'] strong, strong").count();
    const headerCount = await page.locator(".prose h1, .prose h2, .prose h3, .markdown h1, .markdown h2, .markdown h3, h1, h2, h3, h4").count();
    const listCount = await page.locator(".prose ul, .prose ol, .markdown ul, .markdown ol, [class*='message'] ul, [class*='message'] ol").count();
    const rawAsterisks = (finalBody.match(/\*\*[^*]+\*\*/g) || []).length;

    console.log(`[AUDIT-1] <strong> elements in response: ${strongCount}`);
    console.log(`[AUDIT-1] Header elements (h1-h4): ${headerCount}`);
    console.log(`[AUDIT-1] List elements (ul/ol): ${listCount}`);
    console.log(`[AUDIT-1] Raw ** markdown (not rendered): ${rawAsterisks}`);

    // Check for Reconnecting error
    const hasReconnecting = finalBody.toLowerCase().includes("reconnecting");
    console.log(`[AUDIT-1] "Reconnecting" error present: ${hasReconnecting}`);

    // Console errors
    const significantErrors = errors.filter(
      (e) => !e.includes("favicon") && !e.includes("manifest")
    );
    console.log(
      `[AUDIT-1] Console errors: ${significantErrors.length ? significantErrors.slice(0, 5).join("; ") : "none"}`
    );

    await ctx.close();
  });
});

// =============================================================
// TEST 2: Platform Admin Dashboard
// =============================================================
test.describe("2. Platform Admin Dashboard", () => {
  test("Dashboard shows KPIs and Quick Actions", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const { errors, networkErrors } = collectErrors(page);

    await loginAs(page, "admin@mingai.test", "Admin1234!");
    await page.goto("/settings/dashboard");
    await idle(page);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/02-pa-dashboard.png`,
      fullPage: true,
    });

    const bodyText = (await page.textContent("body")) || "";

    // KPI cards
    const kpiTerms = ["Tenant", "Agent", "User", "Revenue", "Cost", "Active"];
    const kpiFound = kpiTerms.filter((k) => bodyText.includes(k));
    console.log(`[AUDIT-2] KPI keywords found: ${kpiFound.join(", ") || "NONE"}`);

    // Quick Actions
    const actionTerms = ["Provision", "Configure", "Review", "Quick Action"];
    const actionsFound = actionTerms.filter((k) => bodyText.includes(k));
    console.log(`[AUDIT-2] Quick Action keywords: ${actionsFound.join(", ") || "NONE"}`);

    // Numeric data presence (are KPIs showing real numbers?)
    const numbers = bodyText.match(/\d+/g) || [];
    console.log(`[AUDIT-2] Numeric values on page: ${numbers.length}`);

    const api404s = networkErrors.filter((e) => e.includes("404"));
    console.log(`[AUDIT-2] API 404 errors: ${api404s.length ? api404s.join("; ") : "none"}`);

    await ctx.close();
  });
});

// =============================================================
// TEST 3: Platform Admin LLM Profiles
// =============================================================
test.describe("3. Platform Admin LLM Profiles", () => {
  test("Shows profiles with Azure deployment names", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const { errors } = collectErrors(page);

    await loginAs(page, "admin@mingai.test", "Admin1234!");
    await page.goto("/settings/llm-profiles");
    await idle(page);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/03-pa-llm-profiles.png`,
      fullPage: true,
    });

    const bodyText = (await page.textContent("body")) || "";

    const deployments = ["agentic-router", "agentic-worker", "agentic-vision", "text-embedding", "gpt"];
    const found = deployments.filter((d) => bodyText.toLowerCase().includes(d));
    console.log(`[AUDIT-3] Azure deployments found: ${found.join(", ") || "NONE"}`);

    // Count table rows (profiles)
    const tableRows = await page.locator("tbody tr").count();
    console.log(`[AUDIT-3] Profile table rows: ${tableRows}`);

    // Check for "Active" status badges
    const activeBadges = await page.locator('text="Active"').count();
    console.log(`[AUDIT-3] Active status badges: ${activeBadges}`);

    await ctx.close();
  });
});

// =============================================================
// TEST 4: Platform Admin Issue Queue
// =============================================================
test.describe("4. Platform Admin Issue Queue", () => {
  test("Shows issues with actionable details", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const { errors } = collectErrors(page);

    await loginAs(page, "admin@mingai.test", "Admin1234!");
    await page.goto("/settings/issue-queue");
    await idle(page);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/04-pa-issue-queue.png`,
      fullPage: true,
    });

    const bodyText = (await page.textContent("body")) || "";

    const issueIndicators = ["P0", "P1", "P2", "P3", "open", "critical", "high", "medium", "low"];
    const found = issueIndicators.filter((i) => bodyText.toLowerCase().includes(i.toLowerCase()));
    console.log(`[AUDIT-4] Issue indicators: ${found.join(", ") || "NONE"}`);

    // Count issue rows
    const issueRows = await page.locator("tbody tr, [class*='issue'] [class*='row'], [class*='issue-item']").count();
    console.log(`[AUDIT-4] Issue rows/items: ${issueRows}`);

    // Try clicking first issue
    const firstIssue = page.locator("tbody tr, [class*='issue-item']").first();
    if (await firstIssue.isVisible().catch(() => false)) {
      await firstIssue.click();
      await page.waitForTimeout(1500);

      await page.screenshot({
        path: `${SCREENSHOT_DIR}/04-pa-issue-detail.png`,
        fullPage: true,
      });

      const detailText = (await page.textContent("body")) || "";
      const actionVerbs = ["Assign", "Acknowledge", "Resolve", "Close", "Escalate", "Update"];
      const actionsFound = actionVerbs.filter((a) => detailText.includes(a));
      console.log(`[AUDIT-4] Detail panel actions: ${actionsFound.join(", ") || "NONE"}`);
    } else {
      console.log(`[AUDIT-4] No clickable issue rows found`);
    }

    await ctx.close();
  });
});

// =============================================================
// TEST 5: Tenant Admin Settings Pages (404 storm fix)
// =============================================================
test.describe("5. Tenant Admin Settings Pages", () => {
  const pages = [
    { name: "Workspace", path: "/settings/workspace" },
    { name: "SSO", path: "/settings/sso" },
    { name: "Issue Reporting", path: "/settings/issue-reporting" },
    { name: "Knowledge Base", path: "/settings/knowledge-base" },
  ];

  for (const sp of pages) {
    test(`5${pages.indexOf(sp) + 1}. TA ${sp.name} loads without 404 storm`, async ({
      browser,
    }) => {
      const ctx = await browser.newContext();
      const page = await ctx.newPage();

      await loginAs(page, "tenant_admin@mingai.test", "TenantAdmin1234!");

      // Collect network errors for this specific page
      const netErrors: string[] = [];
      page.on("response", (resp) => {
        if (resp.status() >= 400) {
          netErrors.push(`${resp.status()} ${new URL(resp.url()).pathname}`);
        }
      });

      await page.goto(sp.path);
      await idle(page);

      await page.screenshot({
        path: `${SCREENSHOT_DIR}/05-ta-${sp.name.toLowerCase().replace(/\s/g, "-")}.png`,
        fullPage: true,
      });

      const bodyText = (await page.textContent("body")) || "";

      const hasVisibleError =
        bodyText.includes("Failed to load") ||
        bodyText.includes("Something went wrong") ||
        bodyText.includes("Page not found");
      console.log(`[AUDIT-5${pages.indexOf(sp) + 1}] ${sp.name} -- Visible error on page: ${hasVisibleError}`);

      const api404s = netErrors.filter((e) => e.includes("404"));
      const api401s = netErrors.filter((e) => e.includes("401"));
      const api500s = netErrors.filter((e) => e.includes("500"));
      console.log(`[AUDIT-5${pages.indexOf(sp) + 1}] ${sp.name} -- 404 errors: ${api404s.length} (${api404s.slice(0, 3).join("; ")})`);
      console.log(`[AUDIT-5${pages.indexOf(sp) + 1}] ${sp.name} -- 401 errors: ${api401s.length}`);
      console.log(`[AUDIT-5${pages.indexOf(sp) + 1}] ${sp.name} -- 500 errors: ${api500s.length}`);

      // Check if the page has meaningful content (not just a blank/error state)
      const hasForm = (await page.locator("form, input, select, textarea").count()) > 0;
      const hasTable = (await page.locator("table, tbody").count()) > 0;
      const hasContent = bodyText.length > 200;
      console.log(`[AUDIT-5${pages.indexOf(sp) + 1}] ${sp.name} -- Has form elements: ${hasForm}, Has table: ${hasTable}, Content length: ${bodyText.length}`);

      await ctx.close();
    });
  }
});

// =============================================================
// TEST 6: Tenant Admin Glossary
// =============================================================
test.describe("6. Tenant Admin Glossary", () => {
  test("Glossary shows terms with Active status", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();

    await loginAs(page, "tenant_admin@mingai.test", "TenantAdmin1234!");
    await page.goto("/settings/glossary");
    await idle(page);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/06-ta-glossary.png`,
      fullPage: true,
    });

    const bodyText = (await page.textContent("body")) || "";

    const activeBadges = await page.locator('text="Active"').count();
    console.log(`[AUDIT-6] "Active" status badges: ${activeBadges}`);

    const termIndicators = ["LTV", "ROI", "EBITDA", "ARR", "MRR", "CAGR", "CAC", "NPS"];
    const found = termIndicators.filter((t) => bodyText.includes(t));
    console.log(`[AUDIT-6] Glossary terms found: ${found.join(", ") || "NONE"}`);

    // Check for table rows
    const rows = await page.locator("tbody tr").count();
    console.log(`[AUDIT-6] Glossary table rows: ${rows}`);

    await ctx.close();
  });
});

// =============================================================
// TEST 7: Sidebar Navigation -- No Stub Pages
// =============================================================
test.describe("7a. PA Sidebar Navigation", () => {
  test("All PA nav items load real content", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();

    await loginAs(page, "admin@mingai.test", "Admin1234!");
    await page.goto("/settings/dashboard");
    await idle(page);

    // Collect sidebar links
    const links = page.locator("nav a[href], aside a[href]");
    const linkCount = await links.count();
    console.log(`[AUDIT-7a] PA sidebar links found: ${linkCount}`);

    const visited: string[] = [];
    const stubs: string[] = [];
    const loadFailures: string[] = [];

    for (let i = 0; i < linkCount; i++) {
      const href = await links.nth(i).getAttribute("href");
      if (!href || visited.includes(href) || href === "#" || href.startsWith("http")) continue;
      visited.push(href);

      await page.goto(href);
      await idle(page, 3000);
      const bodyText = (await page.textContent("body")) || "";

      if (
        bodyText.includes("coming in a future phase") ||
        bodyText.includes("Coming soon") ||
        bodyText.includes("Under construction") ||
        bodyText.includes("Not yet implemented")
      ) {
        stubs.push(href);
      }
      if (bodyText.includes("Failed to load") || bodyText.includes("Something went wrong")) {
        loadFailures.push(href);
      }
    }

    console.log(`[AUDIT-7a] PA pages visited: ${visited.join(", ")}`);
    console.log(`[AUDIT-7a] PA stub pages: ${stubs.length ? stubs.join(", ") : "none"}`);
    console.log(`[AUDIT-7a] PA load failures: ${loadFailures.length ? loadFailures.join(", ") : "none"}`);

    await ctx.close();
  });
});

test.describe("7b. TA Sidebar Navigation", () => {
  test("All TA nav items load real content", async ({ browser }) => {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();

    await loginAs(page, "tenant_admin@mingai.test", "TenantAdmin1234!");
    await page.goto("/settings/dashboard");
    await idle(page);

    const links = page.locator("nav a[href], aside a[href]");
    const linkCount = await links.count();
    console.log(`[AUDIT-7b] TA sidebar links found: ${linkCount}`);

    const visited: string[] = [];
    const stubs: string[] = [];
    const loadFailures: string[] = [];

    for (let i = 0; i < linkCount; i++) {
      const href = await links.nth(i).getAttribute("href");
      if (!href || visited.includes(href) || href === "#" || href.startsWith("http")) continue;
      visited.push(href);

      await page.goto(href);
      await idle(page, 3000);
      const bodyText = (await page.textContent("body")) || "";

      if (
        bodyText.includes("coming in a future phase") ||
        bodyText.includes("Coming soon") ||
        bodyText.includes("Under construction") ||
        bodyText.includes("Not yet implemented")
      ) {
        stubs.push(href);
      }
      if (bodyText.includes("Failed to load") || bodyText.includes("Something went wrong")) {
        loadFailures.push(href);
      }
    }

    console.log(`[AUDIT-7b] TA pages visited: ${visited.join(", ")}`);
    console.log(`[AUDIT-7b] TA stub pages: ${stubs.length ? stubs.join(", ") : "none"}`);
    console.log(`[AUDIT-7b] TA load failures: ${loadFailures.length ? loadFailures.join(", ") : "none"}`);

    await ctx.close();
  });
});
