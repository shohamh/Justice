import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { journeyActors, journeyActorStorageState, roleStorageState, type Role } from "../fixtures/auth";

/**
 * Seam inventory (read-only; every mutation below is driven through one of
 * these controls, never page.request/fetch/database setup — page.request is
 * used exactly once, in the CP-SAT test, purely to *read* the same
 * export-inputs endpoint the UI's own "ייצוא קלטי ופלטי solver" button calls,
 * as an anti-vacuousness safeguard, per Global Constraints):
 *
 * - Constraint submit/approve: soldier submits at /my-requests
 *   (constraint-form-toggle -> constraint-form-card, fields req-start/
 *   req-end/req-reason/req-submit) -> POST /api/me/constraints. Two-stage
 *   approval at /approvals?tab=constraints ([data-testid^="approval-row-"],
 *   stage text at [data-testid^="constraint-stage-"]) -> commander approves
 *   first (approve-<id>), then duty manager (same testid pattern, second
 *   visit) -> POST /api/constraints/<id>/approve each time. Status only
 *   becomes "approved" after both stages; verified back via /my-requests
 *   (tab=existing)'s green "אושר" badge (my_requests.approved, MyRequestsPage
 *   statusBadge()) — not just the two 2xx responses.
 *
 * - Duty manual override via ShiftAssignModal's "Replace" flow — its
 *   PRECONDITION (a real weapon_ineligible=true original assignee) is now
 *   REAL and proven reachable below, closing that half of task_af3d0c50 (see
 *   "Weapon-ineligibility precondition" below for how it's actually reached).
 *   ShiftDetailPanel (reachable only from /unit-calendar's FullCalendar
 *   events) shows a "החלף" (weapon_ineligible.replace) button next to any
 *   primary assignee with weapon_ineligible=true; clicking it immediately
 *   calls DELETE .../assignments/<id> (removing that assignee) and then opens
 *   ShiftAssignModal against the freshly-refetched shift, with the freed
 *   primary slot and real override-reason UI (OverrideReasonModal) for
 *   selecting a replacement. COMPLETING that override (positive "succeeds
 *   with a reason" / negative "empty reason rejected" pair) is now proven by
 *   the two tests below closing task_bd77e412's remainder. Getting there
 *   required first fixing a real, separate product bug in
 *   useModalBackClose's nested-modal handling: with three levels of nested
 *   modal (ShiftDetailPanel -> ShiftAssignModal -> the weapon-warning
 *   ConfirmDialog it must show first, since PN 1000037's precondition
 *   requires a duty type with required_range_type set, which makes
 *   weapon_warning=true universal for everyone at this file's far-future
 *   dates too), confirming that dialog used to fire TWO history.back() calls,
 *   not one — closing ShiftAssignModal itself (a level the pop should never
 *   have reached) before OverrideReasonModal ever rendered. Root cause:
 *   handlePopState's bail-out only checked "is the current entry mine",
 *   which is only a correct proxy for "the browser genuinely navigated past
 *   me" when nesting is exactly two levels deep — with a third level, a
 *   deeper descendant's own pop can land on some OTHER ancestor's entry,
 *   which the outer modals then misread as "not mine, so I've been popped
 *   past" and close. Fixed in useModalBackClose.ts by tracking each modal's
 *   actual parent entry id (captured at push time) and only closing when the
 *   popped-to state matches that captured parent, not merely whenever it
 *   isn't the modal's own id. See useModalBackClose.test.tsx's "three-level
 *   nesting" describe block for the isolated regression test.
 *
 * - Duty manual override via the standard bulk ShiftEditAssignmentsModal
 *   (opened via [data-testid^="manual-assignment-open-"], the same modal
 *   exercised in multi_user_duty_problems.spec.ts) — FIXED and now proven
 *   end to end by the positive test below, closing half of background task
 *   task_af3d0c50 ("ShiftEditAssignmentsModal has no override UI;
 *   ShiftAssignModal's Replace-flow trigger is unreachable"). Previously this
 *   modal had NO override-reason UI at all: a constrained candidate looked
 *   like an ordinary, fully-selectable row (blocked_reason is only set when
 *   the allow_manual_override setting is off, which is not this fixture's
 *   default), and selecting them and clicking "שמור"
 *   ([data-testid="manual-assignment-save"]) called the same assign-batch
 *   endpoint with no override_reason, which the backend
 *   (services/assignments.py's create_assignment) rejected with
 *   AssignmentError("override_reason_required") — surfaced by the route as
 *   409 Conflict, not 400 (routes/shifts.py's assign_batch catches
 *   AssignmentError and re-raises as 409), with no i18n mapping for that
 *   code, so the visible error was the generic "שגיאה בשיבוץ". The fix adds a
 *   ConstraintWarningIcon on any candidate row carrying
 *   personal_constraint_warning and routes a save that includes one through
 *   the same OverrideReasonModal pattern the range flow below already used
 *   (see ShiftEditAssignmentsModal.tsx's handleSave/doSave). The test below
 *   drives this through a real browser: selecting constrainedSoldier,
 *   confirming the warning icon is visible, saving, filling a reason in
 *   OverrideReasonModal, confirming, and checking both the 2xx response
 *   (with override_reason in the request body) and the real post-refresh UI
 *   state (constrainedSoldier showing up as an actual assignee row) — not
 *   just the response. The OTHER half of task_af3d0c50 — ShiftAssignModal's
 *   Replace-flow trigger being unreachable — is unrelated to this fix and
 *   remains a real, separate, still-open gap; see the entry above.
 *
 * - CP-SAT auto-assign — always hard-excludes: backend/app/algorithm/
 *   availability.py's eligibility_blockers() adds "personal_constraint"
 *   unconditionally for any soldier/duty pair whose dates overlap an
 *   approved constraint, regardless of the allow_manual_override setting.
 *   No UI surfaces this per-candidate; verified two ways here: (1) after
 *   publishing, the constrained soldier's name never appears in
 *   [data-testid="algorithm-proposal-review"] (created via createAndRun
 *   AlgorithmDuty, adapted from multi_user_duty_problems.spec.ts's
 *   createAndPublishAlgorithmDuty); (2) as the anti-vacuousness safeguard the
 *   plan calls for, the job's own "⬇ ייצוא קלטי ופלטי solver" button (real
 *   UI control, AlgorithmJobTabs.tsx's handleDownload -> GET
 *   /api/algorithm/jobs/<job>/export-inputs) is clicked and its response
 *   intercepted to confirm the constrained soldier really was in the
 *   solver's loaded soldier pool with approved_constraint_dates overlapping
 *   the duty, before asserting their absence from the published result — so
 *   the absence is attributable to the hard exclusion, not to being out of
 *   scope or never loaded in the first place.
 *   Range-side is the opposite of CP-SAT's: it is a *soft* conflict
 *   (RangeEditAssignmentsModal / range_auto_assign.py's _bulk_eligibility only
 *   hard-excludes a constrained soldier when the constraints.allow_manual_override
 *   system setting is off, which is not this fixture's default) — see the two
 *   range tests below. Manual selection via RangeEditAssignmentsModal's
 *   candidate table shows the same conflict marker (a titled ⚠️ next to the
 *   name, driven by RangeCandidate.conflict_warning) and saving routes through
 *   the same OverrideReasonModal pattern, POSTing /api/ranges/{id}/assignments
 *   /batch with override_reason (services/ranges.py's assign_batch, batched
 *   version of _validate_and_build_assignment, raises RangeValidationError
 *   ("override_reason_required") server-side too if it's missing — so the
 *   client-side gate in saveSelection() is a UX convenience layered on top of
 *   a real server-side requirement, not the only thing enforcing it). Auto-select
 *   (autoSelectPrimary/autoSelectReserve in RangeEditAssignmentsModal.tsx) does
 *   NOT filter by personal_constraint_conflict or auto_selectable at all — unlike
 *   RangeBulkAutoAssignModal's bulk path, it just takes the top
 *   `primarySlotsLeft` of the already-ranked candidate list — so a constrained
 *   soldier who ranks well can end up in the auto-selected set, and saving that
 *   selection then requires the same override-reason gate as a manual pick.
 *   The test below forces this non-vacuously by scoping required_count well
 *   above the whole branch-scoped candidate pool so auto-select's slice takes
 *   every eligible candidate (constrainedSoldier included) rather than relying
 *   on guessing exact rank order.
 *
 * - Weapon-ineligibility precondition — now genuinely reachable, closed by
 *   two separate things: Task 1 (commit 93782971) broadened mitvahim-range
 *   seeding to 115 of 120 soldiers, deliberately leaving PN 1000037 (team
 *   ריי, officer, 5th member) with last_mitvahim_date=NULL as the intended
 *   "weapon-ineligible original assignee"; this file's own setup helper
 *   (`setupWeaponIneligiblePrimaryAndRun` below) supplies the rest.
 *
 *   Two independent structural gates matter here, confirmed by reading
 *   eligibility.py/weapon_eligibility.py directly, not by inspection alone:
 *
 *   (1) A hard, always-on "structural" gate (services/eligibility.py's
 *   `_ineligibility_reason`, reached via `compute_eligibility_exclusions` from
 *   algorithm_bridge.py's `load_soldier_inputs`, which both routes/shifts.py's
 *   candidates endpoint and the CP-SAT solver's hard-exclusion set consume).
 *   It checks a duty type's `requirements` JSON flags — `requires_mitvahim`
 *   (blocks a null/stale `last_mitvahim_date`, using the
 *   `eligibility.mitvahim_months` setting, evaluated against the *duty's own
 *   start_date* — not real-world today) and `officers_allowed`/
 *   `enlisted_allowed` (both unconditional) — completely independently of any
 *   admin toggle. Every SEEDED duty type carrying a required_range_type sets
 *   one of these role flags to False: שמירות/אבט"ש are officers_allowed:False
 *   (would exclude PN 1000037, an officer) while הגנ"ש/קצין תורן/מפקד תורן are
 *   enlisted_allowed:False (would exclude constrainedSoldier, a non-officer).
 *   No seeded duty type leaves both open, so neither actor can ever reach a
 *   seeded weapon duty type as-is.
 *
 *   (2) A separate, cache-producing gate (weapon_eligibility.py's
 *   `compute_eligibility`, gated by the real "אכיפת כשירות נשק לתורנויות" /
 *   weapon_qualification.enforce_eligibility admin setting, default True) that
 *   `services/assignments.py`'s `create_assignment` calls at assignment-creation
 *   time (keyed off `duty_type.required_range_type`, a DB column independent of
 *   the `requirements` JSON) to set `weapon_ineligible`/`weapon_ineligible_reason`
 *   on the new DutyAssignment row — with NO hard block either way; an
 *   ineligible soldier can always be assigned, just flagged.
 *
 *   Since gate (1) is duty-type-scoped and gate (2) is a completely separate
 *   check, the real, live-UI mechanism is: temporarily widen gate (1) for
 *   שמירות only, via the real DutyTypeRequirementsEditor at /planning/config
 *   (dutyManager-reachable, `require_duty_manager_or_admin`) — uncheck
 *   "נדרש מטווחים עדכני" (requires_mitvahim) and check "קצינים מותרים"
 *   (officers_allowed) — leaving `required_range_type` (still "laser") and
 *   the admin enforce-eligibility setting (still True) both untouched. With
 *   gate (1) open, PN 1000037 becomes a normal selectable candidate in the
 *   standard bulk ShiftEditAssignmentsModal; assigning them there hits gate
 *   (2) for real (they still have no last_mitvahim_date at all), so
 *   `create_assignment` sets weapon_ineligible=true on that assignment
 *   immediately — no settings-toggle dance, no algorithm job, no recheck call
 *   needed. `setupWeaponIneligiblePrimary` below does exactly this, then
 *   reverts the two requirements flags in a `finally` once the caller's own
 *   Replace-flow interaction is done (requires_mitvahim has to stay off for
 *   the whole interaction, not just the setup half, because constrainedSoldier's
 *   own last_mitvahim_date — real and current, ~2026-08 — is itself far too
 *   stale relative to this file's deliberately-far-future shift dates to pass
 *   gate (1) at those dates; this is a duty-type-wide setting, not per-shift,
 *   so it cannot be reverted in between). Both actors also carry
 *   weapon_warning=true in this window (same gate-2 staleness applies to
 *   everyone at these dates) — a soft, non-blocking flag that only surfaces a
 *   ConfirmDialog before the constraint-override modal; see the entry above
 *   for the nested-modal history bug that ConfirmDialog used to trigger
 *   (task_bd77e412), now fixed.
 *
 *   The previously-considered algorithm-job route (flip
 *   weapon_qualification.enforce_eligibility off around a job to bypass the
 *   solver's hard exclusion, then back on to trigger recheck_assignments) is
 *   NOT used here and remains genuinely broken for job creation specifically:
 *   routes/algorithm.py's SolverSettingsIn declares
 *   `enforce_weapon_qualification: bool = True` as a hard Pydantic default,
 *   and create_job() persists the fully-resolved request (defaults included)
 *   as job.settings_json, so resolve_solver_settings()'s admin-setting
 *   fallback never triggers for any reachable job-creation path — flagged
 *   separately as background task task_f58fff09 ("Fix
 *   enforce_weapon_qualification admin toggle never reaching solver"), not
 *   needed for this file since the manual bulk-assignment path above never
 *   goes through SolverSettingsIn at all.
 */

