import { test, expect } from "@playwright/test";
import { injectPlatformAdmin } from "./helpers/auth";
import {
  mockPlatformDashboard,
  mockTenantList,
  mockTenantDetail,
  mockLLMProfiles,
  mockCostAnalytics,
  mockPlatformIssueQueue,
  mockHealthBreakdown,
  mockQuotaUsage,
} from "./helpers/api-mocks";

/**
 * TEST-025: Platform Admin E2E Tests
 *
 * Validates platform admin dashboard, tenant management, LLM profiles,
 * tenant suspension, and cost analytics dashboard flows.
 */
test.describe("TEST-025: Platform Admin", () => {
  test.beforeEach(async ({ context }) => {
    await injectPlatformAdmin(context);
  });

  test.describe("Platform Dashboard", () => {
    test("platform admin can view all tenants on the dashboard", async ({
      page,
    }) => {
      await mockPlatformDashboard(page);
      await page.goto("/platform");
      await page.waitForLoadState("networkidle");

      // Expect heading
      await expect(
        page.getByRole("heading", { name: "Platform Dashboard" }),
      ).toBeVisible();

      // Expect KPI cards
      const kpiLabels = [
        "Active Users",
        "Documents Indexed",
        "Queries Today",
        "Satisfaction",
      ];
      for (const label of kpiLabels) {
        await expect(page.getByText(label, { exact: false })).toBeVisible();
      }

      // Expect tenant health table
      await expect(
        page.getByRole("heading", { name: "Tenant Overview" }),
      ).toBeVisible();

      // Tenant data should be visible
      await expect(page.getByText("Acme Corp")).toBeVisible();
      await expect(page.getByText("Beta Inc")).toBeVisible();
      await expect(page.getByText("Gamma LLC")).toBeVisible();
    });
  });

  test.describe("Tenant Management", () => {
    test("platform admin can view the tenant list", async ({ page }) => {
      await mockTenantList(page);
      await page.goto("/platform/tenants");
      await page.waitForLoadState("networkidle");

      // Expect page heading
      await expect(
        page.getByRole("heading", { name: "Tenants" }),
      ).toBeVisible();

      // Expect table columns
      const columnHeaders = ["Name", "Plan", "Status", "Contact", "Created"];
      for (const header of columnHeaders) {
        await expect(
          page.locator("th").filter({ hasText: new RegExp(header, "i") }),
        ).toBeVisible();
      }

      // Expect tenant data rows
      await expect(page.getByText("Acme Corp")).toBeVisible();
      await expect(page.getByText("Beta Inc")).toBeVisible();
      await expect(page.getByText("Gamma LLC")).toBeVisible();
    });

    test("platform admin can open the provision new tenant wizard", async ({
      page,
    }) => {
      await mockTenantList(page);
      await page.goto("/platform/tenants");
      await page.waitForLoadState("networkidle");

      // Click "New Tenant" button
      const newTenantButton = page.getByRole("button", {
        name: /new tenant/i,
      });
      await expect(newTenantButton).toBeVisible();
      await newTenantButton.click();

      // Wizard modal should appear
      await expect(
        page.getByRole("heading", { name: /provision new tenant/i }),
      ).toBeVisible();

      // Step 1 of 3 should be displayed
      await expect(page.getByText("Step 1 of 3")).toBeVisible();

      // Next button should initially be disabled
      const nextButton = page.getByRole("button", { name: /next/i });
      await expect(nextButton).toBeDisabled();

      // Fill required fields
      await page.getByPlaceholder("Acme Corporation").fill("New Test Tenant");
      await page
        .getByPlaceholder("admin@acme.com")
        .fill("admin@newtenant.com");

      // Slug should auto-populate
      const slugInput = page.getByPlaceholder("acme-corporation");
      await expect(slugInput).toHaveValue("new-test-tenant");

      // Next button should now be enabled
      await expect(nextButton).toBeEnabled();

      // Advance to step 2
      await nextButton.click();
      await expect(page.getByText("Step 2 of 3")).toBeVisible();

      // Advance to step 3 (review)
      await page.getByRole("button", { name: /next/i }).click();
      await expect(page.getByText("Step 3 of 3")).toBeVisible();

      // Review should show entered data
      await expect(page.getByText("New Test Tenant")).toBeVisible();
      await expect(page.getByText("admin@newtenant.com")).toBeVisible();
    });

    test("platform admin can view tenant detail and suspend a tenant", async ({
      page,
    }) => {
      await mockTenantList(page);
      await mockTenantDetail(page);
      await mockHealthBreakdown(page);
      await mockQuotaUsage(page);
      await page.goto("/platform/tenants/tenant-001");
      await page.waitForLoadState("networkidle");

      // Back link should be visible
      await expect(page.getByText("Back to Tenants")).toBeVisible();

      // Tenant name should be displayed
      await expect(page.getByText("Acme Corp")).toBeVisible();

      // Status should be "active"
      await expect(page.getByText("active", { exact: false })).toBeVisible();

      // Suspend button should be available for active tenants
      const suspendButton = page.locator("button", {
        hasText: "Suspend Tenant",
      });
      await expect(suspendButton).toBeVisible();

      // Click suspend to open confirmation dialog
      await suspendButton.click();

      // Confirmation dialog should appear
      await expect(page.getByText("Suspend Tenant").last()).toBeVisible();
      await expect(
        page.getByText("This will block all logins and API access"),
      ).toBeVisible();

      // Confirm and Cancel buttons should be present
      await expect(
        page.getByRole("button", { name: "Confirm Suspend" }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Cancel" }),
      ).toBeVisible();
    });

    test("suspend confirmation can be cancelled", async ({ page }) => {
      await mockTenantList(page);
      await mockTenantDetail(page);
      await mockHealthBreakdown(page);
      await mockQuotaUsage(page);
      await page.goto("/platform/tenants/tenant-001");
      await page.waitForLoadState("networkidle");

      // Open suspend confirmation
      await page.locator("button", { hasText: "Suspend Tenant" }).click();
      await expect(
        page.getByRole("button", { name: "Confirm Suspend" }),
      ).toBeVisible();

      // Cancel the action
      await page.getByRole("button", { name: "Cancel" }).click();

      // Confirmation dialog should be dismissed
      await expect(
        page.getByRole("button", { name: "Confirm Suspend" }),
      ).not.toBeVisible();

      // Suspend button should still be there
      await expect(
        page.locator("button", { hasText: "Suspend Tenant" }),
      ).toBeVisible();
    });
  });

  test.describe("LLM Profiles", () => {
    test("platform admin can view and manage LLM profiles", async ({
      page,
    }) => {
      await mockLLMProfiles(page);
      await page.goto("/platform/llm-profiles");
      await page.waitForLoadState("networkidle");

      // Page heading
      await expect(
        page.getByRole("heading", { name: "LLM Profiles" }),
      ).toBeVisible();

      // Subtitle
      await expect(
        page.getByText("Configure model deployments for tenant workspaces"),
      ).toBeVisible();

      // "New Profile" button should be visible
      const newProfileButton = page.getByRole("button", {
        name: /new profile/i,
      });
      await expect(newProfileButton).toBeVisible();
    });

    test("new profile button opens the profile form", async ({ page }) => {
      await mockLLMProfiles(page);
      await page.goto("/platform/llm-profiles");
      await page.waitForLoadState("networkidle");

      // Click "New Profile"
      await page.getByRole("button", { name: /new profile/i }).click();

      // Profile form modal/overlay should appear
      await expect(
        page.locator("form, [role='dialog'], .fixed").first(),
      ).toBeVisible({ timeout: 5_000 });
    });
  });

  test.describe("Cost Analytics", () => {
    test("platform admin can view the cost analytics dashboard", async ({
      page,
    }) => {
      await mockCostAnalytics(page);
      await page.goto("/platform/analytics/cost");
      await page.waitForLoadState("networkidle");

      // Page heading
      await expect(
        page.getByRole("heading", { name: "Cost Analytics" }),
      ).toBeVisible();

      // Subtitle
      await expect(
        page.getByText("Cross-tenant cost breakdown, revenue, and margin analysis"),
      ).toBeVisible();

      // Period selector buttons should be visible
      const periodLabels = ["7 Days", "30 Days", "90 Days"];
      for (const label of periodLabels) {
        await expect(
          page.getByRole("button", { name: label }),
        ).toBeVisible();
      }
    });

    test("period selector switches between time ranges", async ({ page }) => {
      await mockCostAnalytics(page);
      await page.goto("/platform/analytics/cost");
      await page.waitForLoadState("networkidle");

      // Default is 30 Days
      const thirtyDayTab = page.getByRole("button", { name: "30 Days" });
      await expect(thirtyDayTab).toHaveClass(/border-b-accent/);

      // Click "7 Days"
      const sevenDayTab = page.getByRole("button", { name: "7 Days" });
      await sevenDayTab.click();
      await expect(sevenDayTab).toHaveClass(/border-b-accent/);
      await expect(thirtyDayTab).toHaveClass(/border-b-transparent/);

      // Click "90 Days"
      const ninetyDayTab = page.getByRole("button", { name: "90 Days" });
      await ninetyDayTab.click();
      await expect(ninetyDayTab).toHaveClass(/border-b-accent/);
      await expect(sevenDayTab).toHaveClass(/border-b-transparent/);
    });
  });

  test.describe("Platform Issue Queue", () => {
    test("platform admin can view platform-wide issue queue", async ({
      page,
    }) => {
      await mockPlatformIssueQueue(page);
      await page.goto("/platform/issues");
      await page.waitForLoadState("networkidle");

      // Page heading
      await expect(
        page.getByRole("heading", { name: "Issue Queue" }),
      ).toBeVisible();

      // Severity filter chips
      const severities = ["P0", "P1", "P2", "P3", "P4"];
      for (const sev of severities) {
        await expect(
          page.getByRole("button", { name: sev, exact: true }),
        ).toBeVisible();
      }

      // Status filter chips
      const statuses = ["Open", "In Progress", "Waiting Info", "Closed"];
      for (const status of statuses) {
        await expect(
          page.getByRole("button", { name: status }),
        ).toBeVisible();
      }
    });

    test("severity filter chips toggle correctly", async ({ page }) => {
      await mockPlatformIssueQueue(page);
      await page.goto("/platform/issues");
      await page.waitForLoadState("networkidle");

      // P0 should start unselected
      const p0Chip = page.getByRole("button", { name: "P0", exact: true });
      await expect(p0Chip).toHaveClass(/border-border/);

      // Select P0
      await p0Chip.click();
      await expect(p0Chip).toHaveClass(/border-accent-ring/);

      // Deselect P0
      await p0Chip.click();
      await expect(p0Chip).toHaveClass(/border-border/);
    });
  });
});
