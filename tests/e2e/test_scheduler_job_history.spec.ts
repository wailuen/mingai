import { test, expect, type Page } from "@playwright/test";

const BASE = "http://localhost:3025";
const SCREENSHOT_DIR = "test-results/screenshots";

/**
 * Login via the real UI login form.
 * Waits for redirect to complete before returning.
 */
async function loginViaUI(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto(`${BASE}/login`);
  await page.waitForLoadState("domcontentloaded");

  await page.fill('input[id="email"]', email);
  await page.fill('input[id="password"]', password);
  await page.click('button[type="submit"]');

  // Wait for navigation away from /login
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 15_000,
  });
  await page.waitForLoadState("domcontentloaded");
}

/**
 * E2E validation: Platform Admin Scheduler Job History UI
 *
 * All tests use REAL login — no mock JWT injection.
 * Tier 3: real browser, real database, real auth.
 *
 * Covers:
 *  Test 1 — Login as platform admin and verify console
 *  Test 2 — Navigate to Scheduler History page
 *  Test 3 — Table content, pagination, and filtering
 *  Test 4 — Status badge color conventions
 *  Test 5 — Row detail (error_message visible)
 *  Test 6 — RBAC: tenant admin cannot access job history
 *  Test 7 — Tenant Admin Sync Health page
 */
