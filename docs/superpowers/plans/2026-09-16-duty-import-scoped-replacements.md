# Duty Import and Scoped Replacements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ("- [ ]") syntax for tracking.

**Goal:** Fix Excel assignment imports, expose range-qualification run defaults, make modal layering follow opening order, and deliver scoped manual/automatic duty replacements from algorithm results.

**Architecture:** Keep authorization and replacement validation in the backend, expose only server-computed capabilities and candidates to the frontend, and use one atomic replacement operation for published and algorithm-draft assignments. Keep import resolution metadata explicit so a resolved duty type is not confused with a missing matching shift; create generated shifts only during confirmation. Add a small application-level modal-layer allocator whose monotonically increasing tokens encode actual opening order.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest; React, TypeScript, Vitest, Tailwind CSS; existing Justice authz, scoring, import-session, and modal components.

**Spec:** docs/superpowers/specs/2026-09-16-duty-import-scoped-replacements-design.md

## Global Constraints

- Backend is the source of truth for scope, eligibility, replacement validation, and effective algorithm settings.
- The system key weapon_qualification.enforce_eligibility remains the default for algorithm runs.
- Modal layers are assigned by opening order; do not solve the nested-modal bug with a fixed child z-index.
- Generated import shifts are created only when at least one associated assignment remains selected.
- Every production behavior change is preceded by a focused failing regression test and followed by focused verification.
- Do not alter unrelated worktrees or commit directly to dev or master.

---

### Task 1: Resolve Excel assignment types and generate missing shifts

**Files:**
- Modify: backend/app/services/import_sessions.py (_resolve_assignments, confirm_session)
- Modify: backend/app/services/import_parsers/schema.py if the parsed-state contract needs a generated-shift field
- Modify: frontend/src/pages/ImportSessionReviewPage.tsx
- Test: backend/app/services/tests/test_import_sessions_service.py
- Test: backend/tests/integration/test_import_sessions_config_confirm.py
- Test: frontend/src/pages/ImportSessionReviewPage.test.tsx

**Interfaces:**
- Assignment parsed state exposes resolved_duty_type_id and a stable generated_shift_key when type/location/date/time resolution is sufficient but no shift matches.
- confirm_session maps generated keys to newly created DutyShift IDs before creating assignments and leaves no generated shift when all linked assignments are skipped.

- [ ] Step 1: Add the service regression for a resolved type without a matching shift. Build the smallest import-session fixture with one valid assignment and no duty shift; assert that the assignment has a resolved type, a generated key, and a non-blocking warning rather than an unresolved-type error.

~~~python
assert row["resolved_duty_type_id"] == duty_type.id
assert row["generated_shift_key"]
assert "לא נמצאה משמרת תואמת" in row["warnings"]
assert row["action"] == "new"
~~~

- [ ] Step 2: Run the focused test and verify it fails for the missing generated-shift metadata.

~~~powershell
backend\.venv\Scripts\python.exe -m pytest app/services/tests/test_import_sessions_service.py -k generated_shift -q
~~~

Expected: FAIL because the current resolver reports an error and does not expose a generated key.

- [ ] Step 3: Implement explicit assignment resolution metadata and stable key reuse. Resolve and return the duty type independently of shift matching; use type, location, dates, and normalized default times as the key; mark only valid no-match rows as generated new assignments.

- [ ] Step 4: Add the confirmation regression for one generated shift shared by multiple assignments. Confirm two selected assignments with the same key and assert one new shift and two assignments reference it; confirm that skipping every linked assignment creates neither a shift nor an assignment.

- [ ] Step 5: Run the confirmation tests before changing implementation.

~~~powershell
backend\.venv\Scripts\python.exe -m pytest app/services/tests/test_import_sessions_service.py backend/tests/integration/test_import_sessions_config_confirm.py -k generated -q
~~~

Expected: FAIL because confirmation currently rejects rows without an existing resolved_duty_shift_id.

- [ ] Step 6: Create generated shifts on demand during confirmation. Group effective selected assignments by generated key, calculate primary/reserve counts from those rows, create and audit one shift per key, map its ID, and then create assignments through the existing validation path.

- [ ] Step 7: Fix the review UI to show the duty-type combobox only when the type ID is absent. Preserve the selection while the row has a generated-shift warning, and keep the warning visible after reparsing.

- [ ] Step 8: Add and run the frontend regression for a resolved type with a shift-matching warning.

