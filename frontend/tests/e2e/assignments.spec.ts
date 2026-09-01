import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("admin creates a duty type, location, assignment; transparency renders", async ({ page }) => {
  const suffix = `${Date.now() % 100000}`;

  // Need a duty type + location first.
  await page.getByTestId("nav-planning").click();
  await page.getByTestId("nav-duty-config").click();
  await page.getByTestId("dt-name").fill(`שמירה-${suffix}`);
  await page.getByTestId("dt-score").fill("2.00");
  await page.getByTestId("dt-submit").click();
  await expect(page.getByTestId(`dt-row-שמירה-${suffix}`)).toBeVisible();
  await page.getByTestId("loc-name").fill(`מוצב-${suffix}`);
  await page.getByTestId("loc-submit").click();
  await expect(page.getByTestId(`loc-row-מוצב-${suffix}`)).toBeVisible();

  // Create an assignment (DM page; soldier dropdown defaults to the first soldier — the admin).
  await page.getByTestId("nav-planning").click();
  await page.getByTestId("nav-duty-management").click();
  await expect(page).toHaveURL(/\/planning\/assignment/);
  await page.getByTestId("dm-start").fill("2026-11-01");
  await page.getByTestId("dm-end").fill("2026-11-02");
  await page.getByTestId("dm-create").click();
  await expect(page.getByTestId("assignment-list").locator("li")).not.toHaveText(/^$/);

  // Transparency page renders.
  await page.getByTestId("nav-transparency").click();
  await expect(page.getByTestId("transparency-table")).toBeVisible();
});
