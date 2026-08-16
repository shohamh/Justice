# Rank advancement enlistment anchoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calculate initial next-rank dates cumulatively from enlistment, preserve promotion-date chaining for system promotions, and restrict rank/date corrections to admins or in-scope מדור-and-above commanders/duty managers.

**Architecture:** Keep the existing `RankAdvancementInterval` table and `current_rank_since` model. Add a pure service-level distinction between an initial/manual rank schedule (cumulative from enlistment) and a system-promotion schedule (current-rank-since plus one interval). Centralize rank-correction authorization in the authority service, expose a per-soldier capability in the existing Soldier DTO, and let the modal render either the existing full profile editor or a narrow rank/date editor.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest/testcontainers, React/TypeScript, Vitest, Testing Library, react-i18next.

**Spec:** `docs/superpowers/specs/2026-08-16-rank-advancement-enlistment-anchoring.md`

## Global Constraints

- Initial/manual rank setup calculates the next rank by summing configured intervals from the first rank in the active track through the current rank and adding the total to `enlistment_date`.
- System promotions calculate the successor date from the actual promotion date and set `current_rank_since` to that date.
- Explicit next-rank dates are manual corrections and set `next_rank_date_overridden = true`; interval recomputation must skip them.
- Admins bypass rank-correction authorization. Non-admin authorization requires a commander direct-command root or duty-manager scope root at level מדור or above that contains the target.
- Lower-level commanders and duty managers cannot edit rank, rank track, or next-rank date through any direct API path.
- No database migration is needed.
- Preserve unrelated dirty files in the main checkout; all implementation commits land on `feat/rank-advancement-initial-date`, based on `dev`.

---

### Task 1: Add cumulative initial scheduling and preserve promotion-date chaining

