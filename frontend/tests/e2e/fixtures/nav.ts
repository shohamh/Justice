import { expect, type Locator, type Page } from "@playwright/test";

/**
 * UnifiedNav renders each top-level item twice: a mobile-only bottom-bar
 * link (bare testid, e.g. "nav-commander") and a desktop-only sidebar link
 * ("desktop-" prefixed), toggled purely via CSS (`md:hidden` / `hidden
 * md:flex`) so only one is ever visible per viewport. Tests run against both
 * the "desktop" and "mobile-390" projects, so resolve whichever the current
 * viewport actually shows rather than hardcoding the bare testid.
 */
export function navItem(page: Page, testId: string): Locator {
  return page.locator(`[data-testid="${testId}"]:visible, [data-testid="desktop-${testId}"]:visible`);
}

/**
 * HierarchyTree's per-node action buttons (add child, add soldier, ...) live
 * in the desktop action grid (always visible at >=sm widths) and, at
 * narrower widths, inside a "..." actions menu that only mounts its items
 * once opened. Click the button at `index` among all nodes matching
 * `testIdPrefix`, opening its actions menu first if it isn't already
 * visible.
 */
async function clickTreeAction(page: Page, testIdPrefix: string, index: number): Promise<void> {
  const btn = page.getByTestId(new RegExp(`^${testIdPrefix}-`)).nth(index);
  const isMobileViewport = (page.viewportSize()?.width ?? 1280) < 640;
  if (isMobileViewport) {
    const becameVisible = await expect(btn).toBeVisible({ timeout: 3000 }).then(() => true, () => false);
    if (!becameVisible) {
      const testId = await btn.getAttribute("data-testid");
      const nodeId = testId!.replace(`${testIdPrefix}-`, "");
      await page.getByTestId(`tree-actions-menu-${nodeId}`).click();
    }
  }
  await btn.click();
}

export async function clickTreeAddSoldier(page: Page, index = 0): Promise<void> {
  await clickTreeAction(page, "tree-add-soldier", index);
}

export async function clickTreeAddChild(page: Page, index = 0): Promise<void> {
  await clickTreeAction(page, "tree-add-child", index);
}

export async function clickTreeCommanderBtn(page: Page, index = 0): Promise<void> {
  await clickTreeAction(page, "tree-commander-btn", index);
}
