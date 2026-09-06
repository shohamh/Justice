import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";
import { createUniqueName } from "./fixtures/data";
import { navItem } from "./fixtures/nav";

test.use({ storageState: roleStorageState("admin") });

test("admin configures a duty type, location, and exemption type with mapping", async ({ page }) => {
  await navItem(page, "nav-planning").click();
  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/planning\/config/);

  const suffix = createUniqueName("e2e");
  const dtName = `שמירה-${suffix}`;
  const locName = `מוצב-${suffix}`;
  const etName = `פטור-${suffix}`;

  // Duty type.
  await page.getByTestId("dt-name").fill(dtName);
  await page.getByTestId("dt-score").fill("1.50");
  await page.getByTestId("dt-submit").click();
  await expect(page.getByTestId(`dt-row-${dtName}`)).toBeVisible();

  // Location.
  await page.getByTestId("loc-name").fill(locName);
  await page.getByTestId("loc-submit").click();
  await expect(page.getByTestId(`loc-row-${locName}`)).toBeVisible();

  // Exemption type.
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  // Map the exemption type to the duty type via the checkbox. The checkbox is a
  // controlled input whose state flips only after the PUT round-trip resolves, so
  // click and let the auto-retrying assertion wait for the state to settle.
  const cb = page.getByTestId(`map-${etName}-${dtName}`);
  await cb.click();
  await expect(cb).toBeChecked();
});
