import { chromium } from "playwright";

const BASE = "http://localhost:3022";
const SCREENSHOTS = "/tmp/mingai-validation/screenshots";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  // Login as end user
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  await page.locator('input[type="email"]').first().fill("user@mingai.test");
  await page.locator('input[type="password"]').first().fill("User1234!");
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(3000);

  // Navigate to chat
  await page.goto(`${BASE}/chat`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);

  // Find and click the "Auto" dropdown in the input bar
  const autoBtn = page.locator('button:has-text("Auto")').first();
  const isVisible = await autoBtn.isVisible().catch(() => false);
  console.log(`Auto button visible: ${isVisible}`);

  if (isVisible) {
    await autoBtn.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${SCREENSHOTS}/01-enduser-mode-dropdown.png`, fullPage: true });

    // Get all options in the dropdown
    const dropdownItems = page.locator('[role="option"], [role="menuitem"], [data-testid*="mode"], [class*="dropdown"] button, [class*="dropdown"] li, [class*="Dropdown"] button, [class*="menu"] button, [class*="Menu"] button, [class*="popover"] button, [class*="Popover"] button');
    const count = await dropdownItems.count();
    console.log(`Dropdown items found: ${count}`);

    for (let i = 0; i < count; i++) {
      const text = await dropdownItems.nth(i).innerText().catch(() => "?");
      console.log(`  Item ${i}: "${text.trim()}"`);
    }

    // Also get any new text that appeared
    const bodyText = await page.locator("body").innerText();
    const agents = ["Auto", "HR", "IT", "Procurement", "Finance", "Legal", "General"];
    const found = agents.filter(a => bodyText.includes(a));
    console.log(`Agent text found after click: ${found.join(", ")}`);
  }

  // Also check the glossary suggested tab more carefully
  // First login as tenant admin
  await ctx.close();

  const ctx2 = await browser.newContext();
  const page2 = await ctx2.newPage();

  await page2.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page2.waitForTimeout(2000);
  await page2.locator('input[type="email"]').first().fill("tenant_admin@mingai.test");
  await page2.locator('input[type="password"]').first().fill("TenantAdmin1234!");
  await page2.locator('button[type="submit"]').first().click();
  await page2.waitForTimeout(3000);

  // Go to glossary
  await page2.goto(`${BASE}/settings/glossary`, { waitUntil: "domcontentloaded" });
  await page2.waitForTimeout(2000);

  // Look for any tab-like elements
  const allBtns = await page2.locator("button").allInnerTexts();
  console.log("\nGlossary page buttons:");
  allBtns.forEach((b, i) => {
    if (b.trim()) console.log(`  ${i}: "${b.trim()}"`);
  });

  // Check if there's a "Suggested" or miss-signals section
  const bodyText2 = await page2.locator("body").innerText();
  if (bodyText2.includes("Suggest")) console.log("Found 'Suggest' text on glossary page");
  if (bodyText2.includes("Miss")) console.log("Found 'Miss' text on glossary page");
  if (bodyText2.includes("Signal")) console.log("Found 'Signal' text on glossary page");

  await ctx2.close();
  await browser.close();
})();
