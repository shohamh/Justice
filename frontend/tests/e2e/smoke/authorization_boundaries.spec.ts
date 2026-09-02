import type { BrowserContext, Page } from "@playwright/test";

import { test, expect } from "../fixtures/test";
import { createUniqueName } from "../fixtures/data";
import { roleStorageState } from "../fixtures/auth";


function isoDaysFromNow(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

async function contextWithState(browser: Parameters<typeof test>[0]["browser"], role: "soldier") {
  const use = test.info().project.use as { baseURL?: string; viewport?: { width: number; height: number } };
  const context = await browser.newContext({ baseURL: use.baseURL, viewport: use.viewport, storageState: roleStorageState(role) });
  return { context, page: await context.newPage() };
}

async function submitConstraint(page: Page, reason: string, startDate: string, endDate: string) {
  await page.goto("/my-requests");
  await page.getByTestId("constraint-form-toggle").click();
  await page.getByTestId("req-start").fill(startDate);
  await page.getByTestId("req-end").fill(endDate);
  await page.getByTestId("req-reason").fill(reason);
  await expect(page.getByTestId("req-submit")).toBeEnabled();
  const response = page.waitForResponse((r) => r.url().endsWith("/api/me/constraints") && r.request().method() === "POST");
  await page.getByTestId("req-submit").click();
  expect((await response).status()).toBe(201);
}

test.describe.configure({ mode: "serial" });

test("out-of-scope reviewer cannot view or mutate another unit request @smoke", async ({ browser }) => {
  const reason = `authorization-${createUniqueName("boundary")}`;
  const soldier = await contextWithState(browser, "soldier");
  const outOfScope = await contextWithState(browser, "soldier");
  try {
    await submitConstraint(soldier.page, reason, isoDaysFromNow(38), isoDaysFromNow(40));
    await soldier.page.goto("/my-requests?tab=existing&type=constraints&status=pending");
    const row = soldier.page.getByTestId("constraints-list").locator('[data-testid^="constraint-row-"]', { hasText: reason }).first();
    await expect(row).toBeVisible();
    const rowTestId = await row.getAttribute("data-testid");
    const constraintId = rowTestId?.replace("constraint-row-", "");
    expect(constraintId).toBeTruthy();

    await outOfScope.page.goto("/approvals?tab=constraints");
    await expect(outOfScope.page).toHaveURL(/\/approvals\?tab=constraints/);
    await expect(outOfScope.page.getByTestId("approvals-list")).not.toContainText(reason);

    const rejectResponse = await outOfScope.page.evaluate(async (id) => {
      const refresh = await fetch("/api/auth/refresh", { method: "POST" });
      const { access_token } = await refresh.json() as { access_token: string };
      const response = await fetch(`/api/constraints/${id}/reject`, {
        method: "POST",
        headers: { Authorization: `Bearer ${access_token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ decision_note: "not authorized" }),
      });
      return response.status;
    }, constraintId);
    expect(rejectResponse).toBe(403);
    await soldier.page.goto("/my-requests?tab=existing&type=constraints&status=pending");
    await expect(soldier.page.getByTestId("constraints-list")).toContainText(reason);
  } finally {
    await soldier.context.close();
    await outOfScope.context.close();
  }
});
