import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for PrakritiDesk's E2E suite (frontend/e2e/).
 *
 * Timeout strategy:
 *   - `timeout` (per test) is generous because a real run exercises
 *     multiple sequential screens (check-in -> OTP -> consent -> vitals ->
 *     intake), each involving a network round trip.
 *   - `expect.timeout` is shorter: individual assertions should resolve
 *     quickly once mocked routes fulfill, so a slow assertion is more
 *     likely a real bug than a slow backend.
 *   - `actionTimeout` bounds any single click/fill so a hung element
 *     locator fails fast instead of eating the whole test's budget.
 */
export default defineConfig({
  testDir: "./e2e/tests",

  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },

  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,

  reporter: process.env.CI ? [["html", { open: "never" }], ["github"]] : "list",

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000",
    actionTimeout: 10_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      // Most PrakritiDesk kiosks are touch-screen terminals, not desktop
      // browsers -- this project approximates that viewport/input mode
      // for the patient-facing flows.
      name: "kiosk-touchscreen",
      testMatch: /patient-intake\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1080, height: 1920 }, // portrait kiosk display
        hasTouch: true,
      },
    },
    {
      // The doctor dashboard is used on a normal desktop/laptop browser.
      name: "doctor-desktop",
      testMatch: /doctor-dashboard\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      // Needs both viewports available in the same run (one context per role).
      name: "realtime-sync",
      testMatch: /realtime-sync\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Auto-starts the Next.js dev server for local runs; CI should instead
  // build + start it as a separate pipeline step and set
  // PLAYWRIGHT_BASE_URL, skipping this (see the CI command in README).
  webServer: process.env.CI
    ? undefined
    : {
        command: "npm run dev",
        url: "http://127.0.0.1:3000",
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