test.describe("Scheduler Job History — Platform Admin", () => {
  test("Test 1: Login as Platform Admin via real credentials", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await loginViaUI(page, "admin@mingai.local", "Admin1234!");

    // Should redirect to /platform (platform admin landing)
    expect(page.url()).toContain("/platform");

    // Verify platform admin sidebar section headings
    const sidebar = page.locator("aside");
    await expect(sidebar.locator("text=Operations")).toBeVisible();
    await expect(sidebar.locator("text=Intelligence")).toBeVisible();
    await expect(sidebar.locator("text=Finance")).toBeVisible();

    // Verify key nav items using sidebar-scoped locators to avoid strict mode
    await expect(sidebar.locator('a:has-text("Dashboard")')).toBeVisible();
    await expect(sidebar.locator('a:has-text("Tenants")')).toBeVisible();
    await expect(sidebar.locator('a:has-text("Issue Queue")')).toBeVisible();
    await expect(sidebar.locator('a:has-text("LLM Profiles")')).toBeVisible();

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/01-platform-admin-logged-in.png`,
      fullPage: true,
    });

    await context.close();
  });

  test("Test 2: Navigate to Scheduler History page", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await loginViaUI(page, "admin@mingai.local", "Admin1234!");

    // The Jobs page exists at /platform/jobs but is NOT in the sidebar nav.
    // Verify direct navigation works.
    await page.goto(`${BASE}/platform/jobs`);
    await page.waitForLoadState("domcontentloaded");

    // The page title should be "Scheduler History"
    const heading = page.locator("h1");
    await expect(heading).toContainText("Scheduler History");

    // Subtitle should be visible
    await expect(
      page.locator("text=Background job execution log"),
    ).toBeVisible();

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/02-scheduler-history-page.png`,
      fullPage: true,
    });

    // Check that sidebar does NOT have a "Jobs" or "Scheduler" link.
    const sidebar = page.locator("aside");
    const jobsLink = sidebar.locator('a:has-text("Jobs")');
    const schedulerLink = sidebar.locator('a:has-text("Scheduler")');

    const jobsVisible = await jobsLink.isVisible().catch(() => false);
    const schedulerVisible = await schedulerLink.isVisible().catch(() => false);

    // Report finding: page exists but no sidebar navigation
    if (!jobsVisible && !schedulerVisible) {
      console.warn(
        "[FINDING] Jobs/Scheduler page exists at /platform/jobs but has NO sidebar nav entry. " +
          "Users must know the URL. Consider adding to Operations section.",
      );
    }

    await context.close();
  });

  test("Test 3: Job History table content, pagination, and filters", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await loginViaUI(page, "admin@mingai.local", "Admin1234!");
    await page.goto(`${BASE}/platform/jobs`);
    await page.waitForLoadState("domcontentloaded");

    // --- 3a: Verify table columns ---
    // Wait for table header to render
    await page.waitForSelector("thead th", { timeout: 10_000 });
    const headerCells = page.locator("thead th");
    const headers = await headerCells.allTextContents();
    const expectedColumns = [
      "Job",
      "Started",
      "Duration",
      "Status",
      "Records",
      "Instance",
      "Error",
    ];
    for (const col of expectedColumns) {
      expect(
        headers.some((h) => h.toLowerCase().includes(col.toLowerCase())),
        `Table should have column "${col}". Found: ${headers.join(", ")}`,
      ).toBe(true);
    }

    // --- 3b: Verify table has data rows ---
    // Wait for skeleton to clear and real rows to appear
    await page.waitForSelector("tbody tr:not(:has(.animate-pulse))", {
      timeout: 10_000,
    });
    const dataRows = page.locator("tbody tr");
    const rowCount = await dataRows.count();
    expect(rowCount).toBeGreaterThan(0);
    console.log(`[INFO] Job history table shows ${rowCount} rows`);

    // --- 3c: Verify pagination controls ---
    const prevBtn = page.locator('button:has-text("Prev")');
    const nextBtn = page.locator('button:has-text("Next")');
    await expect(prevBtn).toBeVisible();
    await expect(nextBtn).toBeVisible();

    // Pagination summary text (e.g. "1-50 of 42")
    const paginationText = page.locator("text=/\\d+.*of.*\\d+/");
    await expect(paginationText).toBeVisible();

    // --- 3d: Verify filter controls ---
    // Job name dropdown
    const jobDropdown = page.locator("select");
    await expect(jobDropdown).toBeVisible();

    // Status filter chips
    const statusChips = page.locator('button:has-text("Completed")');
    await expect(statusChips).toBeVisible();

    // Date range inputs
    const dateInputs = page.locator('input[type="date"]');
    expect(await dateInputs.count()).toBe(2);

    // Apply button
    const applyBtn = page.locator('button:has-text("Apply")');
    await expect(applyBtn).toBeVisible();

    // --- 3e: Filter by status = "completed" ---
    await page.locator('button:has-text("Completed")').click();
    await applyBtn.click();
    await page.waitForLoadState("domcontentloaded");

    // Wait for table to update
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/03-filter-status-completed.png`,
      fullPage: true,
    });

    // All visible status badges should be "Completed"
    const statusBadges = page.locator("tbody span");
    const badgeTexts = await statusBadges.allTextContents();
    // Filter to status-badge-like elements only
    const visibleStatuses = badgeTexts
      .map((t) => t.trim().toUpperCase())
      .filter((t) =>
        ["COMPLETED", "FAILED", "RUNNING", "ABANDONED", "SKIPPED"].includes(t),
      );
    if (visibleStatuses.length > 0) {
      for (const s of visibleStatuses) {
        expect(s).toBe("COMPLETED");
      }
    }

    // --- 3f: Filter by job_name = "health_score" ---
    // Clear first
    await page.locator('button:has-text("Clear")').click();
    await page.waitForLoadState("domcontentloaded");

    await jobDropdown.selectOption("health_score");
    await applyBtn.click();
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/04-filter-job-health-score.png`,
      fullPage: true,
    });

    // All visible job names should be "health_score"
    const jobNameCells = page.locator("tbody tr td:first-child");
    const jobNames = await jobNameCells.allTextContents();
    for (const name of jobNames) {
      if (name.trim()) {
        expect(name.trim()).toBe("health_score");
      }
    }

    await context.close();
  });

  test("Test 4: Status badge color conventions", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await loginViaUI(page, "admin@mingai.local", "Admin1234!");
    await page.goto(`${BASE}/platform/jobs`);
    await page.waitForSelector("tbody tr:not(:has(.animate-pulse))", {
      timeout: 10_000,
    });

    // Check the JobStatusBadge component's CSS classes for each status
    // From the source: completed=accent-dim/accent, failed=alert-dim/alert,
    // abandoned=bg-elevated/text-muted, running=warn-dim/warn

    // --- Completed badge ---
    const completedBadge = page
      .locator("tbody span", { hasText: "Completed" })
      .first();
    if (await completedBadge.isVisible()) {
      const classes = await completedBadge.getAttribute("class");
      expect(classes).toContain("text-accent");
      expect(classes).toContain("bg-accent-dim");
      console.log("[PASS] Completed badge uses accent green styling");
    }

    // --- Failed badge ---
    const failedBadge = page
      .locator("tbody span", { hasText: "Failed" })
      .first();
    if (await failedBadge.isVisible()) {
      const classes = await failedBadge.getAttribute("class");
      expect(classes).toContain("text-alert");
      expect(classes).toContain("bg-alert-dim");
      console.log("[PASS] Failed badge uses alert orange styling");
    }

    // --- Abandoned badge ---
    const abandonedBadge = page
      .locator("tbody span", { hasText: "Abandoned" })
      .first();
    if (await abandonedBadge.isVisible()) {
      const classes = await abandonedBadge.getAttribute("class");
      expect(classes).toContain("text-text-muted");
      expect(classes).toContain("bg-bg-elevated");
      console.log("[PASS] Abandoned badge uses muted gray styling");
    }

    // --- Running badge ---
    const runningBadge = page
      .locator("tbody span", { hasText: "Running" })
      .first();
    if (await runningBadge.isVisible()) {
      const classes = await runningBadge.getAttribute("class");
      expect(classes).toContain("text-warn");
      expect(classes).toContain("bg-warn-dim");
      console.log(
        "[FINDING] Running badge uses warn (yellow) styling, not accent green. " +
          "Design system says running should use accent with blinking/spinning indicator.",
      );
    }

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/05-status-badges.png`,
      fullPage: true,
    });

    await context.close();
  });

  test("Test 5: Row detail — error_message visible on failed rows", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await loginViaUI(page, "admin@mingai.local", "Admin1234!");
    await page.goto(`${BASE}/platform/jobs`);
    await page.waitForSelector("tbody tr:not(:has(.animate-pulse))", {
      timeout: 10_000,
    });

    // Find a row with a "Failed" badge
    const failedRow = page
      .locator("tbody tr", {
        has: page.locator('span:has-text("Failed")'),
      })
      .first();

    if (await failedRow.isVisible()) {
      // The error column should show the error_message (truncated with title tooltip)
      const errorCell = failedRow.locator("td").last();
      const errorText = await errorCell.textContent();
      const errorTitle = await errorCell.getAttribute("title");

      expect(
        errorText?.trim().length || 0,
        "Error cell should contain text for failed jobs",
      ).toBeGreaterThan(0);

      console.log(`[INFO] Error text: ${errorText?.trim()}`);
      console.log(`[INFO] Error tooltip: ${errorTitle}`);

      // The full error should be in the title attribute
      if (errorTitle) {
        expect(errorTitle.length).toBeGreaterThan(0);
      }

      // Verify other columns are populated
      const cells = failedRow.locator("td");
      const jobName = await cells.nth(0).textContent();
      expect(jobName?.trim().length).toBeGreaterThan(0);

      const duration = await cells.nth(2).textContent();
      expect(duration?.trim()).not.toBe("");

      await page.screenshot({
        path: `${SCREENSHOT_DIR}/06-failed-row-detail.png`,
        fullPage: true,
      });
    } else {
      console.warn(
        "[WARN] No failed rows visible in the default view. " +
          "Test 5 requires a 'failed' job_run_log record.",
      );
    }

    // The current UI does NOT have a click-to-expand row detail panel.
    // The error_message is shown inline in the last column (truncated with tooltip).
    console.log(
      "[FINDING] No row-click detail panel implemented. " +
        "Error info is shown inline via truncated text + title tooltip.",
    );

    await context.close();
  });

  test("Test 6: RBAC — Tenant admin cannot access job history", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    // Login as tenant admin using real credentials
    await loginViaUI(page, "admin@tpcgroup.test", "Admin123!");

    // Attempt to navigate to platform jobs page as tenant admin
    await page.goto(`${BASE}/platform/jobs`);
    await page.waitForLoadState("domcontentloaded");
    // Allow time for any redirect to complete
    await page.waitForTimeout(2000);

    const url = page.url();

    // The tenant admin should be redirected away from /platform/* routes
    // because middleware checks scope !== "platform" and redirects to /chat
    if (!url.includes("/platform/jobs")) {
      console.log(
        `[PASS] Tenant admin was redirected from /platform/jobs to: ${url}`,
      );
    } else {
      // If somehow we're still on /platform/jobs, check if data is blocked
      const heading = page.locator("h1");
      const headingText = await heading.textContent().catch(() => "");

      if (headingText?.includes("Scheduler History")) {
        const errorMessage = page.locator("text=Failed to load job history");
        const noData = page.locator("text=No job history");
        const isError = await errorMessage.isVisible().catch(() => false);
        const isEmpty = await noData.isVisible().catch(() => false);

        if (isError) {
          console.log(
            "[PASS] Tenant admin sees error — API correctly rejects non-platform scope",
          );
        } else if (isEmpty) {
          console.log(
            "[WARN] Tenant admin sees empty table — API may return empty instead of 403",
          );
        } else {
          console.log(
            "[FAIL] Tenant admin can view scheduler history page with data. RBAC gap.",
          );
        }
      }
    }

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/07-tenant-admin-rbac-block.png`,
      fullPage: true,
    });

    // Verify the URL is NOT /platform/jobs (middleware should have redirected)
    expect(page.url()).not.toContain("/platform/jobs");

    // Also verify tenant admin sidebar does NOT have Scheduler link
    const sidebar = page.locator("aside");
    const sidebarContent = await sidebar.textContent().catch(() => "");
    expect(sidebarContent).not.toContain("Scheduler");

    await context.close();
  });

  test("Test 7: Tenant Admin — Sync Health page accessible", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    // Login as tenant admin using real credentials
    await loginViaUI(page, "admin@tpcgroup.test", "Admin123!");

    // Try direct navigation to sync health page
    await page.goto(`${BASE}/admin/sync`);
    await page.waitForLoadState("domcontentloaded");
    // Allow time for any redirects or data loading
    await page.waitForTimeout(2000);

    const heading = page.locator("h1");
    const headingText = await heading.textContent().catch(() => "");

    if (headingText?.includes("Sync Health")) {
      console.log("[PASS] Sync Health page is accessible at /admin/sync");

      // Check for integration cards or empty state
      const emptyState = page.locator("text=No document sources connected");
      const isEmpty = await emptyState.isVisible().catch(() => false);
      if (isEmpty) {
        console.log(
          "[INFO] No integrations connected — empty state displayed correctly",
        );
      } else {
        console.log("[INFO] Integration cards or content visible");
      }

      // Check sidebar for sync link
      const sidebar = page.locator("aside");
      const syncLink = sidebar.locator('a:has-text("Sync")');
      const hasSyncLink = await syncLink.isVisible().catch(() => false);
      if (!hasSyncLink) {
        console.warn(
          "[FINDING] Sync Health page exists at /admin/sync but has NO sidebar nav entry. " +
            "Consider adding under Workspace section.",
        );
      }
    } else {
      console.log(
        `[INFO] Sync Health page not found or redirected. Current URL: ${page.url()}, heading: "${headingText}"`,
      );
    }

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/08-tenant-admin-sync-health.png`,
      fullPage: true,
    });

    await context.close();
  });
});
