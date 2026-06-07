import { test, expect } from "@playwright/test";

// One self-contained flow (no cross-spec state dependency): the bootstrap admin
// logs in for the first time, is forced to change the password, lands on home,
// then onboards a soldier and sees the generated temp password.
test("admin first login: forced password change, then onboard a soldier", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();

  // Forced redirect to the change-password page.
  await expect(page).toHaveURL(/\/change-password$/);
  await expect(page.getByTestId("forced-notice")).toBeVisible();
  await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("new-password").fill("AdminNewPassw0rd");
  await page.getByTestId("change-password-submit").click();

  // Now on home, admin sees the commander nav entry (which contains Team).
  await expect(page).toHaveURL("/");
  await expect(page.getByTestId("nav-commander")).toBeVisible();

  // Onboard a soldier via the commander sheet → Team Hierarchy.
  await page.getByTestId("nav-commander").click();
  await page.getByTestId("nav-team").click();
  await expect(page).toHaveURL(/\/team$/);
  const pn = `91${Date.now() % 100000}`;
  await page.getByTestId("onboard-pn").fill(pn);
  await page.getByTestId("onboard-name").fill("חייל בדיקה");
  await page.getByTestId("onboard-submit").click();
  await expect(page.getByTestId("temp-password")).toBeVisible();
  await expect(page.getByTestId(`soldier-row-${pn}`)).toBeVisible();
});
