# מטווחים UI Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shift-like range planning board with shared UI primitives, complete planned-range lifecycle controls, range notifications, stable seed scenarios, and regression coverage for auto-assignment.

**Architecture:** Keep shifts and ranges as separate domain models and services. Extract only presentation primitives (`PlanningTable`, `EventDetailModal`, `RosterSection`, and `AssignmentRow`) and migrate the shifts page to consume them while the range page uses them from the start. Extend the existing range service/API rather than introducing a unified backend event model.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest; React, TypeScript, TanStack Query, Vitest, Testing Library; PostgreSQL seed fixtures.

## Global Constraints

- `/ranges` is a full planning board parallel to the shifts planning screen.
- A planned range supports editing type, date, start/end time, location, instructions, contact, primary count, reserve count, and notes.
- Physical deletion is allowed only with no assignments and no attendance history; assigned/history ranges are cancelled with a required reason and remain visible.
- Completed ranges cannot be edited, deleted, or cancelled.
- Range notifications use the existing in-app delivery and preference mechanisms.
- `mitvachim.enabled` gates range routes, planning UI, dashboard widgets, and notifications.
- The existing Phase 2 auto-assignment candidate filtering and three-tier ranking remain the algorithm; only tests and integration coverage are expanded.
- Do not introduce a unified backend `OperationalEvent` model or unrelated duty/swap/qualification refactors.

---

### Task 1: Isolated implementation workspace and shared UI contracts

