import { test, expect, type Page } from "@playwright/test";

async function loginAsAdmin(page: Page) {
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

test("admin creates a duty type, location, assignment; transparency renders", async ({ page }) => {
  await loginAsAdmin(page);
  const suffix = `${Date.now() % 100000}`;

  // Need a duty type + location first.
  await page.getByTestId("nav-planning").click();
  await page.getByTestId("nav-duty-config").click();
  await page.getByTestId("dt-name").fill(`שמירה-${suffix}`);
  await page.getByTestId("dt-score").fill("2.00");
  await page.getByTestId("dt-submit").click();
  await expect(page.getByTestId(`dt-row-שמירה-${suffix}`)).toBeVisible();
  await page.getByTestId("loc-name").fill(`מוצב-${suffix}`);
  await page.getByTestId("loc-submit").click();
  await expect(page.getByTestId(`loc-row-מוצב-${suffix}`)).toBeVisible();

  // Create an assignment (DM page; soldier dropdown defaults to the first soldier — the admin).
  await page.getByTestId("nav-planning").click();
  await page.getByTestId("nav-duty-management").click();
  await expect(page).toHaveURL(/\/planning\/assignment/);
  await page.getByTestId("dm-start").fill("2026-11-01");
  await page.getByTestId("dm-end").fill("2026-11-02");
  await page.getByTestId("dm-create").click();
  await expect(page.getByTestId("assignment-list").locator("li")).not.toHaveText(/^$/);

  // Transparency page renders.
  await page.getByTestId("nav-transparency").click();
  await expect(page.getByTestId("transparency-table")).toBeVisible();
});
