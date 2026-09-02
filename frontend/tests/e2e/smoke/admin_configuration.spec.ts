import { test, expect } from "../fixtures/test";
import { roleStorageState } from "../fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("admin configuration is visible and feeds the planning page @full", async ({ page }) => {
  await page.goto("/planning/config");
  await expect(page.getByTestId("duty-config-page")).toBeVisible();
  await expect(page.getByTestId("duty-types-section")).toBeVisible();
  await expect(page.getByTestId("locations-section")).toBeVisible();

  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("personal-data-panel")).toBeVisible();
});
