import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { roleStorageState, type Role } from "../fixtures/auth";

/**
 * Task 4 UI seam inventory (every control/endpoint this spec drives, plus
 * corrections to the plan's brief made after reading the real
 * components/services/routes -- not guesses, per the same discipline
 * swaps.spec.ts/ranges.spec.ts/hierarchy_transfers.spec.ts document for
 * Tasks 1-3):
 *
 * - HYBRID TEST, explicitly: the first two journeys below (interval config,
 *   manual rank/next-rank-date correction) are pure browser interaction --
 *   real UI, real backend, real Postgres, no mocking, exactly like every
 *   other spec in this suite. The THIRD journey ("trigger and observe an
 *   actual promotion") is different on purpose: `_promote_due_soldiers()`
 *   only ever runs from `rank_advancement_worker.py`'s 24h poll loop -- there
 *   is genuinely no UI button, HTTP endpoint, or admin action that fires it
 *   on demand (confirmed by reading `rank_advancement_worker.py` directly;
 *   this is documented as a known, intentional gap in the plan). To prove a
 *   promotion actually happens rather than assuming it from a UI action that
 *   doesn't exist, that one test: (1) uses the real UI to set a soldier's
 *   `next_rank_date` to today (the real precondition, verified against
 *   `_promote_due_soldiers`'s own query below), (2) shells out via Node's
 *   `child_process.execSync` to `backend/app/scripts/run_rank_advancement_once.py`
 *   -- a genuinely useful new ops utility (not test-only scaffolding) that
 *   runs the exact same production `_promote_due_soldiers()` function once,
 *   against the same database the running backend uses, then (3) reloads the
 *   real UI and asserts the real, visible effect. Steps (1) and (3) are
 *   ordinary Playwright browser actions; only step (2) is out-of-band, and
 *   it exercises real production code, not a mock or a fixture shortcut.
 *
 * - CORRECTION (found by reading `backend/app/rank_advancement_worker.py`
 *   directly, per the brief's own "read the actual signature first"
 *   instruction): the brief's Step 1 snippet assumed
 *   `_promote_due_soldiers(session)` takes a session argument and the
 *   wrapper should open its own `session_scope()` and pass it in. The real
 *   signature is `_promote_due_soldiers()` -- no arguments -- and it opens
 *   and commits its own `session_scope()` internally (mirroring
 *   `_promote_on_career_entry`/`_warn_upcoming_soldiers` in the same file).
 *   `run_rank_advancement_once.py` was written to call it with no arguments
 *   and no session of its own -- opening one anyway would just create an
 *   unused second connection and, worse, invite a future edit to pass it in
 *   and silently double-commit.
 *
 * - CORRECTION (found by reading `UnifiedSoldierModal.tsx` directly, not
 *   guessed): `canEditRankNarrow = soldierData.can_edit_rank_advancement &&
 *   !canManage`, where `canManage = isAdmin || isDutyManager`. An admin (or
 *   duty manager) therefore NEVER sees the narrow `rank-correction-toggle`
 *   flow the brief describes -- for those roles `can_edit_rank_advancement`
 *   is true but `canManage` is *also* true, so the toggle button is gated
 *   off and only the full-profile editor (`editing` state) exposes the rank
 *   fields. Separately, `HierarchyTree.tsx`'s `edit-soldier-{pn}` pencil
 *   button always opens `UnifiedSoldierModal` with `initialEditing={true}`,
 *   which lands straight on the full-profile editor and never shows the
 *   narrow toggle either, REGARDLESS of actor. The only way to reach
 *   `rank-correction-toggle` in this app is: open the modal via a plain
 *   `SoldierLink` click (name text inside `tree-soldier-{pn}`, wired through
 *   `SoldierModalContext` with `initialEditing` left `undefined` -> `false`),
 *   switch to the profile tab, and be authorized for
 *   `can_edit_rank_advancement` while NOT being an admin/duty manager. The
 *   `commander` role fixture (2000001, direct commander of branch "פוקוס")
 *   satisfies exactly this: `rank_advancement_edit_authorized` grants any
 *   commander whose commanded-node scope covers the target at "group"
 *   (מדור) level or higher, and "פוקוס" is one level above every מדور
 *   underneath it (same branch-wide coverage already relied on by
 *   `hierarchy_transfers.spec.ts`) -- confirmed directly in
 *   `backend/app/services/authority.py::rank_advancement_edit_authorized`.
 *   This spec therefore drives both the manual-correction and the
 *   promotion-precondition journeys as `commander`, opened via `SoldierLink`,
 *   never via the pencil-edit button.
 *
 * - NOTE (found while picking a target soldier, not part of the fix): some
 *   seeded soldiers hold a rank string with an embedded ASCII `"` (gershayim
 *   convention, e.g. the literal seeded in seed.py's `_team_profiles[1]` as
 *   `'רב"ט'`) that does NOT match the canonical, gershayim-free ladder
 *   string (`"רבט"`) `ENLISTED_RANKS`/the rank ladder use internally and
 *   `GET /soldiers/ranks` returns for the UI's rank Combobox (confirmed:
 *   `TransparencyPage.tsx`'s `RANK_ORDER` map explicitly carries both forms
 *   side by side with a "with and without geresh" comment, i.e. this
 *   duality is known and already handled elsewhere in the app, not a fresh
 *   bug introduced here). A soldier seeded with the gershayim form cannot be
 *   correctly selected in the rank Combobox (no exact match) and
 *   `get_next_rank`/`get_track` treat it as track-less. This spec sidesteps
 *   the whole question by picking soldiers whose seeded rank already matches
 *   the canonical ladder exactly (verified directly against the seeded DB:
 *   "ספארק 1" / 1000039 = "סמל", "ספארק 3" / 1000041 = "טוראי") --
 *   "ספארק 2" / 1000040 (the gershayim-typo'd `'רב"ט'`) is deliberately
 *   avoided.
 *
 * - Interval config: `/admin/settings` (default tab renders
 *   `SystemSettingsContent` directly, no query param needed) ->
 *   `RankAdvancementIntervalsSection`'s per-row inputs, newly given
 *   `data-testid={`rank-interval-months-${track}-${rank}`}` and
 *   `data-testid={`rank-interval-career-entry-${track}-${rank}`}` (Step 3;
 *   neither existed before) -> its own "שמור" button (no testid; the page
 *   also has an unrelated top-level "שמור" button with identical text, so
 *   it's located via the unique section heading "מרווחי עליית דרגה", not by
 *   button text alone) -> `PUT /api/soldiers/rank-advancement-intervals`
 *   (200; admin-only via `require_roles("admin")` in
 *   `backend/app/routes/rank_advancement.py`).
 * - Manual rank + next-rank-date edit: `SoldierLink` (soldier's name, inside
 *   `tree-soldier-{pn}`) -> `modal-tab-profile` -> `rank-correction-toggle`
 *   -> `rank-correction-form` (rank via the Combobox, no dedicated testid --
 *   role=combobox, unique within the form -- and
 *   `next-rank-date-input`) -> `rank-correction-submit` ->
 *   `PATCH /api/soldiers/{id}/profile` (200; fields `rank`, `rank_track`,
 *   `is_officer`, `next_rank_date`, gated by
 *   `rank_advancement_edit_authorized`). Persisted state re-verified after a
 *   real full-page reload (not just the in-place `onRefresh`), asserting the
 *   `next_rank_date_manual` badge text (`soldierData.next_rank_date_overridden`
 *   flipped true) alongside the new rank text.
 * - Promotion precondition + trigger: same narrow flow, on a different
 *   soldier, setting only `next-rank-date-input` to today's date (the exact
 *   `next_rank_date <= today` condition `_promote_due_soldiers` queries on;
 *   `discharge_date`/`left_at` are already NULL on this seeded soldier) ->
 *   submit -> 200 -> out-of-band `run_rank_advancement_once.py` (see above)
 *   -> full reload -> re-open the same soldier -> asserts the rank field
 *   now reads the next rung of the ladder (`get_next_rank("טוראי") ==
 *   "רבט"`) and the badge reverted to `next_rank_date_automatic`
 *   (`next_rank_date_overridden` reset to `false` by `_promote_soldier`).
 */

