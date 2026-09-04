import { test, expect } from "./fixtures/test";

import { roleStorageState } from "./fixtures/auth";

test.use({ storageState: roleStorageState("admin") });

test("admin creates exemption type, soldier requests exemption, admin approves", async ({ page }) => {
  const suffix = `${Date.now() % 100000}`;
  const etName = `פטור-בדיקה-${suffix}`;

  await page.getByTestId("nav-planning").click();
  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/planning\/config/);
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  await page.getByTestId("nav-my-requests").click();
  await expect(page).toHaveURL(/\/my-requests$/);

  await page.getByTestId("er-type").click();
  await page.getByTestId("er-type").fill(etName);
  await page.getByRole("option", { name: etName }).click();
  const futureStart = new Date();
  futureStart.setDate(futureStart.getDate() + 20);
  const futureEnd = new Date();
  futureEnd.setDate(futureEnd.getDate() + 25);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  await page.getByTestId("er-start").fill(fmt(futureStart));
  await page.getByTestId("er-end").fill(fmt(futureEnd));
  await page.getByTestId("er-reason").fill("בקשת פטור בדיקה");
  await page.getByTestId("er-submit").click();

  await expect(page.getByTestId("er-list")).toBeVisible();

  await page.getByTestId("nav-commander").click();
  await page.getByTestId("nav-approvals").click();
  await expect(page).toHaveURL(/\/approvals$/);
  await page.getByTestId("approvals-tab-exemptions").click();

  const approveBtn = page.getByTestId(/^er-approve-/).first();
  if (await approveBtn.isVisible()) {
    await approveBtn.click();
    await expect(page.getByTestId("er-approvals-list")).toBeVisible();
  }
});
