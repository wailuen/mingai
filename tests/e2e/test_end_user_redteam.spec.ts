import { test, expect, Page } from "@playwright/test";
import { injectEndUserAuth } from "./helpers";

const BASE = "http://localhost:3022";

/**
 * Red-team validation of ALL End User flows per:
 *   - workspaces/mingai/03-user-flows/03-end-user-flows.md
 *   - workspaces/mingai/03-user-flows/17-role-first-login-flows.md
 *
 * Each test documents EXACTLY what is observed and what deviates from the spec.
 */

test.describe("Red Team: End User Flows", () => {
  // ── Flow 1: Login & First Experience ───────────────────────────
  test.describe("Flow 1: End User Login & First Experience", () => {
    test("1a: Login form loads and accepts credentials", async ({ page }) => {
      await page.goto(`${BASE}/login`);
      await page.waitForLoadState("networkidle");

      // Capture login page
      await page.screenshot({
        path: "playwright-report/redteam/flow1-login-page.png",
        fullPage: true,
      });

      // Verify login form elements
      const emailInput = page.locator('input[type="email"], input#email');
      const passwordInput = page.locator(
        'input[type="password"], input#password',
      );
      const submitBtn = page.locator('button[type="submit"]');

      console.log(
        "[Flow 1a] Email input visible:",
        await emailInput.isVisible(),
      );
      console.log(
        "[Flow 1a] Password input visible:",
        await passwordInput.isVisible(),
      );
      console.log(
        "[Flow 1a] Submit button visible:",
        await submitBtn.isVisible(),
      );

      // Fill credentials and submit
      await emailInput.fill("user@mingai.test");
      await passwordInput.fill("User1234!");
      await submitBtn.click();

      // Wait for navigation
      await page.waitForTimeout(3000);
      await page.waitForLoadState("networkidle");

      const finalUrl = page.url();
      console.log("[Flow 1a] Post-login URL:", finalUrl);
      await page.screenshot({
        path: "playwright-report/redteam/flow1-post-login.png",
        fullPage: true,
      });

      // EXPECTED: Should land on /chat (not /settings/dashboard or /platform)
      const landsOnChat = finalUrl.includes("/chat");
      const landsOnAdmin = finalUrl.includes("/settings/dashboard");
      const landsOnPlatform = finalUrl.includes("/platform");
      console.log("[Flow 1a] Lands on /chat:", landsOnChat);
      console.log("[Flow 1a] Lands on admin:", landsOnAdmin);
      console.log("[Flow 1a] Lands on platform:", landsOnPlatform);

      if (!landsOnChat) {
        console.log(
          "[Flow 1a] BUG: End user should land on /chat, got:",
          finalUrl,
        );
      }
    });

    test("1b: End user sidebar shows HISTORY ONLY (no admin nav)", async ({
      context,
      page,
    }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      await page.screenshot({
        path: "playwright-report/redteam/flow1-sidebar.png",
        fullPage: true,
      });

      // Check sidebar content
      const sidebarEl = page.locator("aside");
      const sidebarText = await sidebarEl.textContent();
      console.log("[Flow 1b] Sidebar text:", sidebarText);

      // EXPECTED: Should contain "New" or conversation list
      // MUST NOT contain: Dashboard, Documents, Users, Agents, Glossary, Analytics, Issues, Settings
      const adminTerms = [
        "Dashboard",
        "Documents",
        "Users",
        "Agents",
        "Glossary",
        "Analytics",
        "Issues",
        "Settings",
        "Workspace",
        "Insights",
      ];
      const foundAdminTerms: string[] = [];
      for (const term of adminTerms) {
        if (sidebarText?.includes(term)) {
          foundAdminTerms.push(term);
        }
      }

      if (foundAdminTerms.length > 0) {
        console.log(
          "[Flow 1b] BUG: Admin navigation found in end-user sidebar:",
          foundAdminTerms,
        );
      } else {
        console.log("[Flow 1b] PASS: No admin navigation in sidebar");
      }

      // Check for Privacy link at bottom
      const privacyLink = page.locator('a[href="/settings/privacy"]');
      const hasPrivacy = (await privacyLink.count()) > 0;
      console.log("[Flow 1b] Privacy link present:", hasPrivacy);

      // Check for New Chat button
      const newChatBtn = page.locator("button, a").filter({ hasText: /new/i });
      console.log("[Flow 1b] New Chat button count:", await newChatBtn.count());
    });

    test("1c: Empty state layout - centered greeting", async ({
      context,
      page,
    }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      await page.screenshot({
        path: "playwright-report/redteam/flow1-empty-state.png",
        fullPage: true,
      });

      const mainContent = page.locator("main");
      const mainText = await mainContent.textContent();
      console.log("[Flow 1c] Main area text:", mainText?.substring(0, 500));

      // EXPECTED per spec: agent icon (diamond/hex), greeting, subtitle, input bar embedded (NOT fixed), KB hint below input, suggestion chips
      // Check greeting text
      const hasGreeting =
        mainText?.includes("Good morning") ||
        mainText?.includes("Good afternoon") ||
        mainText?.includes("Good evening");
      console.log("[Flow 1c] Has time-based greeting:", hasGreeting);

      // Check for "What would you like to know today?"
      const hasSubtitle = mainText?.includes("What would you like to know");
      console.log("[Flow 1c] Has subtitle:", hasSubtitle);

      // Check for suggestion chips
      const hasSuggestions =
        mainText?.includes("invoices") ||
        mainText?.includes("Salary") ||
        mainText?.includes("leave policy") ||
        mainText?.includes("Contract");
      console.log("[Flow 1c] Has suggestion chips:", hasSuggestions);

      // Check for KB hint (should NOT contain "RAG")
      const hasRAG = mainText?.includes("RAG");
      if (hasRAG) {
        console.log(
          "[Flow 1c] BUG: 'RAG' term visible to end user (banned per design system)",
        );
      }

      // Check textarea/input present
      const chatInput = page.locator("textarea");
      const hasInput = (await chatInput.count()) > 0;
      console.log("[Flow 1c] Chat input (textarea) present:", hasInput);
    });

    test("1d: Mode selector in input bar", async ({ context, page }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      // Look for mode selector button (Auto / Research)
      const modeBtn = page
        .locator("button")
        .filter({ hasText: /Auto|Research/i });
      const modeBtnCount = await modeBtn.count();
      console.log("[Flow 1d] Mode selector button count:", modeBtnCount);

      if (modeBtnCount > 0) {
        const modeText = await modeBtn.first().textContent();
        console.log("[Flow 1d] Mode selector default text:", modeText);
      } else {
        console.log("[Flow 1d] BUG: No mode selector found");
      }
    });
  });

  // ── Flow 2: Mode Selector / Agent Selection ───────────────────
  test.describe("Flow 2: Mode Selector / Agent Selection", () => {
    test("2a: Mode selector shows available modes", async ({
      context,
      page,
    }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      // Find and click the mode selector
      const modeBtn = page
        .locator("button")
        .filter({ hasText: /Auto|Research/i });
      if ((await modeBtn.count()) > 0) {
        await modeBtn.first().click();
        await page.waitForTimeout(500);

        await page.screenshot({
          path: "playwright-report/redteam/flow2-mode-dropdown.png",
          fullPage: true,
        });

        // Check what modes are available
        const dropdownItems = page
          .locator("button")
          .filter({ hasText: /Auto|Research/i });
        const count = await dropdownItems.count();
        const modes: string[] = [];
        for (let i = 0; i < count; i++) {
          const t = await dropdownItems.nth(i).textContent();
          if (t) modes.push(t.trim());
        }
        console.log("[Flow 2a] Available modes:", modes);

        // SPEC says: should have Auto / Research as modes
        // SPEC also says: agent picker should show agents like HR Policy, Finance Analyst, etc.
        // ChatInput only has Auto and Research modes - check if there's a separate agent picker
        const hasAutoMode = modes.some((m) => m.includes("Auto"));
        const hasResearchMode = modes.some((m) => m.includes("Research"));
        console.log("[Flow 2a] Has Auto:", hasAutoMode);
        console.log("[Flow 2a] Has Research:", hasResearchMode);

        // Per spec Flow 11, agent picker should show:
        // General Assistant, HR Policy Agent, IT Helpdesk, Procurement, Finance, Legal (locked)
        // Check if agent-specific modes exist
        const agentTerms = [
          "HR",
          "Finance",
          "Procurement",
          "IT Helpdesk",
          "Legal",
          "General",
        ];
        const foundAgents: string[] = [];
        for (const a of agentTerms) {
          if (modes.some((m) => m.includes(a))) foundAgents.push(a);
        }
        console.log("[Flow 2a] Agent modes found:", foundAgents);
        if (foundAgents.length === 0) {
          console.log(
            "[Flow 2a] GAP: No agent-specific modes in selector. Spec requires HR Policy, Finance, Procurement agents to be selectable.",
          );
        }
      } else {
        console.log("[Flow 2a] FAIL: Mode selector not found");
      }
    });
  });

  // ── Flow 3: Chat Interaction ──────────────────────────────────
  test.describe("Flow 3: Chat Interaction", () => {
    test("3a: Send message and verify response rendering", async ({
      context,
      page,
    }) => {
      test.setTimeout(60000);
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      // Type a message
      const chatInput = page.locator("textarea");
      await chatInput.fill("What is the company's vacation policy?");

      // Send via button or Enter
      const sendBtn = page.locator('button[aria-label="Send message"]');
      if ((await sendBtn.count()) > 0 && (await sendBtn.isEnabled())) {
        await sendBtn.click();
      } else {
        await chatInput.press("Enter");
      }

      await page.screenshot({
        path: "playwright-report/redteam/flow3-message-sent.png",
        fullPage: true,
      });

      // Wait for response (streaming, up to 30s)
      console.log("[Flow 3a] Message sent, waiting for response...");
      await page.waitForTimeout(8000);

      await page.screenshot({
        path: "playwright-report/redteam/flow3-response-received.png",
        fullPage: true,
      });

      const mainText = await page.locator("main").textContent();
      console.log(
        "[Flow 3a] Page content after send:",
        mainText?.substring(0, 800),
      );

      // Check for state transition: empty -> active
      // Active state should have messages area with max-width: 860px and input fixed at bottom
      const hasUserMessage = mainText?.includes("vacation policy");
      console.log("[Flow 3a] User message visible:", hasUserMessage);

      // Check for AI response content (any text beyond user message)
      const msgCount = mainText?.length ?? 0;
      console.log("[Flow 3a] Total content length:", msgCount);

      // Check for feedback buttons (thumbs up/down)
      const thumbsUp = page.locator('button[aria-label="Thumbs up"]');
      const thumbsDown = page.locator('button[aria-label="Thumbs down"]');
      console.log("[Flow 3a] Thumbs up buttons:", await thumbsUp.count());
      console.log("[Flow 3a] Thumbs down buttons:", await thumbsDown.count());

      // Check for source citations
      const sourceText = await page.locator("main").textContent();
      const hasSources =
        sourceText?.includes("source") ||
        sourceText?.includes("Source") ||
        sourceText?.includes("citation");
      console.log("[Flow 3a] Source citations visible:", hasSources);

      // Check AI message styling: should NOT have card/bubble background
      // AI messages should flow directly on --bg-base without wrapping card
      const aiMessages = page.locator('[class*="bg-bg-surface"]');
      console.log(
        "[Flow 3a] Elements with bg-bg-surface (potential card wrapping):",
        await aiMessages.count(),
      );

      // Check for error state
      const hasError =
        mainText?.includes("error") ||
        mainText?.includes("Error") ||
        mainText?.includes("failed") ||
        mainText?.includes("Failed");
      if (hasError) {
        console.log("[Flow 3a] WARNING: Error text detected in response area");
      }
    });
  });

  // ── Flow 4: Feedback with Tags ────────────────────────────────
  test.describe("Flow 4: Feedback with Tags (CRITICAL)", () => {
    test("4a: Thumbs down shows feedback tags", async ({ context, page }) => {
      test.setTimeout(60000);
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      // Send a message first to get a response with feedback buttons
      const chatInput = page.locator("textarea");
      await chatInput.fill("Tell me about expense claims");
      const sendBtn = page.locator('button[aria-label="Send message"]');
      if ((await sendBtn.count()) > 0 && (await sendBtn.isEnabled())) {
        await sendBtn.click();
      } else {
        await chatInput.press("Enter");
      }

      // Wait for response
      await page.waitForTimeout(8000);

      // Look for thumbs down button
      const thumbsDown = page.locator('button[aria-label="Thumbs down"]');
      const thumbsDownCount = await thumbsDown.count();
      console.log("[Flow 4a] Thumbs down buttons found:", thumbsDownCount);

      if (thumbsDownCount > 0) {
        await thumbsDown.first().click();
        await page.waitForTimeout(1000);

        await page.screenshot({
          path: "playwright-report/redteam/flow4-thumbs-down-clicked.png",
          fullPage: true,
        });

        // SPEC: After thumbs down, tags should appear:
        // Inaccurate / Incomplete / Irrelevant / Hallucinated / Other
        const bodyText = await page.locator("body").textContent();
        const expectedTags = [
          "Inaccurate",
          "Incomplete",
          "Irrelevant",
          "Hallucinated",
          "Other",
        ];
        const foundTags: string[] = [];
        for (const tag of expectedTags) {
          if (bodyText?.includes(tag)) foundTags.push(tag);
        }
        console.log("[Flow 4a] Feedback tags found:", foundTags);
        console.log("[Flow 4a] Expected tags:", expectedTags);

        if (foundTags.length === 0) {
          console.log(
            "[Flow 4a] BUG: No feedback tags appear after thumbs down. " +
              "Spec requires: Inaccurate, Incomplete, Irrelevant, Hallucinated, Other",
          );
        }

        // Check for free-text comment field
        const commentField = page.locator(
          'textarea[placeholder*="Tell us"], input[placeholder*="Tell us"], textarea[placeholder*="comment"]',
        );
        console.log(
          "[Flow 4a] Comment field present:",
          (await commentField.count()) > 0,
        );
      } else {
        console.log(
          "[Flow 4a] FAIL: No thumbs down button found - cannot test feedback tags",
        );
      }
    });

    test("4b: Thumbs up highlights correctly", async ({ context, page }) => {
      test.setTimeout(60000);
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      const chatInput = page.locator("textarea");
      await chatInput.fill("What is our travel policy?");
      const sendBtn = page.locator('button[aria-label="Send message"]');
      if ((await sendBtn.count()) > 0 && (await sendBtn.isEnabled())) {
        await sendBtn.click();
      } else {
        await chatInput.press("Enter");
      }

      await page.waitForTimeout(8000);

      const thumbsUp = page.locator('button[aria-label="Thumbs up"]');
      if ((await thumbsUp.count()) > 0) {
        await thumbsUp.first().click();
        await page.waitForTimeout(1000);

        await page.screenshot({
          path: "playwright-report/redteam/flow4-thumbs-up.png",
          fullPage: true,
        });

        // Should turn accent-colored (filled)
        const classes = await thumbsUp.first().getAttribute("class");
        console.log("[Flow 4b] Thumbs up class after click:", classes);
        const isHighlighted =
          classes?.includes("accent") || classes?.includes("border-accent");
        console.log("[Flow 4b] Thumbs up highlighted:", isHighlighted);
      } else {
        console.log("[Flow 4b] FAIL: No thumbs up button found");
      }
    });
  });

  // ── Flow 5: Issue Reporting FAB ───────────────────────────────
  test.describe("Flow 5: Issue Reporting FAB", () => {
    test("5a: FAB button is always visible", async ({ context, page }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      // Look for the Report Issue FAB button
      const fabBtn = page.locator('button[aria-label="Report Issue"]');
      const fabVisible =
        (await fabBtn.count()) > 0 && (await fabBtn.first().isVisible());
      console.log("[Flow 5a] Report Issue FAB visible:", fabVisible);

      // Alternative: search by text content
      if (!fabVisible) {
        const altFab = page
          .locator("button")
          .filter({ hasText: /Report Issue/i });
        console.log(
          "[Flow 5a] Alternative FAB search count:",
          await altFab.count(),
        );
      }

      await page.screenshot({
        path: "playwright-report/redteam/flow5-fab-visible.png",
        fullPage: true,
      });

      // Check it's fixed bottom-right
      if (fabVisible) {
        const box = await fabBtn.first().boundingBox();
        console.log("[Flow 5a] FAB position:", box);
        // Should be in bottom-right corner
        const viewport = page.viewportSize();
        if (box && viewport) {
          const isBottomRight =
            box.x > viewport.width * 0.5 && box.y > viewport.height * 0.5;
          console.log("[Flow 5a] FAB in bottom-right quadrant:", isBottomRight);
        }
      }
    });

    test("5b: Issue reporter dialog opens and has required fields", async ({
      context,
      page,
    }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      const fabBtn = page.locator('button[aria-label="Report Issue"]');
      if ((await fabBtn.count()) > 0) {
        await fabBtn.click();
        await page.waitForTimeout(1000);

        await page.screenshot({
          path: "playwright-report/redteam/flow5-dialog-open.png",
          fullPage: true,
        });

        const dialogText = await page.locator("body").textContent();
        console.log("[Flow 5b] Dialog content:", dialogText?.substring(0, 500));

        // SPEC: Issue type categories
        const categories = [
          "Wrong",
          "inaccurate",
          "Missing source",
          "Slow",
          "UI",
          "display",
          "Other",
        ];
        const foundCategories: string[] = [];
        for (const c of categories) {
          if (dialogText?.toLowerCase().includes(c.toLowerCase()))
            foundCategories.push(c);
        }
        console.log("[Flow 5b] Categories found:", foundCategories);

        // Check for description field
        const descField = page.locator("textarea").filter({
          hasText: /.*/,
        });
        console.log(
          "[Flow 5b] Textarea count in dialog:",
          await page.locator("textarea").count(),
        );

        // Check for Next/Submit button
        const nextBtn = page
          .locator("button")
          .filter({ hasText: /Next|Submit|Send/i });
        console.log("[Flow 5b] Action buttons:", await nextBtn.count());

        // SPEC: Screenshot preview with blur by default
        // This is on step 2 (multi-step wizard)
        const hasStepIndicator =
          dialogText?.includes("Step") || dialogText?.includes("step");
        console.log("[Flow 5b] Step indicator present:", hasStepIndicator);
      } else {
        console.log("[Flow 5b] FAIL: FAB button not found, cannot open dialog");
      }
    });

    test("5c: Issue reporter screenshot step has blur", async ({
      context,
      page,
    }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      const fabBtn = page.locator('button[aria-label="Report Issue"]');
      if ((await fabBtn.count()) > 0) {
        await fabBtn.click();
        await page.waitForTimeout(500);

        // Fill step 1 (category + description)
        // Select a category
        const categoryBtns = page.locator("button").filter({
          hasText: /Wrong|inaccurate|Missing|Slow|UI|Other/i,
        });
        if ((await categoryBtns.count()) > 0) {
          await categoryBtns.first().click();
          await page.waitForTimeout(300);
        }

        // Fill description
        const descTextarea = page.locator("textarea");
        const textareaCount = await descTextarea.count();
        if (textareaCount > 0) {
          // Use last textarea which is likely the description field
          await descTextarea
            .last()
            .fill("Test issue description for validation");
          await page.waitForTimeout(300);
        }

        // Click Next to go to step 2 (screenshot)
        const nextBtn = page.locator("button").filter({ hasText: /Next/i });
        if ((await nextBtn.count()) > 0) {
          await nextBtn.first().click();
          await page.waitForTimeout(1000);

          await page.screenshot({
            path: "playwright-report/redteam/flow5-screenshot-step.png",
            fullPage: true,
          });

          const stepText = await page.locator("body").textContent();
          console.log("[Flow 5c] Step 2 content:", stepText?.substring(0, 400));

          // Check for blur toggle
          const blurToggle = page.locator("button").filter({
            hasText: /blur|Blur|Reveal|reveal/i,
          });
          console.log(
            "[Flow 5c] Blur toggle present:",
            (await blurToggle.count()) > 0,
          );

          // Check for Eye/EyeOff icons (blur indicators)
          const eyeIcons = page.locator("svg");
          console.log("[Flow 5c] SVG icons count:", await eyeIcons.count());
        } else {
          console.log("[Flow 5c] No Next button found on step 1");
        }
      }
    });
  });

  // ── Flow 6: Conversation History ──────────────────────────────
  test.describe("Flow 6: Conversation History", () => {
    test("6a: Sidebar shows conversation history", async ({
      context,
      page,
    }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      await page.screenshot({
        path: "playwright-report/redteam/flow6-history-sidebar.png",
        fullPage: true,
      });

      const sidebar = page.locator("aside");
      const sidebarText = await sidebar.textContent();
      console.log("[Flow 6a] Sidebar content:", sidebarText);

      // Check for "New Chat" button
      const newChatBtn = page.locator("button").filter({ hasText: /New|new/i });
      console.log("[Flow 6a] New Chat buttons:", await newChatBtn.count());

      // Check for conversation list items
      const listItems = sidebar.locator("button, a").filter({ hasText: /.+/ });
      const itemCount = await listItems.count();
      console.log("[Flow 6a] Sidebar interactive elements:", itemCount);
      for (let i = 0; i < Math.min(itemCount, 10); i++) {
        const text = await listItems.nth(i).textContent();
        console.log(`[Flow 6a]   Item ${i}:`, text?.trim().substring(0, 80));
      }

      // Check for search functionality in history
      const searchInput = sidebar.locator("input");
      console.log(
        "[Flow 6a] Search input in sidebar:",
        (await searchInput.count()) > 0,
      );

      // SPEC: Conversations sorted by most recent first, with title, date, preview
      // SPEC: Full-text search across titles and content
      if ((await searchInput.count()) === 0) {
        console.log(
          "[Flow 6a] GAP: No search input in sidebar. Spec requires full-text search.",
        );
      }
    });

    test("6b: New Chat button resets state", async ({ context, page }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      // Click New Chat
      const newChatBtn = page.locator("button").filter({ hasText: /New/i });
      if ((await newChatBtn.count()) > 0) {
        await newChatBtn.first().click();
        await page.waitForTimeout(1000);

        await page.screenshot({
          path: "playwright-report/redteam/flow6-new-chat.png",
          fullPage: true,
        });

        // Should show empty state again
        const mainText = await page.locator("main").textContent();
        const hasGreeting =
          mainText?.includes("Good morning") ||
          mainText?.includes("Good afternoon") ||
          mainText?.includes("Good evening");
        console.log("[Flow 6b] Empty state restored:", hasGreeting);
      }
    });
  });

  // ── Flow 7: Privacy Settings ──────────────────────────────────
  test.describe("Flow 7: Privacy Settings", () => {
    test("7a: Privacy link in sidebar navigates correctly", async ({
      context,
      page,
    }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      // Find Privacy link
      const privacyLink = page.locator('a[href="/settings/privacy"]');
      const hasPrivacy = (await privacyLink.count()) > 0;
      console.log("[Flow 7a] Privacy link present:", hasPrivacy);

      if (hasPrivacy) {
        await privacyLink.click();
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(2000);

        const url = page.url();
        console.log("[Flow 7a] Privacy page URL:", url);

        await page.screenshot({
          path: "playwright-report/redteam/flow7-privacy-page.png",
          fullPage: true,
        });

        const pageText = await page.locator("main, body").textContent();
        console.log(
          "[Flow 7a] Privacy page content:",
          pageText?.substring(0, 500),
        );

        // SPEC: Profile learning on/off, memory notes, GDPR export/erase
        const expectedFeatures = [
          "privacy",
          "Privacy",
          "learning",
          "memory",
          "Memory",
          "export",
          "Export",
          "erase",
          "Erase",
          "delete",
          "Delete",
          "GDPR",
        ];
        const foundFeatures: string[] = [];
        for (const f of expectedFeatures) {
          if (pageText?.includes(f)) foundFeatures.push(f);
        }
        console.log("[Flow 7a] Privacy features found:", foundFeatures);
      } else {
        console.log("[Flow 7a] FAIL: No privacy link in sidebar");
      }
    });
  });

  // ── Cross-cutting: Design System Compliance ───────────────────
  test.describe("Design System Compliance", () => {
    test("DS-01: No banned patterns visible", async ({ context, page }) => {
      await injectEndUserAuth(context);
      await page.goto(`${BASE}/chat`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);

      const bodyText = await page.locator("body").textContent();

      // Check banned patterns
      const hasRAG = bodyText?.includes("RAG");
      const hasWorkspaces = bodyText?.includes("Workspaces");
      console.log("[DS-01] 'RAG' visible to user:", hasRAG);
      console.log("[DS-01] 'Workspaces' in sidebar:", hasWorkspaces);

      // Check font family - should be Plus Jakarta Sans
      const fontFamily = await page.evaluate(() => {
        const body = document.body;
        return window.getComputedStyle(body).fontFamily;
      });
      console.log("[DS-01] Body font-family:", fontFamily);
      const hasCorrectFont =
        fontFamily.includes("Plus Jakarta Sans") ||
        fontFamily.includes("Jakarta");
      if (!hasCorrectFont) {
        console.log(
          "[DS-01] GAP: Font is not Plus Jakarta Sans. Got:",
          fontFamily,
        );
      }
    });
  });
});
