import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { journeyActorStorageState, roleStorageState, type Role, type JourneyActor as AuthJourneyActor } from "../fixtures/auth";

/**
 * Task 1 UI seam inventory (every control/endpoint this spec drives, plus
 * corrections to the plan's brief made after reading the real
 * components/services, and one after driving the live app and reading the
 * network — not guesses):
 *
 * - Entry point A (marketplace): `SwapsPage` "mine" tab (`?tab=mine`) lists a
 *   soldier's own upcoming duties with a "בקש החלפה" (swaps.ask_swap) button
 *   -> `AskSwapModal` -> checkbox `ask-swap-marketplace-checkbox` -> submit
 *   "שמור" -> `POST /api/me/swaps` (open_to_marketplace=true). The board tab
 *   (`?tab=board`) lists open marketplace posts with an "אני מחליף"
 *   (swaps.cover) button per card -> `CoverOfferModal` -> radio
 *   "כסה בחינם..." (free, default) or "הצע שיבוץ בתמורה" (trade) -> submit
 *   "שלח הצעה" -> `POST /api/swaps/{id}/offer`.
 * - Entry point B (shift-modal claim, described in the brief but NOT
 *   exercised by this spec — confirmed unreachable for a plain soldier, see
 *   CORRECTION below): `/unit-calendar` -> click an event -> `ShiftDetailPanel`.
 *   When the primary/reserve row underneath already has an *open* swap on
 *   it, an orange banner is *meant* to show the same "אני מחליף" button,
 *   opening the identical `CoverOfferModal`.
 * - CORRECTION (found live while driving this exact flow as a covering
 *   soldier — a real 403 in the network log, not inferred from reading the
 *   route alone): the orange banner never renders for a regular soldier.
 *   `ShiftDetailPanel` populates it from `GET /swaps/for-assignment/{id}`
 *   (`listSwapsForAssignment`), and that route 403s unless the caller is
 *   the assignment's owner or holds `Action.SWAP_APPROVE`
 *   (commander/duty-manager only — see `backend/app/routes/swaps.py`'s
 *   `list_swaps_for_assignment`). `ShiftDetailPanel` swallows the 403
 *   (`.catch(() => ({id, swaps: []}))`), so a covering soldier looking at
 *   someone else's duty just silently never sees the banner or its button —
 *   Entry Point B has no working UI path for the actor the brief describes
 *   using it. This does not affect Entry Point C (`offer_replace`) below,
 *   which is gated by the separate, unrestricted `cover-eligibility` check
 *   instead — confirmed by that button working correctly in Steps 3 and 4.
 *   `claimFromBoardTrade`'s doc comment repeats this note where the
 *   "board claim with a trade counter-offer" test uses Entry Point A
 *   instead to reach the identical `CoverOfferModal` in trade mode.
 * - Entry point C (proactive offer/take): `ShiftDetailPanel`, next to any
 *   assignee who isn't the viewer and has no open swap yet, shows "הצע
 *   החלפה" (swaps.offer_replace) -> `OfferSwapModal`, mode toggle
 *   `"swap" | "free"` (radios "הצע תורנות שלי בתמורה" / "קח תורנות זו
 *   בחינם", no testids). `mode=free` -> `POST /api/swaps/take-free`
 *   (confirmed reachable through the UI — a prior draft of this brief
 *   incorrectly said take-free has no UI call site; `OfferSwapModal`'s free
 *   radio is that call site). Server-side (`swaps.py::take_free`) this still
 *   creates a `SwapRequest` owned by the *original* duty owner with the
 *   acting soldier as an already-accepted `SwapCandidate` — a
 *   `swap_offer` notification goes to the original owner and the same
 *   soldier-then-manager approval pipeline as every other swap applies; it
 *   is NOT instant. `mode=swap` -> `POST /api/me/swaps` with the acting
 *   soldier's own duty and `target_soldier_id` = the soldier being viewed
 *   (server enforces the requester owns the duty offered) — the acting
 *   soldier proactively offers *their own* duty to that specific target; it
 *   is never created "on behalf of" the target and never auto-swaps the
 *   target's own duty back.
 * - CORRECTION (found while implementing, verified by reading
 *   `_apply_cover`/`cover_offer`/`take_free` in `backend/app/services/swaps.py`
 *   end to end): `CoverOfferModal`'s "trade" mode is NOT a reciprocal
 *   two-duty swap. `offered_assignment_ids` is stored on the `SwapCandidate`
 *   row purely as informational metadata (and the frontend never even
 *   displays it back anywhere) — `_apply_cover` only ever overrides the
 *   *original* swap's `duty_assignment_id` to the winning candidate; the
 *   candidate's own offered duty is never reassigned to anyone. So trade
 *   mode is functionally identical to free mode (one duty moves, to the
 *   covering soldier) plus a write-only counter-offer note. This spec tests
 *   trade mode as exactly that — asserting only the original duty moves,
 *   and the covering soldier's own offered duty stays theirs — rather than
 *   asserting a second transfer that the backend does not perform.
 * - CORRECTION (found while implementing, verified by reading
 *   `SwapsPage.tsx`/`ApprovalsPage.tsx`): manager approval is NOT on
 *   `/swaps?tab=pending` — that tab's `PendingApprovalCard` is read-only
 *   status display with no approve/reject controls. The real manager
 *   approve/reject buttons ("אשר"/"דחה", `approvals.approve`/
 *   `approvals.reject`) live on `/approvals?tab=swaps`
 *   (`approvals-tab-swaps`), one visible button per (side, approver_kind)
 *   the logged-in commander/duty-manager actually qualifies for -> `POST
 *   /swaps/{id}/manager-approve` (body `{side, candidate_id?}`).
 * - Soldier-side accept: `SwapsPage` "mine" tab (`MySwapCard`, for a
 *   requester reacting to a candidate) and "incoming" tab (`renderIncomingCard`,
 *   for an invited candidate reacting to a request) both use
 *   "אשר"/"דחה" (approvals.approve/reject) -> `POST
 *   /api/me/swaps/{id}/approve` / `/reject`.
 * - Notifications: bell `notification-bell`, dropdown `notification-dropdown`,
 *   items are untested plain buttons (no testid) that call
 *   `getNotificationLink` on click. `swap_offer`/`swap_offer_incoming`
 *   notifications route to `/swaps?tab=incoming` regardless of whether the
 *   recipient is actually an invited candidate there (`GET /swaps/incoming`
 *   only returns requests where the viewer holds a *pending invited*
 *   `SwapCandidate` row) — so clicking a `swap_offer` notification as the
 *   *requester* (e.g. after a marketplace claim) navigates to
 *   `/swaps?tab=incoming` but the swap does NOT appear there (it's the
 *   requester's own request, visible on "mine" instead). This spec asserts
 *   that real (if slightly surprising) behaviour for the marketplace-claim
 *   case, and asserts the full "row actually visible at the destination"
 *   claim only for the one case where the notified party truly is an
 *   invited candidate: Entry Point C's `mode=swap` notifying the target
 *   soldier with `swap_offer_incoming`.
 */

