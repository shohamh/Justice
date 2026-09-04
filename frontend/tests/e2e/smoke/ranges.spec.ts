import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { journeyActorStorageState, roleStorageState, type Role, type JourneyActor as AuthJourneyActor } from "../fixtures/auth";

/**
 * Task 2 UI seam inventory (every control/endpoint this spec drives, plus
 * corrections to the plan's brief made after reading the real
 * components/services/routes — not guesses, per the same discipline
 * swaps.spec.ts documents for Task 1):
 *
 * - Page boundary: `data-testid="ranges-page"`, route `/ranges`. Feature is
 *   gated by `mitvachim.enabled`, already forced on by seed.py.
 * - Create event: `create-event-button` -> `RangeFormModal` form
 *   `create-event-form`, sections `range-form-section-schedule` (type
 *   `new-range-type`, location `new-range-location`, responsible
 *   `new-range-responsible`, plus `new-date`/`new-start-time`/`new-end-time`/
 *   `new-required-count`/`new-reserve-count`), `range-form-section-contact`
 *   (`new-contact-name`/`new-contact-phone`), `range-form-section-notes`.
 *   Footer `range-form-footer` has no submit testid, just a plain "שמור"
 *   button -> `POST /api/ranges`.
 * - CORRECTION (verified by reading `RangeEditAssignmentsModal.tsx` directly,
 *   per the brief's own explicit "confirm before writing" instruction for
 *   this exact selector): the candidate checkbox testid prefixes are
 *   `candidate-checkbox-{soldierId}` (primary) and
 *   `reserve-candidate-checkbox-{soldierId}` (reserve) — not
 *   `primary-candidate-{soldierId}`/`reserve-candidate-{soldierId}` as the
 *   brief guessed. Reached via per-row `view-assignments-{eventId}` ->
 *   `RangeEditAssignmentsModal`; save button `save-assignments` ->
 *   `POST /api/ranges/{eventId}/assignments/batch` (200, not 201 — no
 *   `status_code` override on that route).
 * - Attendance: `RangeDetailContent` roster `range-detail-roster`, per
 *   assignment `present-{assignmentId}`/`no-show-{assignmentId}` (in
 *   `RangeAttendanceStatusPicker.tsx`), note `note-{assignmentId}` (required
 *   for no_show or any status correction), save `attendance-save-button` ->
 *   `PATCH /api/ranges/{eventId}/assignments/{assignmentId}/attendance`
 *   (batched via `Promise.allSettled`, one PATCH per changed assignment).
 *   The picker's present/no-show buttons only reflect *unsaved* selections
 *   (no highlighting of the already-persisted status), so "the status
 *   persisted" is asserted from `AssignmentRow`'s read-only status text next
 *   to the soldier's name, not from picker button state.
 * - Excusal self-service: `range-self-excusal-action` (rendered only for the
 *   viewer's own future, non-draft assignment) -> `submit-excuse-button` ->
 *   `POST /api/ranges/{eventId}/assignments/{assignmentId}/excuse`.
 *   Manager decision: `excusal-review-queue` (rendered only once pending
 *   requests exist, and only fetched for `user.is_duty_manager`) ->
 *   `approve-excusal-{requestId}`/`reject-excusal-{requestId}` ->
 *   `POST /api/ranges/{eventId}/excusal-requests/{requestId}/decide`.
 * - CORRECTION (found by reading `backend/app/routes/ranges.py`'s
 *   `get_range_event` and `backend/app/auth/authz.py`'s `can()`/`authorize()`
 *   end to end): `GET /ranges/{event_id}` — the single call every
 *   UI path to `RangeDetailContent` goes through (`RangesPage`'s inline
 *   modal, and `RangeDetailModal` used from both `HomePage` and
 *   `UnitCalendar`) — requires either `Action.RANGE_MANAGE` (duty
 *   manager/admin only; `RANGE_MANAGE` is DM-scoped, never granted to a
 *   plain soldier) or the viewer being a commander whose scope root is an
 *   ancestor-of-or-equal-to the event's own `hierarchy_node_id`. There is no
 *   "the viewer is the assigned soldier" exception on this route (unlike the
 *   *list* route's separate `soldier_id=` branch). A plain assigned soldier
 *   therefore gets a 403 on this call and can never reach the self-excusal
 *   button for an event created by `dutyManager` — every event `dutyManager`
 *   creates lands at `dutyManager`'s own node (`RangeFormModal` always
 *   submits the current user's `hierarchy_node_id`, with no node picker),
 *   which is the "פוקוס" branch — one level above every team, so not even a
 *   team-leader commander's scope (which only covers their own team and
 *   below) reaches it. The `commander` role fixture (personal number
 *   2000001, "רען פוקוס") is seeded as the direct commander of that exact
 *   "פוקוס" node, so this spec assigns `commander` as the new event's
 *   *primary* soldier and drives the self-excusal as `commander` instead of
 *   a plain soldier — the only seeded actor for whom this UI path is
 *   actually reachable for a `dutyManager`-created event.
 * - CORRECTION (found by reading `range_excusal.py::decide_primary_excusal`):
 *   approving a *primary* excusal does not leave an "approved" marker on the
 *   assignment — it deletes the assignment outright and, if an eligible
 *   reserve exists, promotes them into the vacated primary slot. There is
 *   no "approved" badge anywhere in the UI to assert against. This spec
 *   instead asserts the real, visible effect: after refresh, the requester's
 *   own `range-self-excusal-action` section is gone (their assignment no
 *   longer exists), the reserve (`assignedGimelim`, seeded personal number
 *   1000010) is promoted into the primary roster count, and the
 *   `excusal-review-queue` (which only lists *pending* requests) no longer
 *   shows the request.
 * - Qualification/eligibility: `range_qualification.tabs.qualification` tab
 *   is reached via `?tab=ineligible` (not `?tab=qualification` as the query
 *   param literal — the tab *label* translation key is
 *   `range_qualification.tabs.qualification`, but `RangesPage.tsx` reads
 *   `params.get("tab") === "ineligible"`). Renders `IneligibleSoldiersTable`
 *   (`ineligible-soldiers-view`), a two-level `DataTable`
 *   (`ineligible-soldiers-table`) of hierarchy units that expands
 *   (`ineligible-node-{id}`) into a per-soldier table where every row always
 *   renders an `ineligible-warning-{soldier_id}` badge (its color, not its
 *   presence, depends on whether the soldier has an urgent upcoming weapon
 *   duty) — this spec filters the unit table to "מארס" (the seeded past
 *   event's team) and asserts at least one such badge renders once expanded,
 *   rather than pinning an exact soldier id the seed's ordering isn't a
 *   contract for.
 */

