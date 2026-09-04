import { test, expect } from "../fixtures/test";
import { roleStorageState } from "../fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("hierarchy table filters, sorts, and exposes an empty state @full", async ({ page }) => {
  await page.goto("/team");
  const table = page.getByTestId("soldier-table");
  await expect(table).toBeVisible();
  await expect(table.locator("thead th")).toHaveCount(6);
  await expect(table.getByTestId(/^soldier-row-/).first()).toBeVisible();

  const filter = table.locator("input");
  await filter.fill("no-such-soldier-in-e2e");
  await expect(table.getByTestId(/^soldier-row-/)).toHaveCount(0);
  await expect(table.locator("tbody")).toContainText("אין חיילים");

  await filter.fill("");
  const nameHeader = table.locator("thead th").nth(1);
  await nameHeader.click();
  await expect(table.getByTestId(/^soldier-row-/).first()).toBeVisible();
});
