import { test, expect } from "@playwright/test";

async function loginAdmin(page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("AdminNewPassw0rd"); // set by change_password.spec.ts
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL("/");
}

test("admin onboards a soldier and gets a temp password", async ({ page }) => {
  await loginAdmin(page);
  await page.getByTestId("nav-team").click();
  await expect(page).toHaveURL(/\/team$/);
  const pn = `91${Date.now() % 100000}`;
  await page.getByTestId("onboard-pn").fill(pn);
  await page.getByTestId("onboard-name").fill("חייל בדיקה");
  await page.getByTestId("onboard-submit").click();
  await expect(page.getByTestId("temp-password")).toBeVisible();
  await expect(page.getByTestId(`soldier-row-${pn}`)).toBeVisible();
});