type JourneyActor =
  | "dutyManager"
  | "commander"
  | "swapRequesterA"
  | "swapCoveringA"
  | "swapRequesterB"
  | "swapCoveringB"
  | "assignedExemption"
  | "assignedGimelim";

const actorStorageRole: Record<JourneyActor, Role> = {
  dutyManager: "dutyManager",
  commander: "commander",
  swapRequesterA: "soldier",
  swapCoveringA: "soldier",
  swapRequesterB: "soldier",
  swapCoveringB: "soldier",
  assignedExemption: "soldier",
  assignedGimelim: "soldier",
};

const journeyStorageActor: Partial<Record<JourneyActor, AuthJourneyActor>> = {
  swapRequesterA: "swapRequesterA",
  swapCoveringA: "swapCoveringA",
  swapRequesterB: "swapRequesterB",
  swapCoveringB: "swapCoveringB",
  assignedExemption: "assignedExemption",
  assignedGimelim: "assignedGimelim",
};

type RoleContext = { context: BrowserContext; page: Page };

// Far enough ahead to clear seed.py's own generated shifts (at most 8 weeks
// out — see seed.py's `for w in range(8)` shift-generation loops) without
// needing the huge multi-year offsets other specs use to survive
// non-reseeded local reruns; this spec's own run procedure always reseeds
// with --clear first, so a modest offset is enough and keeps calendar
// month-by-month navigation cheap.
const swapsBaseOffset = 130 + Math.floor(Math.random() * 20);

