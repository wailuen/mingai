import { test, expect } from "@playwright/test";
import { injectTenantAdminAuth } from "./helpers";
import {
  mockGlossaryTerms,
  mockGlossaryExport,
  mockMissSignals,
  mockSSONotConfigured,
  mockSSOConfigured,
  mockIssueReportingConfig,
  mockIntegrations,
  mockConversationsList,
} from "./helpers/api-mocks";

/**
 * FE-059: Tenant Admin Flow E2E Tests
 *
 * Validates key tenant admin screens: glossary management, SSO configuration,
 * issue reporting settings, and knowledge base / sync health.
 */
test.describe("FE-059: Tenant Admin Flows", () => {
  test.beforeEach(async ({ context, page }) => {
    await injectTenantAdminAuth(context);
    await mockConversationsList(page);
  });

  test.describe("Glossary Management", () => {
    test("glossary page loads and displays terms table", async ({ page }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await page.goto("/settings/glossary");

      // Page title
      await expect(page.locator("h1", { hasText: "Glossary" })).toBeVisible();

      // Subtitle
      await expect(
        page.getByText("Define terms to improve AI response accuracy"),
      ).toBeVisible();

      // Table headers should be visible
      const table = page.locator("table").first();
      await expect(table).toBeVisible({ timeout: 10_000 });

      await expect(table.locator("th", { hasText: "Term" })).toBeVisible();
      await expect(
        table.locator("th", { hasText: "Definition" }),
      ).toBeVisible();
      await expect(table.locator("th", { hasText: "Status" })).toBeVisible();

      // Term data should render
      await expect(table.getByText("ARR")).toBeVisible();
      await expect(table.getByText("CSAT")).toBeVisible();
      await expect(table.getByText("MRR")).toBeVisible();

      // Status indicators
      await expect(table.getByText("Active").first()).toBeVisible();
      await expect(table.getByText("Inactive")).toBeVisible();

      // Pagination controls should be visible
      await expect(page.getByText("3 total terms")).toBeVisible();
      await expect(
        page.locator("button", { hasText: "Previous" }),
      ).toBeVisible();
      await expect(page.locator("button", { hasText: "Next" })).toBeVisible();
    });

    test("glossary search input is functional", async ({ page }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await page.goto("/settings/glossary");

      // Search input should be visible
      const searchInput = page.locator('input[placeholder="Search terms..."]');
      await expect(searchInput).toBeVisible();

      // Type into search
      await searchInput.fill("ARR");

      // Input should reflect the typed value
      await expect(searchInput).toHaveValue("ARR");
    });

    test("glossary status filter is functional", async ({ page }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await page.goto("/settings/glossary");

      // Status filter select should be visible
      const statusFilter = page.locator("select");
      await expect(statusFilter).toBeVisible();

      // Should have All Status, Active, Inactive options
      await expect(statusFilter.locator("option")).toHaveCount(3);
      await expect(statusFilter.locator('option[value=""]')).toHaveText(
        "All Status",
      );
      await expect(statusFilter.locator('option[value="active"]')).toHaveText(
        "Active",
      );
      await expect(statusFilter.locator('option[value="inactive"]')).toHaveText(
        "Inactive",
      );
    });

    test("export CSV button triggers download", async ({ page }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await mockGlossaryExport(page);
      await page.goto("/settings/glossary");

      // Export CSV button should be visible
      const exportButton = page.locator("button", { hasText: "Export CSV" });
      await expect(exportButton).toBeVisible();

      // Click export -- since we mock the API, just verify the button is clickable
      // and does not throw
      await exportButton.click();

      // The button should not be permanently disabled after click
      // (it may briefly show a spinner but should return to normal)
      await expect(exportButton).toBeVisible({ timeout: 5_000 });
    });

    test("add term button opens form modal", async ({ page }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await page.goto("/settings/glossary");

      const addButton = page.locator("button", { hasText: "Add Term" });
      await expect(addButton).toBeVisible();

      await addButton.click();

      // The TermForm modal/overlay should appear
      // It will contain form fields for creating a term
      await expect(page.locator("form, [role='dialog']").first()).toBeVisible({
        timeout: 5_000,
      });
    });

    test("import CSV button opens import dialog", async ({ page }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await page.goto("/settings/glossary");

      const importButton = page.locator("button", { hasText: "Import CSV" });
      await expect(importButton).toBeVisible();

      await importButton.click();

      // BulkImportDialog should appear
      await expect(page.locator("[role='dialog']").first()).toBeVisible({
        timeout: 5_000,
      });
    });

    test("miss signals panel shows uncovered terms", async ({ page }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await page.goto("/settings/glossary");

      // Miss Signals section heading
      await expect(page.locator("h2", { hasText: "Miss Signals" })).toBeVisible(
        { timeout: 10_000 },
      );

      // Description text
      await expect(
        page.getByText(
          "Terms appearing in queries but not covered by glossary",
        ),
      ).toBeVisible();

      // Miss signals table
      const missTable = page.locator("table").last();

      // Headers: Term, Occurrences, Last Seen, Action
      await expect(missTable.locator("th", { hasText: "Term" })).toBeVisible();
      await expect(
        missTable.locator("th", { hasText: "Occurrences" }),
      ).toBeVisible();
      await expect(
        missTable.locator("th", { hasText: "Last Seen" }),
      ).toBeVisible();

      // Data rows
      await expect(missTable.getByText("NPS")).toBeVisible();
      await expect(missTable.getByText("14")).toBeVisible();
      await expect(missTable.getByText("CAC")).toBeVisible();
      await expect(missTable.getByText("8")).toBeVisible();

      // "Add to Glossary" action link
      const addLinks = missTable.getByText("Add to Glossary");
      await expect(addLinks.first()).toBeVisible();
    });

    test("clicking 'Add to Glossary' from miss signals opens form", async ({
      page,
    }) => {
      await mockGlossaryTerms(page);
      await mockMissSignals(page);
      await page.goto("/settings/glossary");

      // Wait for miss signals to load
      await expect(page.getByText("NPS")).toBeVisible({ timeout: 10_000 });

      // Click "Add to Glossary" for the first signal
      const addLinks = page.getByText("Add to Glossary");
      await addLinks.first().click();

      // Term form should open (modal/overlay)
      await expect(page.locator("form, [role='dialog']").first()).toBeVisible({
        timeout: 5_000,
      });
    });
  });

  test.describe("SSO Configuration", () => {
    test("SSO page renders not-configured state with setup button", async ({
      page,
    }) => {
      await mockSSONotConfigured(page);
      await page.goto("/settings/sso");

      // Page title
      await expect(
        page.locator("h1", { hasText: "Single Sign-On" }),
      ).toBeVisible();

      // Description
      await expect(
        page.getByText(
          "Configure SAML or OIDC authentication for your workspace",
        ),
      ).toBeVisible();

      // Not configured message
      await expect(page.getByText("SSO is not configured")).toBeVisible({
        timeout: 10_000,
      });

      // Configure SSO button
      const configureButton = page.locator("button", {
        hasText: "Configure SSO",
      });
      await expect(configureButton).toBeVisible();
    });

    test("clicking Configure SSO opens the setup wizard", async ({ page }) => {
      await mockSSONotConfigured(page);
      await page.goto("/settings/sso");

      await expect(page.getByText("SSO is not configured")).toBeVisible({
        timeout: 10_000,
      });

      await page.locator("button", { hasText: "Configure SSO" }).click();

      // SSOSetupWizard should appear
      // Wizard typically renders as a modal/overlay with step UI
      await expect(page.locator("[role='dialog'], .fixed").first()).toBeVisible(
        { timeout: 5_000 },
      );
    });

    test("SSO page renders configured SAML state with status card", async ({
      page,
    }) => {
      await mockSSOConfigured(page);
      await page.goto("/settings/sso");

      // Wait for the SSOStatusCard to render
      await expect(page.getByText("SAML 2.0")).toBeVisible({
        timeout: 10_000,
      });

      // Status indicator should show "Configured"
      await expect(page.getByText("Configured")).toBeVisible();

      // SAML detail rows should be visible
      await expect(page.getByText("Entity ID")).toBeVisible();
      await expect(
        page.getByText("https://sso.mingai.test/saml"),
      ).toBeVisible();
      await expect(page.getByText("ACS URL")).toBeVisible();
      await expect(page.getByText("Metadata URL")).toBeVisible();

      // Action buttons
      await expect(
        page.locator("button", { hasText: "Test SSO" }),
      ).toBeVisible();
      await expect(
        page.locator("button", { hasText: "Reconfigure" }),
      ).toBeVisible();
    });

    test("Reconfigure button on SSO status card opens wizard", async ({
      page,
    }) => {
      await mockSSOConfigured(page);
      await page.goto("/settings/sso");

      await expect(page.getByText("SAML 2.0")).toBeVisible({
        timeout: 10_000,
      });

      await page.locator("button", { hasText: "Reconfigure" }).click();

      // Wizard should open
      await expect(page.locator("[role='dialog'], .fixed").first()).toBeVisible(
        { timeout: 5_000 },
      );
    });
  });

  test.describe("Issue Reporting Settings", () => {
    test("issue reporting page renders with form controls", async ({
      page,
    }) => {
      await mockIssueReportingConfig(page);
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

      // Enable Issue Reporting toggle should be visible
      await expect(page.getByText("Enable Issue Reporting")).toBeVisible({
        timeout: 10_000,
      });

      const enableToggle = page.getByLabel("Toggle issue reporting");
      await expect(enableToggle).toBeVisible();

      // The toggle should reflect the mocked "enabled: true" state
      await expect(enableToggle).toHaveAttribute("aria-checked", "true");
    });

    test("notification email input is present and populated", async ({
      page,
    }) => {
      await mockIssueReportingConfig(page);
      await page.goto("/settings/issue-reporting");

      // Wait for form to load
      await expect(page.getByText("Notification Email")).toBeVisible({
        timeout: 10_000,
      });

      // Email input should have the mocked value
      const emailInput = page.locator('input[type="email"]');
      await expect(emailInput).toBeVisible();
      await expect(emailInput).toHaveValue("admin@company.com");
    });

    test("auto-escalate toggles are present", async ({ page }) => {
      await mockIssueReportingConfig(page);
      await page.goto("/settings/issue-reporting");

      // P0 escalation toggle (mocked as true)
      await expect(page.getByText("Auto-escalate P0 Issues")).toBeVisible({
        timeout: 10_000,
      });
      const p0Toggle = page.getByLabel("Toggle auto-escalate P0");
      await expect(p0Toggle).toBeVisible();
      await expect(p0Toggle).toHaveAttribute("aria-checked", "true");

      // P1 escalation toggle (mocked as false)
      await expect(page.getByText("Auto-escalate P1 Issues")).toBeVisible();
      const p1Toggle = page.getByLabel("Toggle auto-escalate P1");
      await expect(p1Toggle).toBeVisible();
      await expect(p1Toggle).toHaveAttribute("aria-checked", "false");
    });

    test("escalation threshold input shown when P0 or P1 enabled", async ({
      page,
    }) => {
      await mockIssueReportingConfig(page);
      await page.goto("/settings/issue-reporting");

      // Since auto_escalate_p0 is true, threshold should be visible
      await expect(page.getByText("Escalation Threshold (hours)")).toBeVisible({
        timeout: 10_000,
      });

      const thresholdInput = page.locator('input[type="number"]');
      await expect(thresholdInput).toBeVisible();
      await expect(thresholdInput).toHaveValue("4");
    });

    test("slack webhook input is present", async ({ page }) => {
      await mockIssueReportingConfig(page);
      await page.goto("/settings/issue-reporting");

      await expect(page.getByText("Slack Webhook URL")).toBeVisible({
        timeout: 10_000,
      });

      const webhookInput = page.locator(
        'input[placeholder="https://hooks.slack.com/services/..."]',
      );
      await expect(webhookInput).toBeVisible();
    });

    test("save button is present and clickable", async ({ page }) => {
      await mockIssueReportingConfig(page);
      await page.goto("/settings/issue-reporting");

      await expect(page.getByText("Enable Issue Reporting")).toBeVisible({
        timeout: 10_000,
      });

      const saveButton = page.locator("button", {
        hasText: "Save Changes",
      });
      await expect(saveButton).toBeVisible();
      await expect(saveButton).toBeEnabled();
    });
  });

  test.describe("Knowledge Base / Sync Health", () => {
    test("knowledge base page renders with integration cards", async ({
      page,
    }) => {
      await mockIntegrations(page);
      await page.goto("/settings/knowledge-base");

      // Page title
      await expect(
        page.locator("h1", { hasText: "Document Stores" }),
      ).toBeVisible();

      // Tab navigation
      await expect(
        page.locator("button", { hasText: "SharePoint" }),
      ).toBeVisible();
      await expect(
        page.locator("button", { hasText: "Google Drive" }),
      ).toBeVisible();

      // SharePoint tab should be active by default and show integration cards
      // The mocked integrations include "Corporate SharePoint" and "HR SharePoint"
      await expect(page.getByText("Corporate SharePoint")).toBeVisible({
        timeout: 10_000,
      });
      await expect(page.getByText("HR SharePoint")).toBeVisible();
    });

    test("connect source button is present", async ({ page }) => {
      await mockIntegrations(page);
      await page.goto("/settings/knowledge-base");

      const connectButton = page.locator("button", {
        hasText: "Connect Source",
      });
      await expect(connectButton).toBeVisible();
    });

    test("tab switching between SharePoint and Google Drive", async ({
      page,
    }) => {
      await mockIntegrations(page);
      await page.goto("/settings/knowledge-base");

      // Wait for SharePoint tab content
      await expect(page.getByText("Corporate SharePoint")).toBeVisible({
        timeout: 10_000,
      });

      // Switch to Google Drive tab
      await page.locator("button", { hasText: "Google Drive" }).click();

      // SharePoint content should no longer be visible
      await expect(page.getByText("Corporate SharePoint")).not.toBeVisible();

      // Switch back to SharePoint
      await page.locator("button", { hasText: "SharePoint" }).click();
      await expect(page.getByText("Corporate SharePoint")).toBeVisible();
    });
  });
});
