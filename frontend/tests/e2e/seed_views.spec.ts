import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("seeded data renders correctly across pages", async ({ page }) => {
  await page.getByTestId("nav-commander").click();
  await page.getByTestId("nav-team").click();
  await expect(page.getByTestId("node-tree")).toBeVisible();

  // Expand all tree nodes to expose all names
  const toggles = page.locator('[data-testid^="tree-toggle-"]');
  const toggleCount = await toggles.count();
  for (let i = 0; i < toggleCount; i++) {
    const btn = toggles.nth(i);
    if (await btn.isVisible()) await btn.click();
  }
  await page.waitForTimeout(500);
  const treeItems = await page.getByTestId(/^tree-name-/).count();
  expect(treeItems).toBeGreaterThan(5);

  await expect(page.getByTestId("soldier-table")).toBeVisible();
  const soldierRows = await page.getByTestId(/^soldier-row-/).count();
  expect(soldierRows).toBeGreaterThan(5);

  await page.getByTestId("nav-unit-calendar").click();
  await expect(page).toHaveURL(/\/unit-calendar$/);
  await page.waitForSelector('[data-testid="fullcalendar"]');
  await expect(page.locator(".fc-dayGridMonth-view")).toBeVisible();

  await page.getByTestId("nav-transparency").click();
  await expect(page).toHaveURL(/\/transparency$/);
});
