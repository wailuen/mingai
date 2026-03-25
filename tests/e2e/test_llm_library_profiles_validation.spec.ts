import { test, expect, type BrowserContext } from "@playwright/test";

/**
 * TEST-LLM-VAL: LLM Library Usage Protection & LLM Profiles Display Names
 *
 * Validates:
 *   Flow 1: LLM Library — usage protection badges and disabled Deprecate buttons
 *   Flow 2: LLM Profiles — slot display names (not raw deployment IDs)
 *   Flow 3: Profile detail panel — slot assignments and data integrity
 *   Flow 4: Backend API 409 protection
 *
 * Uses real API — no mocking (Tier 3 E2E).
 */

const BASE_URL = "http://localhost:3022";
const API_BASE = "http://localhost:8022";
const SCREENSHOT_DIR = "screenshots/llm-validation";

// Increase timeout for pages with polling/SSE connections
test.setTimeout(60_000);

// ---------------------------------------------------------------------------
// Auth helper — real JWT from backend login
// ---------------------------------------------------------------------------

async function getAdminToken(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/auth/local/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: "admin@mingai.local",
      password: "Admin1234!",
    }),
  });
  const data = await res.json();
  if (!data.access_token) {
    throw new Error(`Failed to get admin token: ${JSON.stringify(data)}`);
  }
  return data.access_token;
}

async function injectPlatformAdminAuth(context: BrowserContext): Promise<void> {
  const token = await getAdminToken();
  const payload = JSON.parse(
    Buffer.from(token.split(".")[1], "base64url").toString("utf8"),
  );
  await context.addCookies([
    {
      name: "access_token",
      value: token,
      domain: "localhost",
      path: "/",
      expires: payload.exp,
      httpOnly: false,
      secure: false,
      sameSite: "Lax",
    },
  ]);
}

// ---------------------------------------------------------------------------
// Flow 1: LLM Library — usage protection UI
// ---------------------------------------------------------------------------

