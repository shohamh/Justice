import { test, expect } from "../fixtures/test";
import { roleStorageState } from "../fixtures/auth";

test.use({ storageState: roleStorageState("soldier") });

test("regular user can navigate core views and refresh them @smoke @full", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await expect(page.getByTestId("personal-data-panel")).toBeVisible();

  await page.goto("/my-requests");
  await expect(page).toHaveURL(/\/my-requests$/);
  await expect(page.getByTestId("new-requests-tab")).toBeVisible();

  await page.goto("/unit-calendar");
  await expect(page).toHaveURL(/\/unit-calendar$/);
  await expect(page.getByTestId("unit-calendar-page")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("unit-calendar-page")).toBeVisible();

  expect(pageErrors).toEqual([]);
});
