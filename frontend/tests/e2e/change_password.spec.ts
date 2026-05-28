import { test, expect } from "@playwright/test";

// Runs first (alphabetical): logs in as the bootstrap admin and changes the password.
test("forced password change on first login", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/change-password$/);
  await expect(page.getByTestId("forced-notice")).toBeVisible();
  await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("new-password").fill("AdminNewPassw0rd");
  await page.getByTestId("change-password-submit").click();
  await expect(page).toHaveURL("/");
  await expect(page.getByTestId("nav-team")).toBeVisible();
});