// assignedGimelim (seeded personal number 1000010, journeyActors in
// fixtures/auth.ts) is used only by personal number, as the new event's
// reserve — its promotion into the primary slot is asserted from
// dutyManager's own view, so no separate browser context is opened for it.
type JourneyActor = "dutyManager" | "commander";

const actorStorageRole: Record<JourneyActor, Role> = {
  dutyManager: "dutyManager",
  commander: "commander",
};

const journeyStorageActor: Partial<Record<JourneyActor, AuthJourneyActor>> = {};

type RoleContext = { context: BrowserContext; page: Page };

// Far enough ahead to avoid every other spec's fixture horizon (swaps.spec.ts
// uses ~130-150 days out, multi_user_duty_problems.spec.ts uses 1500+ days
// out) while staying well clear of seed.py's own 8-week shift/range
// generation window. This spec's own run procedure always reseeds with
// --clear first, so a modest, distinct offset is enough.
const rangesBaseOffset = 300 + Math.floor(Math.random() * 40);

function isoDateAtOffset(days: number): string {
  return new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

async function openActorContext(browser: Browser, actor: JourneyActor): Promise<RoleContext> {
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

/** dutyManager creates a range event at their own node ("פוקוס"), far enough
 * out to be uncontested. Returns the created event's id and iso date. */
async function createRangeEventAsManager(page: Page, args: { dateOffsetDays: number; locationName: string }): Promise<{ eventId: string; date: string }> {
  const eventDate = isoDateAtOffset(args.dateOffsetDays);
  await page.goto("/ranges");
  await expect(page.getByTestId("ranges-page")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("create-event-button").click();
  const form = page.getByTestId("create-event-form");
  await expect(form).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("new-range-location").click();
  await page.locator('[role="listbox"]:visible [role="option"] button').filter({ hasText: args.locationName }).click();
  await page.getByTestId("new-date").fill(eventDate);
  await page.getByTestId("new-required-count").fill("1");
  await page.getByTestId("new-reserve-count").fill("1");
  const create = page.waitForResponse(r => r.url().endsWith("/api/ranges") && r.request().method() === "POST");
  await form.getByRole("button", { name: "שמור", exact: true }).click();
  const response = await create;
  expect(response.status()).toBe(201);
  const body = await response.json() as { id: string };
  await expect(form).toBeHidden({ timeout: 30_000 });
  return { eventId: body.id, date: eventDate };
}

/** Assigns one primary and one reserve candidate by personal number, via the
 * verified `candidate-checkbox-{soldierId}` / `reserve-candidate-checkbox-{soldierId}`
 * prefixes (see seam-inventory correction above). Matching by personal
 * number (rendered as its own `dir="ltr"` cell) avoids needing the
 * candidate's soldier id up front. */
async function assignPrimaryAndReserve(page: Page, args: { eventId: string; primaryPersonalNumber: string; reservePersonalNumber: string }): Promise<void> {
  await page.goto("/ranges");
  await page.getByTestId(`view-assignments-${args.eventId}`).click();
  await expect(page.getByTestId("save-assignments")).toBeVisible({ timeout: 30_000 });

  const primaryRow = page.locator("tr").filter({ has: page.locator('[data-testid^="candidate-checkbox-"]') }).filter({ hasText: args.primaryPersonalNumber });
  await expect(primaryRow).toBeVisible({ timeout: 30_000 });
  await primaryRow.locator('input[type="checkbox"]').check();

  const reserveRow = page.locator("tr").filter({ has: page.locator('[data-testid^="reserve-candidate-checkbox-"]') }).filter({ hasText: args.reservePersonalNumber });
  await expect(reserveRow).toBeVisible({ timeout: 30_000 });
  await reserveRow.locator('input[type="checkbox"]').check();

  const batch = page.waitForResponse(r => r.url().includes(`/api/ranges/${args.eventId}/assignments/batch`) && r.request().method() === "POST");
  await page.getByTestId("save-assignments").click();
  const batchResult = await batch;
  expect(batchResult.status()).toBe(200);
}

/** Locates the seed's single past laser-range event by its known date
 * (today - 14 days, see seed.py ~line 1692) via the `/ranges` list network
 * response, rather than clicking through the table — avoids depending on any
 * particular sort/filter UI state to reach it. Only safe against a freshly
 * `--clear`-reseeded DB: repeated non-reseeded local runs could accumulate
 * more than one event on this date, which the brief explicitly flags as a
 * known limitation of this approach. */
async function findPastRangeEventId(page: Page, args: { date: string }): Promise<string> {
  const listResponse = page.waitForResponse(r => /\/api\/ranges\?node_id=/.test(r.url()) && r.request().method() === "GET");
  await page.goto("/ranges");
  const response = await listResponse;
  const events = await response.json() as Array<{ id: string; date: string }>;
  const matches = events.filter(e => e.date === args.date);
  expect(matches.length).toBeGreaterThanOrEqual(1);
  return matches[0].id;
}

/** Marks one assignment present (from the seeded reserve slot, still
 * "pending") and one no_show with a required note (a correction on an
 * already-"present" seeded assignment) on the past event, then saves both in
 * one batch. Returns the two assignment ids and the note text so the caller
 * can assert persistence after a refresh. */
async function markPastAttendance(page: Page, args: { eventId: string }): Promise<{ presentAssignmentId: string; noShowAssignmentId: string; noteText: string }> {
  await page.goto(`/ranges?event=${args.eventId}`);
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 30_000 });
  const roster = page.getByTestId("range-detail-roster");
  const presentButtons = roster.locator('[data-testid^="present-"]');
  const noShowButtons = roster.locator('[data-testid^="no-show-"]');
  await expect(presentButtons.first()).toBeVisible({ timeout: 30_000 });
  const total = await presentButtons.count();
  expect(total).toBeGreaterThanOrEqual(2);

  // Last present-button = the seeded reserve slot (still "pending" — a clean
  // present mark). First = the first seeded primary slot (already "present"
  // — an explicit correction to "no_show", which requires a note either way).
  const presentAssignmentId = (await presentButtons.last().getAttribute("data-testid"))!.replace("present-", "");
  const noShowAssignmentId = (await noShowButtons.first().getAttribute("data-testid"))!.replace("no-show-", "");

  await page.getByTestId(`present-${presentAssignmentId}`).click();
  await page.getByTestId(`no-show-${noShowAssignmentId}`).click();
  const noteText = `סימון E2E ${Date.now()}`;
  await page.getByTestId(`note-${noShowAssignmentId}`).fill(noteText);

  const patchPresent = page.waitForResponse(r => r.url().includes(`/assignments/${presentAssignmentId}/attendance`) && r.request().method() === "PATCH");
  const patchNoShow = page.waitForResponse(r => r.url().includes(`/assignments/${noShowAssignmentId}/attendance`) && r.request().method() === "PATCH");
  await page.getByTestId("attendance-save-button").click();
  const [presentResult, noShowResult] = await Promise.all([patchPresent, patchNoShow]);
  expect(presentResult.status()).toBe(200);
  expect(noShowResult.status()).toBe(200);

  return { presentAssignmentId, noShowAssignmentId, noteText };
}

async function assertAttendancePersisted(page: Page, args: { eventId: string; presentAssignmentId: string; noShowAssignmentId: string; noteText: string }): Promise<void> {
  await page.goto(`/ranges?event=${args.eventId}`);
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 30_000 });
  const presentRow = page.locator(`[data-testid="present-${args.presentAssignmentId}"]`).locator("xpath=ancestor::div[contains(@class,'rounded border p-2')][1]");
  await expect(presentRow).toContainText("נכח", { timeout: 30_000 });
  const noShowRow = page.locator(`[data-testid="no-show-${args.noShowAssignmentId}"]`).locator("xpath=ancestor::div[contains(@class,'rounded border p-2')][1]");
  await expect(noShowRow).toContainText("לא נכח", { timeout: 30_000 });
  await expect(noShowRow).toContainText(args.noteText);
}

