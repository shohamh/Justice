import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { roleStorageState, type Role } from "../fixtures/auth";

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
 *   POST /shifts/<shift>/gimelim/preview and /gimelim/commit. It is reached
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
  | "dutyManager"
  | "commander"
  | "assignedExemption"
  | "assignedGimelim"
  | "assignedAbsent"
  | "assignedHakpaza"
  | "firstReserve"
  | "secondReserve";

// Task 1 deliberately opens separate browser contexts. The current fixture
// has one seeded soldier account, so the six soldier-labelled contexts are
// isolated sessions but not yet six distinct identities. Task 4 must extend
// the fixture only if dedicated seeded accounts are made available.
const actorStorageRole: Record<JourneyActor, Role> = {
  dutyManager: "dutyManager",
  commander: "commander",
  assignedExemption: "soldier",
  assignedGimelim: "soldier",
  assignedAbsent: "soldier",
  assignedHakpaza: "soldier",
  firstReserve: "soldier",
  secondReserve: "soldier",
};

type RoleContext = { context: BrowserContext; page: Page };

async function openRoleContext(browser: Browser, actor: JourneyActor): Promise<RoleContext> {
  const projectUse = test.info().project.use as {
    baseURL?: string;
    viewport?: { width: number; height: number };
  };
  const context = await browser.newContext({
    baseURL: projectUse.baseURL ?? "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: roleStorageState(actorStorageRole[actor]),
  });
  return { context, page: await context.newPage() };
}

async function reachAssignmentBoundary(page: Page): Promise<void> {
  await page.goto("/planning/shifts");
  await expect(page).toHaveURL(/\/planning\/shifts$/);
  await expect(page.getByTestId("shifts-page")).toBeVisible();
}

function missingJourneySeam(name: string): never {
  throw new Error(`${name} is intentionally deferred to a later task after its UI selector is locked.`);
}

// Named helper boundaries for Tasks 2-4. They are intentionally inert in Task
// 1: invoking any of them would mutate the real stack before the missing UI
// seams above have component coverage and stable selectors.
async function createAndPublishAlgorithmDuty(_page: Page): Promise<never> {
  return missingJourneySeam("createAndPublishAlgorithmDuty");
}

async function assignManually(_page: Page): Promise<never> {
  return missingJourneySeam("assignManually");
}

async function submitAndApproveExemption(_soldier: Page, _commander: Page, _dutyManager: Page): Promise<never> {
  return missingJourneySeam("submitAndApproveExemption");
}

async function submitGimelim(_page: Page): Promise<never> {
  return missingJourneySeam("submitGimelim");
}

async function reportCannotAttend(_page: Page): Promise<never> {
  return missingJourneySeam("reportCannotAttend");
}

async function grantHakpazaPikudit(_page: Page): Promise<never> {
  return missingJourneySeam("grantHakpazaPikudit");
}

async function activateReserve(_page: Page): Promise<never> {
  return missingJourneySeam("activateReserve");
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

test.fixme("future multi-user duty problem lifecycle uses only visible UI controls", async ({ browser }) => {
  const dutyManager = await openRoleContext(browser, "dutyManager");
  const commander = await openRoleContext(browser, "commander");
  const exemptionSoldier = await openRoleContext(browser, "assignedExemption");
  const gimelimSoldier = await openRoleContext(browser, "assignedGimelim");
  const absentSoldier = await openRoleContext(browser, "assignedAbsent");
  const hakpazaSoldier = await openRoleContext(browser, "assignedHakpaza");
  const firstReserve = await openRoleContext(browser, "firstReserve");
  const secondReserve = await openRoleContext(browser, "secondReserve");
  try {
    await createAndPublishAlgorithmDuty(dutyManager.page);
    await assignManually(dutyManager.page);
    await submitAndApproveExemption(exemptionSoldier.page, commander.page, dutyManager.page);
    await submitGimelim(gimelimSoldier.page);
    await reportCannotAttend(absentSoldier.page);
    await grantHakpazaPikudit(commander.page);
    await activateReserve(dutyManager.page);
    await submitGimelim(firstReserve.page);
    await activateReserve(dutyManager.page);
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
      exemptionSoldier.context.close(),
      gimelimSoldier.context.close(),
      absentSoldier.context.close(),
      hakpazaSoldier.context.close(),
      firstReserve.context.close(),
      secondReserve.context.close(),
    ]);
  }
});
