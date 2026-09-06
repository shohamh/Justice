import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";
import { createUniqueName } from "./fixtures/data";
import { navItem } from "./fixtures/nav";

test.use({ storageState: roleStorageState("admin") });

test("admin onboards a soldier, grants an exemption, then revokes it", async ({ page }) => {
  const suffix = createUniqueName("e2e");
  const etName = `פטור-${suffix}`;

  // Create an exemption type to grant.
  await navItem(page, "nav-planning").click();
  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/planning\/config/);
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  // Onboard a soldier.
  await navItem(page, "nav-commander").click();
  await page.getByTestId("nav-team").click();
  await expect(page).toHaveURL(/\/team$/);
  const pn = `92${Date.now() % 100000}`;
  await page.getByTestId("onboard-pn").fill(pn);
  await page.getByTestId("onboard-name").fill("חייל פטור");
  await page.getByTestId("onboard-submit").click();
  await expect(page.getByTestId(`soldier-row-${pn}`)).toBeVisible();

  // Open the manage-exemptions panel for that soldier.
  await page.getByTestId(`exemptions-${pn}`).click();
  await expect(page.getByTestId("manage-exemptions")).toBeVisible();

  // Grant an exemption.
  await page.getByTestId("grant-type").click();
  await page.getByTestId("grant-type").fill(etName);
  await page.getByRole("option", { name: etName }).click();
  const futureStart = new Date();
  futureStart.setDate(futureStart.getDate() + 30);
  await page.getByTestId("grant-start").fill(futureStart.toISOString().slice(0, 10));
  await page.getByTestId("grant-reason").fill("בדיקה");
  await page.getByTestId("grant-submit").click();

  // It appears in the list; revoke it.
  const row = page.getByTestId("exemptions-list").getByText(etName);
  await expect(row).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await page.locator('[data-testid^="revoke-"]').first().click();
  // After a future-dated grant is revoked it is hard-deleted, so the list empties.
  await expect(page.getByTestId("exemptions-empty")).toBeVisible();
});