~~~powershell
Set-Location frontend
npx vitest run src/pages/ImportSessionReviewPage.test.tsx -t "resolved duty type"
~~~

- [ ] Step 9: Run all import-session focused tests and commit.

~~~powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest app/services/tests/test_import_sessions_service.py tests/integration/test_import_sessions_config_confirm.py -q
git add backend/app/services/import_sessions.py backend/app/services/import_parsers/schema.py backend/app/services/tests/test_import_sessions_service.py backend/tests/integration/test_import_sessions_config_confirm.py frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx
git commit -m "fix: create missing shifts for imported assignments"
~~~

---

### Task 2: Propagate the system range-qualification default into run forms

**Files:**
- Modify: backend/app/routes/algorithm.py (AlgorithmDefaultsOut, get_algorithm_defaults)
- Modify: frontend/src/api/algorithm.ts
- Modify: frontend/src/components/AlgorithmRunForm.tsx
- Modify: frontend/src/components/AlgorithmInlinePanel.tsx if it consumes the same defaults contract
- Test: backend/tests/integration/test_algorithm_routes.py
- Test: frontend/src/api/algorithm.test.ts
- Test: frontend/src/components/AlgorithmRunForm.test.tsx

**Interfaces:**
- GET /algorithm/defaults returns {T, Wt, R, Wr, enforce_weapon_qualification}.
- AlgorithmRunForm initializes SolverSettings.enforce_weapon_qualification from that response and submits the explicit boolean.

- [ ] Step 1: Add failing API and form tests for a false system default. Assert the parsed defaults include false, the checkbox starts unchecked, and the submitted run request contains enforce_weapon_qualification: false.

~~~typescript
expect(await getAlgorithmDefaults()).toEqual({ T: 8, Wt: 14, R: 15, Wr: 28, enforce_weapon_qualification: false });
expect(screen.getByRole("checkbox", { name: /כשירות מטווחים/ })).not.toBeChecked();
~~~

- [ ] Step 2: Run the focused backend/frontend tests and verify the contract failure.

~~~powershell
backend\.venv\Scripts\python.exe -m pytest tests/integration/test_algorithm_routes.py -k defaults -q
Set-Location frontend; npx vitest run src/api/algorithm.test.ts src/components/AlgorithmRunForm.test.tsx
~~~

- [ ] Step 3: Add the boolean to the backend defaults response using the same effective setting resolver used by runs. Keep omitted per-run values backward-compatible with the system setting.

- [ ] Step 4: Extend the frontend type, default state, fetch mapping, and Hebrew label. Make the checkbox use the fetched value, with the existing hardcoded fallback only when the defaults request fails.

- [ ] Step 5: Run focused settings tests, then commit.

~~~powershell
backend\.venv\Scripts\python.exe -m pytest tests/integration/test_algorithm_routes.py -k defaults -q
Set-Location frontend; npx vitest run src/api/algorithm.test.ts src/components/AlgorithmRunForm.test.tsx
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_routes.py frontend/src/api/algorithm.ts frontend/src/api/algorithm.test.ts frontend/src/components/AlgorithmRunForm.tsx frontend/src/components/AlgorithmRunForm.test.tsx frontend/src/components/AlgorithmInlinePanel.tsx
git commit -m "fix: initialize algorithm range qualification from system settings"
~~~

---

### Task 3: Add opening-order modal layering

**Files:**
- Create: frontend/src/contexts/ModalStackContext.tsx
- Modify: frontend/src/main.tsx or the existing application provider composition
- Modify: frontend/src/components/planning/EventDetailModal.tsx
- Modify: frontend/src/components/dashboard/DutyDetailModal.tsx only if it does not use EventDetailModal
- Modify: frontend/src/components/UnifiedSoldierModal.tsx
- Test: frontend/src/components/planning/EventDetailModal.test.tsx
- Test: frontend/src/components/UnifiedSoldierModal.test.tsx or frontend/src/contexts/ModalStackContext.test.tsx

**Interfaces:**
- ModalStackProvider owns a monotonic counter and useModalLayer(open: boolean): number registers on each false-to-true transition and releases on close.
- Participating modal roots receive an inline zIndex derived from the returned layer and a shared base.

- [ ] Step 1: Add a failing stack test with two modals opened in sequence and one reopened. Assert later-opened roots have larger z-index values, and the reopened first modal gets a larger value than both previous values.

