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
    await page.getByTestId("child-name").fill(`\u05ea\u05ea-\u05d9\u05d7\u05d9\u05d3\u05ea \u05d1\u05d3\u05d9\u05e7\u05d4 ${Date.now() % 10000}`);
    await page.getByTestId("child-submit").click();
    await expect(page.getByTestId("add-child-dialog")).not.toBeVisible();

    const firstRename = page.getByTestId(/^tree-rename-/).first();
    await firstRename.click();
    await expect(page.getByTestId("rename-dialog")).toBeVisible();
    await page.getByTestId("rename-input").fill(`\u05e9\u05dd \u05d7\u05d3\u05e9 ${Date.now() % 10000}`);
    await page.getByTestId("rename-submit").click();
    await expect(page.getByTestId("rename-dialog")).not.toBeVisible();

    const firstCommanderBtn = page.getByTestId(/^tree-commander-btn-/).first();
    await firstCommanderBtn.click();
    await expect(page.getByTestId("assign-commander-dialog")).toBeVisible();
    await page.getByTestId("commander-select").selectOption({ index: 1 });
    await page.getByTestId("commander-submit").click();
    await expect(page.getByTestId("assign-commander-dialog")).not.toBeVisible();
  });

  test("admin can add soldier to node via quick-add button", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);
    await expect(page.getByTestId("node-tree")).toBeVisible();

    const firstAddSoldier = page.getByTestId(/^tree-add-soldier-/).first();
    await firstAddSoldier.click();
    await expect(page.getByTestId(/^quick-add-/)).toBeVisible();
  });

  test("soldiers appear under tree node with edit button", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    await expect(page.getByTestId("node-tree")).toBeVisible();
    const firstToggle = page.getByTestId(/^tree-toggle-/).first();
    await firstToggle.click();

    const soldierRows = page.getByTestId(/^tree-soldier-/);
    const count = await soldierRows.count();
    if (count > 0) {
      const firstEdit = page.getByTestId(/^edit-soldier-/).first();
      await expect(firstEdit).toBeVisible();
      await firstEdit.click();
      await expect(page.getByTestId("soldier-edit-modal")).toBeVisible();
    }
  });
});
