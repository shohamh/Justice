import type { BrowserContext, Page } from "@playwright/test";

import { test, expect } from "../fixtures/test";
import { createUniqueName } from "../fixtures/data";
import { roleStorageState } from "../fixtures/auth";

function isoDaysFromNow(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

async function openRoleContext(browser: Parameters<typeof test>[0]["browser"], role: "soldier" | "commander" | "dutyManager") {
  const projectUse = test.info().project.use as { baseURL?: string; viewport?: { width: number; height: number } };
  const context = await browser.newContext({
    baseURL: typeof projectUse.baseURL === "string" ? projectUse.baseURL : "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: roleStorageState(role),
  });
  const page = await context.newPage();
  return { context, page };
}

async function submitConstraint(page: Page, reason: string, startDate: string, endDate: string) {
  await page.goto("/my-requests");
  await expect(page).toHaveURL(/\/my-requests$/);
  await page.getByTestId("constraint-form-toggle").click();
  await expect(page.getByTestId("constraint-form-card")).toBeVisible();
  await page.getByTestId("req-start").fill(startDate);
  await page.getByTestId("req-end").fill(endDate);
  await page.getByTestId("req-reason").fill(reason);
  await expect(page.getByTestId("req-submit")).toBeEnabled();
  const submitResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/me/constraints") && response.request().method() === "POST",
  );
  await page.getByTestId("req-submit").click();
  expect((await submitResponse).status()).toBe(201);
}

async function openExistingConstraintRow(page: Page, reason: string) {
  await page.goto("/my-requests?tab=existing&type=constraints");
  await expect(page).toHaveURL(/\/my-requests\?tab=existing/);
  await expect(page.getByTestId("existing-requests-tab")).toBeVisible();
  const row = page
    .getByTestId("group-constraints")
    .locator('[data-testid^="constraint-row-"]', { hasText: reason })
    .first();
  await expect(row).toBeVisible();
  return row;
}

async function openApprovalRow(page: Page, reason: string) {
  await page.goto("/approvals?tab=constraints");
  await expect(page).toHaveURL(/\/approvals\?tab=constraints/);
  await expect(page.getByTestId("approvals-list")).toBeVisible();
  const row = page
    .getByTestId("approvals-list")
    .locator('[data-testid^="approval-row-"]', { hasText: reason })
    .first();
  await expect(row).toBeVisible();
  return row;
}

test.describe.configure({ mode: "serial" });

test("authorized commander and duty manager approve a request across role contexts @smoke", async ({ browser }) => {
  const reason = `אישור-${createUniqueName("approval-flow")}`;
  const rangeOffset = Math.floor(Math.random() * 300);
  const startDate = isoDaysFromNow(24 + rangeOffset);
  const endDate = isoDaysFromNow(27 + rangeOffset);

  const resources: BrowserContext[] = [];
  const closeAll = async () => Promise.all(resources.map((context) => context.close()));

  try {
    const soldier = await openRoleContext(browser, "soldier");
    resources.push(soldier.context);
    const commander = await openRoleContext(browser, "commander");
    resources.push(commander.context);
    const dutyManager = await openRoleContext(browser, "dutyManager");
    resources.push(dutyManager.context);

    await submitConstraint(soldier.page, reason, startDate, endDate);

    const soldierPendingRow = await openExistingConstraintRow(soldier.page, reason);
    await expect(soldierPendingRow).toContainText("ממתין");

    const commanderRow = await openApprovalRow(commander.page, reason);
    await expect(commanderRow.getByTestId(/constraint-stage-.*/)).toContainText("1/2");
    await commanderRow.getByRole("button", { name: "אשר" }).click();
    await expect(commanderRow.getByTestId(/constraint-stage-.*/)).toContainText("2/2");

    await soldier.page.reload();
    const soldierWaitingRow = await openExistingConstraintRow(soldier.page, reason);
    await expect(soldierWaitingRow).toContainText("ממתין");
    await expect(soldierWaitingRow.getByTestId(/constraint-.*-commander-step/)).toBeVisible();

    const dutyManagerRow = await openApprovalRow(dutyManager.page, reason);
    await expect(dutyManagerRow.getByTestId(/constraint-stage-.*/)).toContainText("2/2");
    await dutyManagerRow.getByRole("button", { name: "אשר" }).click();
    await expect(dutyManager.page.getByTestId("approvals-list")).not.toContainText(reason);

    await dutyManager.page.reload();
    await expect(dutyManager.page).toHaveURL(/\/approvals\?tab=constraints/);
    await expect(dutyManager.page.getByTestId("approvals-list")).not.toContainText(reason);

    await soldier.page.reload();
    const soldierApprovedRow = await openExistingConstraintRow(soldier.page, reason);
    await expect(soldierApprovedRow).toContainText("אושר");
    await expect(soldierApprovedRow.getByTestId(/constraint-.*-decided-by/)).toBeVisible();
  } finally {
    await closeAll();
  }
});

test("rejection requires a reason and the soldier sees the rejected status and note @smoke", async ({ browser }) => {
  const reason = `דחייה-${createUniqueName("approval-reject")}`;
  const rejectNote = `הערת-דחייה-${createUniqueName("approval-note")}`;
  const rangeOffset = Math.floor(Math.random() * 300);
  const startDate = isoDaysFromNow(30 + rangeOffset);
  const endDate = isoDaysFromNow(32 + rangeOffset);

  const resources: BrowserContext[] = [];
  const closeAll = async () => Promise.all(resources.map((context) => context.close()));

  try {
    const soldier = await openRoleContext(browser, "soldier");
    resources.push(soldier.context);
    const commander = await openRoleContext(browser, "commander");
    resources.push(commander.context);

    await submitConstraint(soldier.page, reason, startDate, endDate);

    const commanderRow = await openApprovalRow(commander.page, reason);
    const rejectButton = commanderRow.getByRole("button", { name: "דחה" });
    await expect(rejectButton).toBeDisabled();

    await commanderRow.getByTestId(/reject-note-.*/).fill(rejectNote);
    await expect(rejectButton).toBeEnabled();
    await rejectButton.click();
    await expect(commander.page.getByTestId("approvals-list")).not.toContainText(reason);

    const soldierRejectedRow = await openExistingConstraintRow(soldier.page, reason);
    await expect(soldierRejectedRow).toContainText("נדחה");
    await expect(soldierRejectedRow).toContainText(rejectNote);

    await soldier.page.reload();
    await expect(soldier.page).toHaveURL(/\/my-requests\?tab=existing/);
    await expect(await openExistingConstraintRow(soldier.page, reason)).toContainText("נדחה");
  } finally {
    await closeAll();
  }
});
