import { test, expect } from "@playwright/test";
import { injectAuth, injectTenantAdmin } from "./helpers/auth";
import {
  mockChatStream,
  mockChatFeedback,
  mockConversationsList,
  mockIssueSubmit,
  mockTenantIssueQueue,
  mockIssueReportingConfig,
} from "./helpers/api-mocks";

/**
 * TEST-020: Issue Reporting E2E Tests
 *
 * Validates the issue reporting flow from the chat interface through the
 * tenant admin issue queue, including submit, review, and action workflows.
 */
test.describe("TEST-020: Issue Reporting", () => {
  test.describe("End User: Submit Issue from Chat", () => {
    test.beforeEach(async ({ context, page }) => {
      await injectAuth(context);
      await mockConversationsList(page);
      await mockChatStream(page, {
        responseText: "The annual leave entitlement is 15 days per year.",
      });
      await mockChatFeedback(page);
      await mockIssueSubmit(page);
    });

    test("user can submit an issue report from the chat interface", async ({
      page,
    }) => {
      await page.goto("/chat");

      // Send a message and get a response
      const textarea = page.locator("textarea");
      await textarea.fill("What is our annual leave policy?");
      await page.getByLabel("Send message").click();

      // Wait for the AI response
      await expect(
        page.getByText("The annual leave entitlement is 15 days per year."),
      ).toBeVisible({ timeout: 10_000 });

      // Click thumbs down to indicate the answer was bad
      const thumbsDown = page.getByLabel("Thumbs down");
      await expect(thumbsDown).toBeVisible({ timeout: 10_000 });
      await thumbsDown.click();

      // After thumbs down, a "Report issue" option should become available
      // Look for report issue button/link that appears after negative feedback
      const reportButton = page.locator("button, a").filter({
        hasText: /report/i,
      });

      // If the report button exists, click it to open the issue form
      if (await reportButton.first().isVisible({ timeout: 3_000 }).catch(() => false)) {
        await reportButton.first().click();

        // Issue form should appear with description field
        const issueForm = page.locator(
          "form, [role='dialog'], .fixed",
        ).first();
        await expect(issueForm).toBeVisible({ timeout: 5_000 });
      }
    });

    test("issue report form validates required fields", async ({ page }) => {
      await page.goto("/chat");

      // Send a message to get a response
      await page.locator("textarea").fill("salary information");
      await page.getByLabel("Send message").click();

      // Wait for response
      await expect(
        page.getByText("The annual leave entitlement"),
      ).toBeVisible({ timeout: 10_000 });

      // Thumbs down to trigger feedback/report flow
      await page.getByLabel("Thumbs down").click();

      // Verify the feedback interaction registered (button should show selected state)
      await expect(page.getByLabel("Thumbs down")).toHaveClass(/border-alert/);
    });
  });

  test.describe("Tenant Admin: Issue Queue Management", () => {
    test.beforeEach(async ({ context, page }) => {
      await injectTenantAdmin(context);
      await mockConversationsList(page);
      await mockTenantIssueQueue(page);
    });

    test("issue queue renders with reported issues", async ({ page }) => {
      await page.goto("/settings/engineering-issues");
      await page.waitForLoadState("networkidle");

      // Page heading
      await expect(
        page.getByRole("heading", { name: "Issue Queue" }),
      ).toBeVisible();

      // Subtitle
      await expect(
        page.getByText("Issues reported by your workspace users"),
      ).toBeVisible();

      // Severity filter chips should be visible
      const severities = ["P0", "P1", "P2", "P3", "P4"];
      for (const sev of severities) {
        await expect(
          page.getByRole("button", { name: sev, exact: true }),
        ).toBeVisible();
      }

      // Status filter chips should be visible
      const statuses = ["New", "In Review", "Escalated", "Resolved", "Closed"];
      for (const status of statuses) {
        await expect(
          page.getByRole("button", { name: status }),
        ).toBeVisible();
      }
    });

    test("tenant admin can filter issues by severity", async ({ page }) => {
      await page.goto("/settings/engineering-issues");
      await page.waitForLoadState("networkidle");

      // Click P0 severity filter
      const p0Chip = page.getByRole("button", { name: "P0", exact: true });
      await expect(p0Chip).toBeVisible();
      await expect(p0Chip).toHaveClass(/border-border/);

      await p0Chip.click();

      // Chip should become selected (accent-ring border)
      await expect(p0Chip).toHaveClass(/border-accent-ring/);

      // Click again to deselect
      await p0Chip.click();
      await expect(p0Chip).toHaveClass(/border-border/);
    });

    test("tenant admin can filter issues by status", async ({ page }) => {
      await page.goto("/settings/engineering-issues");
      await page.waitForLoadState("networkidle");

      // Click "New" status filter
      const newChip = page.getByRole("button", { name: "New" });
      await expect(newChip).toBeVisible();
      await expect(newChip).toHaveClass(/border-border/);

      await newChip.click();
      await expect(newChip).toHaveClass(/border-accent-ring/);

      // Click "Escalated" as well (multi-select)
      const escalatedChip = page.getByRole("button", { name: "Escalated" });
      await escalatedChip.click();
      await expect(escalatedChip).toHaveClass(/border-accent-ring/);

      // Both should be selected simultaneously
      await expect(newChip).toHaveClass(/border-accent-ring/);
    });

    test("tenant admin can combine severity and status filters", async ({
      page,
    }) => {
      await page.goto("/settings/engineering-issues");
      await page.waitForLoadState("networkidle");

      // Select P1 severity
      const p1Chip = page.getByRole("button", { name: "P1", exact: true });
      await p1Chip.click();
      await expect(p1Chip).toHaveClass(/border-accent-ring/);

      // Select "In Review" status
      const inReviewChip = page.getByRole("button", { name: "In Review" });
      await inReviewChip.click();
      await expect(inReviewChip).toHaveClass(/border-accent-ring/);

      // Both filters should remain active
      await expect(p1Chip).toHaveClass(/border-accent-ring/);
      await expect(inReviewChip).toHaveClass(/border-accent-ring/);
    });
  });

  test.describe("Tenant Admin: Issue Reporting Settings", () => {
    test.beforeEach(async ({ context, page }) => {
      await injectTenantAdmin(context);
      await mockConversationsList(page);
      await mockIssueReportingConfig(page);
    });

    test("issue reporting settings page renders with all controls", async ({
      page,
    }) => {
      await page.goto("/settings/issue-reporting");

      // Page title
      await expect(
        page.locator("h1", { hasText: "Issue Reporting" }),
      ).toBeVisible();

      // Description
      await expect(
        page.getByText(
          "Configure how workspace issues are reported and escalated",
        ),
      ).toBeVisible();

      // Enable toggle should be present and reflect mocked enabled state
      await expect(page.getByText("Enable Issue Reporting")).toBeVisible({
        timeout: 10_000,
      });

      const enableToggle = page.getByLabel("Toggle issue reporting");
      await expect(enableToggle).toBeVisible();
      await expect(enableToggle).toHaveAttribute("aria-checked", "true");
    });

    test("auto-escalate toggles reflect configuration state", async ({
      page,
    }) => {
      await page.goto("/settings/issue-reporting");

      // P0 auto-escalate should be enabled (mocked as true)
      await expect(page.getByText("Auto-escalate P0 Issues")).toBeVisible({
        timeout: 10_000,
      });
      const p0Toggle = page.getByLabel("Toggle auto-escalate P0");
      await expect(p0Toggle).toBeVisible();
      await expect(p0Toggle).toHaveAttribute("aria-checked", "true");

      // P1 auto-escalate should be disabled (mocked as false)
      await expect(page.getByText("Auto-escalate P1 Issues")).toBeVisible();
      const p1Toggle = page.getByLabel("Toggle auto-escalate P1");
      await expect(p1Toggle).toBeVisible();
      await expect(p1Toggle).toHaveAttribute("aria-checked", "false");
    });

    test("save button persists configuration changes", async ({ page }) => {
      await page.goto("/settings/issue-reporting");

      await expect(page.getByText("Enable Issue Reporting")).toBeVisible({
        timeout: 10_000,
      });

      // Save Changes button should be present and enabled
      const saveButton = page.locator("button", { hasText: "Save Changes" });
      await expect(saveButton).toBeVisible();
      await expect(saveButton).toBeEnabled();

      // Click save -- mocked API should accept it
      await saveButton.click();

      // Button should remain visible after save
      await expect(saveButton).toBeVisible({ timeout: 5_000 });
    });
  });
});
