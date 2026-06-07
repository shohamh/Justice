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
    await page.getByTestId("nav-commander").click();
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
    await page.getByTestId("nav-commander").click();
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);
    await expect(page.getByTestId("node-tree")).toBeVisible();

    const firstAddSoldier = page.getByTestId(/^tree-add-soldier-/).first();
    await firstAddSoldier.click();
    await expect(page.getByTestId(/^quick-add-/)).toBeVisible();
  });

  test("soldiers appear under tree node with edit button", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-commander").click();
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    await expect(page.getByTestId("node-tree")).toBeVisible();

    // Expand all collapsed tree nodes (two passes for deep nesting)
    for (let pass = 0; pass < 2; pass++) {
      const allToggles = page.getByTestId(/^tree-toggle-/);
      for (let i = 0; i < await allToggles.count(); i++) {
        const t = allToggles.nth(i);
        if (await t.isVisible()) {
          const text = await t.textContent();
          if (text?.trim() === "▶") await t.click();
        }
      }
    }

    const soldierRows = page.getByTestId(/^tree-soldier-/);
    const count = await soldierRows.count();
    if (count > 0) {
      const firstEdit = page.getByTestId(/^edit-soldier-/).first();
      await expect(firstEdit).toBeVisible();
      await firstEdit.click();
      await expect(page.getByTestId("unified-soldier-modal")).toBeVisible();
    }
  });

  test("soldier appears only under their assigned hierarchy node", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-commander").click();
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    // Wait for the tree data to load
    await expect(page.getByTestId("node-tree")).toBeVisible();

    // Expand only collapsed toggle buttons (ones showing "▶") so we don't collapse
    // already-expanded nodes. Use up to 3 passes to reach deeply nested nodes.
    for (let pass = 0; pass < 3; pass++) {
      const allToggles = page.getByTestId(/^tree-toggle-/);
      for (let i = 0; i < await allToggles.count(); i++) {
        const t = allToggles.nth(i);
        if (await t.isVisible()) {
          const text = await t.textContent();
          if (text?.trim() === "▶") await t.click();
        }
      }
      await page.waitForTimeout(200);
    }

    // Wait for soldiers to appear (they load asynchronously)
    const soldierEntries = page.getByTestId(/^tree-soldier-/);
    const soldierCount = await soldierEntries.count();
    expect(soldierCount).toBeGreaterThan(0);

    // Each soldier should appear exactly once in the tree
    const seen = new Map<string, number>();
    for (let i = 0; i < soldierCount; i++) {
      const tid = await soldierEntries.nth(i).getAttribute("data-testid");
      seen.set(tid!, (seen.get(tid!) ?? 0) + 1);
    }
    const dupes = [...seen.entries()].filter(([, c]) => c > 1).map(([id]) => id.replace("tree-soldier-", ""));
    expect(dupes).toEqual([]);
  });

  test("adding existing soldier via quick-add moves them to the new node", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-commander").click();
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    // Wait for the soldier table data to load
    await expect(page.getByTestId("soldier-table")).toBeVisible();
    const soldierRows = page.getByTestId(/^soldier-row-/);
    await expect(soldierRows.first()).toBeVisible({ timeout: 10000 });
    const rowCount = await soldierRows.count();
    expect(rowCount).toBeGreaterThan(0);

    // Pick the first soldier with a non-empty node in the table
    let targetPn = "";
    let targetName = "";
    for (let i = 0; i < rowCount; i++) {
      const cells = await soldierRows.nth(i).locator("td").all();
      if (cells.length >= 5) {
        const nodeText = await cells[4].textContent();
        if (nodeText && nodeText.trim() !== "—") {
          targetPn = (await cells[0].textContent()) || "";
          targetName = (await cells[1].textContent()) || "";
          break;
        }
      }
    }
    expect(targetPn).not.toBe("");

    // Expand collapsed tree nodes to see soldiers (two passes for deep nesting)
    for (let pass = 0; pass < 2; pass++) {
      const toggles = page.getByTestId(/^tree-toggle-/);
      for (let i = 0; i < await toggles.count(); i++) {
        const t = toggles.nth(i);
        if (await t.isVisible()) {
          const text = await t.textContent();
          if (text?.trim() === "▶") await t.click();
        }
      }
    }

    // Note whether the soldier is currently visible in the tree
    const soldierInTree = page.getByTestId(`tree-soldier-${targetPn}`);
    const wasVisible = await soldierInTree.isVisible().catch(() => false);

    // Pick a different node to move the soldier to
    const addSoldierBtns = page.getByTestId(/^tree-add-soldier-/);
    const btnCount = await addSoldierBtns.count();
    expect(btnCount).toBeGreaterThan(1);
    // Use the second add-soldier button (different node from where soldier might be)
    const targetBtn = addSoldierBtns.nth(btnCount > 2 ? 2 : 1);
    await targetBtn.click();

    // Type the soldier's personal number in the autocomplete and select
    const searchInput = page.getByTestId("soldier-search-input");
    await expect(searchInput).toBeVisible();
    await searchInput.fill(targetPn);
    const dropdown = page.getByTestId("soldier-search-dropdown");
    await expect(dropdown).toBeVisible();

    // Click the matching result
    const result = page.getByTestId(`soldier-search-result-${targetPn}`);
    await expect(result).toBeVisible();
    await result.click();

    // Wait for the quick-add to process
    await expect(page.getByTestId("soldier-search-input")).not.toBeVisible({ timeout: 5000 });

    // The soldier should now appear in the tree (the target node is expanded by handleQuickAdd)
    await expect(soldierInTree).toBeVisible({ timeout: 5000 });
  });
});
