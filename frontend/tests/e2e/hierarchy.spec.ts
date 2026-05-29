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

test.describe("Hierarchy tree", () => {
  test("admin sees tree, adds child node, assigns commander, renames node", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    await expect(page.getByTestId("node-tree")).toBeVisible();

    const firstAddChild = page.getByTestId(/^tree-add-child-/).first();
    await firstAddChild.click();
    await expect(page.getByTestId("add-child-dialog")).toBeVisible();
    await page.getByTestId("child-name").fill(`תת-יחידת בדיקה ${Date.now() % 10000}`);
    await page.getByTestId("child-submit").click();
    await expect(page.getByTestId("add-child-dialog")).not.toBeVisible();

    const firstRename = page.getByTestId(/^tree-rename-/).first();
    await firstRename.click();
    await expect(page.getByTestId("rename-dialog")).toBeVisible();
    await page.getByTestId("rename-input").fill(`שם חדש ${Date.now() % 10000}`);
    await page.getByTestId("rename-submit").click();
    await expect(page.getByTestId("rename-dialog")).not.toBeVisible();

    const firstCommanderBtn = page.getByTestId(/^tree-commander-btn-/).first();
    await firstCommanderBtn.click();
    await expect(page.getByTestId("assign-commander-dialog")).toBeVisible();
    await page.getByTestId("commander-select").selectOption({ index: 1 });
    await page.getByTestId("commander-submit").click();
    await expect(page.getByTestId("assign-commander-dialog")).not.toBeVisible();
  });
});
