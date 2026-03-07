import { test, expect } from "@playwright/test";
import { injectTenantAdminAuth, injectEndUserAuth } from "./helpers";

/**
 * FE-061: Privacy and Memory Flows
 *
 * E2E tests verifying memory settings, working memory TTL,
 * onboarding wizard, issue reporting settings, and engineering issue queue.
 */
test.describe("FE-061: Privacy and Memory Flows", () => {
  test.describe("Memory Settings (Tenant Admin)", () => {
    test.beforeEach(async ({ context }) => {
      await injectTenantAdminAuth(context);
    });

    test("memory settings page renders all three policy cards", async ({
      page,
    }) => {
      await page.goto("/settings/memory");
      await page.waitForLoadState("networkidle");

      // Expect page heading
      await expect(
        page.getByRole("heading", { name: "Memory Settings" }),
      ).toBeVisible();

      // Expect "Profile Learning" card
      await expect(
        page.getByRole("heading", { name: "Profile Learning" }),
      ).toBeVisible();

      // Expect "Working Memory" card
      await expect(
        page.getByRole("heading", { name: "Working Memory" }),
      ).toBeVisible();

      // Expect "Memory Notes" card
      await expect(
        page.getByRole("heading", { name: "Memory Notes" }),
      ).toBeVisible();

      // Each card should have a toggle switch
      const switches = page.getByRole("switch");
      // Profile Learning has 1, Working Memory has 1, Memory Notes has 2 (main + auto-extract)
      // But auto-extract may be hidden if main toggle is off, so at minimum 3
      await expect(switches.first()).toBeVisible();
    });

    test("working memory TTL selector works", async ({ page }) => {
      await page.goto("/settings/memory");
      await page.waitForLoadState("networkidle");

      // Find the TTL select dropdown (labeled "Retain for")
      const ttlSelect = page.locator("#ttl-select");
      await expect(ttlSelect).toBeVisible();

      // Verify available options include 1 day, 3 days, 7 days, 14 days, 30 days
      const options = ttlSelect.locator("option");
      await expect(options).toHaveCount(5);

      // Default should be 7 days based on the component state
      await expect(ttlSelect).toHaveValue("7");

      // Change selection to 30 days
      await ttlSelect.selectOption("30");
      await expect(ttlSelect).toHaveValue("30");

      // Change to 1 day
      await ttlSelect.selectOption("1");
      await expect(ttlSelect).toHaveValue("1");
    });
  });

  test.describe("Onboarding Wizard", () => {
    test.beforeEach(async ({ context }) => {
      await injectEndUserAuth(context);
    });

    test("onboarding wizard renders and navigates through steps", async ({
      page,
    }) => {
      await page.goto("/onboarding");
      await page.waitForLoadState("networkidle");

      // Step 1: Welcome
      await expect(page.getByText("Welcome to mingai")).toBeVisible();
      await expect(page.getByText("Step 1 of 6")).toBeVisible();

      // Click "Let's get started"
      const getStartedButton = page.getByRole("button", {
        name: /let.*s get started/i,
      });
      await expect(getStartedButton).toBeVisible();
      await getStartedButton.click();

      // Step 2: Set Up Your Profile
      await expect(page.getByText("Step 2 of 6")).toBeVisible();
      await expect(
        page.getByRole("heading", { name: /set up your profile/i }),
      ).toBeVisible();

      // Expect display name input
      const displayNameInput = page.getByPlaceholder("Your name");
      await expect(displayNameInput).toBeVisible();

      // Next button should be disabled when display name is empty
      const nextButton = page.getByRole("button", { name: /next/i });
      await expect(nextButton).toBeDisabled();

      // Fill in display name
      await displayNameInput.fill("Test User");
      await expect(nextButton).toBeEnabled();

      // Click Next to go to step 3
      await nextButton.click();

      // Step 3: Connect Your Knowledge Base
      await expect(page.getByText("Step 3 of 6")).toBeVisible();
      await expect(
        page.getByRole("heading", { name: /connect your knowledge base/i }),
      ).toBeVisible();

      // Should have SharePoint option and Skip option
      await expect(page.getByText("Connect SharePoint")).toBeVisible();
      await expect(page.getByText("Skip for now")).toBeVisible();
    });
  });

  test.describe("Issue Reporting Settings (Tenant Admin)", () => {
    test.beforeEach(async ({ context }) => {
      await injectTenantAdminAuth(context);
    });

    test("issue reporting settings page renders", async ({ page }) => {
      await page.goto("/settings/issue-reporting");
      await page.waitForLoadState("networkidle");

      // Expect page heading
      await expect(
        page.getByRole("heading", { name: "Issue Reporting" }),
      ).toBeVisible();

      // Expect "Enable Issue Reporting" toggle
      await expect(page.getByText("Enable Issue Reporting")).toBeVisible();

      // Expect the toggle switch with the correct aria-label
      const enableToggle = page.getByRole("switch", {
        name: /toggle issue reporting/i,
      });
      await expect(enableToggle).toBeVisible();

      // Expect notification email field
      await expect(page.getByText("Notification Email")).toBeVisible();

      // Expect auto-escalate P0 toggle
      await expect(page.getByText("Auto-escalate P0 Issues")).toBeVisible();

      // Expect save button
      await expect(
        page.getByRole("button", { name: /save changes/i }),
      ).toBeVisible();
    });
  });

  test.describe("Engineering Issue Queue (Tenant Admin)", () => {
    test.beforeEach(async ({ context }) => {
      await injectTenantAdminAuth(context);
    });

    test("engineering issue queue renders with severity filter chips", async ({
      page,
    }) => {
      await page.goto("/settings/engineering-issues");
      await page.waitForLoadState("networkidle");

      // Expect page heading
      await expect(
        page.getByRole("heading", { name: "Issue Queue" }),
      ).toBeVisible();

      // Expect subtitle
      await expect(
        page.getByText("Issues reported by your workspace users"),
      ).toBeVisible();

      // Expect severity filter chips P0 through P4
      const severities = ["P0", "P1", "P2", "P3", "P4"];
      for (const sev of severities) {
        await expect(
          page.getByRole("button", { name: sev, exact: true }),
        ).toBeVisible();
      }

      // Expect status filter chips
      const statuses = ["New", "In Review", "Escalated", "Resolved", "Closed"];
      for (const status of statuses) {
        await expect(page.getByRole("button", { name: status })).toBeVisible();
      }

      // Clicking a severity chip should toggle its selected state
      const p1Chip = page.getByRole("button", { name: "P1", exact: true });
      await expect(p1Chip).toHaveClass(/border-border/);
      await p1Chip.click();
      await expect(p1Chip).toHaveClass(/border-accent-ring/);

      // Clicking again should deselect
      await p1Chip.click();
      await expect(p1Chip).toHaveClass(/border-border/);
    });
  });
});