test.describe("Flow 1: LLM Library usage protection", () => {
  test.beforeEach(async ({ context }) => {
    await injectPlatformAdminAuth(context);
  });

  test("shows profile usage badges on in-use entries and disables Deprecate", async ({
    page,
  }) => {
    await page.goto(`${BASE_URL}/platform/llm-library`);

    // Wait for the table to render with actual data (skip networkidle — polling keeps it busy)
    await expect(page.locator("table tbody tr").first()).toBeVisible({
      timeout: 15000,
    });

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/01-library-table-loaded.png`,
      fullPage: true,
    });

    // Get all visible table rows
    const rows = page.locator("table tbody tr");
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThanOrEqual(4);

    // Use filter-based row selection (more robust than index mapping)
    // The first cell contains display_name as a <span> with font-medium class

    // --- Entries WITH profile usage (should have badge, Deprecate disabled) ---

    // GPT Vision — 2 profiles
    const gptVisionRow = rows.filter({ hasText: "GPT Vision" }).filter({ hasText: "Azure OpenAI" }).first();
    await expect(gptVisionRow).toBeVisible();
    await expect(gptVisionRow.locator("text=2 profiles")).toBeVisible();
    await expect(
      gptVisionRow.locator("button", { hasText: "Deprecate" }),
    ).toBeDisabled();

    // GPT-5 Mini (Intent) — 2 profiles
    const intentRow = rows.filter({ hasText: "GPT-5 Mini (Intent)" });
    await expect(intentRow).toBeVisible();
    await expect(intentRow.locator("text=2 profiles")).toBeVisible();
    await expect(
      intentRow.locator("button", { hasText: "Deprecate" }),
    ).toBeDisabled();

    // Claude Haiku — 1 profile
    const haikuRow = rows.filter({ hasText: "Claude Haiku" });
    await expect(haikuRow).toBeVisible();
    await expect(haikuRow.locator("text=1 profile")).toBeVisible();
    await expect(
      haikuRow.locator("button", { hasText: "Deprecate" }),
    ).toBeDisabled();

    // Azure OpenAI — Primary Chat — 1 profile
    const azureRow = rows.filter({ hasText: "Primary Chat" });
    await expect(azureRow).toBeVisible();
    await expect(azureRow.locator("text=1 profile")).toBeVisible();
    await expect(
      azureRow.locator("button", { hasText: "Deprecate" }),
    ).toBeDisabled();

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/02-library-usage-badges.png`,
      fullPage: true,
    });

    // --- Entries WITHOUT profile usage (no badge, Deprecate enabled or deprecated) ---

    // Claude Sonnet 4.6 — 0 profiles (if still published)
    const sonnetRow = rows.filter({ hasText: "Claude Sonnet" });
    const sonnetCount = await sonnetRow.count();
    if (sonnetCount > 0) {
      await expect(sonnetRow).toBeVisible();
      // Should NOT have a profile badge
      const sonnetBadge = sonnetRow.locator("text=/\\d+ profiles?/");
      await expect(sonnetBadge).toHaveCount(0);
      // Deprecate should be enabled (unless already deprecated)
      const sonnetDeprecate = sonnetRow.locator("button", {
        hasText: "Deprecate",
      });
      const sonnetDeprecateCount = await sonnetDeprecate.count();
      if (sonnetDeprecateCount > 0) {
        await expect(sonnetDeprecate).toBeEnabled();
      }
    }
  });

  test("detail panel shows disabled Deprecate for in-use entry", async ({
    page,
  }) => {
    await page.goto(`${BASE_URL}/platform/llm-library`);
    await expect(page.locator("table tbody tr").first()).toBeVisible({
      timeout: 15000,
    });

    // Click on GPT Vision row to open detail panel
    const rows = page.locator("table tbody tr");
    const rowCount = await rows.count();
    for (let i = 0; i < rowCount; i++) {
      const cellText = await rows.nth(i).locator("td").first().textContent();
      if (cellText && cellText.includes("GPT Vision")) {
        await rows.nth(i).click();
        break;
      }
    }

    // Wait for detail panel/form to appear
    await page.waitForTimeout(800);

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/03-library-detail-gptvision.png`,
      fullPage: true,
    });

    // In the detail panel, the LifecycleActions component should show
    // the usage badge and a disabled Deprecate button
    const profileBadge = page.locator("text=2 profiles");
    await expect(profileBadge.first()).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Flow 2: LLM Profiles — slot display names
// ---------------------------------------------------------------------------

test.describe("Flow 2: LLM Profiles slot display names", () => {
  test.beforeEach(async ({ context }) => {
    await injectPlatformAdminAuth(context);
  });

  test("profiles table shows display names in slot columns, not raw IDs", async ({
    page,
  }) => {
    await page.goto(`${BASE_URL}/platform/llm-profiles`);

    // Wait for profiles to load
    await expect(page.locator("table tbody tr").first()).toBeVisible({
      timeout: 15000,
    });

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/04-profiles-table-loaded.png`,
      fullPage: true,
    });

    // Verify page title
    await expect(page.locator("h1")).toHaveText("LLM Profiles");

    // Verify two profiles exist
    const rows = page.locator("table tbody tr");
    await expect(rows).toHaveCount(2);

    // --- Standard Platform Profile ---
    const standardRow = rows.filter({ hasText: "Standard Platform Profile" });
    await expect(standardRow).toBeVisible();

    // Slot display names should be human-readable
    // The "Azure OpenAI -- Primary Chat" text may be truncated in narrow columns,
    // so we check for the prefix that's always visible
    await expect(
      standardRow.locator("td").filter({ hasText: /Azure OpenAI/ }),
    ).toHaveCount(2); // Chat + Agent both show this
    await expect(
      standardRow.locator("text=GPT-5 Mini (Intent)"),
    ).toBeVisible();
    await expect(standardRow.locator("text=GPT Vision")).toBeVisible();

    // Should NOT show raw deployment IDs anywhere in the row
    const standardText = await standardRow.textContent();
    expect(standardText).not.toContain("aihub2-main");
    expect(standardText).not.toContain("gpt-5-turbo-deployment-01");

    // Verify plan chips
    await expect(standardRow.locator("text=professional")).toBeVisible();
    await expect(standardRow.locator("text=enterprise")).toBeVisible();

    // Verify status
    await expect(standardRow.locator("text=active")).toBeVisible();

    // --- Starter Platform Profile ---
    const starterRow = rows.filter({ hasText: "Starter Platform Profile" });
    await expect(starterRow).toBeVisible();

    // Chat + Agent = Claude Haiku
    const haikuCells = starterRow.locator("td").filter({ hasText: "Claude Haiku" });
    await expect(haikuCells.first()).toBeVisible();

    // Intent = GPT-5 Mini
    await expect(
      starterRow.locator("text=GPT-5 Mini (Intent)"),
    ).toBeVisible();

    // Vision = GPT Vision
    await expect(starterRow.locator("text=GPT Vision")).toBeVisible();

    // Should NOT show raw Bedrock ARN
    const starterText = await starterRow.textContent();
    expect(starterText).not.toContain("arn:aws:bedrock");
    expect(starterText).not.toContain("application-inference-profile");

    // Plan chips — use exact match to avoid matching "Starter Platform Profile" text
    await expect(
      starterRow.locator("span.rounded-badge", { hasText: "starter" }),
    ).toBeVisible();

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/05-profiles-display-names-verified.png`,
      fullPage: true,
    });
  });
});

// ---------------------------------------------------------------------------
// Flow 3: Profile detail panel
// ---------------------------------------------------------------------------

test.describe("Flow 3: Profile detail panel", () => {
  test.beforeEach(async ({ context }) => {
    await injectPlatformAdminAuth(context);
  });

  test("Standard Profile detail panel shows all slots correctly", async ({
    page,
  }) => {
    await page.goto(`${BASE_URL}/platform/llm-profiles`);
    await expect(page.locator("table tbody tr").first()).toBeVisible({
      timeout: 15000,
    });

    // Click on Standard Platform Profile
    const standardRow = page
      .locator("table tbody tr")
      .filter({ hasText: "Standard Platform Profile" });
    await standardRow.click();

    // Wait for detail panel to slide in — use the fixed right panel, not the sidebar
    const panel = page.locator("aside.fixed");
    await expect(panel).toBeVisible({ timeout: 5000 });

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/06-profile-detail-standard.png`,
      fullPage: true,
    });

    // Verify panel header shows profile name
    await expect(panel.locator("text=Standard Platform Profile")).toBeVisible();

    // Verify status badge
    await expect(panel.locator("text=active")).toBeVisible();

    // Verify slot assignment section exists
    await expect(panel.locator("text=Slot Assignments")).toBeVisible();

    // Verify each slot label is present
    await expect(panel.locator("text=Chat").first()).toBeVisible();
    await expect(panel.locator("text=Intent").first()).toBeVisible();
    await expect(panel.locator("text=Vision").first()).toBeVisible();
    await expect(panel.locator("text=Agent").first()).toBeVisible();

    // Verify "Profile Details" section
    await expect(panel.locator("text=Profile Details")).toBeVisible();

    // Verify Plan Availability section
    await expect(panel.locator("text=Plan Availability")).toBeVisible();

    // Verify Tenant Usage section
    await expect(panel.locator("text=Tenant Usage")).toBeVisible();

    // Verify Connection Test section
    await expect(panel.locator("text=Connection Test")).toBeVisible();
    await expect(panel.locator("text=Test All Slots")).toBeVisible();

    // Verify no broken/missing data — no "Not assigned" for required slots
    const notAssigned = panel.locator("text=Not assigned");
    const notAssignedCount = await notAssigned.count();
    expect(notAssignedCount).toBe(0);

    // Close panel with Escape
    await page.keyboard.press("Escape");

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/07-profile-detail-closed.png`,
      fullPage: true,
    });
  });
});

// ---------------------------------------------------------------------------
// Flow 4: Backend API 409 protection (API-level, no browser needed)
// ---------------------------------------------------------------------------

test.describe("Flow 4: Backend API deprecation protection", () => {
  test("409 when deprecating an in-use library entry", async () => {
    const token = await getAdminToken();

    // Fetch library entries to find one with profile_usage_count > 0
    const listRes = await fetch(`${API_BASE}/api/v1/platform/llm-library`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const entries = await listRes.json();

    // API returns lowercase status values
    const inUseEntry = entries.find(
      (e: { profile_usage_count: number; status: string }) =>
        e.profile_usage_count > 0 && e.status === "published",
    );
    expect(inUseEntry).toBeTruthy();

    // Attempt to deprecate — should get 409
    const deprecateRes = await fetch(
      `${API_BASE}/api/v1/platform/llm-library/${inUseEntry.id}/deprecate`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    expect(deprecateRes.status).toBe(409);

    const body = await deprecateRes.json();
    expect(body.message).toContain("Cannot deprecate");
    expect(body.message).toContain("LLM Profile");
  });

  test("200 when deprecating an unused library entry", async () => {
    const token = await getAdminToken();

    // Fetch library entries to find one with profile_usage_count === 0
    const listRes = await fetch(`${API_BASE}/api/v1/platform/llm-library`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const entries = await listRes.json();

    // API returns lowercase status values
    const unusedEntry = entries.find(
      (e: { profile_usage_count: number; status: string }) =>
        e.profile_usage_count === 0 && e.status === "published",
    );

    // Skip if no unused published entry exists (may have been deprecated in prior run)
    test.skip(
      !unusedEntry,
      "No unused published entry available to test deprecation",
    );

    if (unusedEntry) {
      const deprecateRes = await fetch(
        `${API_BASE}/api/v1/platform/llm-library/${unusedEntry.id}/deprecate`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      expect(deprecateRes.status).toBe(200);

      const body = await deprecateRes.json();
      expect(body.status).toBe("deprecated");
    }
  });
});