**Files:**
- Modify: `backend/app/services/rank_advancement.py`
- Modify: `backend/app/services/registration.py`
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/app/services/soldiers.py`
- Modify: `backend/app/routes/enrollment.py`
- Test: `backend/app/services/tests/test_rank_advancement.py`
- Test: `backend/tests/unit/test_soldiers_field_updates.py`
- Test: `backend/tests/integration/test_soldier_profile.py`
- Test: `backend/tests/integration/test_enrollment_routes.py`

**Interfaces:**
- Produce `compute_initial_next_rank_date(session, *, rank, enlistment_date, fallback_since, track=None) -> date | None` in `app.services.rank_advancement`.
- Produce `compute_next_rank_date_for_soldier(session, *, soldier) -> date | None`, which uses cumulative enlistment anchoring when `current_rank_since` is absent/equal to enlistment and uses `current_rank_since + current-rank interval` after a system promotion.
- Existing worker callers of `compute_next_rank_date(... since=today)` remain unchanged.

- [ ] **Step 1: Write the failing cumulative-calculation tests.**

  Add a service test proving the enlisted defaults produce enlistment + 56 months for current rank סמ"ר, with an independent literal expected date. Add a configured-interval test proving the helper sums the configured values for טוראי, רבט, סמל, and סמר rather than using only סמר's interval. Add tests for no enlistment fallback and for a NULL segment returning `None`.

- [ ] **Step 2: Run the focused tests and verify the expected RED failure.**

  Run:

  ```powershell
  & 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_rank_advancement.py -k "initial or cumulative" -q
  ```

  Expected result: the new tests fail because the cumulative helper does not yet exist.

- [ ] **Step 3: Implement the smallest domain helper.**

  Walk `_LADDERS[track]` through the current rank, call `get_interval_months` for each rank in order, return `None` on an unknown track/rank or NULL interval, and add the sum with `relativedelta(months=total)` to enlistment. If enlistment is absent, delegate to the existing one-interval `compute_next_rank_date` using `fallback_since`.

- [ ] **Step 4: Add the soldier-anchor helper and update initial/manual writers.**

  Make registration, import, profile rank changes, and enrollment rank changes set `current_rank_since` to `enlistment_date` (or their existing fallback) and call the cumulative helper. Keep explicit imported/profile next dates untouched and overridden. Update interval recomputation to use cumulative anchoring for initial/manual rows and the current-rank-since interval for system-promoted rows.

- [ ] **Step 5: Add regression tests for writer behavior and system chaining.**

  Extend the existing registration/profile/import/enrollment tests to assert a סמ"ר soldier's next date is enlistment + 56 months and `current_rank_since` equals enlistment. Keep/extend the worker test that promotes on a known date and asserts the successor date is promotion date + the successor interval, not enlistment-based. Add an interval-recompute test for a cumulative initial row and retain the overridden-row skip test.

- [ ] **Step 6: Run the complete focused backend slice.**

  Run:

  ```powershell
  & 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_rank_advancement.py backend/tests/unit/test_rank_advancement_worker.py backend/tests/unit/test_soldiers_field_updates.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_enrollment_routes.py -q
  ```

  Expected result: all focused tests pass with no new warnings beyond the repository's existing testcontainer deprecation warning.

- [ ] **Step 7: Commit the vertical slice.**

  ```powershell
  git add backend/app/services/rank_advancement.py backend/app/services/registration.py backend/app/services/import_sessions.py backend/app/services/soldiers.py backend/app/routes/enrollment.py backend/app/services/tests/test_rank_advancement.py backend/tests/unit/test_soldiers_field_updates.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_enrollment_routes.py
  git commit -m "feat: anchor initial rank dates to enlistment"
  ```

### Task 2: Enforce scoped rank/date correction authority and expose the API contract

**Files:**
- Modify: `backend/app/services/authority.py`
- Modify: `backend/app/routes/soldiers.py`
- Modify: `backend/app/routes/enrollment.py`
- Modify: `backend/app/routes/soldiers.py` (the existing field-update decision routes live here)
- Test: `backend/app/services/tests/test_authority.py`
- Test: `backend/tests/integration/test_soldier_profile.py`
- Test: `backend/tests/integration/test_soldiers_api.py`
- Test: `backend/tests/integration/test_enrollment_routes.py`
- Test: `backend/tests/unit/test_soldiers_field_updates.py`

**Interfaces:**
- Produce `rank_advancement_edit_authorized(session, *, user, target_node) -> bool` in `app.services.authority`.
- Extend `SoldierOut` with `next_rank_date`, `next_rank_date_overridden`, and `can_edit_rank_advancement`.
- Extend `UpdateProfileRequest` with an explicitly distinguishable `next_rank_date: date | None` field; omitted means no change and explicit null means restore automatic calculation.

- [ ] **Step 1: Write failing authority tests.**

  Add tests for a commander and duty manager whose root is מדור (allowed), a root above מדור (allowed), and a root below מדור (denied). For each, cover a target inside the root and a target outside it. Add admin bypass and a user with only a lower-level scope. Use the existing hierarchy rank convention where lower numeric rank is more senior.

- [ ] **Step 2: Run authority tests to verify RED.**

  ```powershell
  & 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_authority.py -k "rank_advancement" -q
  ```

  Expected result: the new tests fail because the shared predicate does not exist.

- [ ] **Step 3: Implement the shared predicate.**

  Check admin first. For commanders, inspect only `HierarchyNode.commander_id == user.id`; for duty managers, inspect only `DutyManagerScope` roots. Reuse `dm_scope_covers_target(... required_level_key="מדור")` for each root set so the root both meets the threshold and contains the target node. Return false for missing target nodes.

- [ ] **Step 4: Write failing API authorization and override tests.**

  Add profile endpoint cases proving: an eligible commander can set `next_rank_date` and rank; an eligible duty manager can do the same; lower-level commander/duty manager receives 403; out-of-scope eligible actors receive 403; admin succeeds. Assert explicit date sets the override flag, interval changes do not overwrite it, and explicit null restores the automatic date and clears the flag. Assert Soldier responses include the date, override state, and capability.

- [ ] **Step 5: Implement route and service enforcement.**

  Preserve ordinary profile authorization for non-rank fields. Before applying any supplied `rank`, `rank_track`, `is_officer`, or `next_rank_date` field, require `rank_advancement_edit_authorized`; reject mixed requests from actors who lack both ordinary profile authority and rank authority. Use `model_fields_set` so omitted `next_rank_date` is different from explicit null. Keep the service's override flag and cumulative-reset behavior consistent with Task 1.

  Apply the same rank-write guard to enrollment approval and rank field-update approval so a lower-level actor cannot bypass the profile endpoint. Do not restrict initial registration or authorized import creation.

- [ ] **Step 6: Compute and return the frontend capability.**

  When building Soldier DTOs, calculate `can_edit_rank_advancement` against the requesting user and target node. Keep rank/date fields visible according to existing soldier visibility rules, but never rely on the flag alone for authorization.

- [ ] **Step 7: Run the focused backend authorization slice.**

  ```powershell
  & 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_authority.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_soldiers_api.py backend/tests/integration/test_enrollment_routes.py backend/tests/unit/test_soldiers_field_updates.py -q
  ```

- [ ] **Step 8: Commit the API/authorization slice.**

  ```powershell
  git add backend/app/services/authority.py backend/app/routes/soldiers.py backend/app/routes/enrollment.py backend/app/routes/field_updates.py backend/app/services/soldiers.py backend/app/services/tests/test_authority.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_soldiers_api.py backend/tests/integration/test_enrollment_routes.py backend/tests/unit/test_soldiers_field_updates.py
  git commit -m "feat: scope rank corrections to senior supervisors"
  ```

### Task 3: Add the narrow modal correction flow

**Files:**
- Modify: `frontend/src/api/soldiers.ts`
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/components/UnifiedSoldierModal.test.tsx`
- Test: `frontend/src/api/soldiers.test.ts` if API request/response coverage is needed by the existing frontend test pattern

