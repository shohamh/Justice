import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "admin_flow.spec.ts",
  globalSetup: "./tests/e2e/fixtures/admin-flow.ts",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    browserName: "chromium",
    channel: "chrome",
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    video: "off",
    viewport: { width: 390, height: 844 },
  },
});
