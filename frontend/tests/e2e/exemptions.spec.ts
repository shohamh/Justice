import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";
import { createUniqueName } from "./fixtures/data";
import { navItem } from "./fixtures/nav";

test.use({ storageState: roleStorageState("admin") });

test("admin onboards a soldier, grants an exemption, then revokes it", async ({ page }) => {
  const suffix = createUniqueName("e2e");
  const etName = `פטור-${suffix}`;

  // Create an exemption type to grant.
  await navItem(page, "nav-planning").click();
  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/planning\/config/);
  await page.getByTestId("et-open-modal").click();
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-duty-types-reviewed").check();
  await page.getByTestId("et-locations-reviewed").check();
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  // Onboard a soldier.
  await navItem(page, "nav-commander").click();
  await page.getByTestId("nav-team").click();
  await expect(page).toHaveURL(/\/team$/);
  const pn = `92${Date.now() % 100000}`;
  await page.getByTestId("onboard-pn").fill(pn);
  await page.getByTestId("onboard-name").fill("חייל פטور");
  // A soldier onboarded with no hierarchy node is outside every
  // commander/duty-manager's scope (see auth/authz.py's can_see_private_node
  // -- admins get no blanket bypass), so their exemption fields (reason,
  // revoked_by_name) would always come back null/hidden regardless of what
  // actually happened. Assign a node so the rest of this test can observe
  // real state.
  // "פסיפס" (not the bare root) is the node the seeded admin actually
  // commands (see seed.py's `psips.commander_id = s_admin.id`) -- can_see_private
  // requires scope containment, which the plain root wouldn't satisfy either
  // way since it's the admin's own commander assignment that grants scope,
  // not the admin role itself.
  // Click (not type-to-filter): a short/partial query can return zero fuzzy
  // matches and close the dropdown entirely, so pick straight from the
  // unfiltered open list instead. Options are prefixed with a tree-depth
  // glyph ("└פסיפס"), so match by substring, not exact text.
  await page.getByTestId("onboard-node").click();
  await expect(page.getByRole("option", { name: "פסיפס" })).toBeVisible();
  await page.getByRole("option", { name: "פסיפס" }).click();
  await page.getByTestId("onboard-submit").click();
  await expect(page.getByTestId(`soldier-row-${pn}`)).toBeVisible();

  // Open the soldier's unified modal and switch to its exemptions tab.
  await page.getByTestId(`edit-${pn}`).click();
  await expect(page.getByTestId("unified-soldier-modal")).toBeVisible();
  await page.getByTestId("modal-tab-exemptions").click();

  // Grant an exemption (via the shared ExemptionRequestForm inside the panel's grant-form).
  await page.getByTestId("er-type").click();
  await page.getByTestId("er-type").fill(etName);
  await page.getByRole("option", { name: etName }).click();
  const futureStart = new Date();
  futureStart.setDate(futureStart.getDate() + 30);
  const futureEnd = new Date();
  futureEnd.setDate(futureEnd.getDate() + 35);
  await page.getByTestId("er-start").fill(futureStart.toISOString().slice(0, 10));
  await page.getByTestId("er-end").fill(futureEnd.toISOString().slice(0, 10));
  await page.getByTestId("er-reason").fill("בדיקה");
  await page.getByTestId("er-submit").click();

  // It appears in the list; revoke it.
  const row = page.getByTestId("exemptions-list").getByText(etName);
  await expect(row).toBeVisible();
  await page.locator('[data-testid^="revoke-"]').first().click();
  await expect(page.getByTestId("reason-modal-textarea")).toBeVisible();
  await page.getByTestId("reason-modal-textarea").fill("בדיקה - ביטול");
  const revoke = page.waitForResponse(
    (r) => r.request().method() === "DELETE" && r.url().includes("/exemptions/") && r.status() === 204,
  );
  await page.getByTestId("reason-modal-confirm").click();
  await revoke;
  // A revoked exemption is a soft-revoke: it moves from the active list into
  // the "past" list (see ExemptionsPanel's activeItems/expiredItems split on
  // revoked_by_name) rather than being deleted -- so the active list empties
  // while the past list gains an entry.
  await expect(page.getByTestId("exemptions-empty")).toBeVisible();
  await expect(page.getByTestId("exemptions-list-past").locator('[data-testid^="exemption-row-"]')).toHaveCount(1);
});
