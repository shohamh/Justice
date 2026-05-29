import { test, expect } from "@playwright/test";

// The bootstrap admin's one-time forced password change is consumed by whichever
// spec runs first against a given DB. So this helper tolerates both states:
// first login (forced change) and an already-changed admin (log in with new pw).
async function loginAsAdmin(page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test("admin configures a duty type, location, and exemption type with mapping", async ({ page }) => {
  await loginAsAdmin(page);

  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/duty-config$/);

  const suffix = `${Date.now() % 100000}`;
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
