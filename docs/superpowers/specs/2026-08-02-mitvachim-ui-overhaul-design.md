# מטווחים — UI overhaul and shared planning components

## Goal

Bring the ranges experience to the same interaction quality and visual language as the shifts board, while preserving the domain-specific behavior already delivered in the four ranges phases: auto-assignment, drafts, excusal/promotion, attendance/no-show, reminders, and range qualification side effects.

The result is a full planning board at `/ranges`, a shift-like range detail modal, reliable seed data for manual testing, complete range notifications, and regression coverage for the range auto-assignment algorithm.

## Product decisions

- `/ranges` becomes a full planning board, structurally parallel to the shifts planning screen.
- Clicking a range row opens a modal. Row-level actions remain available without opening the modal.
- A planned range supports editing all event fields: type, date, start/end time, location, instructions, contact, primary count, reserve count, and notes.
- Editing date or type when assignments exist requires an explicit confirmation in the UI and server-side validation that the event is still planned.
- A range with no assignments and no attendance history may be physically deleted.
- A range with assignments or attendance history cannot be deleted; it can be cancelled with a required cancellation reason and remains visible in the planning history.
- A completed range cannot be edited, deleted, or cancelled.
- The range modal shows event metadata, arrival instructions, contact details, primary assignees, reserve assignees, drafts, excusal state, and attendance/no-show state.
- Range notifications cover assignment confirmation, excusal decisions, advance reminders, roster changes, cancellation, and no-show outcomes. Existing notification preferences and in-app bell/list surfaces remain the delivery mechanism.
- Seed data includes a past range with present/no-show attendance, an upcoming staffed range, and an upcoming empty range.

## Architecture

### Shared UI layer

Extract reusable primitives from the shifts experience without forcing ranges and shifts into one backend model:

- `PlanningTable`: table shell, sorting, filtering, pagination, responsive states, empty/loading/error states, and row-action layout.
- `EventDetailModal`: modal shell, header, metadata area, action bar, close/back behavior, and responsive sizing.
- `RosterSection` and `AssignmentRow`: primary/reserve grouping, soldier identity display, draft/status badges, and action slots.

Domain content remains separate:

- `ShiftDetailContent` keeps swaps, dismissals, duty-specific details, and reserve-call-up behavior.
- `RangeDetailContent` owns range instructions/contact, auto-assign, draft confirmation, excusal, attendance, and no-show behavior.

The existing shift page is migrated incrementally to consume the shared primitives. The range board consumes the same primitives from its first implementation. No unrelated calendar or duty refactor is included.

### Range planning board

The range table displays date, type, location, primary fill, reserve fill, status, and row actions. It uses the existing scoped range list API and query-key registry. Filters include date range, type, status, and fill state. Sorting is deterministic and defaults to the nearest planned date first.

The create/edit form uses the existing range event API shape, expanded where necessary for all editable fields. Mutations invalidate the list and selected-event queries. Delete and cancel actions use explicit confirmation dialogs; cancellation requires a reason.

### Range modal

The modal is opened from a row click or deep link. It shows the same high-level layout as a shift modal, but its content is range-specific. Primary and reserve rosters are separate sections. Managers can add/remove soldiers, run auto-assign, confirm drafts, review excusals, and mark attendance according to the existing authorization rules. Soldiers can see their own excusal action where permitted.

### Backend behavior

- Extend range update validation to support all planned-event fields and reject edits after completion/cancellation.
- Add cancellation reason persistence and audit context. Preserve existing cancellation status semantics.
- Add a deletion guard that rejects deletion when assignments or attendance/qualification history exists.
- Emit notifications through `create_notification` for roster changes, cancellation, and no-show outcomes, using distinct `NotificationType` values and the range event as the reference.
- Keep the existing Phase 2 candidate filtering and three-tier ranking as the only auto-assignment algorithm. Add direct tests for eligibility filters, tier ordering, primary/reserve quotas, existing assignments, drafts, and shortfall.
- Keep `send_due_range_reminders` and `range_reminder_worker` unchanged except where the new notification/UI types require integration.

### Settings and seed

Ensure `mitvachim.enabled` is present in the admin system-settings view, covered by a frontend rendering test, and respected by range routes, the planning page, dashboard widgets, and notifications. Preserve the existing reminder setting and defaults. Update seed fixtures only as needed to guarantee the three manual-testing scenarios and stable soldier assignments.

## Notifications

Use the existing in-app notification bell/list and preferences. Add distinct types/labels/icons for:

- assignment confirmation and roster changes;
- excusal approved/rejected and reserve self-drop;
- advance reminder and shortfall reminder;
- range cancellation;
- no-show recorded.

Notification bodies include the event date, type, location, and relevant actor/reason. Manager notifications include fill status or the exact no-show/cancellation context.

## Testing strategy

### Backend

- Unit tests for range auto-assign ranking and all quota/shortfall branches.
- Service tests for edit validation, delete/cancel guards, notification recipients/types, and no-show side effects.
- API tests for full edit payloads, cancellation reason requirements, deletion rejection, and authorization.
- Seed test asserting the three range scenarios and assigned soldiers exist after seeding.

### Frontend

- Shared table and modal primitives render sorting/filtering/action states.
- Range board opens the modal, edits fields, handles delete/cancel confirmation, and refreshes queries.
- Modal renders instructions, contact, primary/reserve rosters, drafts, excusal, and attendance states.
- Notification bell/list distinguishes all range notification types.
- System settings renders the `mitvachim.enabled` toggle and reminder setting.
- Auto-assign result/shortfall UI remains covered by existing tests and receives regression cases for the expanded board.

### End-to-end sanity path

With seeded data and `mitvachim.enabled=true`: open the ranges planning board, inspect the past range, record/verify no-show behavior, open the staffed upcoming range, inspect primary/reserve details and contact/instructions, edit a planned empty range, run auto-assign, and cancel a range with a reason.

## Out of scope

- A unified backend `OperationalEvent` model for shifts and ranges.
- Replacing the existing duty calendar with a range-specific calendar.
- A generalized cross-subsystem reminder framework.
- Changes to swap, duty algorithm, or qualification rules unrelated to the range UI and notification requirements.
