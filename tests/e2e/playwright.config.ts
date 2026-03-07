import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for mingai E2E tests.
 * Frontend: http://localhost:3022 (Next.js)
 * Backend: http://localhost:8022 (FastAPI)
 */
export default defineConfig({
  testDir: ".",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  timeout: 30_000,

  use: {
    baseURL: "http://localhost:3022",
    screenshot: "only-on-failure",
    video: "on-first-retry",
    trace: "on-first-retry",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