function isoDateAtOffset(days: number): string {
  return new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
}
function nextDay(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}
function previousDay(date: string): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - 1);
  return value.toISOString().slice(0, 10);
}
// Matches frontend/src/utils/formatDate.ts#formatDate — the display form a
// single-day duty shows on /my-duties ("DD.MM.YYYY").
function displayDate(date: string): string {
  const [year, month, day] = date.split("-");
  return `${day}.${month}.${year}`;
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

/** dutyManager creates a single-primary, no-reserve shift and manually
 * assigns exactly one soldier to it. Returns enough to find it again by
 * unique location text and to compute its /my-duties display date. */
async function assignSingleDuty(
  page: Page,
  args: { personalNumber: string; dateOffsetDays: number; label: string },
): Promise<{ shiftId: string; dutyDate: string; locationName: string }> {
  const dutyDate = isoDateAtOffset(args.dateOffsetDays);
  const endDate = nextDay(dutyDate);
  const locationName = `${args.label} ${Date.now()}`;

  await page.goto("/planning/shifts");
  await expect(page.getByTestId("shifts-page")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("shift-create-button").click();
  const createForm = page.getByTestId("shift-create-form");
  await createForm.getByRole("combobox").nth(0).click();
  await expect(page.locator('[role="listbox"]:visible [role="option"] button').first()).toBeVisible();
  await page.locator('[role="listbox"]:visible [role="option"] button').first().click();
  await createForm.getByRole("button", { name: /מיקום חדש/ }).click();
  await page.getByTestId("location-create-name").fill(locationName);
  const locationCreate = page.waitForResponse(r => r.url().includes("/api/duty-config/locations") && r.request().method() === "POST");
  await page.getByTestId("location-create-submit").click();
  expect((await locationCreate).status()).toBe(201);
  await expect(page.getByTestId("location-create-name")).toBeHidden({ timeout: 30_000 });
  await page.getByTestId("shift-start-date").fill(dutyDate);
  await page.getByTestId("shift-end-date").fill(endDate);
  await page.getByRole("spinbutton").nth(0).fill("1");
  await page.getByRole("spinbutton").nth(1).fill("0");
  const shiftCreate = page.waitForResponse(r => r.url().includes("/api/shifts") && r.request().method() === "POST");
  await page.getByTestId("shift-create-submit").click();
  const shiftResponse = await shiftCreate;
  let shiftId: string = (await shiftResponse.json()).id;
  await page.getByTestId("shift-filter-from").fill(previousDay(dutyDate));
  const checkbox = page.getByTestId(`shift-row-checkbox-${shiftId}`);
  await expect(checkbox).toBeVisible({ timeout: 30_000 });
  shiftId = (await checkbox.getAttribute("data-testid"))!.replace("shift-row-checkbox-", "");

  await page.getByTestId(`manual-assignment-open-${shiftId}`).click();
  const modal = page.getByTestId(`manual-assignment-modal-${shiftId}`);
  await expect(modal).toBeVisible();
  await expect(page.getByTestId("manual-add-primary")).toBeVisible({ timeout: 30_000 });
  const primaryCandidates = modal.locator('[data-testid^="manual-primary-candidate-"] input:not(:checked)');
  if (!(await primaryCandidates.first().isVisible().catch(() => false))) {
    await page.getByTestId("manual-add-primary").click();
  }
  const candidate = modal.locator('[data-testid^="manual-primary-candidate-"]').filter({ hasText: args.personalNumber }).locator('input:not(:checked)').first();
  await expect(candidate).toBeVisible({ timeout: 30_000 });
  await candidate.check();
  const batchAssign = page.waitForResponse(r => r.url().includes(`/api/shifts/${shiftId}/assign-batch`) && r.request().method() === "POST");
  await page.getByTestId("manual-assignment-save").click();
  const batchResult = await batchAssign;
  expect(batchResult.status()).toBe(201);
  await expect(modal).toBeHidden();

  return { shiftId, dutyDate, locationName };
}

/** Entry point A (marketplace ask): "mine" tab -> AskSwapModal ->
 * marketplace checkbox -> save. The "mine" tab's own-upcoming-duties list
 * (unlike its swap-request cards below it) renders only `duty_type_name`
 * plus the duty's raw ISO date range — no location text — so the row is
 * matched by the duty's ISO start date instead. Returns nothing; the
 * resulting SwapRequest is discoverable afterwards via its unique duty
 * location text (SwapDutyHeader, used by every swap-request card). */
async function createMarketplaceAsk(page: Page, args: { dutyIsoDate: string }): Promise<void> {
  await page.goto("/swaps?tab=mine");
  const row = page.locator("li").filter({ hasText: args.dutyIsoDate });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "בקש החלפה", exact: true }).click();
  await page.getByTestId("ask-swap-marketplace-checkbox").check();
  const create = page.waitForResponse(r => r.url().includes("/api/me/swaps") && r.request().method() === "POST");
  await page.getByRole("button", { name: "שמור", exact: true }).click();
  expect((await create).status()).toBe(201);
}

