import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  // The bootstrap-admin journey has a different database precondition and is
  // run explicitly with playwright.admin-flow.config.ts.
  testIgnore: ["**/admin_flow.spec.ts"],
  globalSetup: "./tests/e2e/fixtures/auth.ts",
  timeout: 30_000,
  fullyParallel: false,
  // Specs share the single bootstrap admin (and a rate-limited login), so they
  // must run serially rather than across parallel workers.
  workers: 1,
  retries: 1,
  use: {
    browserName: "chromium",
    channel: "chrome",
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    video: "off",
  },
  projects: [
    {
      name: "desktop",
      use: {
        viewport: { width: 1440, height: 1000 },
      },
    },
    {
      name: "mobile-390",
      use: {
        viewport: { width: 390, height: 844 },
      },
    },
  ],
});
