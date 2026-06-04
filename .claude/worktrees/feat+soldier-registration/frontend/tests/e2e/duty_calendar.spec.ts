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

test("calendar shows on my duties page, navigation works", async ({ page }) => {
  await loginAsAdmin(page);

  await page.getByTestId("nav-my-duties").click();
  await expect(page).toHaveURL(/\/my-duties$/);

  await expect(page.getByTestId("duty-calendar")).toBeVisible();
  await expect(page.getByTestId("my-duties-page")).toBeVisible();

  const nextBtn = page.locator(".react-calendar__navigation__next-button");
  if (await nextBtn.isVisible()) {
    await nextBtn.click();
  }

  const prevBtn = page.locator(".react-calendar__navigation__prev-button");
  if (await prevBtn.isVisible()) {
    await prevBtn.click();
  }
});
