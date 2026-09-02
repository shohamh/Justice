import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("soldier submits personal constraint, sees Hebrew error for past date @smoke", async ({ page }) => {
  await page.getByTestId("nav-my-requests").click();
  await expect(page).toHaveURL(/\/my-requests$/);

  await page.getByTestId("req-start").fill("2020-01-01");
  await page.getByTestId("req-end").fill("2020-01-03");
  await page.getByTestId("req-reason").fill("בדיקה");
  await page.getByTestId("req-submit").click();

  await expect(page.getByTestId("req-error")).toBeVisible();
  await expect(page.getByTestId("req-error")).not.toContainText("error");

  const futureStart = new Date();
  futureStart.setDate(futureStart.getDate() + 10);
  const futureEnd = new Date();
  futureEnd.setDate(futureEnd.getDate() + 12);
  const fmtDate = (d: Date) => d.toISOString().slice(0, 10);

  await page.getByTestId("req-start").fill(fmtDate(futureStart));
  await page.getByTestId("req-end").fill(fmtDate(futureEnd));
  await page.getByTestId("req-reason").fill("חופשה אישית");
  await page.getByTestId("req-submit").click();

  await expect(page.getByTestId("constraints-list")).toBeVisible();
});