/** Entry point A/B claim, free mode (default radio): board tab or
 * ShiftDetailPanel's "אני מחליף" banner both open the same CoverOfferModal. */
async function claimFromBoard(page: Page, args: { locationName: string }): Promise<void> {
  await page.goto("/swaps?tab=board");
  const card = page.locator("li").filter({ hasText: args.locationName });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByRole("button", { name: "אני מחליף", exact: true }).click();
  const offer = page.waitForResponse(r => /\/api\/swaps\/[^/]+\/offer$/.test(r.url()) && r.request().method() === "POST");
  await page.getByRole("button", { name: "שלח הצעה", exact: true }).click();
  expect((await offer).status()).toBe(200);
}

/** Navigates /unit-calendar and opens the given shift's ShiftDetailPanel by
 * clicking forward through months until the event (identified by its
 * unique location text) is visible. Mirrors the established
 * multi_user_duty_problems.spec.ts technique. */
async function openShiftViaCalendar(page: Page, args: { locationName: string }): Promise<void> {
  await page.goto("/unit-calendar");
  const shiftEvent = page.locator(".fc-event").filter({ hasText: args.locationName }).last();
  for (let month = 0; month < 12 && !(await shiftEvent.isVisible().catch(() => false)); month += 1) {
    await page.locator(".fc-next-button").click();
    await page.waitForTimeout(500);
  }
  await expect(shiftEvent).toBeVisible({ timeout: 30_000 });
  await shiftEvent.click();
  await expect(page.getByRole("dialog").filter({ hasText: args.locationName })).toBeVisible({ timeout: 30_000 });
}

/** Board-tab claim in trade mode: same CoverOfferModal as the free-cover
 * flow, offering one of the covering soldier's own duties (matched by its
 * unique ISO start date, since CoverOfferModal's checkbox labels use the
 * raw EffectiveDuty.start_date, not the display-formatted date).
 *
 * NOTE this is Entry Point A (board), not Entry Point B (shift-modal) —
 * see the seam-inventory correction at the top of this file: Entry Point B
 * is not actually reachable by a plain soldier. `GET
 * /swaps/for-assignment/{id}` (the call `ShiftDetailPanel` makes to decide
 * whether to render the orange "open swap" banner with the "אני מחליף"
 * button) 403s for anyone who isn't the assignment owner or a
 * commander/duty-manager (`Action.SWAP_APPROVE`) — confirmed directly via a
 * live network 403 while driving this exact flow as a covering soldier, not
 * inferred from reading the route alone. `ShiftDetailPanel` swallows that
 * 403 (`.catch(() => ({id, swaps: []}))`), so the banner — and therefore
 * the only UI path into Entry Point B for a regular soldier — silently
 * never renders. This does not affect Entry Point C (`offer_replace`),
 * which is gated by the separate, unrestricted `cover-eligibility` check
 * instead. */
