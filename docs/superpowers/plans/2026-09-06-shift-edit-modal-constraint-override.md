# Shift Edit Modal Constraint Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close a real product gap found during E2E test coverage work (tracked as `task_af3d0c50`): `ShiftEditAssignmentsModal` — the standard bulk duty-assignment modal — has no way to supply a personal-constraint override reason, so assigning a constrained soldier through the normal assignment path always fails server-side with `override_reason_required` and no UI recourse. Two sibling modals (`RangeEditAssignmentsModal`, `ShiftAssignModal`) already implement this exact flow correctly with a shared `OverrideReasonModal` component; this plan replicates that proven pattern into `ShiftEditAssignmentsModal`.

**Architecture:** Pure frontend change. The backend (`POST /shifts/{id}/assign-batch`) already accepts and forwards `override_reason` — confirmed by reading `backend/app/routes/shifts.py:944-1033`. The candidate payload already includes `personal_constraint_warning` — confirmed by reading `frontend/src/api/assignments.ts:54-73`. No schema or endpoint changes anywhere in this plan.

**Tech Stack:** React, TypeScript, Vitest + Testing Library (component tests), Playwright (E2E verification of the fixed flow).

**Spec:** `docs/superpowers/specs/2026-08-28-personal-constraint-manual-override-design.md` (the original override feature's design doc, which this plan completes the UI coverage for).

## Global Constraints

- Reuse the existing `OverrideReasonModal` component verbatim — do not create a second, divergent implementation.
- Match `ShiftAssignModal.tsx`'s exact field name and semantics: `personal_constraint_warning` (not `RangeEditAssignmentsModal`'s `personal_constraint_conflict`, which is a different, range-specific type on a different candidate shape).
- Follow TDD: write the failing test first for each new behavior, then implement.
- Preserve the existing conditional `override_reason` spread pattern (`...(overrideReason ? { override_reason: overrideReason } : {})`) so the existing test asserting `assignBatch` is called *without* the key for an unconstrained candidate keeps passing unmodified.
- Preserve Hebrew/RTL UI conventions already used elsewhere in this file (existing `BLOCKED_REASON_LABEL`-style Hebrew strings, RTL layout).
- Do not touch the existing hard-block behavior (`blocked_reason === "constraint"`, which fires only when override is disabled in settings) — that path is correct as-is and out of scope.

## Known findings from research (verified against source, not guessed)

- `handleSave()` (`ShiftEditAssignmentsModal.tsx:260-279`) currently calls `assignBatch(shift.id, { primaries: [...], reserves: [...] })` directly, with no conflict check and no override-reason collection.
- `ShiftCandidate` (`frontend/src/api/assignments.ts:62-73`) already carries `personal_constraint_warning: PersonalConstraintWarning | null` and `blocked_reason: "constraint" | "assignment" | "ineligible" | null` — both already fetched, `personal_constraint_warning` just currently unused in this component.
- Reference implementation to copy from, `ShiftAssignModal.tsx`:
  - `continueAssign()` (lines 158-166): before saving, checks `candidates.some(c => selectedIds.has(c.soldier_id) && c.personal_constraint_warning)`; if true, defers to the override modal instead of saving directly.
  - `doAssign(overrideReason?)` (lines 176-190): spreads `override_reason` into the API call only when present.
  - Auto-select exclusion (lines 137-156): `selectAllPrimary`/`autoSelectReserves` filter out `c.personal_constraint_warning`-flagged candidates so bulk auto-select doesn't silently sweep in a constrained soldier without a human noticing.
  - `OverrideReasonModal` import and instantiation pattern (imports from `./OverrideReasonModal`, same component `RangeEditAssignmentsModal` uses).
- `OverrideReasonModal` (`frontend/src/components/OverrideReasonModal.tsx:1-53`) props: `{ open: boolean; count: number; onCancel: () => void; onConfirm: (reason: string) => void }`. Self-contained state, confirm disabled until non-empty reason.
- Existing test file `ShiftEditAssignmentsModal.test.tsx` has exactly 2 tests: a render/testid check, and an unconstrained-candidate save asserting `assignBatch` is called *without* an `override_reason` key. No existing coverage for constrained candidates, the warning UI, or the override flow.

---

### Task 1: Add the constraint-warning indicator and override flow to `ShiftEditAssignmentsModal`

**Files:**
- Modify: `frontend/src/components/ShiftEditAssignmentsModal.tsx`
- Modify: `frontend/src/components/ShiftEditAssignmentsModal.test.tsx`

