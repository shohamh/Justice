# מטווחים Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task with review checkpoints.

**Goal:** Send one advance reminder for each planned range event to every active assignee and its managing duty manager/commander, with a distinct shortfall warning when the roster is under-filled.

**Architecture:** Add an event-level `reminder_sent_at` gate and one configurable integer setting. Keep the business logic in a synchronous, unit-testable `send_due_range_reminders(session, today=...)` service function; a small asyncio worker opens a session and calls it periodically, registered beside the existing workers. Reuse `create_notification` and the existing scope-resolution helper, adding two range reminder notification types and rendering them in the existing notification list.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL enum migrations, pytest, React/TypeScript, Vitest, TanStack Query, i18n Hebrew strings.

## Global Constraints

- Do not create a generic reminder framework; this worker is range-specific.
- A reminder is date-based and fires only when `event.date - today == reminder_days_before`.
- Notify primary and reserve assignments, excluding assignments already marked excused/removed by Phase 3 semantics.
- The manager receives exactly one normal or escalated notification, never both.
- `mitvachim.enabled == false` disables the cycle without mutating events.
- Keep all implementation in an isolated feature worktree branched from `dev`; do not commit directly to `dev` or `master`.

---

### Task 1: Schema and setting foundation

**Files:**
- Create: `backend/alembic/versions/<revision>_add_range_reminder_fields.py`
- Modify: `backend/app/db/models.py` (`RangeEvent`, `NotificationType`)
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` (ranges settings)
- Modify: `frontend/src/i18n/he.json` (notification type labels)
- Test: `backend/tests/unit/test_range_models.py`

**Interfaces:**
- Produces `RangeEvent.reminder_sent_at: datetime | None`.
- Produces `NotificationType.range_reminder` and `NotificationType.range_reminder_shortfall`.
- Produces the persisted setting key `mitvachim.reminder_days_before`, default `3`.

- [ ] Write model tests proving a new event has a null reminder timestamp and notification enum values are available.
- [ ] Run the focused model tests and confirm they fail because the field/types do not exist.
- [ ] Add the nullable timezone-aware column and PostgreSQL enum values in one Alembic revision with a reversible downgrade.
- [ ] Add the setting to the existing “מטווחים” settings group with numeric input, default `3`, and Hebrew description.
- [ ] Add Hebrew labels for both new notification types and update the i18n enum-coverage test expectations if required by its existing pattern.
- [ ] Run focused backend model/migration tests and frontend i18n tests.
- [ ] Commit as `feat: add range reminder schema and setting` in the feature worktree.

### Task 2: Due-reminder service

**Files:**
- Create: `backend/app/services/range_reminders.py`
- Modify: `backend/app/services/notifications.py` only if an existing scope helper needs a narrowly scoped reusable export
- Test: `backend/tests/unit/test_range_reminders.py`

**Interfaces:**
- Consumes `SystemSetting`, `RangeEvent`, `RangeAssignment`, `Soldier`, hierarchy/scope models, `create_notification`, and `notify_duty_managers_in_scope`.
- Produces `send_due_range_reminders(session: Session, *, today: date | None = None) -> int`, returning the number of events marked sent.

- [ ] Write failing tests for exact threshold matching, no early/late send, feature flag off, cancelled events, and idempotency.
- [ ] Write failing tests asserting one soldier notification per current primary/reserve assignment and one manager notification with event details and fill counts.
- [ ] Write failing tests for full roster versus primary/reserve shortfall, asserting normal and shortfall enum types are mutually exclusive.
- [ ] Run the focused test file and verify failures are caused by the missing service.
- [ ] Implement setting loading with fallback `3`, `mitvachim.enabled` gating, planned-event filtering, and the exact date comparison.
- [ ] Build stable Hebrew notification titles/bodies containing date, time when present, location, contact, and the manager fill summary; use `reference_type="range_event"` and the event id.
- [ ] Resolve managers using the existing hierarchy scope helper, deduplicate recipient ids, create notifications, set `reminder_sent_at` only after the event’s notifications are prepared, and commit once per service call.
- [ ] Run the focused tests, then the existing range service/notification tests.
- [ ] Commit as `feat: implement due range reminder service`.

### Task 3: Background worker and application wiring

**Files:**
- Create: `backend/app/range_reminder_worker.py`
- Modify: `backend/app/main.py` lifespan imports, task creation, and cancellation
- Test: `backend/tests/unit/test_range_reminder_worker.py`

**Interfaces:**
- Produces `async def run_range_reminder_worker() -> None` with the same session/loop lifecycle pattern as `run_swap_expiry_worker`.

- [ ] Write failing tests for one worker cycle invoking the service and for cancellation/cleanup behavior using the existing worker testing conventions.
- [ ] Run the focused worker tests and verify the expected missing-module/function failures.
- [ ] Implement a small polling loop with the established interval pattern, opening a fresh DB session for each cycle, logging failures, and sleeping without swallowing cancellation.
- [ ] Register and cancel the new task in `backend/app/main.py` alongside the existing email and swap workers.
- [ ] Run worker tests and an application import/lifespan smoke test.
- [ ] Commit as `feat: run range reminder worker with application`.

### Task 4: Notification presentation

**Files:**
- Modify: `frontend/src/pages/NotificationsPage.tsx`
- Modify: `frontend/src/components/NotificationBell.tsx` if it has a separate type/icon map
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/pages/NotificationsPage.test.tsx` and/or the existing bell test file

**Interfaces:**
- Consumes backend notification records with `type` equal to `range_reminder` or `range_reminder_shortfall`.
- Produces distinct icon/color presentation for soldier reminder, normal manager reminder, and shortfall manager reminder.

- [ ] Add failing Vitest cases rendering each new type and asserting the shortfall variant is visually distinguishable and uses its translated label/icon.
- [ ] Run the focused frontend tests and confirm failure before implementation.
- [ ] Extend every existing notification type map used by the bell/list, preserving the generic fallback for unknown types.
- [ ] Add Hebrew translations and avoid duplicating divergent labels between the page and bell.
- [ ] Run focused notification tests, frontend typecheck, and lint.
- [ ] Commit as `feat: render range reminder notifications`.

### Task 5: Full verification and handoff

**Files:** none beyond the files above.

- [ ] Run the complete focused backend range suite, then `pytest -q` from `backend` using the worktree’s independent virtual environment.
- [ ] Run the complete frontend Vitest suite, `npm run lint`, and `npm run typecheck`.
- [ ] Run Alembic heads and verify one head after applying the new migration in the test database.
- [ ] Review the diff for notification idempotency, manager scope, enum migration ordering, and no changes to unrelated dirty files.
- [ ] Report the feature-worktree branch, commits, tests, and any environment limitation; integration to `dev` follows the project’s merge-worktree skill.