async function claimFromBoardTrade(page: Page, args: { locationName: string; ownDutyIsoDate: string }): Promise<void> {
  await page.goto("/swaps?tab=board");
  const card = page.locator("li").filter({ hasText: args.locationName });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByRole("button", { name: "אני מחליף", exact: true }).click();
  await page.getByLabel("הצע שיבוץ בתמורה", { exact: true }).check();
  const dutyCheckbox = page.locator("label").filter({ hasText: args.ownDutyIsoDate }).locator('input[type="checkbox"]');
  await expect(dutyCheckbox).toBeVisible({ timeout: 30_000 });
  await dutyCheckbox.check();
  const offer = page.waitForResponse(r => /\/api\/swaps\/[^/]+\/offer$/.test(r.url()) && r.request().method() === "POST");
  await page.getByRole("button", { name: "שלח הצעה", exact: true }).click();
  const offerResponse = await offer;
  expect(offerResponse.status()).toBe(200);
  const body = offerResponse.request().postDataJSON() as { offered_assignment_ids: string[] };
  expect(body.offered_assignment_ids.length).toBe(1);
}

/** Entry point C: from an already-open ShiftDetailPanel, click "הצע החלפה"
 * -> OfferSwapModal. Every duty this spec creates has exactly one primary
 * assignee (the target), so the panel has only one such button. */
async function openOfferReplace(page: Page): Promise<void> {
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "הצע החלפה", exact: true }).click();
  await expect(page.getByText("הצע החלפה עם", { exact: false })).toBeVisible({ timeout: 30_000 });
}

async function takeFreeViaOfferReplace(page: Page): Promise<void> {
  await page.getByLabel("קח תורנות זו בחינם", { exact: true }).check();
  const takeFree = page.waitForResponse(r => r.url().includes("/api/swaps/take-free") && r.request().method() === "POST");
  await page.getByRole("button", { name: "שלח הצעה", exact: true }).click();
  expect((await takeFree).status()).toBe(201);
}

async function offerSwapViaOfferReplace(page: Page, args: { ownDutyIsoDate: string }): Promise<void> {
  // mode defaults to "swap" already.
  const dutyRadio = page.locator("label").filter({ hasText: args.ownDutyIsoDate }).locator('input[type="radio"]');
  await expect(dutyRadio).toBeVisible({ timeout: 30_000 });
  await dutyRadio.check();
  const create = page.waitForResponse(r => r.url().includes("/api/me/swaps") && r.request().method() === "POST");
  await page.getByRole("button", { name: "שלח הצעה", exact: true }).click();
  expect((await create).status()).toBe(201);
}

/** Soldier-side approve as the swap's requester ("mine" tab). */
async function approveAsRequester(page: Page, args: { locationName: string }): Promise<void> {
  await page.goto("/swaps?tab=mine");
  const row = page.locator("li").filter({ hasText: args.locationName });
  await expect(row).toBeVisible({ timeout: 30_000 });
  const approve = page.waitForResponse(r => /\/api\/me\/swaps\/[^/]+\/approve$/.test(r.url()) && r.request().method() === "POST");
  await row.getByRole("button", { name: "אשר", exact: true }).click();
  expect((await approve).status()).toBe(200);
}

/** Soldier-side approve as an invited candidate ("incoming" tab). Returns
 * the URL the page was on right before navigating away, for notification
 * click-through tests that want to drive this via the bell instead. */