type RoleContext = { context: BrowserContext; page: Page };

async function openRoleContext(browser: Browser, role: Role): Promise<RoleContext> {
  const projectUse = test.info().project.use as { baseURL?: string; viewport?: { width: number; height: number } };
  const context = await browser.newContext({
    baseURL: projectUse.baseURL ?? "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: roleStorageState(role),
  });
  return { context, page: await context.newPage() };
}

async function openConstrainedSoldierContext(browser: Browser): Promise<RoleContext> {
  const projectUse = test.info().project.use as { baseURL?: string; viewport?: { width: number; height: number } };
  const context = await browser.newContext({
    baseURL: projectUse.baseURL ?? "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: journeyActorStorageState("constrainedSoldier"),
  });
  return { context, page: await context.newPage() };
}

const CONSTRAINED_SOLDIER_PN = journeyActors.constrainedSoldier;
// Hebrew display name for CONSTRAINED_SOLDIER_PN — not sourced from auth.ts
// (which only stores personal numbers), but derived from seed.py's
// `_team_profiles`/`f"{short} {i+1}"` naming convention for this actor's team
// and index. If seed.py's naming scheme or team assignment for this actor
// ever changes, this literal will need to be updated by hand.
const CONSTRAINED_SOLDIER_NAME = "ריי 4";
const TEAM_NODE_NAME = "צוות ריי";

