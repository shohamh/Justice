import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("my diary page shows stats dashboard", async ({ page }) => {
  await page.getByTestId("nav-my-duties").click();
  await expect(page).toHaveURL(/\/my-duties$/);

  await expect(page.getByTestId("my-diary-page")).toBeVisible();
  await expect(page.getByTestId("my-diary-stat-cards")).toBeVisible();
});
