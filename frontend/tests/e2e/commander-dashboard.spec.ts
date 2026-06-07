import { test, expect } from "@playwright/test";

test.describe("Commander Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.fill('[data-testid="personal-number-input"]', "2000001");
    await page.fill('[data-testid="password-input"]', "1234567890");
    await page.click('[data-testid="login-submit"]');
    await page.waitForURL(/\/$/);
  });

  test("shows commander dashboard with summary cards", async ({ page }) => {
    await page.goto("/command-dashboard");
    await expect(page.locator('[data-testid="command-dashboard-page"]')).toBeVisible();
    await expect(page.locator('[data-testid="summary-cards"]')).toBeVisible();
  });

  test("calendar panel loads", async ({ page }) => {
    await page.goto("/command-dashboard");
    const calendar = page.locator('[data-testid="panel-calendar"]');
    await expect(calendar).toBeVisible();
  });
});
