import { test, expect, type Page } from "@playwright/test";

/**
 * pgvector Migration Validation — Red Team E2E Tests
 *
 * Tests that the chat + search pipeline works end-to-end after
 * replacing Azure AI Search with pgvector.
 *
 * Uses REAL authentication (login form) and REAL backend endpoints.
 */

const BASE = "http://localhost:3022";
const SHOTS = "tests/e2e/screenshots/pgvector-validation";

const EU = { email: "enduser@tpcgroup.test", pass: "Admin1234!" };
const TA = { email: "admin@tpcgroup.test", pass: "Admin1234!" };
const PA = { email: "admin@mingai.test", pass: "Admin1234!" };

// ---------- helpers ----------

async function login(page: Page, email: string, password: string) {
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
}

function collectErrors(page: Page) {
  const console_errors: string[] = [];
  const net_errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") console_errors.push(msg.text());
  });
  page.on("response", (resp) => {
    if (resp.url().includes("/api/") && resp.status() >= 400) {
      net_errors.push(`${resp.status()} ${resp.url().replace(BASE, "")}`);
    }
  });
  return { console_errors, net_errors };
}

// ---------- tests ----------

test.describe("pgvector Migration Validation", () => {
  test.setTimeout(180000);

  test("FLOW-A: Login and navigate to chat (EU)", async ({ page }) => {
    const { net_errors } = collectErrors(page);

    await login(page, EU.email, EU.pass);
    await page.screenshot({ path: `${SHOTS}/01-after-login.png`, fullPage: true });

    const url = page.url();
    console.log("=== FLOW-A: LOGIN ===");
    console.log("Landed URL:", url);

    // Should land on /chat for a viewer
    expect(url).toContain("/chat");

    const body = await page.textContent("body");
    console.log("Has greeting:", body?.includes("Good") || body?.includes("Hello") || body?.includes("Hi"));
    console.log("Has input:", (await page.locator("textarea").count()) > 0);

    // Check empty state elements
    const hasKBHint = body?.includes("Knowledge base") || body?.includes("document");
    console.log("Has KB hint:", hasKBHint);

    // Check for sidebar with HISTORY
    console.log("Has HISTORY:", body?.includes("HISTORY"));

    // Check mode selector (Auto)
    console.log("Has Auto mode:", body?.includes("Auto"));

    const relevant401s = net_errors.filter(
      (e) => !e.includes("notifications/stream")
    );
    console.log("Network errors (excl notifications):", relevant401s.length);
    relevant401s.forEach((e) => console.log("  NET:", e));

    await page.screenshot({ path: `${SHOTS}/02-chat-empty-state.png`, fullPage: true });
    console.log("=== END FLOW-A ===");
  });

  test("FLOW-B: Standard chat query (pgvector pipeline test)", async ({
    page,
  }) => {
    const { console_errors, net_errors } = collectErrors(page);

    await login(page, EU.email, EU.pass);
    await page.waitForTimeout(2000);

    console.log("=== FLOW-B: CHAT QUERY (pgvector test) ===");

    // Type and send a message
    const textarea = page.locator("textarea").first();
    await textarea.waitFor({ state: "visible", timeout: 10000 });
    await textarea.fill("What is our company's document policy?");

    await page.screenshot({ path: `${SHOTS}/03-typed-query.png`, fullPage: true });

    // Send via button or Enter
    const sendBtn = page.locator('button[type="submit"]').first();
    if (await sendBtn.isVisible()) {
      await sendBtn.click();
    } else {
      await textarea.press("Enter");
    }

    console.log("Message sent:", new Date().toISOString());

    // Wait for SSE stream to begin
    await page.waitForTimeout(5000);
    await page.screenshot({ path: `${SHOTS}/04-streaming.png`, fullPage: true });

    // Wait for completion (up to 60s)
    let completed = false;
    for (let i = 0; i < 20; i++) {
      await page.waitForTimeout(3000);
      const text = await page.textContent("body");

      // Check for stream error
      if (text?.includes("Stream error") || text?.includes("error")) {
        const errorMatch = text?.match(/Stream error[^.]+/);
        if (errorMatch) {
          console.log("CRITICAL: Stream error:", errorMatch[0]);
        }
      }

      // Check for response completion signals
      const thumbsBtns = page.locator(
        'button[aria-label*="thumb" i], button[aria-label*="like" i], [class*="feedback"] button'
      );
      if ((await thumbsBtns.count()) > 0) {
        console.log("Response completed at iteration", i);
        completed = true;
        break;
      }

      // Also check for text response presence
      if (
        text?.includes("don\u2019t have information") ||
        text?.includes("I don't have") ||
        text?.includes("document policy") ||
        text?.includes("knowledge base")
      ) {
        console.log("Response text detected at iteration", i);
        completed = true;
        break;
      }
    }

    await page.screenshot({
      path: `${SHOTS}/05-response-complete.png`,
      fullPage: true,
    });

    const finalBody = await page.textContent("body");
    console.log("Completed:", completed);
    console.log("Has response text:", (finalBody?.length ?? 0) > 200);
    console.log(
      "Has Stream error:",
      finalBody?.includes("Stream error") || false
    );
    console.log("Has vector_search error:", finalBody?.includes("vector") && finalBody?.includes("error") || false);

    // Check for pgvector-specific error indicators
    const pgvectorErrors = net_errors.filter(
      (e) =>
        e.includes("chat/stream") ||
        e.includes("search") ||
        e.includes("vector")
    );
    console.log("pgvector-related network errors:", pgvectorErrors.length);
    pgvectorErrors.forEach((e) => console.log("  PGVEC ERR:", e));

    // Overall network errors
    const significant = net_errors.filter(
      (e) => !e.includes("notifications/stream") && !e.includes("401")
    );
    console.log("Significant network errors:", significant.length);
    significant.forEach((e) => console.log("  NET:", e));

    console.log("Console errors:", console_errors.length);
    if (console_errors.length > 0) {
      console.log("  First 5:", console_errors.slice(0, 5).join(" | "));
    }
    console.log("=== END FLOW-B ===");
  });

  test("FLOW-C: Second chat query (no pgvector crash)", async ({ page }) => {
    const { net_errors } = collectErrors(page);

    await login(page, EU.email, EU.pass);
    await page.waitForTimeout(2000);

    console.log("=== FLOW-C: SECOND QUERY ===");

    const textarea = page.locator("textarea").first();
    await textarea.waitFor({ state: "visible", timeout: 10000 });

    // Send first query
    await textarea.fill("Tell me about revenue analysis");
    const sendBtn = page.locator('button[type="submit"]').first();
    if (await sendBtn.isVisible()) {
      await sendBtn.click();
    } else {
      await textarea.press("Enter");
    }

    // Wait for response
    for (let i = 0; i < 15; i++) {
      await page.waitForTimeout(3000);
      const text = await page.textContent("body");
      if (
        text?.includes("revenue") ||
        text?.includes("analysis") ||
        text?.includes("don\u2019t have") ||
        text?.includes("I don't have")
      ) {
        console.log("First response detected at iteration", i);
        break;
      }
    }

    await page.screenshot({
      path: `${SHOTS}/06-second-query-response.png`,
      fullPage: true,
    });

    // Check for 500 errors that would indicate pgvector failures
    const serverErrors = net_errors.filter((e) => e.startsWith("5"));
    console.log("Server errors (5xx):", serverErrors.length);
    serverErrors.forEach((e) => console.log("  5xx:", e));

    // Check browser console for pgvector errors
    const chatStreamErrors = net_errors.filter((e) =>
      e.includes("chat/stream")
    );
    console.log("Chat stream errors:", chatStreamErrors.length);

    console.log("=== END FLOW-C ===");
  });

  test("FLOW-D: Tenant Admin — Documents tab", async ({ page }) => {
    const { net_errors } = collectErrors(page);

    await login(page, TA.email, TA.pass);
    await page.waitForTimeout(2000);

    console.log("=== FLOW-D: TA DOCUMENTS ===");
    console.log("After login URL:", page.url());

    await page.screenshot({
      path: `${SHOTS}/07-ta-dashboard.png`,
      fullPage: true,
    });

    // Navigate to Documents (admin/sync or settings/knowledge-base)
    const docsLink = page.locator(
      'a:has-text("Documents"), a:has-text("Knowledge"), a[href*="sync"], a[href*="knowledge"]'
    );
    if ((await docsLink.count()) > 0) {
      await docsLink.first().click();
      await page.waitForTimeout(3000);
      console.log("Documents page URL:", page.url());
    } else {
      // Try direct navigation
      await page.goto(`${BASE}/admin/sync`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3000);
      console.log("Direct nav to /admin/sync, URL:", page.url());
    }

    await page.screenshot({
      path: `${SHOTS}/08-ta-documents.png`,
      fullPage: true,
    });

    const body = await page.textContent("body");
    console.log("Has Documents content:", body?.includes("Document") || body?.includes("Knowledge") || body?.includes("SharePoint"));

    // Check for connection errors
    const serverErrors = net_errors.filter((e) => e.startsWith("5"));
    console.log("Server errors:", serverErrors.length);
    serverErrors.forEach((e) => console.log("  5xx:", e));

    console.log("=== END FLOW-D ===");
  });

  test("FLOW-E: Platform Admin — Tenant provisioning (pgvector check)", async ({
    page,
  }) => {
    const { net_errors } = collectErrors(page);

    await login(page, PA.email, PA.pass);
    await page.waitForTimeout(2000);

    console.log("=== FLOW-E: PA TENANTS (pgvector provisioning) ===");
    console.log("After login URL:", page.url());

    await page.screenshot({
      path: `${SHOTS}/09-pa-dashboard.png`,
      fullPage: true,
    });

    // Navigate to Tenants
    const tenantsLink = page.locator(
      'a:has-text("Tenants"), a[href*="tenants"]'
    );
    if ((await tenantsLink.count()) > 0) {
      await tenantsLink.first().click();
      await page.waitForTimeout(3000);
    } else {
      await page.goto(`${BASE}/platform/tenants`, {
        waitUntil: "domcontentloaded",
      });
      await page.waitForTimeout(3000);
    }

    console.log("Tenants page URL:", page.url());
    await page.screenshot({
      path: `${SHOTS}/10-pa-tenants.png`,
      fullPage: true,
    });

    // Look for TPC Group tenant and click into it
    const tpcRow = page.locator('text="TPC Group"');
    if ((await tpcRow.count()) > 0) {
      await tpcRow.first().click();
      await page.waitForTimeout(3000);

      await page.screenshot({
        path: `${SHOTS}/11-pa-tenant-detail.png`,
        fullPage: true,
      });

      const detail = await page.textContent("body");
      // Look for provisioning events mentioning pgvector
      console.log(
        "Has pgvector mention:",
        detail?.includes("pgvector") || false
      );
      console.log(
        "Has HNSW mention:",
        detail?.includes("HNSW") || detail?.includes("hnsw") || false
      );
      console.log(
        "Has search_index mention:",
        detail?.includes("search_index") ||
          detail?.includes("create_search_index") ||
          false
      );
      console.log(
        "Has provisioning events:",
        detail?.includes("provision") || detail?.includes("Provision") || false
      );
    } else {
      console.log("TPC Group tenant not found in list");
    }

    const serverErrors = net_errors.filter((e) => e.startsWith("5"));
    console.log("Server errors:", serverErrors.length);
    console.log("=== END FLOW-E ===");
  });
});