**Interfaces:**
- Consumes: `OverrideReasonModal` (existing, unchanged) — `{ open, count, onCancel, onConfirm }`.
- Consumes: `ShiftCandidate.personal_constraint_warning` (existing field, already typed and fetched — just newly read in this file).
- Consumes: `assignBatch(shiftId, { primaries, reserves, override_reason? })` (existing API function, already supports the field).
- Produces: no new exports — internal component behavior only.

- [ ] **Step 1: Write the failing test — visible warning indicator on a constrained candidate**

  Add to `ShiftEditAssignmentsModal.test.tsx`, mirroring the existing render test's setup but giving one candidate a non-null `personal_constraint_warning` (check `ShiftAssignModal.test.tsx` — if it exists — for the exact shape of a realistic `PersonalConstraintWarning` object to mock; otherwise construct one matching the `PersonalConstraintWarning` type from `frontend/src/api/assignments.ts`). Assert some visible warning affordance renders for that candidate's row (an icon, title text, or similar — check what `ShiftAssignModal.tsx` actually renders for this state before deciding the exact assertion, so the test targets real, intended UI, not a guess).

  ```tsx
  it("shows a constraint-warning indicator for a candidate with an approved personal constraint", () => {
    // arrange: candidate with personal_constraint_warning set (non-null)
    // act: render modal
    // assert: warning indicator visible on that candidate's row
  });
  ```

- [ ] **Step 2: Run the test, confirm it fails**

  ```bash
  cd frontend && npx vitest run src/components/ShiftEditAssignmentsModal.test.tsx -t "constraint-warning indicator"
  ```
  Expected: FAIL — no such indicator exists yet.