// Keep this journey's dates far outside the seeded/other-spec horizon, like
// multi_user_duty_problems.spec.ts, but in a distinct offset band so a
// whole-suite run never collides with that spec's 1500-1600 window.
//
// NOTE: this spec also requires a fresh reseed between runs (not just fresh
// dates) — submit_constraint's cap-period check (backend constraints.py,
// computed from start_date) means two runs whose randomly-offset 14-day
// windows happen to land in the same quarter will make the second run's
// setup test fail with a confusing cap-exceeded error. Always reseed the DB
// before re-running this spec against the same database.
const constraintBaseOffset = 1650 + Math.floor(Math.random() * 50);

function isoDate(offsetDays: number): string {
  return new Date(Date.now() + offsetDays * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
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

// The constraint window covers every shift date below (constraintStart ..
// constraintStart+13) while staying under the 15-day personal_cap_days quarterly
// cap even in the worst case (the whole window falling inside a single quarter).
const constraintStart = isoDate(constraintBaseOffset);
const constraintEnd = isoDate(constraintBaseOffset + 13);

// PN 1000037 — Task 1's (commit 93782971) deliberately mitvahim-unqualified
// soldier, team ריי (same team as constrainedSoldier), officer, kept
// last_mitvahim_date=NULL on purpose so it can serve as the weapon-ineligible
// original assignee the Replace-flow tests below need.
const WEAPON_INELIGIBLE_PN = "1000037";

const replaceSetupStart = isoDate(constraintBaseOffset + 3);
const replaceSetupEnd = nextDay(replaceSetupStart);
const replaceSetupLocation = `E2E replace setup ${Date.now()}`;

const replaceNegativeStart = isoDate(constraintBaseOffset + 13);
const replaceNegativeEnd = nextDay(replaceNegativeStart);
const replaceNegativeLocation = `E2E replace negative ${Date.now()}`;

const bulkGapStart = isoDate(constraintBaseOffset + 5);
const bulkGapEnd = nextDay(bulkGapStart);
const bulkGapLocation = `E2E bulk gap ${Date.now()}`;

const cpsatStart = isoDate(constraintBaseOffset + 7);
const cpsatEnd = nextDay(cpsatStart);
const cpsatLocation = `E2E cpsat exclude ${Date.now()}`;

const rangeManualDate = isoDate(constraintBaseOffset + 9);
const rangeManualLocation = `E2E range manual ${Date.now()}`;

const rangeAutoDate = isoDate(constraintBaseOffset + 11);
const rangeAutoLocation = `E2E range auto ${Date.now()}`;

const constraintReason = `מסע E2E אילוץ אישי ${Date.now()}`;

let constrainedSoldierId = "";

test.describe.configure({ mode: "serial" });

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function selectDutyTypeExact(page: Page, formTestId: string, name: string): Promise<void> {
  const combobox = page.getByTestId(formTestId).getByRole("combobox").nth(0);
  await combobox.click();
  await combobox.fill(name);
  // Click the matching option rather than relying on Enter's selectExactMatch
  // fallback: some duty type names are exact prefixes of others (e.g.
  // 'עבודות רס"ר' vs 'עבודות רס"ר בינוי'), so this anchors on the full exact
  // text rather than a substring/fuzzy match.
  const option = page
    .locator('[role="listbox"]:visible [role="option"] button')
    .filter({ hasText: new RegExp(`^${escapeRegExp(name)}$`) });
  await expect(option.first()).toBeVisible({ timeout: 30_000 });
  await option.first().click();
}

async function createShift(
  page: Page,
  opts: { dutyTypeName: string; locationName: string; start: string; end: string; requiredCount: number; scopeNodeName?: string },
): Promise<string> {
  await page.goto("/planning/shifts");
  await expect(page.getByTestId("shifts-page")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("shift-create-button").click();
  const form = page.getByTestId("shift-create-form");
  await expect(form).toBeVisible();
  await selectDutyTypeExact(page, "shift-create-form", opts.dutyTypeName);
  await form.getByRole("button", { name: /מיקום חדש/ }).click();
  await page.getByTestId("location-create-name").fill(opts.locationName);
  const locationCreate = page.waitForResponse(
    (r) => r.url().includes("/api/duty-config/locations") && r.request().method() === "POST",
  );
  await page.getByTestId("location-create-submit").click();
  expect((await locationCreate).status()).toBe(201);
  await expect(page.getByTestId("location-create-name")).toBeHidden({ timeout: 30_000 });
  await page.getByTestId("shift-start-date").fill(opts.start);
  await page.getByTestId("shift-end-date").fill(opts.end);
  await page.getByRole("spinbutton").nth(0).fill(String(opts.requiredCount));
  await page.getByRole("spinbutton").nth(1).fill("0");
  if (opts.scopeNodeName) {
    await page.getByTestId("sub-hierarchy-selector").getByText(opts.scopeNodeName, { exact: true }).click();
  }
  const shiftCreate = page.waitForResponse((r) => r.url().includes("/api/shifts") && r.request().method() === "POST");
  await page.getByTestId("shift-create-submit").click();
  const created = await shiftCreate;
  expect(created.status()).toBe(201);
  const shiftId = (await created.json()).id as string;
  await page.getByTestId("shift-filter-from").fill(previousDay(opts.start));
  const checkbox = page.getByTestId(`shift-row-checkbox-${shiftId}`);
  await expect(checkbox).toBeVisible({ timeout: 30_000 });
  return shiftId;
}

// Toggle "requires_mitvahim" / "officers_allowed" on a duty type via the real
// DutyTypeRequirementsEditor at /planning/config (dutyManager-reachable).
// Used to temporarily widen שמירות so PN 1000037 (mitvahim-unqualified,
// officer) can be selected as a candidate — see the seam-inventory's
// "Weapon-ineligibility precondition" note for why this, not a settings
// toggle, is the real mechanism.
async function setDutyTypeEligibility(
  page: Page,
  dutyTypeName: string,
  changes: { requiresMitvahim?: boolean; officersAllowed?: boolean },
): Promise<void> {
  await page.goto("/planning/config");
  await expect(page.getByTestId("duty-config-page")).toBeVisible({ timeout: 30_000 });
  const row = page.getByTestId("duty-type-list").locator("tr", { hasText: dutyTypeName });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.locator("button.underline").click();

  async function setCheckbox(labelText: string, desired: boolean): Promise<void> {
    const checkbox = page.locator("label", { hasText: labelText }).locator('input[type="checkbox"]');
    await expect(checkbox).toBeVisible({ timeout: 30_000 });
    if ((await checkbox.isChecked()) !== desired) await checkbox.click();
  }
  if (changes.requiresMitvahim !== undefined) await setCheckbox("נדרש מטווחים עדכני", changes.requiresMitvahim);
  if (changes.officersAllowed !== undefined) await setCheckbox("קצינים מותרים", changes.officersAllowed);

  const save = page.waitForResponse(
    (r) => r.url().includes("/api/duty-config/duty-types/") && r.request().method() === "PATCH",
  );
  await page.getByRole("button", { name: "שמור דרישות", exact: true }).click();
  expect((await save).status()).toBe(200);
}

// Navigate /unit-calendar forward, month by month (FullCalendar has no direct
// date-jump control — same pattern as multi_user_duty_problems.spec.ts's
// activateReserve), to the shift's month, then click its event (identified by
// its unique location name) to open ShiftDetailPanel. Jumps directly by the
// computed month delta (deterministic) rather than polling for visibility
// after every click — the far-future offsets used throughout this file mean
// a naive poll-and-click loop can outrun the event before the calendar's
// per-month fetch finishes rendering it — then nudges by a further +/-2
// months if the exact jump lands one off (view/timezone edge), before giving
// up.
const HEBREW_MONTHS = [
  "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
  "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
];

// Parses FullCalendar's month/year title (e.g. "אפריל 2031") into a 0-based
// month index and year, or null if the heading text doesn't match (still
// mid-transition).
async function readCalendarMonth(page: Page): Promise<{ year: number; month: number } | null> {
  const text = await page.locator("h2.fc-toolbar-title").textContent().catch(() => null);
  if (!text) return null;
  const match = HEBREW_MONTHS.map((name, idx) => ({ name, idx })).find(({ name }) => text.includes(name));
  const yearMatch = text.match(/\d{4}/);
  if (!match || !yearMatch) return null;
  return { year: Number(yearMatch[0]), month: match.idx };
}

async function openShiftDetailPanel(page: Page, locationName: string, targetDateIso: string): Promise<void> {
  await page.goto("/unit-calendar");
  await expect(page.locator(".fc-next-button")).toBeVisible({ timeout: 30_000 });
  const target = new Date(`${targetDateIso}T00:00:00Z`);
  const targetYear = target.getUTCFullYear();
  const targetMonth = target.getUTCMonth();

  // Click "next" one month at a time, re-reading the toolbar's own title each
  // time (rather than clicking a pre-computed number of times) — a fixed
  // click count can under/overshoot if a click lands mid-transition and gets
  // dropped, or the button is briefly disabled while the month's shifts are
  // being fetched.
  for (let step = 0; step < 90; step += 1) {
    const current = await readCalendarMonth(page);
    if (current && (current.year > targetYear || (current.year === targetYear && current.month >= targetMonth))) {
      break;
    }
    await page.locator(".fc-next-button").click();
    await page.waitForTimeout(250);
  }

  const shiftEvent = page.locator(".fc-event").filter({ hasText: locationName }).first();
  await expect(shiftEvent).toBeVisible({ timeout: 30_000 });
  await shiftEvent.click();
}

// Full setup: makes PN 1000037 a genuine, persisted weapon_ineligible primary
// assignee on a fresh שמירות shift. See the seam-inventory's
// "Weapon-ineligibility precondition" note for exactly why each step is
// needed. Widens שמירות's eligibility only for as long as `during` runs (the
// caller's own Replace-flow interaction), then always reverts it —
// requires_mitvahim has to stay off for the whole interaction, not just this
// setup half, since constrainedSoldier's own real (~2026-08) last_mitvahim_date
// is itself far too stale relative to this file's deliberately-far-future
// shift dates to pass that gate at those dates.
async function setupWeaponIneligiblePrimaryAndRun(
  browser: Browser,
  opts: { locationName: string; start: string; end: string },
  during: (shiftId: string) => Promise<void>,
): Promise<void> {
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    await setDutyTypeEligibility(dutyManager.page, "שמירות", { requiresMitvahim: false, officersAllowed: true });

    const shiftId = await createShift(dutyManager.page, {
      dutyTypeName: "שמירות",
      locationName: opts.locationName,
      start: opts.start,
      end: opts.end,
      requiredCount: 1,
      scopeNodeName: TEAM_NODE_NAME,
    });

    await dutyManager.page.getByTestId(`manual-assignment-open-${shiftId}`).click();
    const modal = dutyManager.page.getByTestId(`manual-assignment-modal-${shiftId}`);
    await expect(modal).toBeVisible();
    const candidateRow = modal
      .locator('[data-testid^="manual-primary-candidate-"]')
      .filter({ hasText: WEAPON_INELIGIBLE_PN });
    await expect(candidateRow).toBeVisible({ timeout: 30_000 });
    await candidateRow.locator("input:not(:checked)").first().check();

    const assign = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/api/shifts/${shiftId}/assign-batch`) && r.request().method() === "POST",
    );
    await dutyManager.page.getByTestId("manual-assignment-save").click();
    expect((await assign).status()).toBe(201);
    await expect(modal).toBeHidden({ timeout: 30_000 });

    await during(shiftId);
  } finally {
    // Always revert, even if `during` throws, so a failing assertion doesn't
    // leave שמירות permanently widened for the rest of the suite/run.
    await setDutyTypeEligibility(dutyManager.page, "שמירות", { requiresMitvahim: true, officersAllowed: false });
    await dutyManager.context.close();
  }
}

async function createRangeLocation(page: Page, name: string): Promise<void> {
  await page.goto("/ranges?tab=locations");
  await expect(page.getByTestId("range-locations-content")).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("שם המיקום").fill(name);
  const create = page.waitForResponse(
    (r) => new URL(r.url()).pathname.endsWith("/api/range-locations") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "הוסף מיקום", exact: true }).click();
  expect((await create).status()).toBe(201);
  await expect(page.getByText(name, { exact: true })).toBeVisible({ timeout: 30_000 });
}

async function selectComboboxOption(page: Page, testId: string, name: string): Promise<void> {
  const combobox = page.getByTestId(testId);
  await combobox.click();
  await combobox.fill(name);
  const option = page
    .locator('[role="listbox"]:visible [role="option"] button')
    .filter({ hasText: new RegExp(`^${escapeRegExp(name)}$`) });
  await expect(option.first()).toBeVisible({ timeout: 30_000 });
  await option.first().click();
}

async function createRangeEvent(
  page: Page,
  opts: { locationName: string; date: string; requiredCount: number; reserveCount?: number },
): Promise<string> {
  await createRangeLocation(page, opts.locationName);
  await page.goto("/ranges");
  await expect(page.getByTestId("ranges-page")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("create-event-button").click();
  const form = page.getByTestId("create-event-form");
  await expect(form).toBeVisible();
  await selectComboboxOption(page, "new-range-location", opts.locationName);
  await page.getByTestId("new-date").fill(opts.date);
  await page.getByTestId("new-required-count").fill(String(opts.requiredCount));
  await page.getByTestId("new-reserve-count").fill(String(opts.reserveCount ?? 0));
  const create = page.waitForResponse(
    (r) => new URL(r.url()).pathname.endsWith("/api/ranges") && r.request().method() === "POST",
  );
  await form.getByRole("button", { name: "שמור", exact: true }).click();
  const created = await create;
  expect(created.status()).toBe(201);
  return (await created.json()).id as string;
}

test("setup: constrainedSoldier's personal constraint is submitted and fully approved", async ({ browser }) => {
  test.setTimeout(120_000);
  const soldier = await openConstrainedSoldierContext(browser);
  const commander = await openRoleContext(browser, "commander");
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    await soldier.page.goto("/my-requests");
    await soldier.page.getByTestId("constraint-form-toggle").click();
    await expect(soldier.page.getByTestId("constraint-form-card")).toBeVisible();
    await soldier.page.getByTestId("req-start").fill(constraintStart);
    await soldier.page.getByTestId("req-end").fill(constraintEnd);
    await soldier.page.getByTestId("req-reason").fill(constraintReason);
    const submit = soldier.page.waitForResponse(
      (r) => r.url().includes("/api/me/constraints") && r.request().method() === "POST",
    );
    await soldier.page.getByTestId("req-submit").click();
    const submitResponse = await submit;
    expect(submitResponse.status()).toBe(201);
    // Derive constrainedSoldierId from this response body (ConstraintOut,
    // which always carries soldier_id) rather than from a later test's
    // incidental candidates read — this is the setup test every other test
    // in this file already depends on, so deriving it here keeps the other
    // tests' dependency honest instead of silently riding on a test (the
    // duty-side "documented product gap" one) whose entire purpose is to be
    // deleted or rewritten once that gap closes.
    constrainedSoldierId = (await submitResponse.json()).soldier_id as string;
    expect(constrainedSoldierId).toBeTruthy();

    for (const approver of [commander.page, dutyManager.page]) {
      await approver.goto("/approvals?tab=constraints");
      const row = approver.locator('[data-testid^="approval-row-"]').filter({ hasText: constraintReason });
      await expect(row).toBeVisible({ timeout: 30_000 });
      const approveButton = row.locator('[data-testid^="approve-"]');
      await expect(approveButton).toBeVisible({ timeout: 30_000 });
      const approve = approver.waitForResponse(
        (r) => r.url().includes("/api/constraints/") && r.url().includes("/approve") && r.request().method() === "POST",
      );
      await approveButton.click();
      expect((await approve).status()).toBe(200);
    }

    await soldier.page.goto("/my-requests?tab=existing");
    const approvedRow = soldier.page.locator('[data-testid^="constraint-row-"]').filter({ hasText: constraintReason });
    await expect(approvedRow).toBeVisible({ timeout: 30_000 });
    await expect(approvedRow.getByText("אושר", { exact: true })).toBeVisible({ timeout: 30_000 });
  } finally {
    await Promise.all([soldier.context.close(), commander.context.close(), dutyManager.context.close()]);
  }
});

test("duty-side manual override: PN 1000037 becomes a genuine weapon-ineligible primary assignee, reachable via ShiftDetailPanel's Replace button (Task 2 — closes the reachability half of task_af3d0c50)", async ({ browser }) => {
  test.setTimeout(300_000);
  await setupWeaponIneligiblePrimaryAndRun(
    browser,
    { locationName: replaceSetupLocation, start: replaceSetupStart, end: replaceSetupEnd },
    async (shiftId) => {
      const dutyManager = await openRoleContext(browser, "dutyManager");
      try {
        await openShiftDetailPanel(dutyManager.page, replaceSetupLocation, replaceSetupStart);
        // PN 1000037 is now a real, published primary assignee with
        // weapon_ineligible=true (set by create_assignment at setup time,
        // since they have no last_mitvahim_date at all) — ShiftDetailPanel's
        // "החלף" button next to them is the observable proof of this, not an
        // assumption. This is the precondition the OLD "documented product
        // gap" test in this file used to prove was unreachable; it is now
        // reachable, verified live, end to end.
        const replaceButton = dutyManager.page.getByRole("button", { name: "החלף", exact: true });
        await expect(replaceButton).toBeVisible({ timeout: 30_000 });

        // Clicking "החלף" immediately DELETEs the ineligible assignment, then
        // GETs the shift again and opens ShiftAssignModal against it (real
        // ShiftDetailPanel.tsx behavior, not assumed) — wait for both real
        // network calls, not just the click, and confirm the modal — with a
        // real, unblocked candidate carrying the ConstraintWarningIcon
        // (constrainedSoldier) — actually opens.
        const refetchShift = dutyManager.page.waitForResponse(
          (r) => new URL(r.url()).pathname.endsWith(`/shifts/${shiftId}`) && r.request().method() === "GET",
        );
        const candidatesFetch = dutyManager.page.waitForResponse(
          (r) => new URL(r.url()).pathname.endsWith(`/shifts/${shiftId}/candidates`) && r.request().method() === "GET",
        );
        await replaceButton.click();
        await refetchShift;
        await candidatesFetch;

        const row = dutyManager.page.locator("table tr").filter({ hasText: CONSTRAINED_SOLDIER_PN });
        await expect(row).toBeVisible({ timeout: 30_000 });
        await expect(row).toHaveCount(1);
        await expect(row.locator('button[title*="אילוץ אישי מאושר"]')).toBeVisible({ timeout: 30_000 });
      } finally {
        await dutyManager.context.close();
      }
    },
  );
});

// The OTHER half of task_af3d0c50 — actually completing the override (fill a
// reason, confirm, assign) — used to be blocked by a real, separate product
// bug in useModalBackClose's nested-modal history handling (see the
// seam-inventory's "Duty manual override via ShiftAssignModal's 'Replace'
// flow" note for the root cause and fix). Now that it's fixed, this proves
// the plan's originally-intended positive/negative pair for real: an empty
// reason is rejected client-side (confirm stays disabled), and a filled-in
// reason succeeds end to end.
test("duty-side manual override via the Replace flow: empty override reason is rejected, a real reason succeeds end to end (Task 2 completion, closes task_bd77e412)", async ({ browser }) => {
  test.setTimeout(300_000);
  await setupWeaponIneligiblePrimaryAndRun(
    browser,
    { locationName: replaceNegativeLocation, start: replaceNegativeStart, end: replaceNegativeEnd },
    async (shiftId) => {
      const dutyManager = await openRoleContext(browser, "dutyManager");
      try {
        await openShiftDetailPanel(dutyManager.page, replaceNegativeLocation, replaceNegativeStart);
        const replaceButton = dutyManager.page.getByRole("button", { name: "החלף", exact: true });
        await expect(replaceButton).toBeVisible({ timeout: 30_000 });

        const refetchShift = dutyManager.page.waitForResponse(
          (r) => new URL(r.url()).pathname.endsWith(`/shifts/${shiftId}`) && r.request().method() === "GET",
        );
        const candidatesFetch = dutyManager.page.waitForResponse(
          (r) => new URL(r.url()).pathname.endsWith(`/shifts/${shiftId}/candidates`) && r.request().method() === "GET",
        );
        await replaceButton.click();
        await refetchShift;
        await candidatesFetch;

        const row = dutyManager.page.locator("table tr").filter({ hasText: CONSTRAINED_SOLDIER_PN });
        await expect(row).toBeVisible({ timeout: 30_000 });
        await expect(row).toHaveCount(1);
        await expect(row.locator('button[title*="אילוץ אישי מאושר"]')).toBeVisible({ timeout: 30_000 });
        const checkbox = row.locator('input[type="checkbox"]');
        await expect(checkbox).toHaveCount(1);
        await checkbox.check();
        await expect(checkbox).toBeChecked();

        // Both actors carry weapon_warning=true at this file's deliberately
        // far-future dates (nobody can have a currently-valid weapon
        // qualification years out), so selecting constrainedSoldier here —
        // who ALSO carries personal_constraint_warning — always opens the
        // weapon-warning ConfirmDialog first, per ShiftAssignModal.tsx's
        // handleAssign(). This three-level stacking (ShiftDetailPanel ->
        // ShiftAssignModal -> ConfirmDialog, all using useModalBackClose) is
        // unavoidable for proving the Replace-flow scenario at all, since PN
        // 1000037 can only ever become weapon_ineligible=true on a duty type
        // carrying required_range_type — which necessarily makes
        // weapon_warning=true universal at these dates too. It's exactly the
        // shape the nested-modal history bug used to break, and exactly the
        // shape this test now proves fixed.
        await dutyManager.page.getByRole("button", { name: /^שבץ/ }).click();
        const weaponConfirm = dutyManager.page.getByTestId("confirm-dialog-confirm");
        await expect(weaponConfirm).toBeVisible({ timeout: 30_000 });
        await weaponConfirm.click();

        // ShiftAssignModal must survive this confirm (the bug used to close
        // it here) and continueAssign() must proceed straight to
        // OverrideReasonModal, since the selected candidate carries
        // personal_constraint_warning.
        const shiftAssignTitle = dutyManager.page.getByText("שיבוץ ידני", { exact: true });
        await expect(shiftAssignTitle).toBeVisible({ timeout: 30_000 });
        const reasonInput = dutyManager.page.getByPlaceholder("נימוק העקיפה...");
        await expect(reasonInput).toBeVisible({ timeout: 30_000 });

        // Negative: OverrideReasonModal's confirm button
        // (disabled={!reason.trim()}) rejects an empty/whitespace-only reason
        // client-side — no assign-batch call at all.
        const confirmOverride = dutyManager.page.getByRole("button", { name: "אישור", exact: true });
        await expect(confirmOverride).toBeDisabled();
        await reasonInput.fill("   ");
        await expect(confirmOverride).toBeDisabled();

        // Positive: a real reason enables confirm and completes the
        // assignment for real.
        await reasonInput.fill("חריגה מאושרת לשיבוץ ידני E2E — Replace flow");
        await expect(confirmOverride).toBeEnabled();
        const assign = dutyManager.page.waitForResponse(
          (r) => r.url().includes(`/api/shifts/${shiftId}/assign-batch`) && r.request().method() === "POST",
        );
        await confirmOverride.click();
        const assignResult = await assign;
        expect(assignResult.status()).toBe(201);
        expect((assignResult.request().postDataJSON() as { override_reason?: string }).override_reason).toBeTruthy();

        // onSaved (ShiftDetailPanel.tsx) closes ShiftAssignModal and the panel
        // both — confirm the real, visible post-refresh state rather than
        // just trusting the response.
        await expect(shiftAssignTitle).toBeHidden({ timeout: 30_000 });
        await dutyManager.page.reload();
        await openShiftDetailPanel(dutyManager.page, replaceNegativeLocation, replaceNegativeStart);
        // constrainedSoldier is now the real, saved primary assignee — proof
        // the override actually completed, not just that the response was
        // 2xx. (They may also show their own "החלף" here, since gate 2 makes
        // them weapon_ineligible too at these far-future dates — that's an
        // expected, separately-documented side effect of the fixture, not
        // asserted against here.)
        await expect(dutyManager.page.getByText(CONSTRAINED_SOLDIER_NAME)).toBeVisible({ timeout: 30_000 });
      } finally {
        await dutyManager.context.close();
      }
    },
  );
});

test("the standard bulk ShiftEditAssignmentsModal can override a personal constraint end to end (Task 1's fix)", async ({ browser }) => {
  test.setTimeout(120_000);
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    // 'עבודות רס"ר' carries no weapon requirement, so this exercises the
    // override-reason path in isolation, without the unrelated
    // weapon-warning confirm this journey's other shifts trigger.
    const shiftId = await createShift(dutyManager.page, {
      dutyTypeName: 'עבודות רס"ר',
      locationName: bulkGapLocation,
      start: bulkGapStart,
      end: bulkGapEnd,
      requiredCount: 1,
    });
    await dutyManager.page.getByTestId(`manual-assignment-open-${shiftId}`).click();
    const modal = dutyManager.page.getByTestId(`manual-assignment-modal-${shiftId}`);
    await expect(modal).toBeVisible();

    const candidateRow = modal
      .locator('[data-testid^="manual-primary-candidate-"]')
      .filter({ hasText: CONSTRAINED_SOLDIER_PN });
    await expect(candidateRow).toBeVisible({ timeout: 30_000 });
    // Task 1's fix: the bulk modal now renders a ConstraintWarningIcon next to
    // a candidate carrying personal_constraint_warning, instead of an
    // ordinary, unmarked selectable row (title carries the approved-window
    // summary — see ConstraintWarningIcon.tsx).
    await expect(candidateRow.locator('button[title*="אילוץ אישי מאושר"]')).toBeVisible({ timeout: 30_000 });
    await candidateRow.locator("input:not(:checked)").first().check();

    await dutyManager.page.getByTestId("manual-assignment-save").click();

    // Task 1's fix: saving a selection that includes a constrained candidate
    // now opens OverrideReasonModal client-side (handleSave/doSave in
    // ShiftEditAssignmentsModal.tsx) instead of firing assign-batch straight
    // away and getting back a 409.
    const reasonInput = dutyManager.page.getByPlaceholder("נימוק העקיפה...");
    await expect(reasonInput).toBeVisible({ timeout: 30_000 });
    await reasonInput.fill("חריגה מאושרת לשיבוץ ידני E2E");

    const save = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/api/shifts/${shiftId}/assign-batch`) && r.request().method() === "POST",
    );
    await dutyManager.page.getByRole("button", { name: "אישור", exact: true }).click();
    const saveResult = await save;
    expect(saveResult.status()).toBe(201);
    expect((saveResult.request().postDataJSON() as { override_reason?: string }).override_reason).toBeTruthy();

    // onSaved (ShiftsPage.tsx) closes this modal and refreshes the shifts
    // list — confirm the modal actually goes away rather than just trusting
    // the response.
    await expect(modal).toBeHidden({ timeout: 30_000 });

    // Refresh and re-open: assert the real, visible post-refresh UI state —
    // constrainedSoldier now shows up as an actual saved assignee row in the
    // summary table (assignment-primary-<id>), not merely a pending one.
    await dutyManager.page.reload();
    await dutyManager.page.getByTestId(`manual-assignment-open-${shiftId}`).click();
    await expect(modal).toBeVisible();
    await expect(
      modal.locator('[data-testid^="assignment-primary-"]').filter({ hasText: CONSTRAINED_SOLDIER_NAME }),
    ).toBeVisible({ timeout: 30_000 });
  } finally {
    await dutyManager.context.close();
  }
});

