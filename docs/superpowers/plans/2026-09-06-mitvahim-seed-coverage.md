# Mitvahim Seed Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the second (and final) half of tracked background task `task_af3d0c50`: `ShiftAssignModal`'s constraint-override UI (already correct and already reused elsewhere) has no reachable trigger for the two non-officer weapon-tier duty types (`שמירות`, `אבט"ש`), because `backend/app/scripts/seed.py` only ever marks 2 soldiers (in one team) present at a qualifying range event — every other seeded soldier is permanently blocked by the unrelated `requires_mitvahim` structural gate before weapon-ineligibility ever becomes relevant. Confirmed by direct investigation this is a **seed-data completeness gap, not a product/backend bug**: `mark_attendance()` → `last_mitvahim_date` sync (`backend/app/services/ranges.py:781-814`) is fully implemented and production-quality; seed.py simply never exercises it beyond one team.

**Architecture:** Extend `backend/app/scripts/seed.py`'s existing range-attendance seeding pattern (already used at lines ~1722-1741 for laser/no-show/expiry demo data) to cover the broader seeded population, following the exact same `mark_attendance(..., status=present)` mechanism already proven there — no changes to `eligibility.py`, `ranges.py`, or any frontend component. Once most soldiers are realistically mitvahim-qualified, the `ShiftAssignModal`/"Replace" flow becomes reachable for a deliberately-left-unqualified minority, and the E2E spec's remaining "documented gap" test can finally become the real positive test the original plan wanted.

**Tech Stack:** Python (backend seed script), pytest, Playwright Test.

**Spec:** `docs/superpowers/specs/2026-08-28-personal-constraint-manual-override-design.md` (the override feature's design doc, which this plan finally completes E2E coverage for).

## Global Constraints

- This is a **seed-data-only backend change** — do not touch `backend/app/services/eligibility.py`, `backend/app/services/ranges.py`, or any frontend component. If implementation reveals this assumption was wrong (a real reachability bug exists even with realistic data), stop and report rather than guessing a broader fix — the research behind this plan was thorough but re-verify anything load-bearing yourself.
- Preserve the EXISTING laser-range demo block (lines ~1702-1741) exactly as-is — it deliberately exercises no-show/qualification-expiry side effects for one specific team and must keep doing so. Add a NEW, separate seeding step for company-wide coverage; don't rewrite the existing one.
- Follow seed.py's existing conventions for "most qualified, a few deliberately not" distributions (check how `last_alal_date`/other per-soldier qualification flags are already distributed across the seeded population for the established pattern to match).
- Keep at least one, clearly identifiable, deterministic (not randomly chosen) soldier without mitvahim qualification, specifically so E2E tests can reliably target them as the "weapon-ineligible original assignee." Do not leave this to chance/randomization.
- `frontend/tests/e2e/fixtures/auth.ts`'s existing `constrainedSoldier` actor (personal number `1000036`, team `ריי`) MUST end up mitvahim-qualified after this change (they need to pass the structural gate to be a valid *replacement* candidate) — verify this explicitly, don't assume.
- Verify against a freshly reseeded database, run at least twice in a row, before considering either task done.
- Do not weaken any authorization or eligibility check to make testing easier — this plan only adds realistic historical data, it does not change what the checks require.

## Known findings from research (verified against source, not guessed)

- `last_mitvahim_date` is set automatically by `mark_attendance()` → `_sync_profile_date_on_present()` (`backend/app/services/ranges.py:781-814`) whenever a soldier's range assignment attendance is marked `present` on a `laser` or `live` range event (`_MITVAHIM_RANGE_TYPES = (RangeType.laser, RangeType.live)`, line 781). This is the exact same mechanism already used for `last_alal_date` on `alal`-type events.
- The eligibility gate (`backend/app/services/eligibility.py:137-141`) blocks a candidate if `last_mitvahim_date` is unset or older than `mitvahim_months*30` days.
- Exactly two duty types require this: `שמירות` (seed.py:579) and `אבט"ש` (seed.py:635).
- Current seed.py behavior (lines 1685-1741): `range_soldiers` is scoped to ONE team (`all_teams[0]`, line 1688). Of those, only `range_soldiers[:4]` get a `RangeAssignment` at all, and only 2 of those 4 get `mark_attendance(..., present)` — the rest of the entire seeded population (100+ soldiers across all other teams) never touches this code path at all, so `last_mitvahim_date` stays `NULL` for essentially everyone.
- `constrainedSoldier` (E2E journey actor, PN `1000036`, team `ריי`) is NOT in `all_teams[0]` (confirm this directly — don't assume `all_teams[0]` isn't `ריי`'s team, check seed.py's team ordering) and is therefore currently mitvahim-unqualified under existing seed data — this is exactly why the earlier E2E work couldn't use them as a *replacement* candidate for a mitvahim-gated duty type.

---

### Task 1: Broaden mitvahim qualification seeding to the wider population

**Files:**
- Modify: `backend/app/scripts/seed.py`

**Interfaces:**
- Consumes: existing `mark_attendance()` (`backend/app/services/ranges.py`), existing `RangeEvent`/`RangeAssignment` models, existing `all_soldiers`/`all_teams` collections already built earlier in `seed()`.
- Produces: most seeded soldiers now have a realistic `last_mitvahim_date`; a small, deterministic, documented minority do not.

- [ ] **Step 1: Confirm `constrainedSoldier`'s current team assignment and mitvahim status**

  Read seed.py's team-creation loop to confirm which team is `all_teams[0]` (the one already getting mitvahim coverage) versus team `ריי` (where PN `1000036` / `constrainedSoldier` lives, per `frontend/tests/e2e/fixtures/auth.ts`). Confirm they are currently NOT overlapping (i.e., `constrainedSoldier` is currently unqualified) — this is the exact problem Task 2 needs solved.

- [ ] **Step 2: Identify a deterministic "stays unqualified" soldier for the weapon-ineligible original-assignee role**

  Pick one specific, easily-referenceable soldier (by personal number, following the existing convention of hardcoded/predictable personal numbers used elsewhere in this seed script and in `auth.ts`) who will be DELIBERATELY excluded from the new company-wide mitvahim pass. This soldier becomes the "weapon-ineligible original assignee" that Task 2's E2E test targets via the Replace flow. Document the choice with a code comment explaining why this specific soldier is excluded (mirroring the existing no-show soldier's comment style at seed.py:1737-1740).