- [ ] **Step 3: Implement the warning indicator**

  In `ShiftEditAssignmentsModal.tsx`'s candidate row rendering (`CandidateTable`/wherever primary and reserve rows render — read the current row JSX first), add a visible warning affordance when `candidate.personal_constraint_warning` is truthy, matching `ShiftAssignModal.tsx`'s existing visual treatment for the same state (reuse the same icon/component if one exists there, don't invent a new visual language).

- [ ] **Step 4: Run the test, confirm it passes**

  Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Write the failing test — selecting a constrained candidate and saving opens the override modal, and confirming with a reason completes the assignment**

  ```tsx
  it("opens the override-reason modal when saving with a constrained candidate selected, and completes the assignment once a reason is confirmed", async () => {
    // arrange: one candidate with personal_constraint_warning set
    // act: select that candidate, click save
    // assert: OverrideReasonModal is now open (not assignBatch called yet)
    // act: type a reason, confirm
    // assert: assignBatch called with override_reason: <the typed reason>
  });
  ```

- [ ] **Step 6: Run the test, confirm it fails**

- [ ] **Step 7: Implement the override flow in `handleSave()`**

  Restructure `handleSave()` (or add a wrapping function, matching `ShiftAssignModal.tsx`'s `continueAssign()`/`doAssign()` split) so that: if any selected candidate (primary or reserve) has `personal_constraint_warning` truthy, defer to opening `OverrideReasonModal` instead of calling `assignBatch` directly; on confirm, call `assignBatch` with the collected reason spread in exactly like the reference implementation (`...(overrideReason ? { override_reason: overrideReason } : {})`); on cancel, do nothing (no API call, modal closes, selection state preserved).

- [ ] **Step 8: Run the test, confirm it passes**

- [ ] **Step 9: Write the failing test — the existing unconstrained-candidate test still passes unmodified**

  Re-run the existing test from Step 5's neighbor (the one asserting `assignBatch` called without `override_reason`) — it should need NO changes if Step 7 preserved the conditional spread correctly. If it breaks, that's a signal the restructuring changed behavior for the unconstrained case — fix the implementation, not the test, unless you find the test itself was asserting something incidental to the old code structure rather than real behavior.

  ```bash
  cd frontend && npx vitest run src/components/ShiftEditAssignmentsModal.test.tsx
  ```
  Expected: all tests in the file PASS, including this pre-existing one, unmodified.

- [ ] **Step 10: Write the failing test — auto-select excludes constrained candidates**

  Find `ShiftEditAssignmentsModal.tsx`'s equivalent of `ShiftAssignModal.tsx`'s `selectAllPrimary`/auto-select-all buttons (check the file for a "select all" or similar bulk-select control on the primary/reserve candidate tables). Write a test asserting that clicking it does NOT select a candidate with `personal_constraint_warning` set, matching `ShiftAssignModal.tsx`'s existing exclusion behavior. If no such bulk auto-select control exists in `ShiftEditAssignmentsModal.tsx` at all (unlike `ShiftAssignModal.tsx`), skip this step entirely and note in the seam-inventory-style comment (or PR description) that there's no auto-select surface in this modal to exclude from — don't invent one.

- [ ] **Step 11: Run the test (if written), confirm it fails, then implement, then confirm it passes**

  Same TDD cycle as prior steps, only if Step 10 found a real auto-select control to guard.

- [ ] **Step 12: Run the full component test file and the broader frontend checks**

  ```bash
  cd frontend
  npx vitest run src/components/ShiftEditAssignmentsModal.test.tsx
  npm run typecheck
  npm run lint
  ```
  All must pass clean.

- [ ] **Step 13: Commit**

  ```bash
  git add frontend/src/components/ShiftEditAssignmentsModal.tsx frontend/src/components/ShiftEditAssignmentsModal.test.tsx
  git commit -m "fix: allow overriding a personal constraint in the standard bulk assignment modal"
  ```

---

### Task 2: E2E verification — replace the documented-gap test with a real positive test

**Files:**
- Modify: `frontend/tests/e2e/smoke/personal_constraint_override.spec.ts`
- Modify: `docs/e2e-coverage-matrix.md`

**Context:** This spec currently has a test titled "the standard bulk ShiftEditAssignmentsModal cannot override a personal constraint (documented product gap)" — proving the gap Task 1 just fixed. That test's own header comment (per the ledger from the plan that wrote it) explicitly says it exists to be deleted/rewritten once the gap closes. This task does exactly that, and additionally proves the fix works end-to-end through a real browser, not just the component-level tests from Task 1.

**Interfaces:**
- Reuses the existing `constrainedSoldier` journey actor and constraint-setup helper already in this spec file — do not duplicate.

- [ ] **Step 1: Read the current gap-documenting test and the file's seam-inventory header in full**

  Understand exactly what it currently asserts (candidates blocked, no override path) so you replace it accurately rather than guessing its structure.

- [ ] **Step 2: Replace the gap-documenting test with a positive override-succeeds test**

  Using the standard `manual-assignment-open-${shiftId}` bulk modal (the one `multi_user_duty_problems.spec.ts`'s `assignManually` helper already exercises for the non-constrained case), select `constrainedSoldier` as a candidate on a duty whose dates overlap their approved constraint, confirm a visible warning indicator appears (matching Task 1's new UI), save, confirm the `OverrideReasonModal` appears, fill a reason, confirm. Wait for `POST /api/shifts/{shift_id}/assign-batch` to return 2xx with `override_reason` in the request body. Refresh and assert `constrainedSoldier` now shows as the assignee (real visible UI state, not just the response).

- [ ] **Step 3: Update the spec's seam-inventory header**

  Remove the "documented gap" language for this specific path (the bulk modal now DOES support override), while leaving the OTHER duty-side gap (the `ShiftAssignModal`/Replace-flow's unreachable trigger, `task_af3d0c50`'s other half) documented as-is — that one is unrelated to this fix and remains a real, separate gap unless a future plan addresses it too.

- [ ] **Step 4: Run against a freshly seeded DB, twice**

  ```powershell
  cd backend
  .venv\Scripts\python.exe -m app.scripts.seed --db-url "postgresql+psycopg://app:app_pw@localhost:5432/justice_e2e" --clear
  cd ..\frontend
  Remove-Item -Recurse -Force .playwright\auth
  npx playwright test --grep personal_constraint_override --project=desktop --retries=0
  ```
  All tests in the file (the pre-existing ones plus the rewritten one) must pass, twice, with no retries.

- [ ] **Step 5: Update the coverage matrix**

  Update `docs/e2e-coverage-matrix.md`'s existing `personal_constraint_override` row to reflect that the bulk-modal gap is now fixed and positively tested, not just documented — cite this plan/fix commit, and note `task_af3d0c50` is now half-resolved (bulk modal fixed; `ShiftAssignModal` trigger-reachability half still open, if it remains a real, separate gap worth tracking on its own).

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/tests/e2e/smoke/personal_constraint_override.spec.ts docs/e2e-coverage-matrix.md
  git commit -m "test: prove the bulk assignment modal's constraint-override fix end to end"
  ```

## Verification commands

```bash
cd frontend
npx vitest run src/components/ShiftEditAssignmentsModal.test.tsx
npm run typecheck
npm run lint
npx playwright test --grep personal_constraint_override --project=desktop --retries=0
```

Before claiming completion: confirm the pre-existing unconstrained-candidate test in `ShiftEditAssignmentsModal.test.tsx` still passes unmodified (proves no regression to the common case), confirm the E2E positive test asserts real post-refresh UI state (not just a 2xx), and confirm the coverage-matrix update accurately reflects what's fixed vs. what (if anything) remains open.
