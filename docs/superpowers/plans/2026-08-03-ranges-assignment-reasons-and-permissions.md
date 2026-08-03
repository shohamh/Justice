# Ranges Assignment Reasons and Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make range assignment explanations, manual reasons, Hebrew messaging, current-user upcoming ranges, self-excusal, and permission-gated controls correct and testable end-to-end.

**Architecture:** Persist assignment explanation metadata on `RangeAssignment`, with stable backend reason codes and optional editable text. Extend the range response with current-user assignment and attendance-authority capabilities, then keep the existing shared React Query keys so mutations invalidate both the planning page and home dashboard. Keep UI labels/error mapping in the existing Hebrew i18n catalog and retain the range detail modal as the read-only surface for unauthorized users.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest, React, TypeScript, TanStack Query, Vitest, i18next, Tailwind CSS.

## Global Constraints

- Do not reuse `RangeAssignment.note`; it remains the attendance note.
- Automatic reason codes must reflect actual range auto-assignment ranking/eligibility behavior, not invented explanations.
- Manual assignments default to the Hebrew reason "שיבוץ ידני" and may be edited by a planner.
- Every mutation remains protected by backend authorization; UI visibility is not a security boundary.
- A soldier may open a range detail modal read-only, but must not see planner, cancellation, assignment, confirmation, or attendance mutation controls without the corresponding capability.
- Self-excusal is a top-level action labeled "אני לא אוכל להגיע" and is not rendered inside assignment rows.
- Raw API error codes and English feature strings must not be rendered to users.
- Preserve unrelated user work and the existing contrast fix on this branch.

---

### Task 1: Persist assignment reasons and expose range capabilities

**Files:**
- Create: `backend/alembic/versions/20260803_add_range_assignment_reasons.py`
- Modify: `backend/app/db/models.py:RangeAssignment`
- Modify: `backend/app/routes/ranges.py:RangeAssignmentOut, AddAssignmentBody, _event_out, range routes`
- Modify: `backend/app/services/range_auto_assign.py`
- Test: `backend/app/services/tests/test_range_auto_assign.py` (create this focused service test module)
- Test: `backend/app/routes/tests/test_ranges.py` (create this focused route test module using existing route fixtures)

**Interfaces:**
- `RangeAssignment` produces nullable `assignment_reason_code: str` and `assignment_reason_text: str | None`.
- `RangeAssignmentOut` returns both fields.
- `AddAssignmentBody` accepts `assignment_reason_code` and `assignment_reason_text`, defaulting to `manual` and `שיבוץ ידני` when omitted.
- `RangeEventOut` adds `assigned_to_me: bool` and `can_edit_attendance: bool`.

- [ ] **Step 1: Write failing persistence/API tests.**

  Add tests that create a range assignment and assert its response includes the reason fields, that omitted manual input gets `manual`/`שיבוץ ידני`, and that a list/detail response includes current-user `assigned_to_me` plus the server-authoritative `can_edit_attendance` capability.

- [ ] **Step 2: Run the focused backend tests and verify the new assertions fail.**

  Run from `backend`:

  ```powershell
  pytest -q app/services/tests/test_range_auto_assign.py app/routes/tests/test_ranges.py
  ```

  Expected: failures because the model/API fields and capability fields do not yet exist.

- [ ] **Step 3: Add the Alembic migration and model fields.**

  Add nullable text columns, backfill existing rows to `assignment_reason_code = 'legacy'` and `assignment_reason_text = 'שיבוץ קיים'`, then remove the temporary server default if the migration pattern requires it. Keep downgrade support.

- [ ] **Step 4: Extend route schemas and response construction.**

  Pass the authenticated user into `_event_out`. Compute `assigned_to_me` with a query against `RangeAssignment`. Compute `can_edit_attendance` using the existing `range_attendance_edit_authorized` service and the event node. Apply this to list and detail responses without leaking drafts to unauthorized readers.

- [ ] **Step 5: Extend manual add/update APIs.**

  Store normalized manual reason data on add. Add `PATCH /ranges/{event_id}/assignments/{assignment_id}/reason` with a max length and planner authorization, returning the updated assignment. Reject blank custom reason text and assignments from another event.

- [ ] **Step 6: Run the focused backend tests and migration checks.**

  Run the focused tests plus:

  ```powershell
  alembic upgrade head
  pytest -q app/services/tests/test_range_auto_assign.py app/routes/tests/test_ranges.py
  ```

  Expected: PASS.

