import { defineConfig } from "@playwright/test";

// Real-provider (Keycloak) SSO journeys. Started by tests/e2e/oidc/run.ps1 against
// a disposable stack: app on http://localhost:5183, backend :8010, Keycloak on
// http://127.0.0.1:8180 (a different *site* than the app, so the cross-site callback
// cookie behaviour is real). No globalSetup: these specs log in themselves.
export default defineConfig({
  testDir: "./tests/e2e/oidc",
  timeout: 120_000, // the first Keycloak login after a cold start can take a minute on a small machine
  fullyParallel: false,
  workers: 1,
  retries: 1, // a cold or memory-starved Keycloak occasionally stalls one sign-in; a retry is reported by Playwright as "flaky"
  expect: { timeout: 20_000 }, // admin pages load slowly on a memory-starved machine
  reporter: [["list"]],
  use: {
    browserName: "chromium",
    channel: process.env.E2E_BROWSER_CHANNEL || undefined,
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5183",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 1000 },
  },
});
