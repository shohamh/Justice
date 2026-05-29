import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  // Specs share the single bootstrap admin (and a rate-limited login), so they
  // must run serially rather than across parallel workers.
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
});