**Interfaces:**
- `SoldierDTO` includes `next_rank_date: string | null`, `next_rank_date_overridden: boolean`, and `can_edit_rank_advancement: boolean`.
- `updateSoldierProfile` accepts `next_rank_date?: string | null`.

- [ ] **Step 1: Write failing modal tests.**

  Add a test fixture with a next-rank date and capability. Assert the profile view displays the date and an automatic/manual indication. Add an eligible commander/duty-manager auth fixture that can open only the narrow rank/date editor, submits the chosen rank-track/date, and calls `updateSoldierProfile` with those exact fields. Add an ineligible commander fixture that has no rank/date edit control. Preserve the existing rejected-save re-enable test.

- [ ] **Step 2: Run the modal tests and verify RED.**

  From the frontend directory run:

  ```powershell
  npm test -- --run src/components/UnifiedSoldierModal.test.tsx
  ```

  Expected result: the new tests fail because the DTO fields and narrow editor do not exist.

- [ ] **Step 3: Implement the API types and Hebrew labels.**

  Add the three DTO fields and optional update field. Add concise Hebrew labels for next-rank date, automatic/manual status, and the narrow rank correction action.

- [ ] **Step 4: Implement the modal behavior.**

  Show the next-rank date in read-only profile details. Keep the existing full editor for users with ordinary profile-edit authority, but disable/hide rank-sensitive fields when `can_edit_rank_advancement` is false. Add a profile-only narrow edit action for a capable commander/duty manager who lacks ordinary profile-edit authority; it edits rank, rank track, and next-rank date only. Clearing the date sends explicit `null`. Keep all save errors translated and ensure saving state is always released.

- [ ] **Step 5: Run frontend focused verification.**

  ```powershell
  npm test -- --run src/components/UnifiedSoldierModal.test.tsx
  npm run typecheck
  npm run lint
  ```

- [ ] **Step 6: Commit the frontend slice.**

  ```powershell
  git add frontend/src/api/soldiers.ts frontend/src/components/UnifiedSoldierModal.tsx frontend/src/components/UnifiedSoldierModal.test.tsx frontend/src/i18n/he.json
  git commit -m "feat: add scoped rank correction modal"
  ```

### Final verification

- [ ] Run the complete backend fast suite from the worktree.
- [ ] Run the complete frontend test suite, typecheck, and lint.
- [ ] Review `git diff dev...HEAD` for accidental unrelated changes and verify the worktree contains only the intended commits/files.
- [ ] Run `git diff --check`.
- [ ] Perform the required task reviews and final whole-branch review before integration; do not merge directly to `master` or `dev`.
