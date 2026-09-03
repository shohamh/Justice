import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { journeyActorStorageState, roleStorageState, type Role, type JourneyActor as AuthJourneyActor } from "../fixtures/auth";

/**
 * Task 1 UI seam inventory (read-only; later tasks must drive every mutation
 * through the controls listed here, never page.request/fetch/database setup):
 *
 * - Duty creation and algorithm entry: /planning/shifts is the live route
 *   (the older /planning/assignment and /algorithm routes redirect here).
 *   The stable page boundary is [data-testid="shifts-page"]. Its creation
 *   control is the visible "משמרת חדשה" button (POST /shifts); individual
 *   shift selection
 *   uses [data-testid^="shift-row-checkbox-"] and the bulk action opens the
 *   inline AlgorithmRunForm. "הרץ אלגוריתם" submits POST /algorithm/jobs.
 *   The surrounding run view exposes
 *   algo-badge-running/draft/done/failed, but the form controls themselves
 *   currently have no stable test ids.
 * - Algorithm publication: AlgorithmRunForm selects draft/direct-publish and
 *   AlgorithmJobTabs presents job/proposal controls. "אשר ופרסם (הפוך לרשמי)"
 *   uses POST /algorithm/jobs/<job>/proposals/bulk-accept. The current route
 *   and stable assignment boundary remain /planning/shifts and shifts-page;
 *   Task 2 must lock a result/proposal selector before automating publication.
 * - Manual assignment: every active shift has the visible button titled
 *   "ערוך שיבוצים", which opens ShiftEditAssignmentsModal. It exposes the
 *   "הוסף ראשיים", "הוסף רזרבות", and "שמור" controls but no stable
 *   test ids. Its UI calls POST /shifts/<shift>/assign-batch, so it is the
 *   later manual path.
 * - Exemption: /my-requests -> er-form-toggle -> er-form-card; the form uses
 *   er-start, er-end, er-reason, and er-submit. /approvals?tab=exemptions
 *   exposes approvals-tab-exemptions, er-approvals-list,
 *   er-approval-row-<id>, er-stage-<id>, and er-approve-<id>. Those controls
 *   call POST /me/exemption-requests and the commander/duty-manager approval
 *   endpoints under /exemption-requests/<request>.
 * - Gimelim: a duty detail's DismissalModal exposes the visible mode
 *   "גימלים", medical-reason input, preview, and commit. It calls
 *   POST /shifts/<shift>/gimelim/preview and /shifts/<shift>/gimelim/commit. It is reached
 *   from ShiftDetailPanel only for a duty manager/admin and currently has no
 *   soldier submission route or stable browser selectors for its states.
 * - Hakpaza Pikudit: /commander/hakpaza is settings-gated. Its visible staged
 *   headings are "שלב 1" through "שלב 4"; it selects a soldier, a published
 *   assignment, a candidate, and confirmation. It calls POST
 *   /hakpaza/candidates and POST /hakpaza; approval is POST
 *   /hakpaza/<request>/approve. No stable test ids exist.
 * - Absence and replacement: the only inspected absence UI is range attendance
 *   (RangeDetailContent's no-show-<assignment>, note-<assignment>, and
 *   attendance-save-button; PATCH /ranges/<event>/assignments/<assignment>/attendance).
 *   There is no inspected regular-duty absence flow or duty-problem panel yet.
 *   Regular-duty reserve activation is represented in DismissalModal's
 *   covering-reserve chooser (POST /shifts/<shift>/dismissals); it likewise
 *   lacks a stable selector/history assertion boundary.
 * - Commander visibility: /unit-calendar has unit-calendar-page and event
 *   warning badges, and the commander dashboard has upcoming-snapshot. Neither
 *   currently identifies exemption/Hakpaza duty problems with a stable selector.
 */

type JourneyActor =
  | "admin"
  | "dutyManager"
  | "commander"
  | "assignedExemption"
  | "assignedGimelim"
  | "assignedAbsent"
  | "assignedHakpaza"
  | "firstReserve"
  | "secondReserve";

const actorStorageRole: Record<JourneyActor, Role> = {
  admin: "admin",
  dutyManager: "dutyManager",
  commander: "commander",
  assignedExemption: "soldier",
  assignedGimelim: "soldier",
  assignedAbsent: "soldier",
  assignedHakpaza: "soldier",
  firstReserve: "soldier",
  secondReserve: "soldier",
};