~~~typescript
expect(Number(first.style.zIndex)).toBeLessThan(Number(second.style.zIndex));
rerender(<StackFixture firstOpen secondOpen={false} />);
rerender(<StackFixture firstOpen secondOpen />);
expect(Number(first.style.zIndex)).toBeLessThan(Number(second.style.zIndex));
~~~

- [ ] Step 2: Run the focused modal test and verify failure because all roots currently use z-50.

~~~powershell
Set-Location frontend
npx vitest run src/components/planning/EventDetailModal.test.tsx src/contexts/ModalStackContext.test.tsx
~~~

- [ ] Step 3: Implement the provider and transition-aware registration. Use a stable registration while open, release on close, and allocate a fresh highest layer on reopen; do not derive layers from component nesting.

- [ ] Step 4: Wrap the application provider tree and migrate the shift/event and unified soldier modal roots. Preserve ordinary dropdown z-indexes above the modal layer.

- [ ] Step 5: Run focused modal tests, including the homepage shift-to-soldier interaction regression, and commit.

~~~powershell
npx vitest run src/components/planning/EventDetailModal.test.tsx src/components/UnifiedSoldierModal.test.tsx src/pages/HomePage.test.tsx
git add frontend/src/contexts/ModalStackContext.tsx frontend/src/main.tsx frontend/src/components/planning/EventDetailModal.tsx frontend/src/components/dashboard/DutyDetailModal.tsx frontend/src/components/UnifiedSoldierModal.tsx frontend/src/components/planning/EventDetailModal.test.tsx frontend/src/components/UnifiedSoldierModal.test.tsx frontend/src/contexts/ModalStackContext.test.tsx frontend/src/pages/HomePage.test.tsx
git commit -m "fix: layer nested modals by opening order"
~~~

---

### Task 4: Enforce scoped replacement capabilities in the shifts API

**Files:**
- Modify: backend/app/routes/shifts.py (ShiftCandidateOut, candidates, assignment mutations)
- Modify: backend/app/routes/calendar.py (CalendarShiftAssignee and capability calculation)
- Modify: existing assignment service module when atomic replacement validation belongs below the route layer
- Test: backend/tests/integration/test_shift_candidates.py
- Test: backend/tests/integration/test_shifts_routes.py
- Test: backend/tests/integration/test_algorithm_shifts.py if draft assignments use the same candidate path

**Interfaces:**
- GET /shifts/{shift_id}/candidates?include_drafts=true returns only candidates the actor may use, with the draft-aware score used by replacement mode.
- POST /shifts/{shift_id}/assignments/{assignment_id}/replace accepts {replacement_soldier_id: UUID} and atomically updates the existing assignment after scope, eligibility, duplicate, relationship, and capacity validation.
- Calendar assignees expose a backend-computed can_replace flag.

- [ ] Step 1: Add failing integration tests for candidate filtering and mutation denial. Create a duty manager whose scope contains one current assignee and one candidate but excludes a second candidate; assert the excluded soldier is absent and an out-of-scope target or replacement receives a 403/422 response.

~~~python
assert {item["soldier_id"] for item in candidates.json()} == {in_scope_candidate.id}
assert client.post(replace_url, json={"replacement_soldier_id": outside_scope.id}).status_code == 403
~~~

- [ ] Step 2: Run the focused tests and verify they fail because candidates are currently shift-wide and no atomic endpoint exists.

~~~powershell
backend\.venv\Scripts\python.exe -m pytest tests/integration/test_shift_candidates.py tests/integration/test_shifts_routes.py -k scope -q
~~~

- [ ] Step 3: Filter candidate queries by the actor's scope and add replacement-score fields without changing unrestricted admin behavior. For replacement mode, count active published and algorithm-draft assignments while excluding the target assignment.

- [ ] Step 4: Implement the atomic replacement endpoint through the existing assignment validation/audit path. Check both current and new soldier scope for non-admin duty managers; preserve the assignment's status and reserve relationships.

- [ ] Step 5: Add server-computed calendar can_replace and enforce the same scope for individual remove/dismiss mutations.

- [ ] Step 6: Run focused backend scope, candidate, and replacement tests, then commit.

~~~powershell
backend\.venv\Scripts\python.exe -m pytest tests/integration/test_shift_candidates.py tests/integration/test_shifts_routes.py tests/integration/test_algorithm_shifts.py -q
git add backend/app/routes/shifts.py backend/app/routes/calendar.py backend/app/services backend/tests/integration/test_shift_candidates.py backend/tests/integration/test_shifts_routes.py backend/tests/integration/test_algorithm_shifts.py
git commit -m "feat: enforce scoped duty assignment replacements"
~~~

