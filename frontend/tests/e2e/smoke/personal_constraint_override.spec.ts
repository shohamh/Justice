import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { journeyActorStorageState, roleStorageState, type Role } from "../fixtures/auth";

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
 * - Duty manual override via ShiftAssignModal's "Replace" flow — REAL,
 *   PRE-EXISTING PRODUCT GAP, confirmed unreachable by two independent,
 *   increasingly careful investigations (see "Weapon-ineligibility
 *   precondition" below for the full trail) — not exercised by this file at
 *   all. ShiftDetailPanel (reachable only from /unit-calendar's FullCalendar
 *   events) shows a "החלף" (weapon_ineligible.replace) button next to any
 *   primary assignee with weapon_ineligible=true, which opens ShiftAssignModal
 *   with real override-reason UI (OverrideReasonModal). But there is no live
 *   UI path that ever produces a weapon_ineligible=true assignee in the first
 *   place, so this modal's override logic — while implemented correctly per
 *   OverrideReasonModal.tsx — has no reachable trigger. Do not resurrect a
 *   "Replace" test here without re-reading the precondition finding below
 *   first; two attempts already died on two different, independently fatal
 *   causes.
 *
 * - Duty manual override — the real, pre-existing product gap this suite
 *   documents (not a defect in the test): the standard bulk
 *   ShiftEditAssignmentsModal (opened via [data-testid^=
 *   "manual-assignment-open-"], the same modal exercised in
 *   multi_user_duty_problems.spec.ts) has NO override-reason UI at all. A
 *   constrained candidate looks like an ordinary, fully-selectable row there
 *   (blocked_reason is only set when the allow_manual_override setting is
 *   off, which is not this fixture's default). Selecting them and clicking
 *   "שמור" ([data-testid="manual-assignment-save"]) calls the same
 *   assign-batch endpoint with no override_reason, which the backend
 *   (services/assignments.py's create_assignment) rejects with
 *   AssignmentError("override_reason_required") — surfaced by the route as
 *   **409 Conflict, not 400** (routes/shifts.py's assign_batch catches
 *   AssignmentError and re-raises as 409). The frontend has no i18n mapping
 *   for the "override_reason_required" code (translateApiError falls back to
 *   ShiftEditAssignmentsModal's own fallback string), so the visible error is
 *   the generic "שגיאה בשיבוץ", not anything constraint-specific.
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
 * - Weapon-ineligibility precondition — TWO INDEPENDENT INVESTIGATIONS, TWO
 *   INDEPENDENT DEAD ENDS. Both confirmed by actually running things and
 *   reading real output/source, not by inspection alone:
 *
 *   (1) Every SEEDED duty type carrying a required_range_type is either
 *   officer-only (הגנ"ש/קצין תורן/מפקד תורן/קצין מלווה אבט"ש —
 *   enlisted_allowed:false, which would exclude constrainedSoldier, a
 *   non-officer, from ever appearing as a Replace candidate) or
 *   requires_mitvahim (שמירות/אבט"ש). requires_mitvahim blocks 118 of the
 *   current 120 seeded soldiers (only two soldiers — unrelated to
 *   constrainedSoldier's team — have last_mitvahim_date set), and — contrary
 *   to an earlier assumption here that eligibility_blockers() never sees it —
 *   is fed into the exact same exempted_duty_type_ids the CP-SAT solver
 *   hard-excludes on (services/algorithm_bridge.py's load_soldier_inputs
 *   calls eligibility.py's compute_eligibility_exclusions, which folds every
 *   DutyTypeRequirements gate into the same set consumed by
 *   availability.py's "duty_type_exemption" blocker, and routes/shifts.py's
 *   candidates endpoint uses the very same function for its blocked_reason).
 *   So neither the manual nor the algorithm path can ever put anyone at all
 *   on a seeded weapon duty type. Setting last_mitvahim_date on a soldier to
 *   dodge this gate wouldn't help either — weapon_eligibility.py's
 *   _profile_valid_until treats that same field as live-range (and therefore
 *   laser-tier) proof, so it would make them weapon-*eligible* too. This is
 *   exercised directly below as the rescoped test (a fresh שמירות shift,
 *   scoped to constrainedSoldier's own team so none of the two mitvahim-
 *   holding soldiers are even candidates, asserting every candidate is
 *   blocked with the exact mitvahim ineligibility text).
 *
 *   (2) A second, independent attempt tried sidestepping (1) entirely: create
 *   a brand-new test-only duty type with required_range_type="laser" and
 *   every other eligibility flag left open (no mitvahim/officer gate at
 *   all), then flip the global "אכיפת כשירות נשק לתורנויות"
 *   (weapon_qualification.enforce_eligibility) admin setting off around an
 *   algorithm run so the solver wouldn't hard-exclude anyone for lacking the
 *   qualification, publish, then flip it back on to trigger recheck_
 *   assignments() and flag the published assignee weapon_ineligible=true.
 *   This died on a SEPARATE, deeper bug, confirmed via direct backend
 *   reproduction (a standalone script calling solve() directly found
 *   OPTIMAL/an actual assignment with enforce_weapon_qualification=False —
 *   proving the solver-side plumbing is correct — while the real
 *   POST /api/algorithm/jobs endpoint, hit exactly as the UI's
 *   AlgorithmInlinePanel hits it, reproducibly returned INFEASIBLE): the
 *   request schema routes/algorithm.py's SolverSettingsIn declares
 *   `enforce_weapon_qualification: bool = True` as a hard Pydantic default,
 *   and create_job() stores `body.settings.model_dump(mode="json")` — the
 *   FULLY-RESOLVED request, defaults included — verbatim as job.settings_json.
 *   Since that key is therefore always PRESENT (True) in job.settings_json,
 *   resolve_solver_settings()'s admin-setting fallback
 *   (`settings_json.get("enforce_weapon_qualification", <admin setting>)`)
 *   never triggers for any job created this way — the admin toggle is silently
 *   inert for every reachable job-creation path. The one UI surface that DOES
 *   send this field explicitly, AlgorithmRunForm.tsx, is dead code: App.tsx
 *   unconditionally redirects /algorithm to /planning/shifts. So there is no
 *   live path, whatsoever, to create an algorithm job with
 *   enforce_weapon_qualification=False — this mechanism cannot work
 *   regardless of how carefully the admin-toggle UI is scripted. (This is a
 *   real, independently-worth-fixing product bug — flagged separately, not
 *   fixed here.) The custom-laser-duty-type helpers this second attempt wrote
 *   were removed from this file along with it; do not recreate them without
 *   first fixing the SolverSettingsIn default (or the fallback would still
 *   never engage).
 *
 *   Given both of the only two candidate mechanisms are independently dead,
 *   Steps 4/5 of the plan (a positive "override succeeds" + negative "reason
 *   required" pair via ShiftAssignModal's Replace flow) are not implemented in
 *   this file — see the rescoped test below instead.
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

const CONSTRAINED_SOLDIER_PN = "1000036";
const CONSTRAINED_SOLDIER_NAME = "ריי 4";
const TEAM_NODE_NAME = "צוות ריי";

// Keep this journey's dates far outside the seeded/other-spec horizon, like
// multi_user_duty_problems.spec.ts, but in a distinct offset band so a
// whole-suite run never collides with that spec's 1500-1600 window.
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

const mitvahimGateStart = isoDate(constraintBaseOffset + 1);
const mitvahimGateEnd = nextDay(mitvahimGateStart);
const mitvahimGateLocation = `E2E mitvahim gate ${Date.now()}`;

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
    expect((await submit).status()).toBe(201);

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

test("duty-side manual override precondition (a weapon-ineligible original assignee) is not reachable through any live UI path (documented product gap)", async ({ browser }) => {
  test.setTimeout(120_000);
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    // "שמירות" is the seeded non-officer weapon-tier duty type — see the
    // seam-inventory's "Weapon-ineligibility precondition" note for why this,
    // not a fresh custom duty type, is the only avenue left after both
    // investigated mechanisms turned out to be dead ends. Scoped to
    // constrainedSoldier's own team so none of the two soldiers who DO hold
    // last_mitvahim_date (an unrelated pair elsewhere in the org) are
    // candidates here — every candidate returned must be mitvahim-blocked.
    const shiftId = await createShift(dutyManager.page, {
      dutyTypeName: "שמירות",
      locationName: mitvahimGateLocation,
      start: mitvahimGateStart,
      end: mitvahimGateEnd,
      requiredCount: 1,
      scopeNodeName: TEAM_NODE_NAME,
    });

    const candidatesPromise = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/api/shifts/${shiftId}/candidates`) && r.request().method() === "GET",
    );
    await dutyManager.page.getByTestId(`manual-assignment-open-${shiftId}`).click();
    const candidates = (await (await candidatesPromise).json()) as Array<{
      soldier_id: string;
      personal_number: string;
      blocked: boolean;
      blocked_reason: string | null;
      blocked_detail: string | null;
    }>;

    const constrained = candidates.find((c) => c.personal_number === CONSTRAINED_SOLDIER_PN);
    expect(constrained, "constrainedSoldier must be a candidate for שמירות (in scope, not officer-only)").toBeTruthy();
    constrainedSoldierId = constrained!.soldier_id;

    // The real assertion: EVERY candidate in team ריי — not just
    // constrainedSoldier — is blocked by the unrelated requires_mitvahim gate
    // (services/eligibility.py's duty_type_ineligibility_reason()), because no
    // one on this team has last_mitvahim_date set. This proves the
    // *precondition* for reaching ShiftAssignModal's Replace/override flow (a
    // weapon-ineligible original assignee actually landing on this duty type)
    // is itself unreachable — not merely that the override UI is missing, as
    // the sibling test below documents for the bulk modal.
    expect(candidates.length).toBeGreaterThan(0);
    for (const c of candidates) {
      expect(c.blocked, `soldier ${c.personal_number} should be blocked`).toBe(true);
      expect(c.blocked_reason).toBe("ineligible");
      expect(c.blocked_detail).toBe("לא בוצע מטווח מבצעי בטווח הזמן הנדרש");
    }

    const modal = dutyManager.page.getByTestId(`manual-assignment-modal-${shiftId}`);
    await expect(modal).toBeVisible();
    // Blocked candidates render with no data-testid at all (only unblocked
    // rows get `manual-primary-candidate-${soldier_id}` — confirmed by reading
    // ShiftEditAssignmentsModal.tsx), so zero such rows existing is itself the
    // observable proof that no one is selectable here.
    await expect(modal.locator('[data-testid^="manual-primary-candidate-"]')).toHaveCount(0);
    await expect(
      modal.getByText("לא כשיר לסוג תורנות זה — לא בוצע מטווח מבצעי בטווח הזמן הנדרש").first(),
    ).toBeVisible({ timeout: 30_000 });
  } finally {
    await dutyManager.context.close();
  }
});

test("the standard bulk ShiftEditAssignmentsModal cannot override a personal constraint (documented product gap)", async ({ browser }) => {
  test.setTimeout(120_000);
  const dutyManager = await openRoleContext(browser, "dutyManager");
  try {
    // 'עבודות רס"ר' carries no weapon requirement, so this exercises the bulk
    // modal's *only* gate (the missing override-reason UI) without the
    // unrelated weapon-warning confirm this journey's other shifts trigger.
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
    const candidate = modal
      .locator('[data-testid^="manual-primary-candidate-"]')
      .filter({ hasText: CONSTRAINED_SOLDIER_PN })
      .locator("input:not(:checked)")
      .first();
    await expect(candidate).toBeVisible({ timeout: 30_000 });
    await candidate.check();

    const save = dutyManager.page.waitForResponse(
      (r) => r.url().includes(`/api/shifts/${shiftId}/assign-batch`) && r.request().method() === "POST",
    );
    await dutyManager.page.getByTestId("manual-assignment-save").click();
    const saveResult = await save;
    // The backend rejects with AssignmentError("override_reason_required"),
    // which the route re-raises as 409 (not 400 — see the seam-inventory note
    // above); there is no i18n mapping for that code, so the UI falls back to
    // the modal's own generic error text.
    expect(saveResult.status()).toBe(409);
    // Scoped to the dialog (role="dialog", from EventDetailModal.tsx), not the
    // narrower `modal` (manual-assignment-modal-<id>) div: reading
    // ShiftEditAssignmentsModal.tsx shows the error <p> is rendered as a
    // SIBLING right after that div closes, not nested inside it — so
    // `modal.getByText(...)` never finds it (confirmed empirically: the error
    // genuinely renders, but only visible to a page-wide/dialog-wide locator).
    const dialog = dutyManager.page.getByRole("dialog");
    await expect(dialog.getByText("שגיאה בשיבוץ", { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(modal).toBeVisible();

    // ShiftEditAssignmentsModal is wrapped in EventDetailModal, whose close
    // button's accessible name is "סגור" (an aria-label overriding the "✕"
    // text) — unlike ShiftAssignModal's own plain "✕" button used elsewhere
    // in this file, which has no aria-label.
    await dutyManager.page.getByRole("button", { name: "סגור", exact: true }).click();
    await dutyManager.page.reload();
    await dutyManager.page.getByTestId(`manual-assignment-open-${shiftId}`).click();
    await expect(modal).toBeVisible();
    await expect(modal.getByText("אין שיבוצים עדיין", { exact: true })).toBeVisible({ timeout: 30_000 });
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