**Files:**
- Create: `frontend/src/components/planning/PlanningTable.tsx`
- Create: `frontend/src/components/planning/EventDetailModal.tsx`
- Create: `frontend/src/components/planning/RosterSection.tsx`
- Create: `frontend/src/components/planning/AssignmentRow.tsx`
- Create: `frontend/src/components/planning/index.ts`
- Create: `frontend/src/components/planning/PlanningTable.test.tsx`
- Create: `frontend/src/components/planning/EventDetailModal.test.tsx`
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`
- Modify: `frontend/src/components/ShiftEditAssignmentsModal.tsx`

**Interfaces:**
- `PlanningTable<T>` accepts `columns`, `rows`, `getRowId`, `onRowClick`, `filters`, `sort`, `pagination`, `rowActions`, and loading/error/empty state props.
- `EventDetailModal` accepts `open`, `title`, `subtitle`, `metadata`, `actions`, `onClose`, and a children slot.
- `RosterSection` accepts a `kind` (`primary` or `reserve`), assignment list, and assignment action renderer.
- `AssignmentRow` accepts soldier identity, assignment status, draft state, and action slots.

- [ ] **Step 1: Create the feature worktree from `dev` and record the base SHA.**

Run `git worktree add .worktrees/mitvachim-ui-overhaul -b feature/mitvachim-ui-overhaul dev`; record `git rev-parse dev` before implementation.

- [ ] **Step 2: Write shared primitive tests first.**

Test that the table renders loading/error/empty states, deterministic headers and row actions, and invokes row click without invoking an action click. Test that the modal renders title, metadata, close action, and responsive content slot. Test roster grouping and assignment status/draft badges.

- [ ] **Step 3: Implement the shared primitives with existing design-system components.**

Keep sorting/filtering state controlled by callers; do not embed range or shift business rules. Ensure keyboard focus, accessible labels, and mobile overflow match the existing shift UI.

- [ ] **Step 4: Migrate shift detail/roster presentation to the primitives.**

Preserve all current shift-specific swap, dismissal, reserve-call-up, and authorization behavior. Run `npm test -- --run frontend/src/components/planning` and the existing shift page tests.

- [ ] **Step 5: Commit the shared UI slice.**

Run `npm run typecheck` and `npm run lint`; commit with `feat: extract shared planning components`.

### Task 2: Range lifecycle API, persistence, and authorization

**Files:**
- Modify: `backend/app/db/models.py` or the existing range model module
- Modify: `backend/app/routes/ranges.py`
- Modify: `backend/app/services/ranges.py`
- Modify: `backend/app/schemas/ranges.py` or the existing range schemas module
- Create: `backend/alembic/versions/<revision>_add_range_cancellation_reason.py`
- Test: `backend/tests/unit/test_ranges_service.py`
- Test: `backend/tests/integration/test_ranges_api.py`

**Interfaces:**
- `UpdateRangeEventBody` carries all editable fields plus `force_schedule_change: bool` for date/type changes with assignments.
- `DELETE /ranges/{range_id}` returns success only for an unassigned range without attendance/qualification history.
- `POST /ranges/{range_id}/cancel` requires `{ "reason": string }` and returns the cancelled range.
- Service errors map to existing 4xx conventions and never bypass scoped manager authorization.

- [ ] **Step 1: Add failing service tests for full edits, completed/cancelled rejection, delete guards, and cancellation reasons.**

Cover empty-range delete, assigned-range delete rejection, attendance-history delete rejection, missing/blank cancellation reason, planned cancellation, and completed/cancelled immutability.

- [ ] **Step 2: Add the cancellation reason column and migration.**

Use a nullable text column for legacy rows; store the normalized reason on cancellation and include it in the serialized event/audit context.

- [ ] **Step 3: Implement service validation and route schemas.**

Validate date/time ordering and planned-only mutation before changing any field. Require explicit confirmation for date/type changes when assignments exist, and reject the request server-side when the confirmation flag is absent.

- [ ] **Step 4: Implement guarded delete and reasoned cancel endpoints.**

Reuse existing range authorization helpers and history queries. Do not physically remove rows that have assignments, attendance, or qualification side effects.

- [ ] **Step 5: Run focused backend tests and commit.**

Run `pytest -q backend/tests/unit/test_ranges_service.py backend/tests/integration/test_ranges_api.py`; commit with `feat: add range lifecycle guards`.

### Task 3: Range notification types and side effects

**Files:**
- Modify: `backend/app/db/models.py` notification enum/model
- Modify: `backend/app/services/ranges.py`
- Modify: `backend/app/services/range_excusal.py`
- Modify: `backend/app/services/range_reminders.py`
- Modify: `backend/app/routes/ranges.py`
- Modify: `frontend/src/api/notifications.ts`
- Modify: `frontend/src/components/NotificationBell.tsx`
- Modify: `frontend/src/pages/NotificationsPage.tsx`
- Test: `backend/tests/unit/test_ranges_service.py`
- Test: `backend/tests/unit/test_range_excusal.py`
- Test: `backend/tests/unit/test_range_attendance.py`
- Test: `frontend/src/components/NotificationBell.test.tsx`

**Interfaces:**
- Add distinct notification types for roster change, range cancellation, and range no-show; retain existing assignment, excusal, reminder, and shortfall types.
- Notification payload/reference includes range ID, date, type, location, actor, and reason/context.

- [ ] **Step 1: Write failing recipient/type tests.**

Assert primary/reserve assignees receive roster and cancellation changes, managers receive fill/no-show context, and no-show notifications are emitted only on a recorded no-show transition.

- [ ] **Step 2: Add enum values, labels, icons, and migration handling.**

Keep existing notification preferences compatible and give new types safe fallback labels for old clients.

- [ ] **Step 3: Emit notifications from roster mutation, cancel, and attendance/no-show transitions.**

Use `create_notification` and existing reference fields; avoid duplicate notifications for idempotent updates. Keep reminder worker behavior intact.

- [ ] **Step 4: Render the new types in bell/list surfaces and test them.**

Preserve unread counts, filtering, and navigation to the range reference.

- [ ] **Step 5: Run focused notification tests and commit.**

Run backend notification/range tests and `npm test -- --run frontend/src/components/NotificationBell.test.tsx`; commit with `feat: notify range lifecycle changes`.

### Task 4: Range planning board and modal

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/api/ranges.ts`
- Create: `frontend/src/components/ranges/RangePlanningTable.tsx`
- Create: `frontend/src/components/ranges/RangeDetailContent.tsx`
- Create: `frontend/src/components/ranges/RangeFormModal.tsx`
- Create: `frontend/src/components/ranges/RangeCancelDialog.tsx`
- Modify: `frontend/src/components/ranges/RangeAttendancePanel.tsx`
- Test: `frontend/src/pages/RangesPage.test.tsx`
- Create: `frontend/src/components/ranges/RangeFormModal.test.tsx`

**Interfaces:**
- Range table columns: date, type, location, primary fill, reserve fill, status, row actions.
- Filters: date range, type, status, and fill state; default sort is nearest planned date first.
- `RangeDetailContent` receives the selected range and existing range mutation callbacks; it renders instructions/contact, separate primary/reserve rosters, drafts, excusal, attendance/no-show.

- [ ] **Step 1: Extend typed range API clients for full edit, delete, and cancel payloads.**

Add `force_schedule_change` and cancellation reason types while retaining existing auto-assign, confirm, roster, excusal, and attendance methods.

- [ ] **Step 2: Write failing page/modal tests.**

Test row click, row actions, filters/sort, instructions/contact/roster rendering, edit confirmation for date/type changes with assignments, empty-range delete, assigned-range cancellation reason, and query invalidation after mutations.

- [ ] **Step 3: Implement the board using `PlanningTable`.**

Keep row actions explicit and stop action clicks from opening the modal. Show cancelled/history rows and hide edit/delete/cancel controls for completed events according to server state.

- [ ] **Step 4: Implement `RangeDetailContent` with `EventDetailModal`, `RosterSection`, and `AssignmentRow`.**