test("CP-SAT auto-assign always hard-excludes the constrained soldier", async ({ browser }) => {
  test.setTimeout(180_000);
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    expect(constrainedSoldierId).toBeTruthy();

    const shiftId = await createShift(dutyManager.page, {
      dutyTypeName: 'עבודות רס"ר',
      locationName: cpsatLocation,
      start: cpsatStart,
      end: cpsatEnd,
      requiredCount: 3,
      scopeNodeName: TEAM_NODE_NAME,
    });

    const checkbox = dutyManager.page.getByTestId(`shift-row-checkbox-${shiftId}`);
    await checkbox.check();
    await dutyManager.page.getByRole("button", { name: "שיבוץ אוטומטי", exact: true }).click();
    const jobCreate = dutyManager.page.waitForResponse(
      (r) => r.url().includes("/api/algorithm/jobs") && r.request().method() === "POST",
    );
    await dutyManager.page.getByTestId("algorithm-run-submit").click();
    const jobResponse = await jobCreate;
    const jobId = (await jobResponse.json()).id as string;
    await expect(dutyManager.page.getByTestId("algorithm-proposal-review")).toBeVisible({ timeout: 120_000 });

    // Anti-vacuousness safeguard: confirm the constrained soldier was actually
    // loaded into this job's solver input, with approved_constraint_dates
    // overlapping this duty's dates, via the same real "export inputs" button
    // the UI itself exposes — before trusting their absence from the output.
    const exportResponse = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/api/algorithm/jobs/${jobId}/export-inputs`) && r.request().method() === "GET",
    );
    await dutyManager.page.getByRole("button", { name: /ייצוא קלטי ופלטי solver/ }).click();
    const exportPayload = await (await exportResponse).json();
    const soldierInput = (exportPayload.soldiers as Array<{ id: string; approved_constraint_dates: [string, string][] }>).find(
      (s) => s.id === constrainedSoldierId,
    );
    expect(soldierInput, "constrained soldier must be present in the solver's input pool").toBeTruthy();
    const overlapsThisDuty = soldierInput!.approved_constraint_dates.some(
      ([start, end]) => start <= cpsatStart && end >= cpsatStart,
    );
    expect(overlapsThisDuty, "constrained soldier's approved constraint must overlap this duty's dates").toBe(true);

    const publish = dutyManager.page.getByTestId("algorithm-publish-proposals");
    if (await publish.isEnabled()) await publish.click();
    await expect(dutyManager.page.getByTestId("algorithm-proposal-review")).toContainText("פורסם", { timeout: 45_000 });

    const review = dutyManager.page.getByTestId("algorithm-proposal-review");
    await expect(review).not.toContainText(CONSTRAINED_SOLDIER_NAME);
    // Non-vacuous: some other team-ריי member DID get assigned — the 3
    // required slots were filled from the 4-person eligible pool minus the
    // one hard-excluded soldier, not left empty for unrelated reasons.
    await expect(review).toContainText("ריי");
  } finally {
    await dutyManager.context.close();
  }
});

test("range manual override: selecting constrainedSoldier as a candidate with an override reason succeeds", async ({ browser }) => {
  test.setTimeout(120_000);
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    expect(constrainedSoldierId).toBeTruthy();

    const eventId = await createRangeEvent(dutyManager.page, {
      locationName: rangeManualLocation,
      date: rangeManualDate,
      requiredCount: 1,
      reserveCount: 0,
    });

    // RangeEditAssignmentsModal fetches candidates itself as soon as it opens
    // (its own `editable` useEffect) — this is a real read of that same
    // network response, not a mock, used only as an anti-vacuousness check
    // (same pattern as the CP-SAT test's export-inputs read above): confirm
    // constrainedSoldier is genuinely a live, non-excluded candidate here,
    // carrying the soft-conflict marker, before trusting the UI affordance.
    const candidatesPromise = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/ranges/${eventId}/candidates`) && r.request().method() === "GET",
    );
    await dutyManager.page.getByTestId(`view-assignments-${eventId}`).click();
    const candidatesPayload = (await (await candidatesPromise).json()) as {
      candidates: Array<{ soldier_id: string; personal_constraint_conflict: boolean; conflict_warning: string | null }>;
    };
    const constrainedCandidate = candidatesPayload.candidates.find((c) => c.soldier_id === constrainedSoldierId);
    expect(constrainedCandidate, "constrainedSoldier must be a real, non-excluded range candidate").toBeTruthy();
    expect(constrainedCandidate!.personal_constraint_conflict).toBe(true);
    expect(constrainedCandidate!.conflict_warning).toBeTruthy();

    const checkbox = dutyManager.page.getByTestId(`candidate-checkbox-${constrainedSoldierId}`);
    await expect(checkbox).toBeVisible({ timeout: 30_000 });
    // The ⚠️ marker (title = conflict_warning) rendered next to the name is
    // the same row's visible confirmation of the conflict the JSON above
    // already proved — both must agree, not just one or the other.
    const row = dutyManager.page.locator("tr", { has: checkbox });
    await expect(row.getByText("⚠️")).toBeVisible({ timeout: 30_000 });
    await checkbox.check();

    await dutyManager.page.getByTestId("save-assignments").click();
    // Client-side gate: RangeEditAssignmentsModal's saveSelection() detects
    // personal_constraint_conflict on the selection and opens
    // OverrideReasonModal *before* any network call — no request has been
    // sent yet at this point.
    const reasonInput = dutyManager.page.getByPlaceholder("נימוק העקיפה...");
    await expect(reasonInput).toBeVisible({ timeout: 30_000 });
    await reasonInput.fill("חריגה מאושרת למטווח E2E");

    const batchAssign = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/ranges/${eventId}/assignments/batch`) && r.request().method() === "POST",
    );
    await dutyManager.page.getByRole("button", { name: "אישור", exact: true }).click();
    const batchResult = await batchAssign;
    expect(batchResult.status()).toBe(200);
    expect((batchResult.request().postDataJSON() as { override_reason?: string }).override_reason).toBeTruthy();

    // Refresh and re-open: assert the visible roster, not just the 2xx.
    await dutyManager.page.reload();
    await dutyManager.page.getByTestId(`view-assignments-${eventId}`).click();
    const dialog = dutyManager.page.getByRole("dialog");
    await expect(dialog.getByText(CONSTRAINED_SOLDIER_NAME)).toBeVisible({ timeout: 30_000 });
  } finally {
    await dutyManager.context.close();
  }
});

test("range auto-select's real behavior is a soft conflict, not a hard exclusion — saving still requires the override reason", async ({ browser }) => {
  test.setTimeout(120_000);
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    expect(constrainedSoldierId).toBeTruthy();

    // required_count (100) is deliberately far above the whole branch-scoped
    // candidate pool (dutyManager's DutyManagerScope covers branch "פוקוס",
    // ~10 teams × 6 soldiers ≈ 63 people, before range-structural filtering
    // narrows it further) so that autoSelectPrimary's `.slice(0,
    // primarySlotsLeft)` — which does NOT filter by personal_constraint_conflict
    // or auto_selectable, see the seam-inventory note above — takes every
    // eligible candidate, constrainedSoldier included, rather than depending on
    // guessing exact rank order among tied candidates.
    const eventId = await createRangeEvent(dutyManager.page, {
      locationName: rangeAutoLocation,
      date: rangeAutoDate,
      requiredCount: 100,
      reserveCount: 0,
    });

    const candidatesPromise = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/ranges/${eventId}/candidates`) && r.request().method() === "GET",
    );
    await dutyManager.page.getByTestId(`view-assignments-${eventId}`).click();
    const candidatesPayload = (await (await candidatesPromise).json()) as {
      candidates: Array<{ soldier_id: string; personal_constraint_conflict: boolean }>;
    };
    expect(
      candidatesPayload.candidates.some((c) => c.soldier_id === constrainedSoldierId),
      "constrainedSoldier must be a real range candidate here too (precondition for the auto-select assertion below)",
    ).toBe(true);

    await dutyManager.page.getByTestId("range-auto-select-primary").click();

    // Non-vacuous, read from the real rendered UI state (not assumed from the
    // fixture math above): the pending-selection summary row for
    // constrainedSoldier, tagged "טרם נשמר", must actually be there.
    const dialog = dutyManager.page.getByRole("dialog");
    await expect(dialog.getByText(CONSTRAINED_SOLDIER_NAME).first()).toBeVisible({ timeout: 30_000 });
    await expect(dialog.getByText("טרם נשמר").first()).toBeVisible({ timeout: 30_000 });

    await dutyManager.page.getByTestId("save-assignments").click();
    // Same client-side gate as the manual test above, now triggered by an
    // auto-selected (not manually clicked) candidate — this is the crux of
    // the asymmetry with CP-SAT: auto-select included constrainedSoldier
    // instead of excluding them, and saving is gated the same way a manual
    // pick would be.
    const reasonInput = dutyManager.page.getByPlaceholder("נימוק העקיפה...");
    await expect(reasonInput).toBeVisible({ timeout: 30_000 });
    await reasonInput.fill("חריגה מאושרת לבחירה אוטומטית E2E");

    const batchAssign = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/ranges/${eventId}/assignments/batch`) && r.request().method() === "POST",
    );
    await dutyManager.page.getByRole("button", { name: "אישור", exact: true }).click();
    const batchResult = await batchAssign;
    expect(batchResult.status()).toBe(200);
    const batchBody = batchResult.request().postDataJSON() as { override_reason?: string; primaries: string[] };
    expect(batchBody.override_reason).toBeTruthy();
    expect(batchBody.primaries).toContain(constrainedSoldierId);
    // Non-vacuous the other direction too: auto-select picked more than just
    // the one constrained soldier out of the whole eligible pool.
    expect(batchBody.primaries.length).toBeGreaterThan(1);

    await dutyManager.page.reload();
    await dutyManager.page.getByTestId(`view-assignments-${eventId}`).click();
    const reloadedDialog = dutyManager.page.getByRole("dialog");
    await expect(reloadedDialog.getByText(CONSTRAINED_SOLDIER_NAME)).toBeVisible({ timeout: 30_000 });
  } finally {
    await dutyManager.context.close();
  }
});