async function approveAsCandidate(page: Page, args: { locationName: string }): Promise<void> {
  await page.goto("/swaps?tab=incoming");
  const row = page.locator("li").filter({ hasText: args.locationName });
  await expect(row).toBeVisible({ timeout: 30_000 });
  const approve = page.waitForResponse(r => /\/api\/me\/swaps\/[^/]+\/approve$/.test(r.url()) && r.request().method() === "POST");
  await row.getByRole("button", { name: "אשר", exact: true }).click();
  expect((await approve).status()).toBe(200);
}

/** Clicks every visible manager-approve ("אשר") button inside the swap card
 * matching `locationName` on /approvals?tab=swaps, looping until none
 * remain. A given logged-in commander/duty-manager only ever sees the
 * button(s) for the (side, approver_kind) rows they personally qualify for
 * (SwapKindApproval's canAct gate), so this naturally exercises "commander
 * approves their rows" and "duty manager approves their rows" as two
 * independent calls without needing to know the swap's config up front.
 *
 * Reloads the page (`page.goto`) before every single click rather than
 * reusing one live locator across clicks: approving one row invalidates
 * and refetches the pending-swaps query, and clicking into that live
 * re-render raced Playwright's actionability wait badly enough to hang
 * the whole test (observed directly — "element was detached from the DOM,
 * retrying" looping for the full 600s test timeout on the very first
 * click). A fresh navigation before each click removes that race
 * entirely: every click lands on a static, already-settled DOM. */
async function approveAllVisibleManagerRows(page: Page, args: { locationName: string }): Promise<void> {
  for (let guard = 0; guard < 6; guard += 1) {
    await page.goto("/approvals?tab=swaps");
    const header = page.locator("p.font-medium").filter({ hasText: args.locationName }).first();
    // Actively wait (poll) for the card to load rather than an instant
    // `.count()` check — the pending-swaps query is still in flight right
    // after navigation, and an instant count of 0 there doesn't mean "no
    // more approvals needed", it means "hasn't loaded yet" (this bit a
    // prior version of this helper: it silently no-opped on every call,
    // leaving zero manager approvals recorded, confirmed directly against
    // the DB). A real "nothing left to approve" case (this actor already
    // cleared every row they qualify for) still resolves this the same
    // way once the list settles: the card just won't be there.
    const found = await header.waitFor({ state: "visible", timeout: 15_000 }).then(() => true).catch(() => false);
    if (!found) break;
    const card = header.locator("xpath=ancestor::div[contains(@class,'space-y-2')][1]");
    const approveButtons = card.getByRole("button", { name: "אשר", exact: true });
    if ((await approveButtons.count()) === 0) break;
    const approve = page.waitForResponse(r => /\/api\/swaps\/[^/]+\/manager-approve$/.test(r.url()) && r.request().method() === "POST");
    await approveButtons.first().click();
    expect((await approve).status()).toBe(200);
  }
}