const SPARK_TEAM_NODE_NAME = "צוות ספארק";
// root -> פסיפס -> פוקוס -> שבירה -> צוות ספארק (verified directly against
// the seeded DB, same chain hierarchy_transfers.spec.ts uses for its own
// sibling teams "ריי"/"ספארק" under the same מדור).
const ANCESTOR_CHAIN = ["כלל המסגרת", "פסיפס", "פוקוס", "שבירה"];

const MANUAL_EDIT_SOLDIER = { personalNumber: "1000039", fullName: "ספארק 1", initialRank: "סמל" };
const PROMOTION_SOLDIER = { personalNumber: "1000041", fullName: "ספארק 3", initialRank: "טוראי", nextRank: "רבט" };

type RoleContext = { context: BrowserContext; page: Page };

async function openActorContext(browser: Browser, role: Role): Promise<RoleContext> {
  const projectUse = test.info().project.use as {
    baseURL?: string;
    viewport?: { width: number; height: number };
  };
  const context = await browser.newContext({
    baseURL: projectUse.baseURL ?? "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: roleStorageState(role),
  });
  return { context, page: await context.newPage() };
}

/** Same expansion helper as hierarchy_transfers.spec.ts: expands a node via
 * its own toggle only if currently collapsed, never blindly (which would
 * collapse an already-open node). */
