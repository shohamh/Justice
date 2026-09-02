import { test, expect } from "../fixtures/test";

import { createUniqueName } from "../fixtures/data";
import { roleStorageState } from "../fixtures/auth";

test.use({ storageState: roleStorageState("soldier") });

function isoDaysFromNow(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

test("soldier submits a future personal-constraint request and sees it in the existing list @smoke", async ({ page }) => {
  const reason = `אילוץ-${createUniqueName("soldier-request")}`;
  const rangeOffset = Math.floor(Math.random() * 300);
  const startDate = isoDaysFromNow(16 + rangeOffset);
  const endDate = isoDaysFromNow(18 + rangeOffset);

  await page.goto("/my-requests");
  await expect(page).toHaveURL(/\/my-requests$/);
  await expect(page.getByTestId("new-requests-tab")).toBeVisible();

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

  await page.goto("/my-requests?tab=existing&type=constraints&status=pending");
  await expect(page).toHaveURL(/\/my-requests\?tab=existing/);
  await expect(page.getByTestId("existing-requests-tab")).toBeVisible();

  const row = page
    .getByTestId("constraints-list")
    .locator('[data-testid^="constraint-row-"]', { hasText: reason })
    .first();
  await expect(row).toBeVisible();
  await expect(row).toContainText("ממתין");
  await expect(row).toContainText(reason);
  await expect(row).toContainText(startDate);
  await expect(row).toContainText(endDate);
  await expect(row.getByTestId(/constraint-.*-waiting-on/)).toBeVisible();

  await page.reload();
  await expect(page).toHaveURL(/\/my-requests\?tab=existing/);
  await expect(row).toBeVisible();
  await expect(row).toContainText(reason);
});