async function assertDutyOwnedBy(page: Page, args: { dutyDate: string }): Promise<void> {
  await page.goto("/my-duties");
  await expect(page.getByTestId("my-diary-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(displayDate(args.dutyDate), { exact: false })).toBeVisible({ timeout: 30_000 });
}

async function assertDutyNotOwnedBy(page: Page, args: { dutyDate: string }): Promise<void> {
  await page.goto("/my-duties");
  await expect(page.getByTestId("my-diary-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(displayDate(args.dutyDate), { exact: false })).toHaveCount(0);
}

test.describe.configure({ mode: "serial" });

test("marketplace claim, free cover, dual-role manager approval, notification click-through @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  const requester = await openActorContext(browser, "swapRequesterA");
  const covering = await openActorContext(browser, "swapCoveringA");
  try {
    const duty = await assignSingleDuty(dutyManager.page, {
      personalNumber: "1000015", dateOffsetDays: swapsBaseOffset, label: "E2E swap marketplace",
    });

    await createMarketplaceAsk(requester.page, { dutyIsoDate: duty.dutyDate });
    await claimFromBoard(covering.page, { locationName: duty.locationName });

    // Notification click-through (requester side): swap_offer fires to the
    // requester on claim. getNotificationLink routes swap_offer to
    // /swaps?tab=incoming regardless of whether the recipient is actually an
    // invited candidate there (see seam-inventory correction above) — assert
    // the click really navigates, without asserting the row shows up on a
    // tab it factually doesn't belong on for this notification type.
    await requester.page.goto("/");
    const bell = requester.page.getByTestId("notification-bell");
    await expect(bell).toBeVisible({ timeout: 30_000 });
    await bell.click();
    const dropdown = requester.page.getByTestId("notification-dropdown");
    await expect(dropdown).toBeVisible();
    const notifItem = dropdown.locator("button.text-sm.font-medium.truncate").first();
    await expect(notifItem).toBeVisible({ timeout: 30_000 });
    await notifItem.click();
    await expect(requester.page).toHaveURL(/\/swaps\?tab=incoming/);
    // The swap actually lives on "mine" for the requester — confirm it's
    // there (and visible to them) rather than asserting the (false) claim
    // that it's on "incoming".
    await requester.page.goto("/swaps?tab=mine");
    await expect(requester.page.locator("li").filter({ hasText: duty.locationName })).toBeVisible({ timeout: 30_000 });

    // No separate soldier-side requester approval here: `cover_offer` (the
    // service behind CoverOfferModal's submit, both free and trade mode)
    // sets `requester_side_approved=True` itself the moment a cover is
    // offered ("asking already implied consent") — MySwapCard's approve
    // button only renders while that flag is still false, so this scenario
    // goes straight to manager approval.

    // Dual-role manager approval, exercised independently: commander clears
    // every commander-kind row they qualify for (both sides), then
    // dutyManager clears every duty-manager-kind row — two separate
    // sessions, two separate (side, approver_kind) dimensions, neither one
    // able to satisfy the other's requirement.
    await approveAllVisibleManagerRows(commander.page, { locationName: duty.locationName });
    await approveAllVisibleManagerRows(dutyManager.page, { locationName: duty.locationName });

    // Ownership actually moved.
    await assertDutyOwnedBy(covering.page, { dutyDate: duty.dutyDate });
    await assertDutyNotOwnedBy(requester.page, { dutyDate: duty.dutyDate });
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
      requester.context.close(),
      covering.context.close(),
    ]);
  }
});

test("board claim with a trade counter-offer @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  const requester = await openActorContext(browser, "swapRequesterB");
  const covering = await openActorContext(browser, "swapCoveringB");
  try {
    const duty = await assignSingleDuty(dutyManager.page, {
      personalNumber: "1000017", dateOffsetDays: swapsBaseOffset + 10, label: "E2E swap trade",
    });
    const ownDuty = await assignSingleDuty(dutyManager.page, {
      personalNumber: "1000018", dateOffsetDays: swapsBaseOffset + 20, label: "E2E swap trade-offer",
    });

    await createMarketplaceAsk(requester.page, { dutyIsoDate: duty.dutyDate });

    // Entry Point B (shift-modal claim via /unit-calendar) is not used here
    // — see claimFromBoardTrade's doc comment for the confirmed reason it's
    // unreachable for a plain soldier. Entry Point A's board tab reaches the
    // identical CoverOfferModal in trade mode instead.
    await claimFromBoardTrade(covering.page, { locationName: duty.locationName, ownDutyIsoDate: ownDuty.dutyDate });

    // No separate soldier-side requester approval here either — same
    // `cover_offer` auto-approval as the free-cover test above.
    await approveAllVisibleManagerRows(commander.page, { locationName: duty.locationName });
    await approveAllVisibleManagerRows(dutyManager.page, { locationName: duty.locationName });

    // Only the original (requested) duty actually changes hands — trade
    // mode's "offered" duty is informational only (see seam-inventory
    // correction). Assert exactly that: `duty` moved to `covering`, and
    // `ownDuty` (the thing "offered" in trade) never left `covering`.
    await assertDutyOwnedBy(covering.page, { dutyDate: duty.dutyDate });
    await assertDutyNotOwnedBy(requester.page, { dutyDate: duty.dutyDate });
    await assertDutyOwnedBy(covering.page, { dutyDate: ownDuty.dutyDate });
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
      requester.context.close(),
      covering.context.close(),
    ]);
  }
});