- [ ] **Step 3: Add a new, separate seeding block for company-wide mitvahim coverage**

  After the existing laser-range demo block (which must remain untouched), add a new block that:
  - Creates one additional past `RangeEvent` (type `laser` or `live`, your choice, past-dated) OR reuses the existing block's `past_event` if that's cleaner without disturbing its existing semantics — read the surrounding code first to decide which is less invasive.
  - Creates a `RangeAssignment` for every soldier in `all_soldiers` EXCEPT the one identified in Step 2 (and except any soldiers who genuinely shouldn't be eligible for other structural reasons — check for any pre-existing exclusions like discharged/departed soldiers, and skip those too, matching how other bulk-seeding loops in this file already filter `all_soldiers`).
  - Calls `mark_attendance(..., status=RangeAttendanceStatus.present, marked_by=s_admin.id)` for each of those assignments, so `last_mitvahim_date` gets set realistically for the whole population.
  - Confirm this doesn't violate any capacity/uniqueness constraint on `RangeEvent`/`RangeAssignment` (check `required_count`/`reserve_count` fields — these look like simple integer fields for display purposes, not hard caps enforced elsewhere during seeding, but verify before assuming).

- [ ] **Step 4: Verify `constrainedSoldier` and the deliberately-excluded soldier end up in the expected states**

  Run the seed script against a scratch/E2E database and directly query the DB (or use `backend/app/scripts/tests/test_seed_bootstrap.py`'s existing pattern, if it already asserts on other qualification distributions) to confirm: `constrainedSoldier` (PN `1000036`) has `last_mitvahim_date` set; the Step 2 soldier does not.

  ```powershell
  cd backend
  .venv\Scripts\python.exe -m app.scripts.seed --db-url "postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e" --clear
  ```
  Then query directly, e.g.:
  ```sql
  SELECT personal_number, last_mitvahim_date FROM soldiers WHERE personal_number IN ('1000036', '<step-2-soldier-pn>');
  ```

- [ ] **Step 5: Run backend tests**

  ```bash
  cd backend
  .venv\Scripts\python.exe -m pytest -q -k "seed or mitvahim or range"
  ```
  All must pass. If any existing test asserted on the OLD (narrow) mitvahim distribution — e.g., a specific count of mitvahim-qualified soldiers, or an assumption that only one team has range history — read and update that test to match the new, intentionally broader reality, rather than reverting your seed change to keep an incidental old assertion green.

- [ ] **Step 6: Run the full backend fast suite**

  ```bash
  cd backend
  .venv\Scripts\python.exe -m pytest -q
  ```
  Confirm no unrelated regressions. Treat any failure here as either a real regression from this change (fix the seed change) or a pre-existing/unrelated flake (verify by checking if the same test fails on `dev` before this branch — don't assume without checking).

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/scripts/seed.py
  git commit -m "fix: seed realistic mitvahim range-qualification history for most soldiers"
  ```

---

### Task 2: E2E — the real positive test for duty-side override via the Replace flow (finally closing task_af3d0c50)

**Files:**
- Modify: `frontend/tests/e2e/smoke/personal_constraint_override.spec.ts`
- Modify: `docs/e2e-coverage-matrix.md`

**Context:** This spec currently has a test documenting that the weapon-ineligible-original-assignee precondition was unreachable (from the earlier, now-outdated investigation). Task 1 makes it reachable. This task replaces that test with the ORIGINAL positive scenario the very first version of this plan wanted: select `constrainedSoldier` (now mitvahim-qualified, with their pre-existing approved personal constraint) as a replacement for a deliberately-unqualified original assignee, via `ShiftDetailPanel`'s "Replace" button → `ShiftAssignModal` → `ConstraintWarningIcon` → `OverrideReasonModal` → confirm → real assignment. Also add the reason-required negative case that was dropped earlier for lack of a reachable positive case (it now has one).

**Interfaces:**
- Reuses: `constrainedSoldier` and the existing constraint-setup helper already in this spec file.
- New: needs to reference Task 1's deliberately-unqualified soldier (by personal number) as the shift's original assignee — read Task 1's actual choice from its commit/report before hardcoding this in the test.

- [ ] **Step 1: Read the current spec file's remaining "documented gap" test and seam-inventory header in full**

  Confirm exactly what's currently asserted (the precondition is unreachable) so you replace it accurately.

- [ ] **Step 2: Set up a duty assignment where the original assignee is genuinely weapon-ineligible**

  Using a `שמירות` or `אבט"ש` shift (far-future date, established offset convention), manually assign Task 1's deliberately-unqualified soldier as the original primary via the standard bulk modal (this should now succeed for THAT soldier specifically on a non-mitvahim-gated step, or — if the shift itself IS mitvahim-gated — confirm how a mitvahim-INeligible soldier can still be initially assigned at all; read `ShiftDetailPanel.tsx`'s weapon-ineligible detection logic to confirm whether initial assignment happens through a path that doesn't hard-block on mitvahim, e.g. algorithm-published assignments computed before eligibility changes, or whether you need a different setup order — verify this against real behavior, the plan's assumption here may need adjustment once you see it live).

- [ ] **Step 3: Test — Replace flow override succeeds with a reason**

  As `dutyManager`, open the shift's detail panel, click "Replace" (`t("weapon_ineligible.replace")`), confirm `ShiftAssignModal` opens, confirm `constrainedSoldier`'s row shows `ConstraintWarningIcon` (proving they're a real, constraint-flagged candidate — not hard-blocked, since they're now mitvahim-qualified), select them, confirm, fill `OverrideReasonModal`'s reason, confirm. Wait for the real assign/replace endpoint's 2xx with `override_reason` in the request body. Refresh and assert `constrainedSoldier` now shows as the real assignee (visible UI state).

- [ ] **Step 4: Test — omitting the override reason is rejected**

  Repeat candidate selection, but attempt to confirm `OverrideReasonModal` with an empty reason. Assert the assignment is NOT made (check whether the confirm button is client-side disabled on empty input, or whether it submits and the server rejects — assert whichever is actually true, per `OverrideReasonModal.tsx`'s real behavior, already confirmed generic/shared across all three modals using it).

- [ ] **Step 5: Update the seam-inventory header**

  Remove the "unreachable precondition" gap language entirely — `task_af3d0c50` is now fully closed on both halves. Note the seed.py change this relied on (Task 1's commit) so a future reader understands why this became testable.

- [ ] **Step 6: Run against a freshly seeded DB, twice**

  ```powershell
  cd backend
  .venv\Scripts\python.exe -m app.scripts.seed --db-url "postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e" --clear
  cd ..\frontend
  Remove-Item -Recurse -Force .playwright\auth
  npx playwright test --grep personal_constraint_override --project=desktop --retries=0
  ```
  All tests in the file must pass, twice, with no retries.

- [ ] **Step 7: Update the coverage matrix**

  Update the existing `personal_constraint_override` row: `task_af3d0c50` is now fully resolved (both halves), cite Task 1's and Task 2's commits.

- [ ] **Step 8: Commit**

  ```bash
  git add frontend/tests/e2e/smoke/personal_constraint_override.spec.ts docs/e2e-coverage-matrix.md
  git commit -m "test: prove duty-side constraint override via the Replace flow end to end"
  ```

## Verification commands

```bash
cd backend
.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npx playwright test --grep personal_constraint_override --project=desktop --retries=0
```

Before claiming completion: confirm fresh-database repeatability (2x) for the E2E run, confirm the backend fast suite is clean (no regressions from the broadened seed data), confirm `constrainedSoldier` and the deliberately-unqualified soldier are both deterministic (not randomly chosen) and documented, and confirm the coverage matrix and seam-inventory header now accurately say `task_af3d0c50` is fully closed.