Reuse existing domain panels for auto-assignment, excusal, attendance, and no-show. Display primary/reserve assignees and all requested event metadata.

- [ ] **Step 5: Implement full edit/create and cancel/delete dialogs.**

Enforce `start <= end`, require cancellation reason, and show a warning before date/type edits with an existing roster.

- [ ] **Step 6: Run frontend range tests, typecheck, and lint; commit.**

Use `npm test -- --run frontend/src/pages/RangesPage.test.tsx frontend/src/components/ranges/RangeFormModal.test.tsx`, `npm run typecheck`, and `npm run lint`; commit with `feat: add range planning board`.

### Task 5: Auto-assignment regression coverage

**Files:**
- Modify: `backend/tests/unit/test_range_auto_assign.py`
- Modify: `backend/app/services/range_auto_assign.py` only if a test exposes an existing defect
- Test: `backend/tests/unit/test_ranges_service.py`

**Interfaces:**
- Preserve the current auto-assignment entry point and result shape.
- Tests must exercise eligibility filters, three-tier ordering, primary/reserve quotas, existing assignments, draft output, and shortfall reporting.

- [ ] **Step 1: Add deterministic failing tests for each algorithm branch.**

Use small in-memory candidate fixtures with explicit qualification, overlap, availability, prior-assignment, tier, and quota values; assert exact selected IDs and shortfall counts.

- [ ] **Step 2: Run `pytest -q backend/tests/unit/test_range_auto_assign.py` and verify the new tests fail only where behavior is missing.**

- [ ] **Step 3: Make the smallest implementation correction if required.**

Do not change ranking policy or introduce database imports into the pure algorithm module.

- [ ] **Step 4: Run algorithm and service tests and commit.**

Run `pytest -m algorithm -q backend/tests/unit/test_range_auto_assign.py backend/tests/unit/test_ranges_service.py`; commit with `test: cover range auto assignment branches`.

### Task 6: Settings, gating, and seed scenarios

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Modify: `frontend/src/pages/SystemSettingsPage.test.tsx`
- Modify: `backend/app/routes/ranges.py`
- Modify: `backend/app/scripts/seed.py`
- Modify: `backend/app/scripts/tests/test_seed_bootstrap.py`
- Modify: `frontend/src/components/dashboard/UpcomingRangesWidget.tsx`
- Test: `backend/tests/integration/test_public_settings_ranges.py`

**Interfaces:**
- The admin settings view renders `mitvachim.enabled` and the range reminder setting under the existing מטווחים group.
- Seed creates a past staffed range with present/no-show attendance, an upcoming staffed range with primary/reserve assignments, and an upcoming empty range.

- [ ] **Step 1: Add failing settings/seed tests.**

Assert the toggle is rendered for an authorized admin, hidden from unauthorized users, backend/public settings expose the expected value, disabled settings gate routes/widgets/notifications, and seeding is idempotent with the three scenarios.

- [ ] **Step 2: Trace and fix settings gating across routes, page, widget, and notification paths.**

Use the existing `mitvachim.enabled` setting rather than adding a second flag; preserve reminder defaults.

- [ ] **Step 3: Stabilize seed IDs/assignments and attendance data.**

Keep past range status usable for no-show testing, assign named soldiers deterministically, and avoid duplicate rows on repeated seed runs.

- [ ] **Step 4: Run seed/settings tests and commit.**

Run `pytest -q backend/app/scripts/tests/test_seed_bootstrap.py backend/tests/integration/test_public_settings_ranges.py` and the settings/widget frontend tests; commit with `fix: expose and seed range settings scenarios`.

### Task 7: Integration verification and final review

**Files:**
- Modify: `frontend/CHANGELOG.md` only during the project release skill, not in the feature branch
- No new product files unless a failing integration test identifies a concrete gap.

- [ ] **Step 1: Run backend focused suites.**

Run `pytest -m "algorithm or notifications or misc" -q` plus all range unit/integration/service tests.

- [ ] **Step 2: Run frontend tests, lint, and typecheck.**

Run `npm test`, `npm run lint`, and `npm run typecheck` from `frontend`.

- [ ] **Step 3: Perform the seeded end-to-end sanity path.**

With `mitvachim.enabled=true`, open the board, inspect past no-show data, inspect staffed primary/reserve/contact/instructions, edit the empty range, auto-assign it, and cancel a staffed range with a reason.

- [ ] **Step 4: Dispatch broad code review and address findings through the review loop.**

Review the full branch against this plan and the approved spec, including authorization parity, query invalidation, notification idempotency, migration compatibility, and preservation of user-owned changes.

- [ ] **Step 5: Complete through `merge-worktree-to-dev`.**

After all tests pass, present the project skill's four integration options. Do not merge directly to `master` or update the changelog in this feature branch.
