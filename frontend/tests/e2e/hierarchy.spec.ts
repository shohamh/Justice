import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";
import { navItem, clickTreeAddSoldier, clickTreeAddChild, clickTreeCommanderBtn } from "./fixtures/nav";

test.use({ storageState: roleStorageState("admin") });

test.describe("Hierarchy tree", () => {
  test("admin sees tree, adds child node, assigns commander, renames node", async ({ page }) => {
    await navItem(page, "nav-commander").click();
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    await expect(page.getByTestId("node-tree")).toBeVisible();

    await clickTreeAddChild(page);
    await expect(page.getByTestId("add-child-dialog")).toBeVisible();
    await page.getByTestId("child-name").fill(`\u05ea\u05ea-\u05d9\u05d7\u05d9\u05d3\u05ea \u05d1\u05d3\u05d9\u05e7\u05d4 ${Date.now() % 10000}`);
    await page.getByTestId("child-submit").click();
    await expect(page.getByTestId("add-child-dialog")).not.toBeVisible();

    const firstRename = page.getByTestId(/^tree-edit-name-/).first();
    await firstRename.click();
    await expect(page.getByTestId("edit-node-dialog")).toBeVisible();
    await page.getByTestId("edit-node-name-input").fill(`\u05e9\u05dd \u05d7\u05d3\u05e9 ${Date.now() % 10000}`);
    await page.getByTestId("edit-node-submit").click();
    await expect(page.getByTestId("edit-node-dialog")).not.toBeVisible();

    await clickTreeCommanderBtn(page);
    await expect(page.getByTestId("assign-commander-dialog")).toBeVisible();
    // Search for a soldier outside the fixture-reserved personal-number
    // ranges (see fixtures/auth.ts) — an unfiltered pick could promote one
    // of those accounts to commander (see services/dm_scope.py) and corrupt
    // other tests/projects sharing this database.
    await page.getByTestId("commander-search").fill("נילוס");
    await page.getByTestId(/^commander-option-/).first().click();
    await page.getByTestId("commander-submit").click();
    await expect(page.getByTestId("assign-commander-dialog")).not.toBeVisible();
  });

  test("admin can add soldier to node via quick-add button", async ({ page }) => {
    await navItem(page, "nav-commander").click();
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);
    await expect(page.getByTestId("node-tree")).toBeVisible();

    await clickTreeAddSoldier(page);
    await expect(page.getByTestId(/^quick-add-/)).toBeVisible();
  });

  test("soldiers appear under tree node with edit button", async ({ page }) => {
    await navItem(page, "nav-commander").click();
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
    await navItem(page, "nav-commander").click();
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

  test("adding existing soldier via quick-add creates a pending transfer request", async ({ page }) => {
    await navItem(page, "nav-commander").click();
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

    // Pick a different node to move the soldier to
    const addSoldierBtns = page.getByTestId(/^tree-add-soldier-/);
    const btnCount = await addSoldierBtns.count();
    expect(btnCount).toBeGreaterThan(1);
    // Use the second add-soldier button (different node from where soldier might be)
    await clickTreeAddSoldier(page, btnCount > 2 ? 2 : 1);

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

    // Moving an existing soldier goes through the hierarchy-transfer request
    // flow (pending the destination's approval), not an instant move — see
    // HierarchyTree.tsx's handleQuickAdd.
    await expect(page.getByTestId("transfer-reason")).toBeVisible();
    await page.getByTestId("confirm-dialog-confirm").click();

    // A pending transfer request was created; the app confirms it succeeded.
    await expect(page.getByTestId("message-dialog-close")).toBeVisible();
    await page.getByTestId("message-dialog-close").click();
  });
});
