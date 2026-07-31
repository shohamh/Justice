# מטווחים (Ranges) — Phase 4: advance reminders design spec

## Goal

Send an advance notice N days before a range event: to every currently
assigned soldier (primary + reserve), and to the DM/commander managing
it — escalated if the roster isn't full. Builds on
[Phase 1](2026-07-31-mitvachim-phase1-design.md)/
[2](2026-07-31-mitvachim-phase2-auto-assign-design.md)/
[3](2026-07-31-mitvachim-phase3-excusal-design.md) — one new setting, one
new column, one new background worker; no new tables.

## Current state (relevant existing patterns)

- No generic "N days before X" reminder abstraction exists anywhere in
  the codebase today (confirmed by earlier research into the
  notifications system) — the only comparable background pollers are
  `backend/app/swap_expiry_worker.py` (asyncio loop, ~300s poll) and
  `backend/app/email_worker.py`. This phase introduces the first
  scheduled-reminder worker, specific to ranges (not a generalized
  framework — no other subsystem asked for this).
- `create_notification`/`NotificationType`
  (`backend/app/services/notifications.py:273`, `models.py:982`) is
  reused for delivery, same as every other notification in the app.
- `scope_root_ids()`/`_node_in_scope()` (`backend/app/auth/authz.py`) is
  reused to resolve which DMs/commanders manage a given
  `RangeEvent.hierarchy_node_id`.

## Rejected approaches

- **Multiple configurable reminder thresholds (e.g. 7 days + 1 day)**:
  rejected per your choice — a single fixed threshold
  (`mitvachim.reminder_days_before`) is simpler to reason about and
  sufficient; multiple thresholds can be revisited later if actually
  needed.
- **Reminding only assigned soldiers, not the DM**: rejected per your
  choice — the DM/commander managing the event also gets a reminder, so
  they can catch and fix an under-filled roster before the event, not
  just find out too late.
- **A generic cross-subsystem reminder framework**: rejected as
  overkill — only ranges have this requirement today; building an
  abstraction for a single consumer is premature.

## Design

**New `SystemSetting`**: `mitvachim.reminder_days_before` (int) — how
many days before `RangeEvent.date` the reminder fires.

**New worker `backend/app/range_reminder_worker.py`**, same shape as
`swap_expiry_worker.py` (asyncio loop, similar poll interval — daily
granularity is sufficient since the threshold is date-based, but polling
every few minutes like the existing worker is harmless and keeps the
pattern consistent):

Each cycle:
1. Query `RangeEvent` rows where `status = "planned"`,
   `reminder_sent_at IS NULL`, and
   `date - today() == reminder_days_before` (read from
   `SystemSetting`; skip entirely if `mitvachim.enabled` is false).
2. For each matching event:
   - Notify every `RangeAssignment` (primary and reserve, any
     non-excused status) individually — soldier-facing reminder,
     includes event date/time/location/contact info.
   - Resolve the managing DM/commander scope for
     `event.hierarchy_node_id` and notify them — a summary reminder
     (event details + current fill: `X/required_count` primary,
     `Y/reserve_count` reserve).
   - If `filled_primary < required_count` or
     `filled_reserve < reserve_count`, send the DM notification as an
     escalated variant (distinct `NotificationType` or an urgency flag
     in the payload) calling out the exact shortfall, instead of (not
     in addition to) the normal DM reminder.
   - Set `RangeEvent.reminder_sent_at = now()` so the event is never
     reminded twice.

**Known accepted limitation**: a soldier added to the roster *after* the
reminder has already fired for that event (e.g. via a Phase 3
auto-promotion, or a late manual add) does not get their own personal
reminder — the one-time `reminder_sent_at` flag is event-scoped, not
per-assignment. This is acceptable because the DM's shortfall-aware
reminder already surfaces roster gaps before the event; re-triggering
per-soldier reminders on every roster change would meaningfully
complicate the worker for a rare edge case.

## Data model changes

**`RangeEvent`** (extends Phase 1 table) — add:
```python
reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
```

**New `SystemSetting` key**: `mitvachim.reminder_days_before` (int).

**New `NotificationType`** (or reuse an existing generic one with a
payload flag — implementation detail for the plan): a distinct type for
the escalated/shortfall DM reminder so it can render differently (e.g. a
warning icon) from the plain DM reminder and the soldier reminder.

## Backend

**New service function** (`backend/app/services/ranges.py` or a small
new `range_reminders.py`):
- `send_due_range_reminders(session)` — implements the per-cycle logic
  above; called by the worker's loop body, structured so it's directly
  unit-testable without spinning up the actual asyncio loop (mirroring
  how `swap_expiry_worker.py`'s core logic is presumably separated from
  its loop wrapper — verify exact split during planning).

**Worker registration**: `range_reminder_worker.py` started alongside
`swap_expiry_worker.py`/`email_worker.py` wherever those are launched
(`dev.ps1`/app startup — exact wiring is a planning-phase detail).

## Frontend

- Soldier-facing reminder renders in the existing notification bell/list
  like any other notification, using `RangeEvent` details already
  fetchable via the Phase 1 `GET /ranges/{id}` endpoint.
- DM-facing reminder (normal and escalated variants) same, with the
  escalated variant visually distinguished per the new `NotificationType`
  (icon/color), consistent with how other notification types are
  differentiated today (`typeLabels` maps in
  `NotificationBell.tsx`/`NotificationsPage.tsx`).

## Testing

Backend (pytest):
- `send_due_range_reminders` fires exactly at `date - today ==
  reminder_days_before`, not before or after.
- Idempotent: running twice for the same event only sends once
  (`reminder_sent_at` gate).
- Soldier reminders sent to every primary + reserve `RangeAssignment`.
- DM reminder sent to the correct scope (subunit's DM/commander).
- Escalated variant sent instead of the normal one when primary or
  reserve fill is short; normal variant when fully filled.
- No reminders sent when `mitvachim.enabled` is false.
- `cancelled` events never trigger a reminder.

Frontend (vitest):
- Notification list renders the escalated DM reminder distinctly from
  the normal one and from the soldier reminder.
