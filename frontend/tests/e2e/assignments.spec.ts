import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";
import { navItem } from "./fixtures/nav";

test.use({ storageState: roleStorageState("admin") });

test("admin creates a duty type, location, assignment; transparency renders", async ({ page }) => {
  const suffix = `${Date.now() % 100000}`;

  // Need a duty type + location first.
  await navItem(page, "nav-planning").click();
  await page.getByTestId("nav-duty-config").click();
  await page.getByTestId("dt-add-btn").click();
  await page.getByTestId("dt-name").fill(`שמירה-${suffix}`);
  await page.getByTestId("dt-score").fill("2.00");
  await page.getByTestId("dt-is-external").selectOption("false");
  await page.getByTestId("dt-review-confirm").check();
  await page.getByTestId("dt-submit").click();
  await expect(page.getByTestId(`dt-row-שמירה-${suffix}`)).toBeVisible();
  await page.getByTestId("loc-name").fill(`מוצב-${suffix}`);
  await page.getByTestId("loc-submit").click();
  await expect(page.getByTestId(`loc-row-מוצב-${suffix}`)).toBeVisible();

  // Create a shift for the new duty type/location (the old dedicated duty-
  // management/assignment page and its dm-* fields are gone -- /planning/assignment
  // now redirects to /planning/shifts, and shift creation lives in ShiftFormModal).
  await navItem(page, "nav-planning").click();
  await page.getByTestId("nav-shifts-management").click();
  await page.getByTestId("shift-create-button").click();
  await expect(page.getByTestId("shift-create-form")).toBeVisible();
  await page.getByTestId("shift-duty-type").click();
  await page.locator('ul[role="listbox"]').getByRole("option", { name: `שמירה-${suffix}` }).click();
  await page.getByTestId("shift-location").click();
  await page.locator('ul[role="listbox"]').getByRole("option", { name: `מוצב-${suffix}` }).click();
  await page.getByTestId("shift-start-date").fill("2026-11-01");
  await page.getByTestId("shift-end-date").fill("2026-11-01");
  // Confirm the create actually succeeded rather than asserting the row is
  // visible in the list -- the list's default view is date/node-filtered, and
  // this shift's date can fall outside whatever window happens to be shown.
  const created = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/shifts") && r.status() === 201);
  await page.getByTestId("shift-create-submit").click();
  await created;

  // Transparency page renders.
  await navItem(page, "nav-transparency").click();
  await expect(page.getByTestId("transparency-table")).toBeVisible();
});