const journeyStorageActor: Partial<Record<JourneyActor, AuthJourneyActor>> = {
  assignedExemption: "assignedExemption",
  assignedGimelim: "assignedGimelim",
  assignedAbsent: "assignedAbsent",
  assignedHakpaza: "assignedHakpaza",
  firstReserve: "firstReserve",
  secondReserve: "secondReserve",
};

type RoleContext = { context: BrowserContext; page: Page };
let journeyShiftId = "";
let journeyManualLocationName = "";
// Keep generated duties outside the seeded and accumulated local E2E horizon
// so repeated real-UI runs do not make the scenario actors unavailable.
const journeyBaseOffset = 1500 + Math.floor(Math.random() * 100);
const journeyAlgorithmStart = new Date(Date.now() + journeyBaseOffset * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
const journeyManualStart = new Date(Date.now() + (journeyBaseOffset + 10) * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
const journeyExemptionReason = `מסע E2E פטור לאחר שיבוץ ${Date.now()}`;
function nextJourneyDate(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}
function previousJourneyDate(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - 1);
  return value.toISOString().slice(0, 10);
}
function displayJourneyDate(date: string): string {
  const [year, month, day] = date.split("-");
  return `${day}.${month}.${year}`;
}

async function openRoleContext(browser: Browser, actor: JourneyActor): Promise<RoleContext> {
  const projectUse = test.info().project.use as {
    baseURL?: string;
    viewport?: { width: number; height: number };
  };
  const journeyActor = journeyStorageActor[actor];
  const context = await browser.newContext({
    baseURL: projectUse.baseURL ?? "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: journeyActor ? journeyActorStorageState(journeyActor) : roleStorageState(actorStorageRole[actor]),
  });
  return { context, page: await context.newPage() };
}

async function reachAssignmentBoundary(page: Page): Promise<void> {
  await page.goto("/planning/shifts");
  await expect(page).toHaveURL(/\/planning\/shifts$/);
  await expect(page.getByTestId("shifts-page")).toBeVisible();
}

async function createAndPublishAlgorithmDuty(page: Page): Promise<void> {
  await page.goto("/planning/shifts");
  await expect(page.getByTestId("shifts-page")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("shift-create-button").click();
  const dutyTypeCombobox = page.getByTestId("shift-create-form").getByRole("combobox").nth(0);
  await dutyTypeCombobox.click();
  await expect(page.locator('[role="listbox"]:visible [role="option"] button').first()).toBeVisible();
  await page.locator('[role="listbox"]:visible [role="option"] button').first().click();
  const algorithmLocationName = `E2E algorithm ${Date.now()}`;
  await page.getByTestId("shift-create-form").getByRole("button", { name: /מיקום חדש/ }).click();
  await page.getByTestId("location-create-name").fill(algorithmLocationName);
  const algorithmLocationCreate = page.waitForResponse(response => response.url().includes("/api/duty-config/locations") && response.request().method() === "POST");
  await page.getByTestId("location-create-submit").click();
  expect((await algorithmLocationCreate).status()).toBe(201);
  await expect(page.getByTestId("location-create-name")).toBeHidden({ timeout: 30_000 });
  await page.getByTestId("shift-start-date").fill(journeyAlgorithmStart);
  await page.getByTestId("shift-end-date").fill(nextJourneyDate(journeyAlgorithmStart));
  await page.getByRole("spinbutton").nth(0).fill("1");
  await page.getByRole("spinbutton").nth(1).fill("0");
  const algorithmCreate = page.waitForResponse(response => response.url().includes("/api/shifts") && response.request().method() === "POST");
  await page.getByTestId("shift-create-submit").click();
  const algorithmResponse = await algorithmCreate;
  journeyShiftId = (await algorithmResponse.json()).id;
  await page.getByTestId("shift-filter-from").fill(previousJourneyDate(journeyAlgorithmStart));
  const checkbox = page.getByTestId(`shift-row-checkbox-${journeyShiftId}`);
  await expect(checkbox).toBeVisible({ timeout: 30_000 });
  journeyShiftId = (await checkbox.getAttribute("data-testid"))!.replace("shift-row-checkbox-", "");
  await checkbox.check();
  await page.getByRole("button", { name: "שיבוץ אוטומטי", exact: true }).click();
  await page.getByTestId("algorithm-run-submit").click();
  await expect(page.getByTestId("algorithm-proposal-review")).toBeVisible({ timeout: 120_000 });
  const publish = page.getByTestId("algorithm-publish-proposals");
  if (await publish.isEnabled()) await publish.click();
  await expect(page.getByTestId("algorithm-proposal-review")).toContainText("פורסם", { timeout: 45_000 });
}

async function assignManually(page: Page): Promise<void> {
  await page.goto("/planning/shifts");
  await page.getByTestId("shift-create-button").click();
  const createForm = page.getByTestId("shift-create-form");
  const createComboboxes = createForm.getByRole("combobox");
  await createComboboxes.nth(0).click();
  await expect(page.locator('[role="listbox"]:visible [role="option"] button').first()).toBeVisible();
  await page.locator('[role="listbox"]:visible [role="option"] button').first().click();
  const manualLocationName = `E2E manual ${Date.now()}`;
  journeyManualLocationName = manualLocationName;
  await createForm.getByRole("button", { name: /מיקום חדש/ }).click();
  await page.getByTestId("location-create-name").fill(manualLocationName);
  const manualLocationCreate = page.waitForResponse(response => response.url().includes("/api/duty-config/locations") && response.request().method() === "POST");
  await page.getByTestId("location-create-submit").click();
  expect((await manualLocationCreate).status()).toBe(201);
  await expect(page.getByTestId("location-create-name")).toBeHidden({ timeout: 30_000 });
  await page.getByTestId("shift-start-date").fill(journeyManualStart);
  await page.getByTestId("shift-end-date").fill(nextJourneyDate(journeyManualStart));
  await page.getByRole("spinbutton").nth(0).fill("4");
  await page.getByRole("spinbutton").nth(1).fill("2");
  const manualCreate = page.waitForResponse(response => response.url().includes("/api/shifts") && response.request().method() === "POST");
  await page.getByTestId("shift-create-submit").click();
  const manualResponse = await manualCreate;
  journeyShiftId = (await manualResponse.json()).id;
  await page.getByTestId("shift-filter-from").fill(previousJourneyDate(journeyManualStart));
  const newShiftCheckbox = page.getByTestId(`shift-row-checkbox-${journeyShiftId}`);
  await expect(newShiftCheckbox).toBeVisible({ timeout: 30_000 });
  journeyShiftId = (await newShiftCheckbox.getAttribute("data-testid"))!.replace("shift-row-checkbox-", "");
  await page.getByTestId(`manual-assignment-open-${journeyShiftId}`).click();
  const modal = page.getByTestId(`manual-assignment-modal-${journeyShiftId}`);
  await expect(modal).toBeVisible();
  await expect(page.getByTestId("manual-add-primary")).toBeVisible({ timeout: 30_000 });
  const primaryCandidates = modal.locator('[data-testid^="manual-primary-candidate-"] input:not(:checked)');
  if (!(await primaryCandidates.first().isVisible().catch(() => false))) {
    await page.getByTestId("manual-add-primary").click();
  }
  for (const personalNumber of ["1000009", "1000010", "1000011", "1000012"]) {
    const candidate = modal.locator('[data-testid^="manual-primary-candidate-"]').filter({ hasText: personalNumber }).locator('input:not(:checked)').first();
    await expect(candidate).toBeVisible({ timeout: 30_000 });
    await candidate.check();
  }
  const reserveCandidates = modal.locator('[data-testid^="manual-reserve-candidate-"] input:not(:checked)');
  if (!(await reserveCandidates.first().isVisible().catch(() => false))) {
    await page.getByTestId("manual-add-reserve").click();
  }
  for (const preferredNumber of ["1000002", "1000003"]) {
    const preferred = modal.locator('[data-testid^="manual-reserve-candidate-"]').filter({ hasText: preferredNumber }).locator('input:not(:checked)').first();
    if (await preferred.isVisible().catch(() => false)) await preferred.check();
    else {
      await expect(reserveCandidates.first()).toBeVisible({ timeout: 30_000 });
      await reserveCandidates.first().check();
    }
  }
  const batchAssign = page.waitForResponse(response =>
    response.url().includes(`/api/shifts/${journeyShiftId}/assign-batch`) && response.request().method() === "POST",
  );
  await page.getByTestId("manual-assignment-save").click();
  const batchResult = await batchAssign;
  expect(batchResult.status()).toBe(201);
  await expect(modal).toBeHidden();
}

async function submitAndApproveExemption(soldier: Page, commander: Page, admin: Page): Promise<void> {
  await soldier.goto("/my-requests");
  await soldier.getByTestId("er-form-toggle").click();
  await expect(soldier.getByTestId("er-form-card")).toBeVisible();
  await soldier.getByTestId("er-type").click();
  await soldier.locator('[role="listbox"]:visible [role="option"] button').nth(1).click();
  await soldier.getByTestId("er-start").fill(journeyManualStart);
  await soldier.getByTestId("er-end").fill(journeyManualStart);
  await soldier.getByTestId("er-reason").fill(journeyExemptionReason);
  const exemptionSubmission = soldier.waitForResponse(response => response.url().includes("/api/me/exemption-requests") && response.request().method() === "POST");
  await soldier.getByTestId("er-submit").click();
  expect((await exemptionSubmission).status()).toBe(201);
  await soldier.goto("/my-requests?tab=existing");
  await expect(soldier.getByTestId("er-list")).toContainText(journeyExemptionReason, { timeout: 30_000 });

  for (const approver of [commander, admin]) {
    await approver.goto("/approvals?tab=exemptions");
    const row = approver.locator('[data-testid^="er-approval-row-"]').filter({ hasText: journeyExemptionReason });
    await expect(row).toBeVisible({ timeout: 30_000 });
    const approve = row.locator('[data-testid^="er-approve-"]');
    if (await approve.count() > 0) {
      const approvalResponse = approver.waitForResponse(response =>
        response.url().includes("/api/exemption-requests/") && response.url().includes("/approve-") && response.request().method() === "POST",
      );
      await approve.click();
      expect((await approvalResponse).status()).toBe(200);
    }
  }
}

async function submitGimelim(page: Page): Promise<void> {
  await page.goto("/my-duties");
  const report = page.locator('[data-testid^="report-gimelim-"]').first();
  await expect(report).toBeVisible({ timeout: 30_000 });
  await report.click();
  const modal = page.getByTestId("dismissal-modal");
  await expect(modal).toBeVisible();
  await page.getByTestId("dismissal-mode-gimelim").click();
  await modal.locator("textarea").fill("מסמך רפואי למסע E2E");
  await page.getByTestId("gimelim-preview-action").click();
  await expect(page.getByTestId("gimelim-preview")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("gimelim-commit-action").click();
  await expect(modal).toBeHidden({ timeout: 30_000 });
}

async function reportCannotAttend(page: Page): Promise<void> {
  await page.goto("/my-duties");
  const report = page.locator('[data-testid^="report-absence-"]').first();
  await expect(report).toBeVisible({ timeout: 30_000 });
  await report.click();
  await expect(page.getByTestId("absence-report-modal")).toBeVisible();
  await page.getByTestId("absence-reason").fill("לא יכול להגיע למסע E2E");
  await page.getByTestId("absence-submit").click();
  await expect(page.getByTestId("absence-report-modal")).toBeHidden({ timeout: 30_000 });
}

async function grantHakpazaPikudit(page: Page): Promise<void> {
  const publicSettingsLoad = page.waitForResponse(response =>
    response.url().includes("/api/settings/public") && response.request().method() === "GET",
  );
  await page.goto("/");
  await publicSettingsLoad;
  const refreshedPublicSettingsLoad = page.waitForResponse(response =>
    response.url().includes("/api/settings/public") && response.request().method() === "GET",
  );
  await page.reload();
  await refreshedPublicSettingsLoad;
  const soldiersRequest = page.waitForRequest(request =>
    /\/api\/soldiers(\?|$)/.test(request.url()) && request.method() === "GET",
  );
  await page.goto("/commander/hakpaza");
  const authorization = (await soldiersRequest).headers()["authorization"];
  const soldiers = await page.evaluate(async (auth: string) => {
    const res = await fetch(`/api/soldiers?_=${Date.now()}`, { headers: { Authorization: auth }, cache: "no-store" });
    return res.json();
  }, authorization) as Array<{ id: string; personal_number: string }>;
  const hakpazaSoldierId = soldiers.find(s => s.personal_number === "1000012")!.id;
  const soldier = page.getByTestId(`hakpaza-soldier-${hakpazaSoldierId}`);
  await expect(soldier).toBeVisible({ timeout: 30_000 });
  await soldier.click();
  const assignment = page.locator('[data-testid^="hakpaza-assignment-radio-"]').first();
  await expect(assignment).toBeVisible({ timeout: 30_000 });
  await assignment.check();
  await page.getByTestId("hakpaza-find-candidates").click();
  const candidate = page.locator('[data-testid^="hakpaza-candidate-"]').first();
  await expect(candidate).toBeVisible({ timeout: 30_000 });
  await candidate.click();
  await page.getByTestId("hakpaza-review-candidate").click();
  await page.getByTestId("hakpaza-submit").click();
  await expect(page.getByText("בקשת ההקפצה נשלחה")).toBeVisible({ timeout: 30_000 });
}

async function enableHakpaza(page: Page): Promise<void> {
  const settingsLoad = page.waitForResponse(response =>
    response.url().includes("/api/admin/system-settings") && response.request().method() === "GET",
  );
  await page.goto("/admin/settings");
  await settingsLoad;
  const label = page.getByText("הקפצה פיקודית מופעלת", { exact: true });
  await expect(label).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(100);
  const toggle = label.locator("../..").getByRole("button");
  if ((await toggle.getAttribute("aria-pressed")) !== "true") {
    await toggle.click();
    const save = page.getByRole("button", { name: "שמור", exact: true }).first();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    if (await save.isEnabled().catch(() => false)) {
      await save.click();
    } else {
      const importButton = page.getByRole("button", { name: "ייבוא הגדרות", exact: true });
      await expect(importButton).toBeVisible();
      await importButton.click();
      await page.locator('input[type="file"]').setInputFiles({
        name: "hakpaza-settings.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify({ "forced_callup.enabled": true })),
      });
    }
    await expect(page.getByText("נשמר ✓", { exact: true })).toBeVisible({ timeout: 30_000 });
  }
  await page.reload();
  const persistedLabel = page.getByText("הקפצה פיקודית מופעלת", { exact: true });
  await expect(persistedLabel).toBeVisible({ timeout: 30_000 });
  await expect(persistedLabel.locator("../..").getByRole("button")).toHaveAttribute("aria-pressed", "true");
}

async function activateReserve(page: Page): Promise<void> {
  await page.goto("/unit-calendar");
  const shiftEvent = page.locator(".fc-event").filter({ hasText: journeyManualLocationName }).last();
  for (let month = 0; month < 60 && !(await shiftEvent.isVisible().catch(() => false)); month += 1) {
    await page.locator(".fc-next-button").click();
    await page.waitForTimeout(1_000);
  }
  await expect(shiftEvent).toBeVisible({ timeout: 30_000 });
  await shiftEvent.click();
  const dismiss = page.locator('[data-testid^="shift-dismiss-assignment-"]').first();
  await expect(dismiss).toBeVisible({ timeout: 30_000 });
  await dismiss.click();
  await expect(page.getByTestId("dismissal-modal")).toBeVisible();
  const covering = page.getByTestId("dismissal-covering-reserve");
  if (await covering.count() > 0) {
    await covering.click();
    await page.locator('[role="listbox"]:visible [role="option"] button').first().click();
  }
  await page.getByTestId("dismissal-save-replacement").click();
  await expect(page.getByTestId("dismissal-modal")).toBeHidden({ timeout: 30_000 });
}

test.describe.configure({ mode: "serial" });

test("duty manager reaches the existing assignment UI boundary without mutation APIs @smoke", async ({ browser }) => {
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    await reachAssignmentBoundary(dutyManager.page);
  } finally {
    await dutyManager.context.close();
  }
});

test("future multi-user duty problem lifecycle uses only visible UI controls", async ({ browser }) => {
  test.setTimeout(300_000);
    const dutyManager = await openRoleContext(browser, "dutyManager");
    const commander = await openRoleContext(browser, "commander");
  let admin = await openRoleContext(browser, "admin");
  const exemptionSoldier = await openRoleContext(browser, "assignedExemption");
  const gimelimSoldier = await openRoleContext(browser, "assignedGimelim");
  const absentSoldier = await openRoleContext(browser, "assignedAbsent");
  const hakpazaSoldier = await openRoleContext(browser, "assignedHakpaza");
  const firstReserve = await openRoleContext(browser, "firstReserve");
  const secondReserve = await openRoleContext(browser, "secondReserve");
  try {
    await createAndPublishAlgorithmDuty(dutyManager.page);
    await assignManually(dutyManager.page);
    await submitAndApproveExemption(exemptionSoldier.page, commander.page, admin.page);
    await submitGimelim(gimelimSoldier.page);
    await reportCannotAttend(absentSoldier.page);
    await enableHakpaza(admin.page);
    await admin.context.close();
    admin = await openRoleContext(browser, "admin");
    await grantHakpazaPikudit(admin.page);
    await activateReserve(dutyManager.page);
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
      admin.context.close(),
      exemptionSoldier.context.close(),
      gimelimSoldier.context.close(),
      absentSoldier.context.close(),
      hakpazaSoldier.context.close(),
      firstReserve.context.close(),
      secondReserve.context.close(),
    ]);
  }
});
