import { test, expect, type Page, type BrowserContext } from "@playwright/test";

const BASE_URL = "http://localhost:3022";
const SCREENSHOT_DIR = "tests/e2e/screenshots/eu-value-audit";

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

async function goToChat(page: Page, context: BrowserContext) {
  const token = createEndUserJWT();
  await context.addCookies([
    { name: "access_token", value: token, domain: "localhost", path: "/" },
  ]);
  await page.goto(`${BASE_URL}/chat`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000); // Let UI render and API calls settle
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return errors;
}

function collectNetworkErrors(page: Page): string[] {
  const netErrors: string[] = [];
  page.on("response", (resp) => {
    if (resp.url().includes("/api/") && resp.status() >= 400) {
      netErrors.push(`${resp.status()} ${resp.url().replace(BASE_URL, "")}`);
    }
  });
  return netErrors;
}

test.describe("EU Value Audit - End User Flows", () => {
  test.setTimeout(120000);

  test("EU-FLOW-1: Login Page Audit", async ({ page }) => {
    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2000);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/01-login-page.png`,
      fullPage: true,
    });

    const content = await page.textContent("body");
    console.log("=== EU-FLOW-1: LOGIN PAGE ===");
    console.log("Has mingai branding:", content?.includes("mingai"));
    console.log(
      "Has Enterprise RAG Platform:",
      content?.includes("Enterprise RAG Platform"),
    );
    console.log("Has email input:", (await page.locator("#email").count()) > 0);
    console.log(
      "Has password input:",
      (await page.locator("#password").count()) > 0,
    );
    console.log("Has sign in button:", content?.includes("Sign in"));
    console.log(
      "Has secure login text:",
      content?.includes("Secure enterprise login"),
    );
    console.log("=== END EU-FLOW-1 LOGIN ===");
  });

  test("EU-FLOW-1b: Chat Empty State Audit", async ({ page, context }) => {
    const errors = collectConsoleErrors(page);
    const netErrors = collectNetworkErrors(page);
    await goToChat(page, context);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/02-chat-empty-state.png`,
      fullPage: true,
    });

    console.log("=== EU-FLOW-1b: CHAT EMPTY STATE ===");
    console.log("URL:", page.url());

    const body = await page.textContent("body");

    // Empty state elements
    console.log(
      "Has greeting:",
      body?.includes("Good") || body?.includes("Hello") || body?.includes("Hi"),
    );
    console.log("Has subtitle:", body?.includes("What would you like to know"));
    console.log(
      "Has 'Ask anything' placeholder:",
      body?.includes("Ask anything"),
    );

    // KB hint
    console.log("Has KB hint (SharePoint):", body?.includes("SharePoint"));
    console.log("Has KB hint (Google Drive):", body?.includes("Google Drive"));
    console.log(
      "Has KB hint (Knowledge base active):",
      body?.includes("Knowledge base active"),
    );

    // Suggestion chips
    console.log(
      "Has suggestion chips:",
      body?.includes("Outstanding invoices") || body?.includes("Annual leave"),
    );

    // Agent/mode selector
    console.log("Has Auto mode selector:", body?.includes("Auto"));

    // Sidebar
    console.log("Has HISTORY section:", body?.includes("HISTORY"));
    console.log("Has search history:", body?.includes("Search history"));

    // Privacy link
    console.log("Has Privacy link:", body?.includes("Privacy"));

    // Topbar
    console.log("Has End User badge:", body?.includes("End User"));

    // NEGATIVE checks (should NOT have admin nav)
    console.log(
      "Has Dashboard (SHOULD BE FALSE):",
      body?.includes("Dashboard"),
    );
    console.log(
      "Has Documents (SHOULD BE FALSE):",
      body?.includes("Documents") && !body?.includes("document"),
    );
    console.log(
      "Has Users (SHOULD BE FALSE):",
      body?.includes("Users") && !body?.includes("End User"),
    );

    // Button audit
    const buttons = page.locator("button:visible");
    const btnCount = await buttons.count();
    console.log("\nVisible buttons:", btnCount);
    for (let i = 0; i < Math.min(btnCount, 20); i++) {
      const text = (await buttons.nth(i).textContent())?.trim();
      const aria = await buttons.nth(i).getAttribute("aria-label");
      if (text || aria)
        console.log(`  btn[${i}]: "${text?.substring(0, 40)}" aria="${aria}"`);
    }

    console.log("\nNetwork errors:", netErrors.length);
    netErrors.forEach((e) => console.log("  NET:", e));
    console.log("Console errors:", errors.length);
    if (errors.length > 0)
      console.log("  First 3:", errors.slice(0, 3).join(" | "));
    console.log("=== END EU-FLOW-1b ===");
  });

  test("EU-FLOW-2: Chat Send & Stream", async ({ page, context }) => {
    const errors = collectConsoleErrors(page);
    const netErrors = collectNetworkErrors(page);
    await goToChat(page, context);

    console.log("=== EU-FLOW-2: CHAT SEND & STREAM ===");

    const textarea = page.locator("textarea").first();
    await textarea.waitFor({ state: "visible", timeout: 10000 });
    await textarea.fill("What is the annual leave policy?");

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/03-typed-message.png`,
      fullPage: true,
    });

    // Send
    const sendBtn = page.locator('button[type="submit"]').first();
    if (await sendBtn.isVisible()) {
      await sendBtn.click();
    } else {
      await textarea.press("Enter");
    }

    console.log("Message sent at:", new Date().toISOString());

    // Wait 5s for stream start
    await page.waitForTimeout(5000);
    await page.screenshot({
      path: `${SCREENSHOT_DIR}/04-streaming.png`,
      fullPage: true,
    });

    // Wait for stream completion (up to 45s more)
    for (let i = 0; i < 15; i++) {
      await page.waitForTimeout(3000);
      const text = await page.textContent("body");

      if (text?.includes("Stream error")) {
        console.log("CRITICAL: Stream error at iteration", i);
        break;
      }

      // Check for feedback/thumbs buttons appearing (signal of completion)
      const thumbs = page.locator(
        '[class*="feedback"] button, button[aria-label*="thumb" i]',
      );
      if ((await thumbs.count()) > 0) {
        console.log("Stream completed at iteration", i);
        break;
      }
    }

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/05-response-complete.png`,
      fullPage: true,
    });

    const finalBody = await page.textContent("body");
    console.log("Has Stream error:", finalBody?.includes("Stream error"));
    console.log(
      "Has leave/annual/policy content:",
      finalBody?.includes("leave") ||
        finalBody?.includes("annual") ||
        finalBody?.includes("policy"),
    );
    console.log(
      "Has agent indicator (AUTO/STANDARD):",
      finalBody?.includes("AUTO") || finalBody?.includes("STANDARD"),
    );
    console.log(
      "Has confidence:",
      finalBody?.includes("confidence") || finalBody?.match(/0\.\d/),
    );
    console.log(
      "Has sources:",
      finalBody?.includes("source") || finalBody?.includes("Source"),
    );

    // Feedback buttons check
    const allBtns = page.locator("button:visible");
    const btnCount = await allBtns.count();
    console.log("Buttons after response:", btnCount);
    for (let i = 0; i < Math.min(btnCount, 25); i++) {
      const t = (await allBtns.nth(i).textContent())?.trim();
      const a = await allBtns.nth(i).getAttribute("aria-label");
      const cls = (await allBtns.nth(i).getAttribute("class")) || "";
      if (
        cls.includes("feedback") ||
        cls.includes("thumb") ||
        a?.includes("thumb")
      ) {
        console.log(
          `  FEEDBACK btn[${i}]: "${t}" aria="${a}" class="${cls.substring(0, 60)}"`,
        );
      }
    }

    console.log("Network errors:", netErrors.length);
    netErrors.forEach((e) => console.log("  NET:", e));
    console.log("Console errors:", errors.length);
    console.log("=== END EU-FLOW-2 ===");
  });

  test("EU-FLOW-5+6: Sidebar & New Conversation", async ({ page, context }) => {
    const errors = collectConsoleErrors(page);
    await goToChat(page, context);

    console.log("=== EU-FLOW-5+6: SIDEBAR & NEW CONV ===");

    // Sidebar analysis
    const sidebar = page.locator("aside");
    if ((await sidebar.count()) > 0) {
      const sidebarText = await sidebar.first().textContent();
      console.log("Sidebar text:", sidebarText?.substring(0, 400));

      // Check for history entries
      console.log("Has HISTORY label:", sidebarText?.includes("HISTORY"));
      console.log("Has search:", sidebarText?.includes("Search"));

      // Count conversation entries (links in sidebar)
      const sidebarLinks = sidebar.locator("a");
      const linkCount = await sidebarLinks.count();
      console.log("Sidebar links:", linkCount);
      for (let i = 0; i < Math.min(linkCount, 8); i++) {
        const href = await sidebarLinks.nth(i).getAttribute("href");
        const text = (await sidebarLinks.nth(i).textContent())?.trim();
        console.log(`  [${i}]: "${text?.substring(0, 50)}" -> ${href}`);
      }
    }

    // New conversation button
    const plusBtn = page.locator("aside button, header button");
    const plusCount = await plusBtn.count();
    console.log("\nSidebar/header buttons:", plusCount);
    for (let i = 0; i < Math.min(plusCount, 10); i++) {
      const t = (await plusBtn.nth(i).textContent())?.trim();
      const a = await plusBtn.nth(i).getAttribute("aria-label");
      console.log(`  btn[${i}]: "${t?.substring(0, 30)}" aria="${a}"`);
    }

    // Try clicking the + button next to HISTORY
    const newConv = page.locator("aside button").first();
    if ((await newConv.count()) > 0) {
      try {
        await newConv.click();
        await page.waitForTimeout(2000);
        console.log("Clicked first sidebar button");

        const afterClick = await page.textContent("body");
        console.log(
          "After click has greeting:",
          afterClick?.includes("Good") || afterClick?.includes("Hello"),
        );
      } catch (e) {
        console.log("Click failed:", e);
      }
    }

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/06-sidebar.png`,
      fullPage: true,
    });
    console.log("=== END EU-FLOW-5+6 ===");
  });

  test("EU-FLOW-7: Agent/Mode Switching (Deep)", async ({ page, context }) => {
    const errors = collectConsoleErrors(page);
    await goToChat(page, context);

    console.log("=== EU-FLOW-7: AGENT/MODE SWITCHING ===");

    // Click the "Auto" dropdown
    const autoBtn = page.locator('button:has-text("Auto")');
    if ((await autoBtn.count()) > 0) {
      console.log("Found Auto button, clicking...");
      await autoBtn.first().click();
      await page.waitForTimeout(1000);

      await page.screenshot({
        path: `${SCREENSHOT_DIR}/07-mode-dropdown-open.png`,
        fullPage: true,
      });

      // Check dropdown options
      const options = page.locator(
        '[role="option"], [role="menuitem"], [class*="option"], li',
      );
      const optCount = await options.count();
      console.log("Dropdown options:", optCount);
      for (let i = 0; i < Math.min(optCount, 10); i++) {
        const t = (await options.nth(i).textContent())?.trim();
        console.log(`  Option[${i}]: "${t}"`);
      }

      // Also check for any popover/dropdown
      const dropdownText = await page.textContent("body");
      console.log(
        "Dropdown visible text contains HR:",
        dropdownText?.includes("HR"),
      );
      console.log(
        "Dropdown visible text contains IT:",
        dropdownText?.includes("IT"),
      );
      console.log(
        "Dropdown visible text contains Finance:",
        dropdownText?.includes("Finance"),
      );
      console.log(
        "Dropdown visible text contains General:",
        dropdownText?.includes("General"),
      );
      console.log(
        "Dropdown visible text contains Policy:",
        dropdownText?.includes("Policy"),
      );
      console.log(
        "Dropdown visible text contains Helpdesk:",
        dropdownText?.includes("Helpdesk"),
      );
      console.log(
        "Dropdown visible text contains Procurement:",
        dropdownText?.includes("Procurement"),
      );
    } else {
      console.log("FAIL: No Auto button found");
    }

    console.log("=== END EU-FLOW-7 ===");
  });

  test("EU-FLOW-8: Issue Reporting Check", async ({ page, context }) => {
    await goToChat(page, context);

    console.log("=== EU-FLOW-8: ISSUE REPORTING ===");

    // Check for floating report button
    const body = await page.textContent("body");
    const html = await page.innerHTML("body");

    console.log("Has Report Issue button (text):", body?.includes("Report"));
    console.log(
      "Has floating FAB (class):",
      html.includes("fab") ||
        html.includes("floating") ||
        html.includes("report-issue"),
    );

    // Check for Ctrl+Shift+F shortcut handler
    await page.keyboard.press("Control+Shift+KeyF");
    await page.waitForTimeout(1000);
    const afterShortcut = await page.textContent("body");
    console.log(
      "After Ctrl+Shift+F has dialog:",
      afterShortcut?.includes("Report Issue") ||
        afterShortcut?.includes("Title") ||
        afterShortcut?.includes("Description"),
    );

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/08-issue-reporting.png`,
      fullPage: true,
    });
    console.log("=== END EU-FLOW-8 ===");
  });

  test("EU-FLOW-9: Profile & Topbar", async ({ page, context }) => {
    await goToChat(page, context);

    console.log("=== EU-FLOW-9: PROFILE & TOPBAR ===");

    // Topbar analysis
    const body = await page.textContent("body");
    console.log("Has End User badge:", body?.includes("End User"));
    console.log("Has mingai branding:", body?.includes("mingai"));
    console.log("Has Privacy link:", body?.includes("Privacy"));

    // Check all topbar buttons
    const topbarBtns = page.locator(
      'header button, [class*="topbar"] button, nav button',
    );
    const tbCount = await topbarBtns.count();
    console.log("Topbar buttons:", tbCount);
    for (let i = 0; i < Math.min(tbCount, 10); i++) {
      const t = (await topbarBtns.nth(i).textContent())?.trim();
      const a = await topbarBtns.nth(i).getAttribute("aria-label");
      console.log(`  btn[${i}]: "${t?.substring(0, 30)}" aria="${a}"`);
    }

    // Try clicking avatar/profile (rightmost in topbar)
    const avatarBtns = page.locator('[class*="avatar"], button:has(img)');
    if ((await avatarBtns.count()) > 0) {
      await avatarBtns.first().click();
      await page.waitForTimeout(1000);
      const dropdown = await page.textContent("body");
      console.log(
        "Profile dropdown has Sign out:",
        dropdown?.includes("Sign out") || dropdown?.includes("Logout"),
      );
      console.log(
        "Profile dropdown has Memory:",
        dropdown?.includes("Memory") || dropdown?.includes("memory"),
      );
      await page.screenshot({
        path: `${SCREENSHOT_DIR}/09-profile-dropdown.png`,
        fullPage: true,
      });
    }

    // Try clicking Privacy link
    const privacyLink = page.locator(
      'a:has-text("Privacy"), button:has-text("Privacy")',
    );
    if ((await privacyLink.count()) > 0) {
      await privacyLink.first().click();
      await page.waitForTimeout(2000);
      console.log("Privacy page URL:", page.url());
      await page.screenshot({
        path: `${SCREENSHOT_DIR}/10-privacy.png`,
        fullPage: true,
      });
    }

    console.log("=== END EU-FLOW-9 ===");
  });
});
