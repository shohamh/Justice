import { test, expect } from "@playwright/test";

test.describe("login", () => {
  // The bootstrap-admin happy path now goes through the forced password-change
  // flow (covered by change_password.spec.ts) and a normal admin login landing
  // on "/" (covered by soldiers.spec.ts). This file keeps the order-independent
  // wrong-password case.
  test("login with wrong password shows Hebrew error @smoke", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("personal-number-input").fill("1000001");
    await page.getByTestId("password-input").fill("wrong-password");
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("login-error")).toHaveText("מספר אישי או סיסמה שגויים");
  });
});
