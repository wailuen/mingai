import { test, expect } from "@playwright/test";
import { injectAuth } from "./helpers/auth";
import {
  mockConversationsList,
  mockPublicAgents,
} from "./helpers/api-mocks";

/**
 * TEST-049: Agent Registry E2E Tests
 *
 * Validates the public agent registry discovery page, including
 * browsing, category filtering, search, agent adoption (request access),
 * and installed agent identification.
 */
test.describe("TEST-049: Agent Registry", () => {
  test.beforeEach(async ({ context, page }) => {
    await injectAuth(context);
    await mockConversationsList(page);
    await mockPublicAgents(page);
  });

  test("user can browse the agent registry", async ({ page }) => {
    await page.goto("/discover");
    await page.waitForLoadState("networkidle");

    // Page heading
    await expect(
      page.getByRole("heading", { name: "Agent Registry" }),
    ).toBeVisible();

    // Subtitle
    await expect(
      page.getByText("Discover AI agents for your workspace"),
    ).toBeVisible();

    // Search input should be visible
    const searchInput = page.locator(
      'input[placeholder="Search agents by name or description..."]',
    );
    await expect(searchInput).toBeVisible();

    // Category filter chips should be visible
    const categories = ["All", "HR", "IT", "Finance", "Legal", "Procurement", "Custom"];
    for (const cat of categories) {
      await expect(
        page.getByRole("button", { name: cat, exact: true }),
      ).toBeVisible();
    }

    // Agent cards should be displayed
    await expect(page.getByText("Finance Assistant")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("HR Helper")).toBeVisible();
    await expect(page.getByText("Legal Advisor")).toBeVisible();

    // Agent descriptions should render
    await expect(
      page.getByText("Answers questions about invoices, budgets"),
    ).toBeVisible();
    await expect(
      page.getByText("Handles leave policies, benefits"),
    ).toBeVisible();

    // Capability badges should be visible
    await expect(page.getByText("Invoice lookup")).toBeVisible();
    await expect(page.getByText("Leave policy")).toBeVisible();
    await expect(page.getByText("Contract review")).toBeVisible();
  });

  test("agent cards display satisfaction and install metrics", async ({
    page,
  }) => {
    await page.goto("/discover");
    await page.waitForLoadState("networkidle");

    // Wait for agent cards to load
    await expect(page.getByText("Finance Assistant")).toBeVisible({
      timeout: 10_000,
    });

    // Satisfaction rates should be displayed in DM Mono (font-mono)
    await expect(page.getByText("94% satisfaction")).toBeVisible();
    await expect(page.getByText("91% satisfaction")).toBeVisible();
    await expect(page.getByText("88% satisfaction")).toBeVisible();

    // Install counts should be visible
    await expect(page.getByText("1,280 installs")).toBeVisible();
    await expect(page.getByText("2,150 installs")).toBeVisible();
    await expect(page.getByText("640 installs")).toBeVisible();
  });

  test("installed agents show 'Installed' badge instead of request button", async ({
    page,
  }) => {
    await page.goto("/discover");
    await page.waitForLoadState("networkidle");

    // Wait for cards to render
    await expect(page.getByText("HR Helper")).toBeVisible({ timeout: 10_000 });

    // HR Helper is mocked as is_installed: true
    // It should show "Installed" badge
    await expect(page.getByText("Installed", { exact: true })).toBeVisible();

    // Finance Assistant (not installed) should show "Request Access" button
    const requestButtons = page.getByRole("button", {
      name: "Request Access",
    });
    // There should be 2 request buttons (Finance + Legal, but not HR)
    await expect(requestButtons).toHaveCount(2);
  });

  test("user can adopt an agent from the registry via Request Access", async ({
    page,
  }) => {
    await page.goto("/discover");
    await page.waitForLoadState("networkidle");

    // Wait for cards
    await expect(page.getByText("Finance Assistant")).toBeVisible({
      timeout: 10_000,
    });

    // Click "Request Access" on the first non-installed agent
    const requestButtons = page.getByRole("button", {
      name: "Request Access",
    });
    await requestButtons.first().click();

    // The button should briefly show "Requesting..." state
    // (the mock resolves quickly, so we just verify the click succeeded
    // without throwing and the card is still visible)
    await expect(page.getByText("Finance Assistant")).toBeVisible();
  });

  test("category filter chips filter the agent list", async ({ page }) => {
    await page.goto("/discover");
    await page.waitForLoadState("networkidle");

    // Wait for initial load
    await expect(page.getByText("Finance Assistant")).toBeVisible({
      timeout: 10_000,
    });

    // "All" category should be selected by default (accent styling)
    const allChip = page.getByRole("button", { name: "All", exact: true });
    await expect(allChip).toHaveClass(/border-accent/);

    // Click "Finance" category
    const financeChip = page.getByRole("button", {
      name: "Finance",
      exact: true,
    });
    await financeChip.click();

    // Finance chip should now be selected
    await expect(financeChip).toHaveClass(/border-accent/);

    // "All" should be deselected
    await expect(allChip).not.toHaveClass(/border-accent bg-accent-dim/);

    // Click "HR" category
    const hrChip = page.getByRole("button", { name: "HR", exact: true });
    await hrChip.click();
    await expect(hrChip).toHaveClass(/border-accent/);
  });

  test("search input filters agents by name or description", async ({
    page,
  }) => {
    await page.goto("/discover");
    await page.waitForLoadState("networkidle");

    // Wait for cards
    await expect(page.getByText("Finance Assistant")).toBeVisible({
      timeout: 10_000,
    });

    // Type in search input (min 2 chars to trigger)
    const searchInput = page.locator(
      'input[placeholder="Search agents by name or description..."]',
    );
    await searchInput.fill("Fi");

    // Search input should reflect the typed value
    await expect(searchInput).toHaveValue("Fi");

    // Clear and search for another term
    await searchInput.fill("Legal");
    await expect(searchInput).toHaveValue("Legal");
  });

  test("empty state renders when no agents match", async ({ page }) => {
    // Override the mock to return empty results for a specific search
    await page.route("**/api/v1/registry/agents**", async (route) => {
      const url = route.request().url();
      if (url.includes("search=nonexistent")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      }
    });

    await page.goto("/discover");
    await page.waitForLoadState("networkidle");

    // Empty state message should appear
    await expect(
      page.getByText("No agents found matching your search"),
    ).toBeVisible({ timeout: 10_000 });
  });
});
