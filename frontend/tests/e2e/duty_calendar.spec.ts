import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("my diary page shows stats dashboard", async ({ page }) => {
  // No persistent nav entry links here anymore (removed in 72501b95) — the
  // page is reached via the search palette or a notification deep link, so
  // navigate directly.
  await page.goto("/my-duties");
  await expect(page).toHaveURL(/\/my-duties$/);

  await expect(page.getByTestId("my-diary-page")).toBeVisible();
  await expect(page.getByTestId("my-diary-stat-cards")).toBeVisible();
});