async function ensureNodeExpanded(page: Page, nodeName: string): Promise<void> {
  const nameSpan = page.getByTestId("node-tree").getByText(nodeName, { exact: true });
  await expect(nameSpan).toBeVisible({ timeout: 30_000 });
  const toggle = nameSpan.locator("xpath=preceding-sibling::button[1]");
  const label = (await toggle.textContent())?.trim();
  if (label === "▶") {
    await toggle.click();
  }
}

async function expandToSparkTeam(page: Page): Promise<void> {
  await page.goto("/team");
  await expect(page.getByTestId("team-page")).toBeVisible({ timeout: 30_000 });
  for (const name of ANCESTOR_CHAIN) {
    await ensureNodeExpanded(page, name);
  }
  await ensureNodeExpanded(page, SPARK_TEAM_NODE_NAME);
}

/** Opens a soldier's profile tab via the plain `SoldierLink` name click (NOT
 * the `edit-soldier-{pn}` pencil, which forces `initialEditing=true` and
 * skips straight past the narrow rank-correction toggle -- see seam
 * inventory). Leaves the modal open on the profile tab, read view. */
async function openSoldierProfileTab(page: Page, args: { personalNumber: string; fullName: string }): Promise<void> {
  await expandToSparkTeam(page);
  const row = page.getByTestId(`tree-soldier-${args.personalNumber}`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: args.fullName, exact: true }).click();
  const modal = page.getByTestId("unified-soldier-modal");
  await expect(modal).toBeVisible({ timeout: 30_000 });
  await modal.getByTestId("modal-tab-profile").click();
}

/** Drives the narrow rank-correction flow: opens it, optionally changes the
 * rank via the Combobox (click-select from its dropdown), optionally changes
 * the next-rank-date, and submits -- waiting for the real PATCH 2xx. */
async function submitRankCorrection(
  page: Page,
  args: { newRank?: string; newNextRankDate?: string },
): Promise<void> {
  const modal = page.getByTestId("unified-soldier-modal");
  const toggle = modal.getByTestId("rank-correction-toggle");
  await expect(toggle).toBeVisible({ timeout: 30_000 });
  await toggle.click();

  const form = modal.getByTestId("rank-correction-form");
  await expect(form).toBeVisible({ timeout: 30_000 });

  if (args.newRank) {
    // Click-select from the dropdown list (rendered via a portal to
    // document.body, so it's searched at the page level, not scoped to
    // `form`) -- the same established pattern as
    // multi_user_duty_problems.spec.ts's Combobox interactions, rather than
    // typing + Enter (the Combobox's `selectExactMatch` on Enter turned out
    // unreliable here: an unmatched Enter falls through to the native
    // form-submit default since only the matched branches call
    // `preventDefault`).
    const combo = form.getByRole("combobox");
    await combo.click();
    const listbox = page.locator('[role="listbox"]:visible');
    await expect(listbox).toBeVisible({ timeout: 30_000 });
    const option = listbox.getByRole("button", { name: args.newRank, exact: true });
    await expect(option).toBeVisible({ timeout: 30_000 });
    await option.click();
    await expect(combo).toHaveValue(args.newRank);
  }

  if (args.newNextRankDate) {
    const dateInput = form.getByTestId("next-rank-date-input");
    await dateInput.fill(args.newNextRankDate);
  }

  const submit = form.getByTestId("rank-correction-submit");
  await expect(submit).toBeEnabled();
  const patch = page.waitForResponse(
    r => /\/api\/soldiers\/[^/]+\/profile$/.test(new URL(r.url()).pathname) && r.request().method() === "PATCH",
  );
  await submit.click();
  const response = await patch;
  expect(response.status()).toBe(200);
}

test.describe.configure({ mode: "serial" });

test("admin edits a rank-advancement interval and it persists @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const admin = await openActorContext(browser, "admin");
  try {
    await admin.page.goto("/admin/settings");
    const monthsInput = admin.page.getByTestId("rank-interval-months-enlisted-טוראי");
    await expect(monthsInput).toBeVisible({ timeout: 30_000 });

    const currentValue = await monthsInput.inputValue();
    const newValue = String((Number(currentValue) || 10) + 5);
    await monthsInput.fill(newValue);

    // Scoped to the interval section's own heading, not button text alone --
    // the page also has an unrelated top-level "שמור" button with identical
    // text (see seam inventory). `.last()` picks the innermost matching div
    // (the section's own root), since document order lists ancestors before
    // descendants.
    const section = admin.page
      .locator("div", { has: admin.page.getByRole("heading", { name: "מרווחי עליית דרגה", exact: true }) })
      .last();
    const saveButton = section.getByRole("button", { name: "שמור" });
    await expect(saveButton).toBeEnabled();
    const put = admin.page.waitForResponse(
      r => r.url().endsWith("/api/soldiers/rank-advancement-intervals") && r.request().method() === "PUT",
    );
    await saveButton.click();
    const response = await put;
    expect(response.status()).toBe(200);

    await admin.page.reload();
    const reloadedInput = admin.page.getByTestId("rank-interval-months-enlisted-טוראי");
    await expect(reloadedInput).toBeVisible({ timeout: 30_000 });
    await expect(reloadedInput).toHaveValue(newValue);
  } finally {
    await admin.context.close();
  }
});