---

### Task 5: Connect algorithm results to scoped, draft-aware replacement UI

**Files:**
- Modify: frontend/src/components/AlgorithmProposalTable.tsx
- Modify: frontend/src/components/AlgorithmJobTabs.tsx
- Modify: frontend/src/components/ShiftEditAssignmentsModal.tsx
- Modify: frontend/src/components/ShiftAssignModal.tsx only if the shared candidate UI is reused
- Modify: frontend/src/api/shifts.ts and related query types
- Modify: frontend/src/i18n/he.json
- Test: frontend/src/components/AlgorithmProposalTable.test.tsx
- Test: frontend/src/components/ShiftEditAssignmentsModal.test.tsx
- Test: frontend/src/components/ShiftAssignModal.test.tsx

**Interfaces:**
- Proposal rows open ShiftEditAssignmentsModal with replaceAssignmentId and the proposal duty_shift_id.
- Replacement mode loads include_drafts=true, offers “replace”, and provides an automatic selection using the first eligible lowest-score candidate.
- On success, proposal/job data is refreshed and the table no longer labels the action “reject”.

- [ ] Step 1: Add failing UI tests for the new action and modal handoff. Click the pending proposal action, assert the same shift's assignment modal opens with the target assignment, and assert the rendered action is “החלף” rather than “דחה”.

~~~typescript
await user.click(screen.getByRole("button", { name: "החלף" }));
expect(screen.getByTestId("shift-edit-assignments-modal")).toHaveAttribute("data-replace-assignment-id", proposal.assignment_id);
~~~

- [ ] Step 2: Add a failing replacement-modal test for automatic selection and candidate scope. Mock the real API boundary response with two candidates and assert the lower draft-aware score is selected, while an out-of-scope candidate is not rendered.

- [ ] Step 3: Run the focused frontend tests and verify failure because the table still calls reject and the modal has no replacement target mode.

~~~powershell
Set-Location frontend
npx vitest run src/components/AlgorithmProposalTable.test.tsx src/components/ShiftEditAssignmentsModal.test.tsx
~~~

- [ ] Step 4: Pass shift/proposal context through AlgorithmJobTabs and add a target-assignment replacement mode to the shared assignments modal. Use the atomic replacement API, exclude the target from counts, and refresh after success.

- [ ] Step 5: Replace the Hebrew label and wire automatic candidate selection to the backend score. Keep manual selection limited to candidates returned by the scoped endpoint and hide action controls for assignees with can_replace: false.

- [ ] Step 6: Run the focused frontend tests and commit.

~~~powershell
npx vitest run src/components/AlgorithmProposalTable.test.tsx src/components/ShiftEditAssignmentsModal.test.tsx src/components/ShiftAssignModal.test.tsx
git add frontend/src/components/AlgorithmProposalTable.tsx frontend/src/components/AlgorithmJobTabs.tsx frontend/src/components/ShiftEditAssignmentsModal.tsx frontend/src/components/ShiftAssignModal.tsx frontend/src/api/shifts.ts frontend/src/i18n/he.json frontend/src/components/AlgorithmProposalTable.test.tsx frontend/src/components/ShiftEditAssignmentsModal.test.tsx frontend/src/components/ShiftAssignModal.test.tsx
git commit -m "feat: replace algorithm proposals with scoped candidates"
~~~

---

### Task 6: Whole-branch verification and review

**Files:**
- Modify only files required by test failures found in Tasks 1-5; do not broaden the feature.

- [ ] Step 1: Inspect the ledger, branch status, and complete diff.

~~~powershell
git status --short
git diff dev...HEAD --stat
git diff --check
~~~

- [ ] Step 2: Run backend focused markers and the complete fast suite.

~~~powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest -m "algorithm or duty or scoring" -q
..\.venv\Scripts\python.exe -m pytest -q
~~~

- [ ] Step 3: Run frontend tests, lint, typecheck, and build.

~~~powershell
Set-Location frontend
npm test -- --run
npm run lint
npm run typecheck
npm run build
~~~

- [ ] Step 4: Dispatch a whole-branch code review against dev, resolve all important findings with a reviewed fix pass, and record any parked minor findings in the SDD ledger.

- [ ] Step 5: Commit only verification fixes and report exact test evidence. Integration into dev is a separate authorized finishing step.