- [ ] **Step 7: Commit.**

  ```powershell
  git add backend/app/db/models.py backend/app/routes/ranges.py backend/app/services/range_auto_assign.py backend/alembic/versions backend/app/services/tests/test_range_auto_assign.py backend/app/routes/tests/test_ranges.py
  git commit -m "feat: persist range assignment reasons and capabilities"
  ```

### Task 2: Generate truthful automatic reasons and test manual reason editing

**Files:**
- Modify: `backend/app/services/range_auto_assign.py`
- Modify: `backend/app/routes/ranges.py`
- Test: `backend/app/services/tests/test_range_auto_assign.py`
- Test: `backend/app/routes/tests/test_ranges.py`

**Interfaces:**
- The auto-assignment service returns created draft assignments with a stable reason code and optional generated text.
- The reason endpoint updates only explanation metadata and never changes assignment role, draft status, attendance, or soldier identity.

- [ ] **Step 1: Write failing reason tests.**

  Cover at least these ranking outcomes: a valid qualification, a future weapon-duty priority, and an otherwise eligible available soldier. Assert the persisted codes match the actual branch used. Add a route test proving a planner can edit text while an unauthorized user receives `403`.

- [ ] **Step 2: Run the focused tests and verify failure.**

  ```powershell
  pytest -q app/services/tests/test_range_auto_assign.py app/routes/tests/test_ranges.py -k "reason or qualification or priority"
  ```

- [ ] **Step 3: Implement reason-code derivation at the ranking source.**

  Return the reason from the same qualification/duty/availability checks used to sort candidates. Use stable codes such as `qualified`, `weapon_duty_priority`, and `available_and_balanced`; do not infer reasons later from an already-created assignment.

- [ ] **Step 4: Implement the reason update route validation.**

  Normalize whitespace, reject empty values, cap the text length, write an audit record for the change, and return the updated assignment.

- [ ] **Step 5: Run the tests and commit.**

  ```powershell
  pytest -q app/services/tests/test_range_auto_assign.py app/routes/tests/test_ranges.py
  git add backend/app/services/range_auto_assign.py backend/app/routes/ranges.py backend/app/services/tests/test_range_auto_assign.py backend/app/routes/tests/test_ranges.py
  git commit -m "feat: explain automatic range assignment choices"
  ```

### Task 3: Assignment modal reason table, manual editing, and Hebrew messages

**Files:**
- Modify: `frontend/src/api/ranges.ts`
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx`
- Modify: `frontend/src/components/ranges/RangeDetailContent.tsx`
- Modify: `frontend/src/components/ranges/RangeDetailContent.test.tsx` (create if absent)
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/i18n/he.test.ts`
- Modify: `frontend/src/utils/translateApiError.ts` or the existing API error mapping module

**Interfaces:**
- `RangeAssignment` includes the two reason fields.
- The modal calls `updateRangeAssignmentReason(eventId, assignmentId, text)` after inline editing.
- `RangeDetailContent` receives `canEditAttendance` and a current-user self-excuse callback.

- [ ] **Step 1: Add failing frontend tests.**

  Assert that the assignment table renders a Hebrew reason column for automatic and manual assignments, that a planner can edit/save a manual reason, and that mutation errors render Hebrew text rather than an English code. Assert no raw English range error string is visible.

- [ ] **Step 2: Run the focused frontend tests and verify failure.**

  ```powershell
  npm.cmd test -- --run --reporter=dot src/components/ranges/RangeEditAssignmentsModal.test.tsx src/pages/RangesPage.test.tsx
  ```

- [ ] **Step 3: Add typed API wrappers and reason presentation.**

  Add the update wrapper, map reason codes to i18n keys, render the reason beside each soldier in the primary/reserve tables, and show an edit control only when `canManage` is true. Preserve pending/error behavior for all existing mutations.

- [ ] **Step 4: Move range UI/error copy into Hebrew i18n.**

  Add keys for assignment reasons, auto-assign shortfall, add/remove/confirm failures, search/empty states, loading/errors, and the self-excuse action. Map known API codes to these keys and use a Hebrew fallback for unknown errors.

- [ ] **Step 5: Move self-excusal to the modal header area.**

  Remove the per-row "בקשת פטור" action. Add a top-level "אני לא אוכל להגיע" button only when the current user has a future confirmed assignment, and retain the reason input/submission flow from that button.

