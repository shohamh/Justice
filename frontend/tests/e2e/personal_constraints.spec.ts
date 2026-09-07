import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";
import { navItem } from "./fixtures/nav";

test.use({ storageState: roleStorageState("admin") });

test("soldier submits personal constraint, past dates are blocked client-side @smoke", async ({ page }) => {
  await navItem(page, "nav-my-requests").click();
  await expect(page).toHaveURL(/\/my-requests$/);

  await page.getByTestId("constraint-form-toggle").click();
  await expect(page.getByTestId("constraint-form-card")).toBeVisible();
  await page.getByTestId("req-start").fill("2020-01-01");
  await page.getByTestId("req-end").fill("2020-01-03");
  await page.getByTestId("req-reason").fill("בדיקה");
  // A past start date now disables submit client-side (see MyRequestsPage's
  // onSubmit/isDateInPast check) rather than round-tripping to the server for
  // a rejection -- confirm the button stays disabled instead of clicking it.
  await expect(page.getByTestId("req-submit")).toBeDisabled();

  const futureStart = new Date();
  futureStart.setDate(futureStart.getDate() + 10);
  const futureEnd = new Date();
  futureEnd.setDate(futureEnd.getDate() + 12);
  const fmtDate = (d: Date) => d.toISOString().slice(0, 10);

  await page.getByTestId("req-start").fill(fmtDate(futureStart));
  await page.getByTestId("req-end").fill(fmtDate(futureEnd));
  await page.getByTestId("req-reason").fill("חופשה אישית");
  await page.getByTestId("req-submit").click();

  // The create form lives under the "new" tab; existing constraints
  // (constraints-list) are under a separate "existing" tab.
  await page.goto("/my-requests?tab=existing");
  await expect(page.getByTestId("constraints-list")).toBeVisible();
});
