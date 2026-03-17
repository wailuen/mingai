import { test, expect, type Page, type BrowserContext } from "@playwright/test";

const BASE_URL = "http://localhost:3022";
const SCREENSHOT_DIR = "tests/e2e/screenshots/eu-value-audit";

/**
 * Create a mock JWT for end-user role.
 * The Next.js middleware uses jwtDecode (client-side, no signature verification).
 */
function createEndUserJWT(): string {
  const header = { alg: "HS256", typ: "JWT" };
  const claims = {
    sub: "end-user-test-user",
    tenant_id: "test-tenant-001",
    roles: ["user"],
    scope: "tenant",
    plan: "professional",
    email: "user@tpcgroup.com.my",
    exp: Math.floor(Date.now() / 1000) + 86400,
  };
  const encode = (obj: object) =>
    Buffer.from(JSON.stringify(obj)).toString("base64url");
  return `${encode(header)}.${encode(claims)}.mock-signature`;
}

async function injectEndUserAuth(context: BrowserContext) {
  const token = createEndUserJWT();
  await context.addCookies([
    {
      name: "access_token",
      value: token,
      domain: "localhost",
      path: "/",
    },
  ]);
}

// Collect console errors
function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      errors.push(msg.text());
    }
  });
  return errors;
}

test.describe("EU Value Audit - End User Flows", () => {
  test.setTimeout(180000);

  test("EU-FLOW-1: Login Page & Chat Empty State", async ({
    page,
    context,
  }) => {
    const errors = collectConsoleErrors(page);

    // First screenshot: login page
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState("networkidle");
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/01-login-page.png`,
      fullPage: true,
    });

    console.log("=== EU-FLOW-1: LOGIN PAGE ===");
    const loginContent = await page.textContent("body");
    console.log(
      "Login page has email field:",
      !!(await page.locator('input[id="email"]').count()),
    );
    console.log(
      "Login page has password field:",
      !!(await page.locator('input[id="password"]').count()),
    );
    console.log(
      "Login page has submit button:",
      !!(await page.locator('button[type="submit"]').count()),
    );
    console.log(
      "Login page shows mingai branding:",
      loginContent?.includes("mingai"),
    );

    // Now inject auth and go to chat
    await injectEndUserAuth(context);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3000);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/02-chat-empty-state.png`,
      fullPage: true,
    });

    console.log("\n=== EU-FLOW-1: CHAT EMPTY STATE ===");
    console.log("URL:", page.url());

    const bodyText = await page.textContent("body");
    console.log("Page text (first 500):", bodyText?.substring(0, 500));

    // Check empty state elements
    console.log(
      "\nHas greeting:",
      bodyText?.includes("Hello") ||
        bodyText?.includes("Welcome") ||
        bodyText?.includes("Hi") ||
        bodyText?.includes("How can"),
    );

    // Check input area
    const textarea = page.locator("textarea");
    const textareaCount = await textarea.count();
    console.log("Textarea count:", textareaCount);
    if (textareaCount > 0) {
      const placeholder = await textarea.first().getAttribute("placeholder");
      console.log("Textarea placeholder:", placeholder);
    }

    // Check sidebar
    const sidebar = page.locator("aside");
    if ((await sidebar.count()) > 0) {
      const sidebarText = await sidebar.first().textContent();
      console.log("\nSidebar text:", sidebarText?.substring(0, 300));

      // Verify sidebar has history NOT admin nav
      console.log(
        "Sidebar has admin items (SHOULD BE FALSE):",
        sidebarText?.includes("Dashboard") ||
          sidebarText?.includes("Settings") ||
          sidebarText?.includes("Documents") ||
          sidebarText?.includes("Users"),
      );
    } else {
      console.log("No <aside> sidebar found");
    }

    // Check for KB hint
    console.log(
      "\nHas KB hint (documents/indexed):",
      bodyText?.includes("document") || bodyText?.includes("indexed"),
    );

    // Check for suggestion chips
    console.log(
      "Has suggestion-like chips:",
      bodyText?.includes("How") ||
        bodyText?.includes("Tell me") ||
        bodyText?.includes("What"),
    );

    // Check for agent/mode selector
    const modeElements = page.locator(
      '[class*="mode"], [class*="agent"], [class*="selector"], select, [role="combobox"]',
    );
    console.log("Mode/agent selector elements:", await modeElements.count());

    // Dump all buttons
    const buttons = page.locator("button:visible");
    const btnCount = await buttons.count();
    console.log("\nAll visible buttons (" + btnCount + "):");
    for (let i = 0; i < Math.min(btnCount, 25); i++) {
      const text = (await buttons.nth(i).textContent())?.trim();
      const aria = await buttons.nth(i).getAttribute("aria-label");
      const title = await buttons.nth(i).getAttribute("title");
      if (text || aria || title) {
        console.log(
          `  [${i}] text="${text?.substring(0, 40)}" aria="${aria}" title="${title}"`,
        );
      }
    }

    // Dump all links
    const links = page.locator("a[href]:visible");
    const linkCount = await links.count();
    console.log("\nAll visible links (" + linkCount + "):");
    for (let i = 0; i < Math.min(linkCount, 15); i++) {
      const href = await links.nth(i).getAttribute("href");
      const text = (await links.nth(i).textContent())?.trim();
      console.log(`  ${href}: "${text?.substring(0, 50)}"`);
    }

    console.log("\nConsole errors:", errors.length);
    errors.forEach((e) => console.log("  ERR:", e.substring(0, 150)));
    console.log("=== END EU-FLOW-1 ===");
  });

  test("EU-FLOW-2: First Chat Message & Stream", async ({ page, context }) => {
    const errors = collectConsoleErrors(page);
    await injectEndUserAuth(context);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3000);

    console.log("=== EU-FLOW-2: CHAT MESSAGE & STREAM ===");

    // Find and fill input
    const textarea = page.locator("textarea");
    if ((await textarea.count()) === 0) {
      console.log("CRITICAL FAIL: No textarea found on chat page");
      await page.screenshot({
        path: `${SCREENSHOT_DIR}/03-no-textarea.png`,
        fullPage: true,
      });
      return;
    }

    await textarea.first().fill("What is the annual leave policy?");
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/03-typed-message.png`,
      fullPage: true,
    });

    // Find send button
    const sendBtn = page
      .locator('button[type="submit"], button[aria-label*="Send"]')
      .first();
    if (await sendBtn.isVisible()) {
      await sendBtn.click();
    } else {
      await textarea.first().press("Enter");
    }

    console.log("Message sent at:", new Date().toISOString());

    // Wait for streaming to start (3s)
    await page.waitForTimeout(3000);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/04-streaming.png`,
      fullPage: true,
    });

    // Wait for response to complete (up to 60s)
    let streamComplete = false;
    let streamError = false;

    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(2000);
      const text = await page.textContent("body");

      if (text?.includes("Stream error") || text?.includes("stream error")) {
        streamError = true;
        console.log("STREAM ERROR detected at iteration", i);
        break;
      }

      // Check if response seems complete by looking for stable content
      // Also check for feedback buttons (thumbs)
      const feedbackBtns = page.locator(
        'button[aria-label*="thumb"], button[aria-label*="like"], [class*="feedback"] button',
      );
      if ((await feedbackBtns.count()) > 0) {
        streamComplete = true;
        console.log("Stream completed (feedback buttons visible) at iter", i);
        break;
      }

      // Check for response text
      if (i > 8) {
        // After ~20s, if we have substantial text, consider done
        if (text && text.length > 500) {
          streamComplete = true;
          console.log("Stream likely complete (long text) at iter", i);
          break;
        }
      }
    }

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/05-response-complete.png`,
      fullPage: true,
    });

    const finalText = await page.textContent("body");

    console.log("\nStream error:", streamError);
    console.log("Stream complete:", streamComplete);
    console.log(
      "Has 'Stream error' text:",
      finalText?.includes("Stream error"),
    );
    console.log(
      "Has leave/annual/policy content:",
      finalText?.includes("leave") ||
        finalText?.includes("annual") ||
        finalText?.includes("policy"),
    );
    console.log(
      "Has agent indicator:",
      finalText?.includes("AUTO") ||
        finalText?.includes("STANDARD") ||
        finalText?.includes("Agent"),
    );
    console.log(
      "Has confidence:",
      finalText?.includes("confidence") || finalText?.includes("0."),
    );
    console.log(
      "Has sources:",
      finalText?.includes("source") || finalText?.includes("Source"),
    );

    // Check for feedback UI
    const allBtns = page.locator("button:visible");
    const btnTexts: string[] = [];
    for (let i = 0; i < (await allBtns.count()); i++) {
      const t = (await allBtns.nth(i).textContent())?.trim();
      const a = await allBtns.nth(i).getAttribute("aria-label");
      if (t || a) btnTexts.push(`"${t?.substring(0, 30)}" (aria: ${a})`);
    }
    console.log("\nButtons after response:", btnTexts.join(" | "));

    console.log("Console errors:", errors.length);
    errors.forEach((e) => console.log("  ERR:", e.substring(0, 150)));
    console.log("=== END EU-FLOW-2 ===");
  });

  test("EU-FLOW-4+5+6: Feedback, Sidebar, New Conversation", async ({
    page,
    context,
  }) => {
    const errors = collectConsoleErrors(page);
    await injectEndUserAuth(context);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);

    console.log("=== EU-FLOW-4+5+6: FEEDBACK, SIDEBAR, NEW CONV ===");

    // Send a message
    const textarea = page.locator("textarea").first();
    await textarea.waitFor({ state: "visible", timeout: 10000 });
    await textarea.fill("What are the expense claim guidelines?");

    const sendBtn = page
      .locator('button[type="submit"], button[aria-label*="Send"]')
      .first();
    if (await sendBtn.isVisible()) {
      await sendBtn.click();
    } else {
      await textarea.press("Enter");
    }

    // Wait for response
    await page.waitForTimeout(25000);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/06-response-for-feedback.png`,
      fullPage: true,
    });

    const bodyAfterResp = await page.textContent("body");
    console.log("Has Stream error:", bodyAfterResp?.includes("Stream error"));

    // === FEEDBACK (EU-FLOW-4) ===
    console.log("\n--- EU-FLOW-4: FEEDBACK ---");

    // Look for thumbs up/down
    const thumbSelectors = [
      'button[aria-label*="thumb"]',
      'button[aria-label*="like"]',
      'button[aria-label*="Thumb"]',
      '[class*="feedback"] button',
      '[class*="thumb"]',
    ];

    let thumbsFound = false;
    for (const sel of thumbSelectors) {
      const count = await page.locator(sel).count();
      if (count > 0) {
        thumbsFound = true;
        console.log(`Found feedback via: ${sel} (${count})`);
        // Try clicking first one (thumbs up)
        try {
          await page.locator(sel).first().click();
          await page.waitForTimeout(1000);
          console.log("Clicked feedback button successfully");
          await page.screenshot({
            path: `${SCREENSHOT_DIR}/07-after-feedback.png`,
            fullPage: true,
          });
        } catch (e) {
          console.log("Click failed:", e);
        }
        break;
      }
    }

    if (!thumbsFound) {
      // Scan all SVGs/icons for thumb-like elements
      const svgButtons = page.locator("button:has(svg)");
      const svgCount = await svgButtons.count();
      console.log("Buttons with SVGs:", svgCount);
      for (let i = 0; i < Math.min(svgCount, 10); i++) {
        const aria = await svgButtons.nth(i).getAttribute("aria-label");
        const title = await svgButtons.nth(i).getAttribute("title");
        const cls = await svgButtons.nth(i).getAttribute("class");
        console.log(
          `  SVG btn[${i}]: aria="${aria}" title="${title}" class="${cls?.substring(0, 60)}"`,
        );
      }
      console.log("FAIL: No feedback thumbs found");
    }

    // === SIDEBAR (EU-FLOW-5) ===
    console.log("\n--- EU-FLOW-5: SIDEBAR ---");

    const sidebar = page.locator("aside");
    if ((await sidebar.count()) > 0) {
      const sidebarText = await sidebar.first().textContent();
      console.log("Sidebar text:", sidebarText?.substring(0, 400));

      // Look for conversation entries
      const convEntries = sidebar.locator("a, button");
      const entryCount = await convEntries.count();
      console.log("Sidebar entries:", entryCount);
      for (let i = 0; i < Math.min(entryCount, 8); i++) {
        const text = (await convEntries.nth(i).textContent())?.trim();
        const href = await convEntries.nth(i).getAttribute("href");
        console.log(
          `  Entry[${i}]: "${text?.substring(0, 50)}" href="${href}"`,
        );
      }
    } else {
      console.log("No sidebar found");
    }

    // === NEW CONVERSATION (EU-FLOW-6) ===
    console.log("\n--- EU-FLOW-6: NEW CONVERSATION ---");

    // Look for new conversation button
    const newConvSelectors = [
      'button[aria-label*="new" i]',
      'button[aria-label*="New" i]',
      'button[aria-label*="compose" i]',
      'button[title*="new" i]',
      'button[title*="New" i]',
      'a[href="/chat"]',
    ];

    let newConvFound = false;
    for (const sel of newConvSelectors) {
      const count = await page.locator(sel).count();
      if (count > 0) {
        newConvFound = true;
        console.log(`Found new conv button via: ${sel}`);
        await page.locator(sel).first().click();
        await page.waitForTimeout(2000);

        await page.screenshot({
          path: `${SCREENSHOT_DIR}/08-new-conversation.png`,
          fullPage: true,
        });

        const resetText = await page.textContent("body");
        console.log(
          "Chat reset to empty state:",
          resetText?.includes("Hello") ||
            resetText?.includes("Welcome") ||
            resetText?.includes("How can"),
        );
        break;
      }
    }

    if (!newConvFound) {
      console.log("No new conversation button found. Listing all buttons:");
      const btns = page.locator("button:visible");
      for (let i = 0; i < Math.min(await btns.count(), 15); i++) {
        const t = (await btns.nth(i).textContent())?.trim();
        const a = await btns.nth(i).getAttribute("aria-label");
        console.log(`  btn[${i}]: "${t?.substring(0, 40)}" aria="${a}"`);
      }
    }

    console.log("\nConsole errors:", errors.length);
    errors.forEach((e) => console.log("  ERR:", e.substring(0, 150)));
    console.log("=== END EU-FLOW-4+5+6 ===");
  });

  test("EU-FLOW-7: Agent/Mode Switching", async ({ page, context }) => {
    const errors = collectConsoleErrors(page);
    await injectEndUserAuth(context);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);

    console.log("=== EU-FLOW-7: AGENT/MODE SWITCHING ===");

    const bodyText = await page.textContent("body");

    // Look for mode/agent selector elements
    const selectorPatterns = [
      '[class*="mode"]',
      '[class*="agent"]',
      '[class*="selector"]',
      "select",
      '[role="combobox"]',
      '[role="listbox"]',
      '[class*="dropdown"]',
      '[class*="chip"]',
    ];

    for (const sel of selectorPatterns) {
      const count = await page.locator(sel).count();
      if (count > 0) {
        console.log(`Found: ${sel} (${count})`);
        // Try clicking first
        try {
          await page.locator(sel).first().click();
          await page.waitForTimeout(500);

          // Check for dropdown options
          const options = page.locator(
            '[role="option"], [role="menuitem"], li[class*="item"]',
          );
          const optCount = await options.count();
          if (optCount > 0) {
            console.log(`Dropdown opened with ${optCount} options`);
            for (let i = 0; i < Math.min(optCount, 5); i++) {
              const optText = await options.nth(i).textContent();
              console.log(`  Option: "${optText?.trim()}"`);
            }
          }
        } catch {
          // ignore
        }
      }
    }

    // Check for Auto/HR/IT text indicators
    console.log(
      "\nHas 'Auto' text:",
      bodyText?.includes("Auto") || bodyText?.includes("auto"),
    );
    console.log(
      "Has 'HR' text:",
      bodyText?.includes("HR") || bodyText?.includes("Policy"),
    );
    console.log("Has 'IT' text:", bodyText?.includes("IT"));
    console.log("Has 'General' text:", bodyText?.includes("General"));
    console.log("Has 'Finance' text:", bodyText?.includes("Finance"));

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/09-agent-mode.png`,
      fullPage: true,
    });

    console.log("Console errors:", errors.length);
    console.log("=== END EU-FLOW-7 ===");
  });

  test("EU-FLOW-8+9: Issue Reporting & Profile/Memory", async ({
    page,
    context,
  }) => {
    const errors = collectConsoleErrors(page);
    await injectEndUserAuth(context);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);

    console.log("=== EU-FLOW-8: ISSUE REPORTING ===");

    // Look for Report Issue FAB
    const fabSelectors = [
      'button[aria-label*="report" i]',
      'button[title*="report" i]',
      '[class*="fab"]',
      '[class*="report"]',
      '[class*="floating"]',
    ];

    let fabFound = false;
    for (const sel of fabSelectors) {
      const count = await page.locator(sel).count();
      if (count > 0) {
        fabFound = true;
        console.log(`Report button found: ${sel}`);
        break;
      }
    }

    if (!fabFound) {
      // Try keyboard shortcut
      await page.keyboard.press("Control+Shift+KeyF");
      await page.waitForTimeout(1000);
      const afterShortcut = await page.textContent("body");
      console.log(
        "After Ctrl+Shift+F, has report dialog:",
        afterShortcut?.includes("Report") || afterShortcut?.includes("Issue"),
      );
    }

    console.log("Report Issue FAB found:", fabFound);

    // === PROFILE & MEMORY (EU-FLOW-9) ===
    console.log("\n=== EU-FLOW-9: PROFILE & MEMORY ===");

    // Check topbar for profile elements
    const profileSelectors = [
      '[class*="avatar"]',
      '[class*="profile"]',
      'button[aria-label*="user" i]',
      'button[aria-label*="profile" i]',
      'button[aria-label*="account" i]',
      'img[alt*="avatar" i]',
    ];

    let profileFound = false;
    for (const sel of profileSelectors) {
      const count = await page.locator(sel).count();
      if (count > 0) {
        profileFound = true;
        console.log(`Profile element found: ${sel}`);
        try {
          await page.locator(sel).first().click();
          await page.waitForTimeout(1000);
          await page.screenshot({
            path: `${SCREENSHOT_DIR}/10-profile-dropdown.png`,
            fullPage: true,
          });
          const dropdownText = await page.textContent("body");
          console.log(
            "Dropdown has Memory:",
            dropdownText?.includes("Memory") ||
              dropdownText?.includes("memory"),
          );
          console.log(
            "Dropdown has Settings:",
            dropdownText?.includes("Settings"),
          );
          console.log(
            "Dropdown has Sign out:",
            dropdownText?.includes("Sign out") ||
              dropdownText?.includes("Logout"),
          );
        } catch {
          // ignore
        }
        break;
      }
    }

    console.log("Profile element found:", profileFound);

    // Try direct navigation to settings/memory pages
    await page.goto(`${BASE_URL}/settings`);
    await page.waitForTimeout(2000);
    console.log("Settings page URL:", page.url());
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/11-settings.png`,
      fullPage: true,
    });

    console.log("Console errors:", errors.length);
    errors.forEach((e) => console.log("  ERR:", e.substring(0, 150)));
    console.log("=== END EU-FLOW-8+9 ===");
  });

  test("EU-COMPREHENSIVE: Full chat page DOM audit", async ({
    page,
    context,
  }) => {
    const errors = collectConsoleErrors(page);
    await injectEndUserAuth(context);
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3000);

    console.log("=== COMPREHENSIVE DOM AUDIT ===");
    console.log("URL:", page.url());

    // Full visible text
    const allText = await page.textContent("body");
    console.log("\nFull page text (first 1500):");
    console.log(allText?.substring(0, 1500));

    // Check structural elements
    console.log("\n--- STRUCTURAL ELEMENTS ---");
    const structures = {
      aside: await page.locator("aside").count(),
      nav: await page.locator("nav").count(),
      main: await page.locator("main").count(),
      header: await page.locator("header").count(),
      footer: await page.locator("footer").count(),
      form: await page.locator("form").count(),
      textarea: await page.locator("textarea").count(),
      select: await page.locator("select").count(),
    };
    console.log("DOM structure:", JSON.stringify(structures));

    // All form elements with details
    const inputs = page.locator(
      "input:visible, textarea:visible, select:visible",
    );
    const inputCount = await inputs.count();
    console.log("\nForm elements:");
    for (let i = 0; i < inputCount; i++) {
      const tag = await inputs.nth(i).evaluate((el) => el.tagName);
      const type = await inputs.nth(i).getAttribute("type");
      const placeholder = await inputs.nth(i).getAttribute("placeholder");
      const name = await inputs.nth(i).getAttribute("name");
      console.log(
        `  ${tag} type="${type}" name="${name}" placeholder="${placeholder}"`,
      );
    }

    // Check for network requests (API calls) during page load
    console.log("\n--- API CALLS ---");
    const responses: string[] = [];
    page.on("response", (resp) => {
      if (resp.url().includes("/api/")) {
        responses.push(`${resp.status()} ${resp.url()}`);
      }
    });

    // Reload to capture API calls
    await page.reload();
    await page.waitForTimeout(3000);

    console.log("API responses during load:");
    responses.forEach((r) => console.log("  " + r));

    // Check for data-testid attributes (testing infrastructure)
    const testIds = page.locator("[data-testid]");
    const testIdCount = await testIds.count();
    console.log("\nData-testid elements:", testIdCount);
    for (let i = 0; i < Math.min(testIdCount, 15); i++) {
      const id = await testIds.nth(i).getAttribute("data-testid");
      console.log(`  ${id}`);
    }

    console.log("\nConsole errors:", errors.length);
    errors.forEach((e) => console.log("  ERR:", e.substring(0, 200)));
    console.log("=== END COMPREHENSIVE ===");
  });
});
