import { test, expect } from "@playwright/test";
import { injectPlatformAdminAuth } from "./helpers";

/**
 * FE-060: Platform Admin Flows
 *
 * E2E tests verifying platform admin dashboard, tenant management,
 * LLM profiles, audit log, cost analytics, issue queue, and alert center.
 */
test.describe("FE-060: Platform Admin Flows", () => {
  test.beforeEach(async ({ context }) => {
    await injectPlatformAdminAuth(context);
  });

  test("platform dashboard renders KPI cards and tenant health table", async ({
    page,
  }) => {
    await page.goto("/platform");
    await page.waitForLoadState("networkidle");

    // Expect heading
    await expect(
      page.getByRole("heading", { name: "Platform Dashboard" }),
    ).toBeVisible();

    // Expect 4 KPI cards (Active Users, Documents Indexed, Queries Today, Satisfaction)
    // KPI cards are in a 4-column grid; each card has an uppercase label
    const kpiLabels = [
      "Active Users",
      "Documents Indexed",
      "Queries Today",
      "Satisfaction",
    ];
    for (const label of kpiLabels) {
      await expect(page.getByText(label, { exact: false })).toBeVisible();
    }

    // Expect TenantHealthTable section
    await expect(
      page.getByRole("heading", { name: "Tenant Overview" }),
    ).toBeVisible();

    // Expect the table to have column headers
    const tableHeaders = ["Tenant", "Plan", "Status"];
    for (const header of tableHeaders) {
      await expect(
        page.locator("th").filter({ hasText: new RegExp(header, "i") }),
      ).toBeVisible();
    }
  });

  test("tenant list renders with provision button", async ({ page }) => {
    await page.goto("/platform/tenants");
    await page.waitForLoadState("networkidle");

    // Expect page heading
    await expect(page.getByRole("heading", { name: "Tenants" })).toBeVisible();

    // Expect table with columns: Name, Plan, Status, Contact, Created, Actions
    const columnHeaders = ["Name", "Plan", "Status", "Contact", "Created"];
    for (const header of columnHeaders) {
      await expect(
        page.locator("th").filter({ hasText: new RegExp(header, "i") }),
      ).toBeVisible();
    }

    // Expect "New Tenant" provision button
    const provisionButton = page.getByRole("button", {
      name: /new tenant/i,
    });
    await expect(provisionButton).toBeVisible();
  });

  test("provision tenant wizard opens and validates step 1", async ({
    page,
  }) => {
    await page.goto("/platform/tenants");
    await page.waitForLoadState("networkidle");

    // Click "New Tenant" button to open the wizard
    await page.getByRole("button", { name: /new tenant/i }).click();

    // Expect wizard modal to appear with "Provision New Tenant" heading
    await expect(
      page.getByRole("heading", { name: /provision new tenant/i }),
    ).toBeVisible();

    // Expect "Step 1 of 3" label
    await expect(page.getByText("Step 1 of 3")).toBeVisible();

    // The Next button should be disabled (name and email not filled)
    const nextButton = page.getByRole("button", { name: /next/i });
    await expect(nextButton).toBeDisabled();

    // Fill in Tenant Name
    await page.getByPlaceholder("Acme Corporation").fill("Test Corp");

    // Fill in Primary Contact Email
    await page.getByPlaceholder("admin@acme.com").fill("admin@test.com");

    // Slug should be auto-populated from name
    const slugInput = page.getByPlaceholder("acme-corporation");
    await expect(slugInput).toHaveValue("test-corp");

    // Next button should now be enabled
    await expect(nextButton).toBeEnabled();

    // Click Next to advance to step 2
    await nextButton.click();
    await expect(page.getByText("Step 2 of 3")).toBeVisible();

    // Click Next again to advance to step 3 (Review)
    await page.getByRole("button", { name: /next/i }).click();
    await expect(page.getByText("Step 3 of 3")).toBeVisible();

    // Verify review shows the entered data
    await expect(page.getByText("Test Corp")).toBeVisible();
    await expect(page.getByText("admin@test.com")).toBeVisible();
  });

  test("LLM profiles page renders", async ({ page }) => {
    await page.goto("/platform/llm-profiles");
    await page.waitForLoadState("networkidle");

    // Expect page heading
    await expect(
      page.getByRole("heading", { name: "LLM Profiles" }),
    ).toBeVisible();

    // Expect "New Profile" button (the create button)
    await expect(
      page.getByRole("button", { name: /new profile/i }),
    ).toBeVisible();
  });

  test("audit log renders with filter controls", async ({ page }) => {
    await page.goto("/platform/audit-log");
    await page.waitForLoadState("networkidle");

    // Expect page heading
    await expect(
      page.getByRole("heading", { name: "Audit Log" }),
    ).toBeVisible();

    // Expect table columns: Timestamp, Actor, Action, Resource, Tenant, Outcome, IP Address
    const auditColumns = ["Timestamp", "Actor", "Action", "Resource", "Tenant"];
    for (const col of auditColumns) {
      await expect(
        page.locator("th").filter({ hasText: new RegExp(col, "i") }),
      ).toBeVisible();
    }

    // Expect filter bar with Actor select and Action select
    const actorLabel = page.getByText("Actor", { exact: true }).first();
    await expect(actorLabel).toBeVisible();

    // Expect the Actor type select dropdown
    const actorSelect = page.locator("select").filter({
      has: page.locator('option:has-text("All Actors")'),
    });
    await expect(actorSelect).toBeVisible();

    // Expect the Action category select dropdown
    const actionSelect = page.locator("select").filter({
      has: page.locator('option:has-text("All Actions")'),
    });
    await expect(actionSelect).toBeVisible();

    // Expect "Apply Filters" button
    await expect(
      page.getByRole("button", { name: /apply filters/i }),
    ).toBeVisible();
  });

  test("cost analytics renders with period selector", async ({ page }) => {
    await page.goto("/platform/analytics/cost");
    await page.waitForLoadState("networkidle");

    // Expect page heading
    await expect(
      page.getByRole("heading", { name: "Cost Analytics" }),
    ).toBeVisible();

    // Expect period tabs: 7 Days, 30 Days, 90 Days
    const periodLabels = ["7 Days", "30 Days", "90 Days"];
    for (const label of periodLabels) {
      await expect(page.getByRole("button", { name: label })).toBeVisible();
    }

    // Default period is 30 Days (should have active styling with accent border)
    const thirtyDayTab = page.getByRole("button", { name: "30 Days" });
    await expect(thirtyDayTab).toHaveClass(/border-b-accent/);

    // Click "7 Days" tab
    await page.getByRole("button", { name: "7 Days" }).click();

    // Verify "7 Days" tab now has active styling
    const sevenDayTab = page.getByRole("button", { name: "7 Days" });
    await expect(sevenDayTab).toHaveClass(/border-b-accent/);

    // Verify "30 Days" tab no longer has active styling
    await expect(thirtyDayTab).toHaveClass(/border-b-transparent/);
  });

  test("issue queue renders with severity filter chips", async ({ page }) => {
    await page.goto("/platform/issues");
    await page.waitForLoadState("networkidle");

    // Expect page heading
    await expect(
      page.getByRole("heading", { name: "Issue Queue" }),
    ).toBeVisible();

    // Expect severity filter chips P0 through P4
    const severities = ["P0", "P1", "P2", "P3", "P4"];
    for (const sev of severities) {
      await expect(
        page.getByRole("button", { name: sev, exact: true }),
      ).toBeVisible();
    }

    // Expect status filter chips
    const statuses = ["Open", "In Progress", "Waiting Info", "Closed"];
    for (const status of statuses) {
      await expect(page.getByRole("button", { name: status })).toBeVisible();
    }

    // Clicking a severity chip should toggle its selected state
    const p0Chip = page.getByRole("button", { name: "P0", exact: true });
    await expect(p0Chip).toHaveClass(/border-border/);
    await p0Chip.click();
    await expect(p0Chip).toHaveClass(/border-accent-ring/);
  });

  test("alert center renders", async ({ page }) => {
    await page.goto("/platform/alerts");
    await page.waitForLoadState("networkidle");

    // Expect "Alert Center" heading
    await expect(
      page.getByRole("heading", { name: "Alert Center" }),
    ).toBeVisible();

    // Expect subtitle text
    await expect(
      page.getByText("Monitor and manage platform alerts"),
    ).toBeVisible();
  });
});