test("commander manually corrects a soldier's rank and next-rank-date @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const commander = await openActorContext(browser, "commander");
  try {
    await openSoldierProfileTab(commander.page, MANUAL_EDIT_SOLDIER);

    // Prove the actor genuinely reached the narrow flow -- canManage is
    // false for `commander` (neither admin nor duty manager), so this
    // toggle is the ONLY rank-editing entry point available (see seam
    // inventory correction on `canEditRankNarrow`).
    const newRank = "סמר"; // next enlisted rung after "סמל", canonical (no gershayim)
    const newNextRankDate = "2029-05-20";
    await submitRankCorrection(commander.page, { newRank, newNextRankDate });

    // Verify via a genuine full-page reload + re-open, not the in-place
    // onRefresh -- proves the PATCH's effect actually persisted server-side.
    await openSoldierProfileTab(commander.page, MANUAL_EDIT_SOLDIER);
    const modal = commander.page.getByTestId("unified-soldier-modal");
    await expect(modal.getByText(newRank, { exact: true })).toBeVisible({ timeout: 30_000 });
    // `next_rank_date_overridden` flipped true -> the "manual" badge, not
    // "automatic" -- the actual proof this was a correction, not just that
    // the date field changed.
    await expect(modal.getByText("נקבע ידנית", { exact: true })).toBeVisible({ timeout: 30_000 });
  } finally {
    await commander.context.close();
  }
});

test("a soldier due for promotion is actually promoted by the real worker function @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const commander = await openActorContext(browser, "commander");
  try {
    // Step A (browser): set the real promotion precondition on a soldier
    // DIFFERENT from the one above, via the same narrow UI flow -- leave
    // rank untouched, only set next_rank_date to today.
    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    await openSoldierProfileTab(commander.page, PROMOTION_SOLDIER);
    await submitRankCorrection(commander.page, { newNextRankDate: todayIso });

    // Step B (out-of-band, NOT a browser action): run the real promotion
    // function once, against the same database the running backend uses.
    // This is the one deliberately non-UI step in this spec -- see the
    // top-of-file seam inventory for why it's here and what it proves.
    const backendDir = resolve(dirname(fileURLToPath(import.meta.url)), "../../../../backend");
    const pythonExe = resolve(backendDir, ".venv/Scripts/python.exe");
    const databaseUrl = process.env.DATABASE_URL ?? "postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e";
    let scriptOutput: string;
    try {
      scriptOutput = execSync(`"${pythonExe}" -m app.scripts.run_rank_advancement_once`, {
        cwd: backendDir,
        env: { ...process.env, DATABASE_URL: databaseUrl },
        encoding: "utf-8",
      });
    } catch (err) {
      const e = err as { stdout?: string; stderr?: string; message: string };
      throw new Error(
        `run_rank_advancement_once.py failed: ${e.message}\nstdout: ${e.stdout ?? ""}\nstderr: ${e.stderr ?? ""}`,
      );
    }
    void scriptOutput;

    // Step C (browser): reload and re-open the soldier, asserting the real,
    // visible effect of the real promotion function -- not just that the
    // script exited 0.
    await openSoldierProfileTab(commander.page, PROMOTION_SOLDIER);
    const modal = commander.page.getByTestId("unified-soldier-modal");
    // Rank actually advanced to the next rung of the ladder.
    await expect(modal.getByText(PROMOTION_SOLDIER.nextRank, { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(modal.getByText(PROMOTION_SOLDIER.initialRank, { exact: true })).toHaveCount(0);
    // next_rank_date_overridden reset to false by _promote_soldier -> the
    // "automatic" badge, not "manual" (which is what we set it to in Step A).
    await expect(modal.getByText("חישוב אוטומטי", { exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(modal.getByText("נקבע ידנית", { exact: true })).toHaveCount(0);
    // The date itself was recomputed (not left at the today's-date manual
    // override from Step A) -- a genuinely new, future date is displayed.
    const todayDisplay = `${String(today.getDate()).padStart(2, "0")}.${String(today.getMonth() + 1).padStart(2, "0")}.${today.getFullYear()}`;
    await expect(modal.getByText(todayDisplay, { exact: true })).toHaveCount(0);
  } finally {
    await commander.context.close();
  }
});
