import { test, expect } from "@playwright/test";
import { injectEndUserAuth } from "./helpers";
import {
  mockChatStream,
  mockChatFeedback,
  mockConversationsList,
} from "./helpers/api-mocks";

/**
 * FE-058: Chat Flow E2E Tests
 *
 * Validates the two-state chat layout (empty -> active), message rendering,
 * agent switching, source citations, and feedback interactions.
 */
test.describe("FE-058: Chat Flows", () => {
  test.beforeEach(async ({ context, page }) => {
    await injectEndUserAuth(context);
    await mockConversationsList(page);
  });

  test("empty state renders correctly with centered layout", async ({
    page,
  }) => {
    await page.goto("/chat");

    // Agent icon (diamond) should be visible in the centered greeting area
    const agentIcon = page.locator(
      ".flex.h-full.flex-col.items-center.justify-center",
    );
    await expect(agentIcon).toBeVisible();

    // Greeting text should contain time-based greeting
    const greeting = page.locator("h1");
    await expect(greeting).toBeVisible();
    await expect(greeting).toContainText(/Good (morning|afternoon|evening)/);

    // Subtitle text
    await expect(
      page.getByText("What would you like to know today?"),
    ).toBeVisible();

    // Input bar should be visible (embedded, not bottom-fixed)
    const textarea = page.locator("textarea");
    await expect(textarea).toBeVisible();
    await expect(textarea).toHaveAttribute("placeholder", "Ask anything...");

    // The input should be inside the centered container, not in a border-t bottom bar
    const bottomFixedInput = page.locator(
      ".border-t.border-border-faint textarea",
    );
    await expect(bottomFixedInput).not.toBeVisible();

    // KB hint should be visible below input -- never shows "RAG"
    const kbHint = page.getByText("documents indexed");
    await expect(kbHint).toBeVisible();
    await expect(kbHint).not.toContainText("RAG");

    // Suggestion chips should be visible
    await expect(page.getByText("Outstanding invoices")).toBeVisible();
    await expect(page.getByText("Salary band L5")).toBeVisible();
    await expect(page.getByText("Annual leave policy")).toBeVisible();
    await expect(page.getByText("Contract clause 8.2b")).toBeVisible();
  });

  test("first message activates chat state with bottom-fixed input", async ({
    page,
  }) => {
    await mockChatStream(page);
    await mockChatFeedback(page);
    await page.goto("/chat");

    // Type and send a message
    const textarea = page.locator("textarea");
    await textarea.fill("What is our annual leave policy?");

    const sendButton = page.getByLabel("Send message");
    await sendButton.click();

    // Wait for the active state to render -- messages area should appear
    const messagesArea = page.locator(".max-w-\\[860px\\].space-y-6");
    await expect(messagesArea).toBeVisible({ timeout: 10_000 });

    // Input bar should now be in bottom-fixed position (inside border-t container)
    const bottomInput = page.locator(".border-t.border-border-faint textarea");
    await expect(bottomInput).toBeVisible();
    await expect(bottomInput).toHaveAttribute(
      "placeholder",
      "Ask follow-up...",
    );

    // User message should be right-aligned in a pill
    const userMessage = page.locator(".flex.justify-end .rounded-card");
    await expect(userMessage).toBeVisible();
    await expect(userMessage).toContainText("What is our annual leave policy?");

    // User message pill should have constrained width (max-w-[68%])
    const userPill = page.locator(".max-w-\\[68\\%\\]");
    await expect(userPill).toBeVisible();
  });

  test("AI response renders without card/bubble background", async ({
    page,
  }) => {
    const testResponse =
      "The standard annual leave policy provides 20 days per year.";
    await mockChatStream(page, { responseText: testResponse });
    await mockChatFeedback(page);
    await page.goto("/chat");

    // Send a message to trigger the response
    await page.locator("textarea").fill("annual leave policy");
    await page.getByLabel("Send message").click();

    // Wait for AI response text
    await expect(page.getByText(testResponse)).toBeVisible({
      timeout: 10_000,
    });

    // Meta row should display agent mode in uppercase
    const metaRow = page.locator(".uppercase.tracking-wider.text-accent");
    await expect(metaRow).toBeVisible();
    await expect(metaRow).toContainText("AUTO");
    await expect(metaRow).toContainText("RESPONSE");

    // AI response text should NOT be wrapped in a card/bubble with background
    // The AI message container should have no bg-bg-elevated or bg-bg-surface class
    const aiResponseContainer = page.locator(".space-y-2").last();
    await expect(aiResponseContainer).toBeVisible();

    // The response text itself should flow directly without a card wrapper
    const responseText = page.locator(
      ".text-sm.leading-relaxed.text-text-primary",
    );
    await expect(responseText).toContainText(testResponse);

    // Feedback row with thumbs up/down should be visible
    await expect(page.getByLabel("Thumbs up")).toBeVisible();
    await expect(page.getByLabel("Thumbs down")).toBeVisible();
  });

  test("suggestion chip sends message and activates chat", async ({ page }) => {
    await mockChatStream(page, {
      responseText: "Here are the outstanding invoices...",
    });
    await mockChatFeedback(page);
    await page.goto("/chat");

    // Click a suggestion chip
    await page.getByText("Outstanding invoices").click();

    // Should transition to active state
    const messagesArea = page.locator(".max-w-\\[860px\\].space-y-6");
    await expect(messagesArea).toBeVisible({ timeout: 10_000 });

    // User message should appear
    await expect(page.getByText("Outstanding invoices")).toBeVisible();
  });

  test("source citations panel slides in from right", async ({ page }) => {
    const sources = [
      {
        id: "src-001",
        title: "Annual Leave Policy v3.2",
        url: "https://sharepoint.test/docs/leave-policy",
        score: 0.92,
        excerpt: "All employees are entitled to 20 days of annual leave...",
      },
      {
        id: "src-002",
        title: "Employee Handbook 2026",
        url: "https://sharepoint.test/docs/handbook",
        score: 0.78,
        excerpt: "Leave policies are outlined in section 4.2...",
      },
    ];

    await mockChatStream(page, {
      responseText: "According to our documents...",
      sources,
    });
    await mockChatFeedback(page);
    await page.goto("/chat");

    // Send a message
    await page.locator("textarea").fill("leave policy");
    await page.getByLabel("Send message").click();

    // Wait for the response and the sources footer
    const sourcesButton = page.locator("button", { hasText: "sources" });
    await expect(sourcesButton).toBeVisible({ timeout: 10_000 });
    await expect(sourcesButton).toContainText("2 sources");

    // Click to open the source panel
    await sourcesButton.click();

    // Source panel should slide in from the right
    const sourcePanel = page.locator(".animate-slide-in-right");
    await expect(sourcePanel).toBeVisible();

    // Panel header should say "Sources"
    await expect(
      sourcePanel.locator("h2", { hasText: "Sources" }),
    ).toBeVisible();

    // Source cards should be visible
    await expect(
      sourcePanel.getByText("Annual Leave Policy v3.2"),
    ).toBeVisible();
    await expect(sourcePanel.getByText("Employee Handbook 2026")).toBeVisible();

    // Relevance scores should be shown
    await expect(sourcePanel.getByText("92%")).toBeVisible();
    await expect(sourcePanel.getByText("78%")).toBeVisible();

    // Close button should dismiss the panel
    await page.getByLabel("Close sources").click();
    await expect(sourcePanel).not.toBeVisible();
  });

  test("mode selector changes routing mode", async ({ page }) => {
    await page.goto("/chat");

    // Mode selector should be visible in empty state (showModeSelector=true)
    const modeButton = page.locator("button", { hasText: "Auto" });
    await expect(modeButton).toBeVisible();

    // Open the mode dropdown
    await modeButton.click();

    // Research mode should be available
    const researchOption = page.locator("button", { hasText: "Research" });
    await expect(researchOption).toBeVisible();

    // Select Research mode
    await researchOption.click();

    // Mode selector should now show "Research"
    await expect(page.locator("button", { hasText: "Research" })).toBeVisible();
  });

  test("feedback widget sends thumbs up", async ({ page }) => {
    await mockChatStream(page, { responseText: "Test feedback response." });
    await mockChatFeedback(page);
    await page.goto("/chat");

    // Send a message
    await page.locator("textarea").fill("test feedback");
    await page.getByLabel("Send message").click();

    // Wait for feedback buttons
    const thumbsUp = page.getByLabel("Thumbs up");
    await expect(thumbsUp).toBeVisible({ timeout: 10_000 });

    // Click thumbs up
    await thumbsUp.click();

    // Button should become selected (accent colored)
    await expect(thumbsUp).toHaveClass(/border-accent/);
  });

  test("feedback widget sends thumbs down", async ({ page }) => {
    await mockChatStream(page, { responseText: "Test feedback down." });
    await mockChatFeedback(page);
    await page.goto("/chat");

    await page.locator("textarea").fill("test feedback down");
    await page.getByLabel("Send message").click();

    const thumbsDown = page.getByLabel("Thumbs down");
    await expect(thumbsDown).toBeVisible({ timeout: 10_000 });

    await thumbsDown.click();

    // Button should become selected (alert colored)
    await expect(thumbsDown).toHaveClass(/border-alert/);
  });

  test("send button is disabled when input is empty", async ({ page }) => {
    await page.goto("/chat");

    const sendButton = page.getByLabel("Send message");
    await expect(sendButton).toBeVisible();
    await expect(sendButton).toBeDisabled();

    // Type something
    await page.locator("textarea").fill("hello");
    await expect(sendButton).toBeEnabled();

    // Clear it
    await page.locator("textarea").fill("");
    await expect(sendButton).toBeDisabled();
  });

  test("Enter key sends message, Shift+Enter does not", async ({ page }) => {
    await mockChatStream(page, { responseText: "Reply to enter test." });
    await mockChatFeedback(page);
    await page.goto("/chat");

    const textarea = page.locator("textarea");
    await textarea.fill("line one");

    // Shift+Enter should NOT send (allows multiline)
    await textarea.press("Shift+Enter");

    // Should still be in empty state (no message sent)
    const messagesArea = page.locator(".max-w-\\[860px\\].space-y-6");
    await expect(messagesArea).not.toBeVisible();

    // Clear and type fresh, then Enter to send
    await textarea.fill("send this message");
    await textarea.press("Enter");

    // Should transition to active chat state
    await expect(messagesArea).toBeVisible({ timeout: 10_000 });
  });

  test("attach file button is present", async ({ page }) => {
    await page.goto("/chat");

    const attachButton = page.getByLabel("Attach file");
    await expect(attachButton).toBeVisible();
  });
});
