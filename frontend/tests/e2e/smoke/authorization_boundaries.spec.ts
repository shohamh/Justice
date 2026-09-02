import type { BrowserContext, Page } from "@playwright/test";

import { test, expect } from "../fixtures/test";
import { createUniqueName } from "../fixtures/data";
import { roleStorageState } from "../fixtures/auth";

const SEED_PASSWORD = "1234567890";
const OUT_OF_SCOPE_COMMANDER_PN = "2000002";

function isoDaysFromNow(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

async function contextWithState(browser: Parameters<typeof test>[0]["browser"], role: "soldier") {
  const projectUse = test.info().project.use as { baseURL?: string; viewport?: { width: number; height: number } };
  const context = await browser.newContext({
    baseURL: typeof projectUse.baseURL === "string" ? projectUse.baseURL : "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: roleStorageState(role),
  });
  const page = await context.newPage();
  return { context, page };
}

async function loginWithPersonalNumber(browser: Parameters<typeof test>[0]["browser"], personalNumber: string) {
  const projectUse = test.info().project.use as { baseURL?: string; viewport?: { width: number; height: number } };
  const context = await browser.newContext({
    baseURL: typeof projectUse.baseURL === "string" ? projectUse.baseURL : "http://localhost:5173",
    viewport: projectUse.viewport,
  });
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill(personalNumber);
  await page.getByTestId("password-input").fill(SEED_PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/$/);
  return { context, page };
}

async function submitConstraint(page: Page, reason: string, startDate: string, endDate: string) {
  await page.goto("/my-requests");
  await expect(page).toHaveURL(/\/my-requests$/);
  await page.getByTestId("constraint-form-toggle").click();
  await page.getByTestId("req-start").fill(startDate);
  await page.getByTestId("req-end").fill(endDate);
  await page.getByTestId("req-reason").fill(reason);
  await page.getByTestId("req-submit").click();
}

async function openExistingConstraintRow(page: Page, reason: string) {
  await page.goto("/my-requests?tab=existing&type=constraints&status=pending");
  await expect(page).toHaveURL(/\/my-requests\?tab=existing/);
  const row = page
    .getByTestId("constraints-list")
    .locator('[data-testid^="constraint-row-"]', { hasText: reason })
    .first();
  await expect(row).toBeVisible();
  return row;
}

async function findConstraintId(page: Page, reason: string) {
  const response = await page.request.get("/api/me/constraints");
  expect(response.ok()).toBeTruthy();
  const items = await response.json() as Array<{ id: string; reason: string | null }>;
  const match = items.find((item) => item.reason === reason);
  expect(match).toBeTruthy();
  return match!.id;
}

test.describe.configure({ mode: "serial" });

test("route-level and action-level authorization boundaries do not allow request mutation @smoke", async ({ browser, page }) => {
  const reason = `הרשאה-${createUniqueName("auth-boundary")}`;
  const startDate = isoDaysFromNow(38);
  const endDate = isoDaysFromNow(40);
  const resources: BrowserContext[] = [];
  const closeAll = async () => Promise.all(resources.map((context) => context.close()));

  try {
    await page.goto("/approvals?tab=constraints");
    await expect(page).toHaveURL(/\/approvals\?tab=constraints/);
    await expect(page.getByRole("alert")).toContainText("שגיאה בטעינת בקשות האישור");

    const soldier = await contextWithState(browser, "soldier");
    resources.push(soldier.context);
    await submitConstraint(soldier.page, reason, startDate, endDate);
    const constraintId = await findConstraintId(soldier.page, reason);
    const soldierPendingRow = await openExistingConstraintRow(soldier.page, reason);
    await expect(soldierPendingRow).toContainText("ממתין");

    const outOfScope = await loginWithPersonalNumber(browser, OUT_OF_SCOPE_COMMANDER_PN);
    resources.push(outOfScope.context);
    await outOfScope.page.goto("/approvals?tab=constraints");
    await expect(outOfScope.page).toHaveURL(/\/approvals\?tab=constraints/);
    await expect(outOfScope.page.getByTestId("approvals-list")).not.toContainText(reason);

    const rejectResponse = await outOfScope.page.request.post(`/api/constraints/${constraintId}/reject`, {
      data: { decision_note: "לא בסמכותי" },
    });
    expect(rejectResponse.status()).toBe(403);

    await soldier.page.reload();
    await expect(soldier.page).toHaveURL(/\/my-requests\?tab=existing/);
    await expect(await openExistingConstraintRow(soldier.page, reason)).toContainText("ממתין");
  } finally {
    await closeAll();
  }
});