- [ ] **Step 6: Run focused frontend validation and commit.**

  ```powershell
  npm.cmd test -- --run --reporter=dot src/components/ranges/RangeEditAssignmentsModal.test.tsx src/pages/RangesPage.test.tsx src/components/ranges/RangeFormModal.test.tsx
  npm.cmd run typecheck
  npm.cmd run lint
  git add frontend/src/api/ranges.ts frontend/src/components/ranges frontend/src/pages/RangesPage.tsx frontend/src/i18n frontend/src/utils
  git commit -m "feat: explain and translate range assignments"
  ```

### Task 4: Upcoming-ranges filtering, cache invalidation, and permission-gated UI

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/components/dashboard/UpcomingRangesWidget.tsx`
- Modify: `frontend/src/components/dashboard/UpcomingRangesWidget.test.tsx`
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/components/ranges/RangeDetailContent.tsx`
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`
- Modify: `frontend/src/components/dashboard/DutyCalendarWidget.test.tsx` if calendar filtering uses the same data

**Interfaces:**
- `RangeEvent.assigned_to_me` controls soldier-facing upcoming widgets.
- `RangeEvent.can_edit_attendance` controls attendance mutation UI.
- The shared `queryKeys.ranges()` and `queryKeys.rangeEvent(id)` remain the invalidation boundary.

- [ ] **Step 1: Add failing dashboard and permission tests.**

  Cover a future range with `assigned_to_me: false` being absent from the upcoming widget, then becoming visible when true. Cover a range detail modal for a user without planner/attendance capability and assert the range remains open while all mutation buttons are absent.

- [ ] **Step 2: Run the focused frontend tests and verify failure.**

  ```powershell
  npm.cmd test -- --run --reporter=dot src/components/dashboard/UpcomingRangesWidget.test.tsx src/pages/RangesPage.test.tsx
  ```

- [ ] **Step 3: Filter soldier-facing upcoming data and preserve planning scope.**

  Filter `UpcomingRangesWidget` input to future planned events with `assigned_to_me === true`. Keep `RangesPage` and planning tables unfiltered so authorized planners see all ranges. Keep range/calendar rows clickable for read-only users.

- [ ] **Step 4: Gate every mutation surface.**

  Keep planner actions behind `canPlan`, assignment editor behind `canManage`, self-excusal behind the current-user assignment condition, and attendance controls behind `can_edit_attendance`. Add negative assertions for edit, cancel, assignment, confirm, remove, self-excuse, and attendance buttons.

- [ ] **Step 5: Verify invalidation after removal.**

  Ensure the assignment modal’s `onChanged` invalidates both `queryKeys.ranges()` and the detail key. Add a test that resolves the post-mutation list without the current user assignment and confirms the dashboard/widget no longer renders the range.

- [ ] **Step 6: Run frontend validation and commit.**

  ```powershell
  npm.cmd test -- --run --reporter=dot src/components/dashboard/UpcomingRangesWidget.test.tsx src/pages/RangesPage.test.tsx
  npm.cmd run typecheck
  npm.cmd run lint
  git add frontend/src/pages/HomePage.tsx frontend/src/components/dashboard frontend/src/pages/RangesPage.tsx frontend/src/components/ranges frontend/src/pages/RangesPage.test.tsx
  git commit -m "fix: refresh range visibility and gate range actions"
  ```

### Task 5: Full verification and handoff

**Files:**
- Test: existing backend and frontend suites.

- [ ] **Step 1: Run backend focused and full tests.**

  ```powershell
  cd backend
  pytest -q app/services/tests/test_range_auto_assign.py app/routes/tests/test_ranges.py
  pytest -q
  ```

- [ ] **Step 2: Run frontend focused and full tests.**

  ```powershell
  cd frontend
  npm.cmd test -- --run --reporter=dot src/components/ranges src/pages/RangesPage.test.tsx src/components/dashboard/UpcomingRangesWidget.test.tsx
  npm.cmd test -- --run --reporter=dot
  npm.cmd run typecheck
  npm.cmd run lint
  ```

- [ ] **Step 3: Review strings, permissions, and API contracts.**

  Search changed range files for raw English UI/error strings, verify all mutation buttons are capability-gated, and run `git diff --check`.

- [ ] **Step 4: Commit any verification-only corrections and report exact results.**

  Do not merge or push in this task unless explicitly requested.
