# Personal Constraint Override E2E Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-browser E2E coverage proving the personal-constraint-override feature (already merged to `dev`) behaves correctly end to end: a duty manager can manually assign a soldier who has an approved personal constraint, given an override reason, while the CP-SAT algorithm's auto-assign path always hard-excludes that same soldier — and document the real (asymmetric) behavior of range auto-select, which does not hard-exclude the same way.

**Architecture:** Same pattern as the existing `frontend/tests/e2e/smoke/*.spec.ts` suite: real FastAPI + PostgreSQL backend, role-based browser contexts, every mutation confirmed via `page.waitForResponse`, a seam-inventory header comment, `test.describe.configure({ mode: "serial" })`.

**Tech Stack:** Playwright Test, Chromium, FastAPI, PostgreSQL, Alembic, TypeScript.

**Spec:** `docs/superpowers/specs/2026-08-28-personal-constraint-manual-override-design.md` (the original feature's design doc — this plan tests it, not extends it) and `docs/superpowers/specs/2026-09-01-browser-automation-strategy.md` (the E2E harness's own strategy doc).

## Global Constraints

- Test Chrome desktop only (matches the other four recently-added journeys' scope decision).
- Use the real frontend, backend, and PostgreSQL stack. Never use `page.request`/direct DB writes to perform the mutation under test — only to *read* already-authenticated state when a UI selector is otherwise ambiguous.
- Do not enable video by default; keep trace/screenshot-on-failure.
- Preserve Hebrew/RTL behavior; assert user-visible translated states.
- Do not weaken backend authorization to make setup easier.
- **Verify against a freshly reseeded database, run at least twice in a row**, before considering this done — `backend/app/scripts/seed.py --db-url <e2e db> --clear`. Seeded `PersonalConstraint` rows are randomized (no fixed seed) and not guaranteed approved — do not rely on them; create and approve the test's own constraint through the UI.
- Where a UI-driven step turns out to target state that cannot actually be reached through the UI (the `ShiftEditAssignmentsModal` override gap below), do not force it — scope the test to what a real user can do and say so in the spec's seam-inventory comment.
- Where the real backend behavior differs from a plausible assumption (range auto-select's soft-conflict vs. CP-SAT's hard-exclusion), assert the *actual* behavior, not the assumption — and say so in the seam-inventory comment so a future reader isn't confused about why the two auto-paths are tested differently.

## Known findings from research (verified against source, not guessed)

- **Constraint creation/approval**: soldier submits at `/my-requests` (`constraint-form-toggle` → `constraint-form-card`, fields `req-start`/`req-end`/`req-reason`/`req-submit`) → `POST /api/me/constraints`. Two-stage approval at `/approvals?tab=constraints` (`[data-testid^="approval-row-"]`, stage badge `constraint-stage-*`) → commander approves first, then duty manager → `POST /api/constraints/{id}/approve` each time; status only becomes `"approved"` after both stages.
- **Duty manual override — real UI gap**: `ShiftEditAssignmentsModal.tsx` (the modal opened by `manual-assignment-open-${shiftId}`, used throughout `multi_user_duty_problems.spec.ts`) has **no override-reason UI at all**. It only hard-disables a candidate when `blocked_reason === "constraint"` (which only happens if `constraints.allow_manual_override` is off). With the default setting (on), a constrained candidate looks like an ordinary selectable row there, and saving will 400 with `override_reason_required` — there's no way to supply a reason through that modal. The only working override UI for duties is `ShiftAssignModal.tsx`, reachable via `ShiftDetailPanel.tsx`'s weapon-ineligible "Replace" button (`t("weapon_ineligible.replace")`, plain text, no testid) when replacing an existing assignment. This is a real, pre-existing product gap — the plan does not fix it, only documents and works around it by testing through the one path that actually works.
- **Range manual override — works as expected**: `RangeEditAssignmentsModal.tsx` detects `personal_constraint_conflict` among selected candidates in `saveSelection()` (~line 180), opens `OverrideReasonModal` (no testids — use `getByRole("textbox")` for the reason, `getByRole("button", { name: /אישור/ })` to confirm), then calls `batchAssignRange(..., override_reason)` → `POST /api/ranges/{id}/assignments/batch`.
- **`OverrideReasonModal`** is shared between the duty and range flows — same selector strategy works for both.
- **CP-SAT auto-assign — always hard-excludes**: `backend/app/algorithm/availability.py:47` adds `"personal_constraint"` to a soldier's blockers unconditionally, regardless of the `constraints.allow_manual_override` setting. No UI surfaces *why* a soldier is excluded — verify indirectly: after running and publishing the algorithm, the constrained soldier never appears in the resulting assignments.
- **Range auto-select — soft conflict, not hard exclusion**: `range-auto-select-primary`/`range-auto-select-reserve` (`RangeEditAssignmentsModal.tsx:396,432`) slice from the ranked candidate list with **no filter** on `personal_constraint_conflict`. The constrained soldier CAN be auto-selected (backend `rank_candidates_with_excluded`, `backend/app/services/range_auto_assign.py:472`, only hard-excludes when `manual_override_allowed()` is False — not the default). So with the default setting, auto-select can pick the constrained soldier, and *saving* that selection then requires the same override-reason gate as a manual pick. This is asymmetric with CP-SAT and is the real, current behavior — test it as such, not as a hard exclusion.
- **Setting**: `constraints.allow_manual_override` (`backend/app/services/constraint_override_settings.py:7`, `MANUAL_OVERRIDE_KEY`), default `True` (`manual_override_allowed()` returns `True` on `SettingNotFound`). No toggle needed for the override-succeeds scenarios. Toggling it off is only needed for the separate "blocked entirely" scenario (Task 1, Step 6).

---

### Task 1: Duty-side override and CP-SAT exclusion (`frontend/tests/e2e/smoke/personal_constraint_override.spec.ts`)

**Files:**
- Create: `frontend/tests/e2e/smoke/personal_constraint_override.spec.ts`
- Modify: `frontend/tests/e2e/fixtures/auth.ts` — add one journey actor: `constrainedSoldier` (next free personal number after the existing highest journey actor — confirm the current ceiling against `backend/app/scripts/seed.py`'s soldier count before picking)
- Modify: `docs/e2e-coverage-matrix.md`

**Interfaces:**
- Constraint submit/approve: see Known Findings above.
- Duty override path: `ShiftDetailPanel` (opened from `/unit-calendar` or a duty's detail view) → weapon-ineligible "Replace" button (`t("weapon_ineligible.replace")`) → `ShiftAssignModal` → candidate row shows `ConstraintWarningIcon` (component file `frontend/src/components/ConstraintWarningIcon.tsx` — read it for the exact rendered marker/title text before writing a selector) → selecting the constrained candidate and confirming opens `OverrideReasonModal` → `POST /api/shifts/{shift_id}/assign-batch` (or whatever the replace endpoint actually is — confirm by reading `ShiftAssignModal.tsx`'s submit handler) with `override_reason`.
- Weapon-ineligibility precondition: the "Replace" button only appears for a weapon-ineligible original assignee. Read `backend/app/scripts/seed.py` for which duty types already have `requires_weapon=true` (research on the ranges task found "שמירות"/"ליווים" flipped on) and which seeded soldier is weapon-ineligible, to set this precondition up with the least new fixture data — or create a fresh duty+assignment where the original soldier is weapon-ineligible if no clean seeded fixture exists.
- CP-SAT path: reuse the `createAndPublishAlgorithmDuty`-style helper from `multi_user_duty_problems.spec.ts` (copy/adapt), but ensure `constrainedSoldier` is in the algorithm's eligible pool for the duty type/dates used, so their absence from the published result is a meaningful assertion (not just "never eligible for unrelated reasons").

- [ ] **Step 1: Add the journey actor**

  Confirm the next free personal number, add `constrainedSoldier` to `journeyActors` in `frontend/tests/e2e/fixtures/auth.ts`.

- [ ] **Step 2: Write the spec skeleton with a seam-inventory header comment**

  Document both the `ShiftEditAssignmentsModal` gap and the CP-SAT-vs-range-auto-select asymmetry explicitly in the header, matching the convention established in `swaps.spec.ts`/`ranges.spec.ts`/`hierarchy_transfers.spec.ts`/`rank_advancement.spec.ts`.

- [ ] **Step 3: Shared setup — create and fully approve a personal constraint for `constrainedSoldier`**

  As `constrainedSoldier`, submit a constraint at `/my-requests` covering a far-future date range (matching the established date-offset convention to avoid cross-spec collisions). As `commander`, approve stage 1 at `/approvals?tab=constraints`. As `dutyManager`, approve stage 2. Wait for both `POST /api/constraints/{id}/approve` calls to return 2xx, and confirm the constraint's status is genuinely `"approved"` before proceeding (read it back, e.g. via the soldier's own `/my-requests` view showing an approved badge — read `PersonalConstraintsPage`/`MyRequestsPage`'s actual status-badge rendering to assert the correct visible text).

- [ ] **Step 4: Test — manual override with a reason succeeds (via the working `ShiftAssignModal`/Replace path)**

  Set up a duty assignment where the original assignee is weapon-ineligible and the duty's dates overlap `constrainedSoldier`'s approved constraint. As `dutyManager`, open the duty's detail panel, click "Replace," select `constrainedSoldier` (confirm the `ConstraintWarningIcon` is visible on their row first — this proves the warning surfaced, not just that assignment happened to succeed), fill the `OverrideReasonModal`'s reason field, confirm. Wait for the assign endpoint's 2xx. Refresh and assert `constrainedSoldier` now shows as the assignee (visible UI state, not just the response).

- [ ] **Step 5: Test — omitting the override reason is rejected**

  Repeat the same selection but attempt to confirm the `OverrideReasonModal` with an empty reason (or attempt to close/bypass it) — assert the assignment is NOT made (no successful assign-batch/replace call, and refreshing shows the original assignee unchanged). Read `OverrideReasonModal.tsx` first to confirm whether the confirm button is simply disabled on an empty reason (client-side gate) or whether it submits and the server rejects with `override_reason_required` (assert whichever is actually true, don't assume).

- [ ] **Step 6: Test — the standard `ShiftEditAssignmentsModal` bulk path cannot override (documents the real gap)**

  Using the standard `manual-assignment-open-${shiftId}` bulk modal (the one already exercised in `multi_user_duty_problems.spec.ts`), attempt to select `constrainedSoldier` as a primary candidate and save. Assert this fails with a visible error (the 400 `override_reason_required` surfacing as some user-visible message — read `ShiftEditAssignmentsModal.tsx`'s error-handling to know the exact rendered text) rather than silently succeeding or silently doing nothing. This is a real product gap this test documents, not a defect in the test — say so in the test's own comment.

- [ ] **Step 7: Test — CP-SAT auto-assign always excludes the constrained soldier**

  Create and run an algorithm job (reusing/adapting the `createAndPublishAlgorithmDuty` helper) for a duty type/date range where `constrainedSoldier` would otherwise be eligible and in scope, publish the result, and assert `constrainedSoldier` does not appear among the published assignments for that job (check via the visible assignment list/table, not an API read). If the algorithm's eligible-candidate pool is hard to control precisely enough to make this assertion meaningful, use `/api/algorithm/jobs/{id}` (or whatever read-only endpoint the UI itself already calls) intercepted from the page's own request to confirm `constrainedSoldier` was actually in the input pool before asserting their absence from the output — otherwise the assertion proves nothing.

- [ ] **Step 8: Run against a freshly seeded DB, twice**

  ```powershell
  cd backend
  .venv\Scripts\python.exe -m app.scripts.seed --db-url "postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e" --clear
  cd ..\frontend
  Remove-Item -Recurse -Force .playwright\auth
  npx playwright test --grep personal_constraint_override --project=desktop --retries=0
  ```
  Repeat twice. Both runs must pass with no retries.

- [ ] **Step 9: Commit**

  ```bash
  git add frontend/tests/e2e/smoke/personal_constraint_override.spec.ts frontend/tests/e2e/fixtures/auth.ts
  git commit -m "test: cover duty-side personal constraint override and CP-SAT hard exclusion"
  ```

---

### Task 2: Range-side override and auto-select's soft-conflict behavior (same spec file, additional tests)

**Files:**
- Modify: `frontend/tests/e2e/smoke/personal_constraint_override.spec.ts` (add tests to the same file — shares the Task 1 setup helper for constraint creation/approval)
- Modify: `docs/e2e-coverage-matrix.md`

**Interfaces:**
- Range override path: `RangesPage` → `view-assignments-{eventId}` → `RangeEditAssignmentsModal` → candidate row shows a `personal_constraint_conflict` marker (title/text at ~line 527-539 — read the current file for the exact rendered text/attribute) → selecting the constrained candidate and saving triggers the same `OverrideReasonModal` pattern as Task 1 → `POST /api/ranges/{event_id}/assignments/batch` with `override_reason`.
- Auto-select: `range-auto-select-primary`/`range-auto-select-reserve` buttons — clicking these can include the constrained soldier in the auto-selected set (soft conflict, not hard exclusion). The meaningful assertion here is NOT "auto-select never picks them" (that's false for ranges) — it's "if auto-select's result includes the constrained soldier, saving still requires the override reason, same as a manual pick."

- [ ] **Step 1: Test — range manual override with a reason succeeds**

  Create a range event (far-future date, reusing the established offset convention) as `dutyManager`, open `view-assignments-{eventId}`, select `constrainedSoldier` as a candidate (confirm the conflict marker is visible first), save with an override reason via `OverrideReasonModal`. Wait for the batch-assign 2xx. Refresh and assert `constrainedSoldier` appears in the event's roster.

- [ ] **Step 2: Test — range auto-select's real behavior (soft conflict, not hard exclusion)**

  Set up a range event where `constrainedSoldier` is otherwise a strong/eligible candidate. Click `range-auto-select-primary` (or reserve). Read the resulting selection: if `constrainedSoldier` is included, assert that saving without an override reason is rejected the same way as Step 1 of Task 1 (client-side gate or server 400 — confirm which), and saving with a reason succeeds. If `constrainedSoldier` is NOT included (auto-select's ranking happened not to pick them for scoring reasons unrelated to the constraint), do not force the scenario — adjust the fixture (e.g. make `constrainedSoldier` clearly the top-ranked candidate by burden/score) until the auto-selected set does include them, so the test actually exercises the soft-conflict-then-override path rather than passing vacuously.

- [ ] **Step 3: Run against a freshly seeded DB, twice** (`--grep personal_constraint_override`, same procedure as Task 1 Step 8)

- [ ] **Step 4: Update the coverage matrix and commit**

  Add a row to `docs/e2e-coverage-matrix.md` explicitly noting: duty manual override tested via the `ShiftAssignModal`/Replace path (the only working one) with the `ShiftEditAssignmentsModal` gap documented as a known follow-up; CP-SAT hard-excludes unconditionally; range manual override works directly through `RangeEditAssignmentsModal`; range auto-select is a soft conflict requiring the same override gate on save, not a hard exclusion — do not describe range auto-select as "excluding" the constrained soldier, since it doesn't.

  ```bash
  git add frontend/tests/e2e/smoke/personal_constraint_override.spec.ts docs/e2e-coverage-matrix.md
  git commit -m "test: cover range-side personal constraint override and auto-select conflict handling"
  ```

---

## Verification commands

Run from `frontend`, against a freshly reseeded E2E database (see Global Constraints):

```powershell
npx playwright test --grep personal_constraint_override --project=desktop --retries=0
```

Run at least twice from a clean reseed before considering this plan done. Before claiming completion, verify: fresh-database repeatability (2x), the Step 5/Task-1 and Step 6/Task-1 negative-path assertions actually distinguish success from failure (not just "didn't throw"), the CP-SAT exclusion assertion is backed by confirming the soldier was actually in the eligible pool first, and the coverage-matrix row accurately describes the CP-SAT/range-auto-select asymmetry rather than glossing over it.