test("take a duty for free via offer-replace (Entry Point C, take-free) @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  const owner = await openActorContext(browser, "assignedExemption");
  const taker = await openActorContext(browser, "swapRequesterA");
  try {
    const duty = await assignSingleDuty(dutyManager.page, {
      personalNumber: "1000009", dateOffsetDays: swapsBaseOffset + 30, label: "E2E swap take-free",
    });

    await openShiftViaCalendar(taker.page, { locationName: duty.locationName });
    await openOfferReplace(taker.page);
    await takeFreeViaOfferReplace(taker.page);

    await approveAsRequester(owner.page, { locationName: duty.locationName });
    await approveAllVisibleManagerRows(commander.page, { locationName: duty.locationName });
    await approveAllVisibleManagerRows(dutyManager.page, { locationName: duty.locationName });

    await assertDutyOwnedBy(taker.page, { dutyDate: duty.dutyDate });
    await assertDutyNotOwnedBy(owner.page, { dutyDate: duty.dutyDate });
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
      owner.context.close(),
      taker.context.close(),
    ]);
  }
});

test("proactively offer own duty via offer-replace (Entry Point C, swap mode) with full notification click-through @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  const target = await openActorContext(browser, "assignedGimelim");
  const actor = await openActorContext(browser, "swapCoveringA");
  try {
    const targetDuty = await assignSingleDuty(dutyManager.page, {
      personalNumber: "1000010", dateOffsetDays: swapsBaseOffset + 40, label: "E2E swap offer-mode target",
    });
    const ownDuty = await assignSingleDuty(dutyManager.page, {
      personalNumber: "1000016", dateOffsetDays: swapsBaseOffset + 50, label: "E2E swap offer-mode own",
    });

    await openShiftViaCalendar(actor.page, { locationName: targetDuty.locationName });
    await openOfferReplace(actor.page);
    await offerSwapViaOfferReplace(actor.page, { ownDutyIsoDate: ownDuty.dutyDate });

    // Full notification click-through: the target soldier is a genuine
    // invited SwapCandidate here (swap_offer_incoming), so /swaps?tab=incoming
    // really does show the row after navigating there via the notification.
    // Note the swap's own duty is `ownDuty` (the acting soldier's duty being
    // offered) — Entry Point C's swap mode never makes `targetDuty` itself
    // part of the request, so every swap-card lookup below matches on
    // `ownDuty.locationName`, not `targetDuty.locationName`.
    await target.page.goto("/");
    const bell = target.page.getByTestId("notification-bell");
    await expect(bell).toBeVisible({ timeout: 30_000 });
    await bell.click();
    const dropdown = target.page.getByTestId("notification-dropdown");
    await expect(dropdown).toBeVisible();
    const notifItem = dropdown.locator("button.text-sm.font-medium.truncate").first();
    await expect(notifItem).toBeVisible({ timeout: 30_000 });
    await notifItem.click();
    await expect(target.page).toHaveURL(/\/swaps\?tab=incoming/);
    await expect(target.page.locator("li").filter({ hasText: ownDuty.locationName })).toBeVisible({ timeout: 30_000 });

    await approveAsCandidate(target.page, { locationName: ownDuty.locationName });
    await approveAllVisibleManagerRows(commander.page, { locationName: ownDuty.locationName });
    await approveAllVisibleManagerRows(dutyManager.page, { locationName: ownDuty.locationName });

    // The acting soldier's own duty (offered in swap mode) now belongs to
    // the target — ownership moved as the acting soldier proposed.
    await assertDutyOwnedBy(target.page, { dutyDate: ownDuty.dutyDate });
    await assertDutyNotOwnedBy(actor.page, { dutyDate: ownDuty.dutyDate });
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
      target.context.close(),
      actor.context.close(),
    ]);
  }
});
