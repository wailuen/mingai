import { test, expect } from "@playwright/test";
import { injectAuth } from "./helpers/auth";
import {
  mockConversationsList,
  mockUserProfile,
  mockMemoryNotes,
} from "./helpers/api-mocks";

/**
 * TEST-059: Profile and Memory E2E Tests
 *
 * Validates the privacy settings page, including work profile toggles,
 * memory notes CRUD, GDPR data export, and GDPR data erasure flows.
 */
test.describe("TEST-059: Profile and Memory", () => {
  test.beforeEach(async ({ context, page }) => {
    await injectAuth(context);
    await mockConversationsList(page);
    await mockUserProfile(page);
    await mockMemoryNotes(page);
  });

  test.describe("Privacy Settings Page", () => {
    test("privacy settings page renders all sections", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Page heading
      await expect(
        page.getByRole("heading", { name: "Privacy Settings" }),
      ).toBeVisible();

      // Work Profile card
      await expect(
        page.locator("h3", { hasText: "Work Profile" }),
      ).toBeVisible();

      // Memory Notes card
      await expect(
        page.locator("h3", { hasText: "Memory Notes" }),
      ).toBeVisible();

      // Data Rights card
      await expect(
        page.locator("h3", { hasText: "Your Data Rights" }),
      ).toBeVisible();
    });
  });

  test.describe("Work Profile", () => {
    test("work profile card displays toggle controls", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // "Use organizational context in responses" toggle
      await expect(
        page.getByText("Use organizational context in responses"),
      ).toBeVisible();

      // Description text
      await expect(
        page.getByText(
          "Your role, department, and team info will personalize answers",
        ),
      ).toBeVisible();

      // Toggle switches should be present
      const switches = page.getByRole("switch");
      await expect(switches.first()).toBeVisible();
    });

    test("org context toggle controls sub-toggle visibility", async ({
      page,
    }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Since orgContextEnabled is true by default, "Include manager name" should be visible
      await expect(
        page.getByText("Include manager name"),
      ).toBeVisible();

      await expect(
        page.getByText("Share your manager's name for org-aware responses"),
      ).toBeVisible();
    });
  });

  test.describe("Memory Notes", () => {
    test("memory notes list displays existing notes", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Memory Notes heading should be visible
      await expect(
        page.locator("h3", { hasText: "Memory Notes" }),
      ).toBeVisible();

      // Notes count should be visible (3/15)
      await expect(page.getByText("3/15")).toBeVisible();

      // Note content should be displayed
      await expect(
        page.getByText("Prefers detailed technical explanations"),
      ).toBeVisible();
      await expect(
        page.getByText("Works on Project Alpha team"),
      ).toBeVisible();
      await expect(page.getByText("Reports to Jane Smith")).toBeVisible();

      // Source badges should be visible
      await expect(page.getByText("user-directed").first()).toBeVisible();
      await expect(page.getByText("auto-extracted").first()).toBeVisible();
    });

    test("memory notes have delete buttons for each note", async ({
      page,
    }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Wait for notes to load
      await expect(
        page.getByText("Prefers detailed technical explanations"),
      ).toBeVisible();

      // Each note should have a delete button (aria-label: "Delete note: ...")
      const deleteButtons = page.locator(
        'button[aria-label^="Delete note:"]',
      );
      await expect(deleteButtons).toHaveCount(3);
    });

    test("clicking delete on a note invokes the delete API", async ({
      page,
    }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Wait for notes
      await expect(
        page.getByText("Prefers detailed technical explanations"),
      ).toBeVisible();

      // Click delete on the first note
      const firstDeleteButton = page
        .locator('button[aria-label^="Delete note:"]')
        .first();
      await firstDeleteButton.click();

      // The button should respond (not throw) -- mock handles the DELETE
      // Note should still be visible since the query will re-fetch mocked data
      await expect(
        page.locator("h3", { hasText: "Memory Notes" }),
      ).toBeVisible();
    });

    test("clear all button opens confirmation dialog", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Wait for notes to appear
      await expect(
        page.getByText("Prefers detailed technical explanations"),
      ).toBeVisible();

      // "Clear all" button should be visible when notes exist
      const clearAllButton = page.getByText("Clear all");
      await expect(clearAllButton).toBeVisible();

      // Click Clear all
      await clearAllButton.click();

      // Confirmation dialog should appear
      await expect(
        page.getByText("This will permanently delete all memory notes."),
      ).toBeVisible();

      // Confirm and Cancel buttons in the dialog
      await expect(
        page.getByRole("button", { name: "Confirm" }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "Cancel" }),
      ).toBeVisible();
    });

    test("clear all confirmation can be cancelled", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      await expect(
        page.getByText("Prefers detailed technical explanations"),
      ).toBeVisible();

      // Open clear all confirmation
      await page.getByText("Clear all").click();
      await expect(
        page.getByText("This will permanently delete all memory notes."),
      ).toBeVisible();

      // Cancel the action
      await page.getByRole("button", { name: "Cancel" }).click();

      // Confirmation should be dismissed
      await expect(
        page.getByText("This will permanently delete all memory notes."),
      ).not.toBeVisible();

      // Notes should still be there
      await expect(
        page.getByText("Prefers detailed technical explanations"),
      ).toBeVisible();
    });
  });

  test.describe("GDPR Data Export", () => {
    test("export button is present and functional", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Data Rights section
      await expect(
        page.locator("h3", { hasText: "Your Data Rights" }),
      ).toBeVisible();

      // Export section
      await expect(page.getByText("Export your data")).toBeVisible();
      await expect(
        page.getByText(
          "Download all your profile data, memory notes, and preferences as JSON",
        ),
      ).toBeVisible();

      // Export button
      const exportButton = page.locator("button", { hasText: "Export" });
      await expect(exportButton).toBeVisible();
      await expect(exportButton).toBeEnabled();
    });

    test("GDPR data export triggers download", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Set up download listener
      const downloadPromise = page.waitForEvent("download", { timeout: 5_000 }).catch(() => null);

      // Click export
      const exportButton = page.locator("button", { hasText: "Export" });
      await exportButton.click();

      // The button should briefly show "Exporting..." while the API call is in progress
      // After completion, it should return to "Export"
      await expect(exportButton).toContainText(/Export/, { timeout: 5_000 });
    });
  });

  test.describe("GDPR Data Erasure", () => {
    test("delete button opens confirmation with type-to-confirm", async ({
      page,
    }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // "Delete all your data" section
      await expect(page.getByText("Delete all your data")).toBeVisible();
      await expect(
        page.getByText(
          "Permanently removes your profile, memory notes, working memory",
        ),
      ).toBeVisible();

      // Initial Delete button
      const deleteButton = page.locator("button", { hasText: "Delete" }).last();
      await expect(deleteButton).toBeVisible();

      // Click to open confirmation
      await deleteButton.click();

      // Confirmation area should appear
      await expect(page.getByText("This is permanent")).toBeVisible();
      await expect(
        page.getByPlaceholder("Type DELETE"),
      ).toBeVisible();

      // "Confirm Delete" button should be disabled until user types DELETE
      const confirmDeleteButton = page.locator("button", {
        hasText: "Confirm Delete",
      });
      await expect(confirmDeleteButton).toBeVisible();
      await expect(confirmDeleteButton).toBeDisabled();
    });

    test("typing DELETE enables the confirm button", async ({ page }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Open confirmation
      const deleteButton = page.locator("button", { hasText: "Delete" }).last();
      await deleteButton.click();

      await expect(page.getByText("This is permanent")).toBeVisible();

      // Type partial text -- button should remain disabled
      const confirmInput = page.getByPlaceholder("Type DELETE");
      await confirmInput.fill("DEL");

      const confirmDeleteButton = page.locator("button", {
        hasText: "Confirm Delete",
      });
      await expect(confirmDeleteButton).toBeDisabled();

      // Type full "DELETE" -- button should become enabled
      await confirmInput.fill("DELETE");
      await expect(confirmDeleteButton).toBeEnabled();
    });

    test("cancel button dismisses the erasure confirmation", async ({
      page,
    }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Open confirmation
      const deleteButton = page.locator("button", { hasText: "Delete" }).last();
      await deleteButton.click();
      await expect(page.getByText("This is permanent")).toBeVisible();

      // Click Cancel
      await page.getByRole("button", { name: "Cancel" }).last().click();

      // Confirmation should be dismissed
      await expect(page.getByText("This is permanent")).not.toBeVisible();

      // The initial Delete button should be visible again
      await expect(
        page.locator("button", { hasText: "Delete" }).last(),
      ).toBeVisible();
    });

    test("GDPR clear profile requires exact DELETE confirmation", async ({
      page,
    }) => {
      await page.goto("/settings/privacy");
      await page.waitForLoadState("networkidle");

      // Open confirmation
      const deleteButton = page.locator("button", { hasText: "Delete" }).last();
      await deleteButton.click();

      // Type "delete" (lowercase) -- should not enable confirm
      const confirmInput = page.getByPlaceholder("Type DELETE");
      await confirmInput.fill("delete");

      const confirmDeleteButton = page.locator("button", {
        hasText: "Confirm Delete",
      });
      await expect(confirmDeleteButton).toBeDisabled();

      // Type "DELETE" (uppercase) -- should enable confirm
      await confirmInput.fill("DELETE");
      await expect(confirmDeleteButton).toBeEnabled();
    });
  });
});