/** commander (the new event's primary — see seam-inventory correction on why
 * a plain soldier can't reach this UI path) submits a self-excusal. Returns
 * the created excusal request id. */
async function submitSelfExcusal(page: Page, args: { eventId: string; reason: string }): Promise<string> {
  await page.goto(`/ranges?event=${args.eventId}`);
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 30_000 });
  const action = page.getByTestId("range-self-excusal-action");
  await expect(action).toBeVisible({ timeout: 30_000 });
  await action.getByRole("button", { name: "אני לא אוכל להגיע", exact: true }).click();
  await page.getByLabel("סיבת היעדרות", { exact: true }).fill(args.reason);
  const excuse = page.waitForResponse(r => /\/api\/ranges\/[^/]+\/assignments\/[^/]+\/excuse$/.test(r.url()) && r.request().method() === "POST");
  await page.getByTestId("submit-excuse-button").click();
  const response = await excuse;
  expect(response.status()).toBe(200);
  const body = await response.json() as { id: string };
  return body.id;
}

async function approveExcusal(page: Page, args: { eventId: string; requestId: string }): Promise<void> {
  await page.goto(`/ranges?event=${args.eventId}`);
  const queue = page.getByTestId("excusal-review-queue");
  await expect(queue).toBeVisible({ timeout: 30_000 });
  const decide = page.waitForResponse(r => r.url().includes(`/excusal-requests/${args.requestId}/decide`) && r.request().method() === "POST");
  await page.getByTestId(`approve-excusal-${args.requestId}`).click();
  const decideResult = await decide;
  expect(decideResult.status()).toBe(200);
}

