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

test("admin onboards a soldier, grants an exemption, then revokes it", async ({ page }) => {
  await loginAsAdmin(page);

  const suffix = `${Date.now() % 100000}`;
  const etName = `פטור-${suffix}`;

  // Create an exemption type to grant.
  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/duty-config$/);
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  // Onboard a soldier.
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
  await page.getByTestId("grant-type").selectOption({ label: etName });
  await page.getByTestId("grant-start").fill("2026-06-01");
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
