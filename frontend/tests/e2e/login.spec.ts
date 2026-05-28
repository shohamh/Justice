import { test, expect } from "@playwright/test";

test.describe("login", () => {
  test("login with bootstrap admin lands on home", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("personal-number-input").fill("1000001");
    await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("login-submit").click();
    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("must-change-password-banner")).toBeVisible();
    await expect(page.getByTestId("logout-button")).toBeVisible();
  });

  test("login with wrong password shows Hebrew error", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("personal-number-input").fill("1000001");
    await page.getByTestId("password-input").fill("wrong-password");
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("login-error")).toHaveText("מספר אישי או סיסמה שגויים");
  });
});