async function assertIneligibleWarningForTeamMars(page: Page): Promise<void> {
  await page.goto("/ranges?tab=ineligible");
  await expect(page.getByTestId("ineligible-soldiers-view")).toBeVisible({ timeout: 30_000 });
  const table = page.getByTestId("ineligible-soldiers-table");
  await table.getByPlaceholder("סינון יחידות...").fill("מארס");
  const expandButton = table.getByRole("button", { name: "הרחב" });
  await expect(expandButton).toBeVisible({ timeout: 30_000 });
  await expandButton.click();
  const warning = page.locator('[data-testid^="ineligible-warning-"]');
  await expect(warning.first()).toBeVisible({ timeout: 30_000 });
}

test.describe.configure({ mode: "serial" });

test("range scheduling, assignment, attendance, excusal, and qualification journey @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  try {
    // Step 3: create event, assign primary (commander) + reserve (assignedGimelim).
    const event = await createRangeEventAsManager(dutyManager.page, {
      dateOffsetDays: rangesBaseOffset, locationName: "מטווח דרום",
    });
    await assignPrimaryAndReserve(dutyManager.page, {
      eventId: event.eventId, primaryPersonalNumber: "2000001", reservePersonalNumber: "1000010",
    });

    // Step 4: mark attendance on the seeded past event.
    const pastEventDate = isoDateAtOffset(-14);
    const pastEventId = await findPastRangeEventId(dutyManager.page, { date: pastEventDate });
    const attendance = await markPastAttendance(dutyManager.page, { eventId: pastEventId });
    await assertAttendancePersisted(dutyManager.page, { eventId: pastEventId, ...attendance });

    // Step 5: excusal request (commander, the new event's primary) + DM decision.
    const excusalReason = `לא אוכל להגיע E2E ${Date.now()}`;
    const requestId = await submitSelfExcusal(commander.page, { eventId: event.eventId, reason: excusalReason });
    await approveExcusal(dutyManager.page, { eventId: event.eventId, requestId });

    // Refresh and assert the real, visible effect of approval (see
    // seam-inventory correction: there is no "approved" badge — the
    // assignment is deleted and the reserve is promoted).
    await commander.page.goto(`/ranges?event=${event.eventId}`);
    await expect(commander.page.getByRole("dialog")).toBeVisible({ timeout: 30_000 });
    await expect(commander.page.getByTestId("range-self-excusal-action")).toHaveCount(0);

    await dutyManager.page.goto(`/ranges?event=${event.eventId}`);
    await expect(dutyManager.page.getByRole("dialog")).toBeVisible({ timeout: 30_000 });
    const roster = dutyManager.page.getByTestId("range-detail-roster");
    await expect(roster).toContainText("ראשיים (1/1)");
    await expect(roster).toContainText("רזרבה (0/1)");
    await expect(dutyManager.page.getByTestId("excusal-review-queue")).toHaveCount(0);

    // Step 6: qualification/eligibility view.
    await assertIneligibleWarningForTeamMars(dutyManager.page);
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
    ]);
  }
});
