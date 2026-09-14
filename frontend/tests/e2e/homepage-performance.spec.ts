import { expect, test } from "@playwright/test";
import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("records homepage API request count and load timing", async ({ page }, testInfo) => {
  const started = new WeakMap<object, number>();
  const requests: { url: string; durationMs: number }[] = [];
  const navigationStart = Date.now();

  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) started.set(request, Date.now());
  });
  page.on("requestfinished", (request) => {
    const start = started.get(request);
    if (start !== undefined) {
      requests.push({ url: new URL(request.url()).pathname, durationMs: Date.now() - start });
      started.delete(request);
    }
  });

  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page.getByTestId("personal-data-panel")).toBeVisible();

  const result = {
    requestCount: requests.length,
    homepageMs: Date.now() - navigationStart,
    requests: requests.sort((a, b) => b.durationMs - a.durationMs),
  };
  await testInfo.attach("homepage-performance.json", {
    body: JSON.stringify(result, null, 2),
    contentType: "application/json",
  });
  console.log(`HOMEPAGE_PERF ${JSON.stringify(result)}`);

  expect(result.requestCount).toBeGreaterThan(0);
});
