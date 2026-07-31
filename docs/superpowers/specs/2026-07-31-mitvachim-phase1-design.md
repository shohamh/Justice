# מטווחים (Ranges) — Phase 1 design spec

## Goal

Introduce a new, experimental "מטווחים" (shooting range / weapons
qualification) subsystem: live-fire range, laser range, and אל"ל
(pre-combat training), each event tied to a subunit, with an assigned
roster (n primary + m reserve), and a per-soldier weapons-qualification
expiry that renews when attendance is confirmed. Ranges should look and
feel like duty (תורנות) on the calendar and homepage, but are a distinct
entity, not a `DutyType`/`DutyShift` subtype.

This is **Phase 1 of 4**. It covers: the data model, calendar/homepage
display, manual assignment, attendance confirmation (with retroactive
correction), qualification expiry tracking, and exemptions — all behind a
kill-switch feature flag. It explicitly excludes:

- **Phase 2**: CP-SAT auto-assignment by the priority criteria (subunit →
  soonest-expiring soldiers already on weapon duty → other non-qualified
  soldiers → soldiers sorted by nearest-expiring valid qualification).
- **Phase 3**: soldier self-service "I can't attend" (with mandatory
  reason) + automatic reserve promotion, editable by DM.
- **Phase 4**: advance-notice reminders ("range in N days").

## Current state (relevant existing patterns)

- `DutyType` (`backend/app/db/models.py:175`) holds contact
  name/phone, instructions, default times, `eligible_node_ids` — the
  template for `RangeEvent`'s "arrival info" fields.
- `DutyShift`/`DutyAssignment` (`models.py:402`, `:308`) are the
  slot-then-assignment split; ranges use a simpler single-table
  assignment (`RangeAssignment`) since Phase 1 has no auto-fill.
- `ExemptionType`/`SoldierExemption`
  (`models.py:228`, `:272`) — `is_global`, `start_date`/`end_date`
  (nullable = open-ended), audit fields (`granted_by`, `revoked_by`,
  `revoke_reason`). Reused as-is for range exemptions, plus one new
  column (see Data model).
- `mark_no_show()` (`backend/app/services/no_show.py:22`) — guard clauses
  (event must be over, one-time per assignment, mandatory note),
  `create_adjustment()` (`app/services/adjustments.py`) writes a
  `ScoreAdjustment` (`models.py:744`), `DutyNoShow` (`models.py:772`)
  links back to it, plus `write_audit()` and a soldier notification. This
  is the template for range attendance marking.
- `SystemSetting` (`models.py:103`, key/JSONB value) + `_PUBLIC_KEYS`
  (`backend/app/routes/public_settings.py:14`) + `SystemSettingsPage.tsx`
  — the existing feature-flag convention (e.g. `forced_callup.enabled`),
  reused for the `mitvachim.enabled` kill switch.
- `dm_scope_covers_level()` / `get_level_rank()`
  (`backend/app/services/authority.py:27,10`) — checks whether a DM's
  scope node is at a configured level or higher (closer to root); already
  used for `exemptions.commander_exemption_min_level` (default `מדור`).
  Reused for the `mitvachim.attendance_edit_min_level` gate (default
  `ענף`).
- `UpcomingDutiesWidget.tsx` / `DutyCalendarWidget.tsx` /
  `UnitCalendarPage.tsx` — homepage and calendar surfaces a `RangeEvent`
  needs to appear alongside duty.
- `Action` / `can()` (`backend/app/auth/authz.py:38,139`), bucketed into
  `_DM_ACTIONS`/`_COMMANDER_ACTIONS`/`_DM_GLOBAL_ACTIONS` — new
  `Action.RANGE_MANAGE` (subunit-scoped DM action) and
  `Action.RANGE_ATTENDANCE_EDIT` (elevated-scope DM action) plug in here.

## Rejected approaches

- **Modeling `RangeEvent` as a new `DutyType`**: rejected per explicit
  decision — ranges need their own qualification/expiry semantics and
  attendance-correction rules that don't map cleanly onto duty's
  swap/no-show model, and coupling them would force every duty-type
  consumer (swap requests, algorithm eligibility, etc.) to special-case
  ranges. A standalone entity that plugs into the same calendar/homepage
  surfaces is simpler and safer.
- **Single "highest level achieved" qualification field per soldier**:
  rejected — the hierarchy (אל"ל ⊇ חי ⊇ לייזר) governs *eligibility*, not
  *expiry tracking*. Each level's validity is tracked and decays
  independently, so a soldier can simultaneously have a still-valid
  `live` qualification and an expired `laser` one from an older event.
- **Single global validity duration for all range types**: rejected —
  configurable per level (`mitvachim.laser_validity_days`,
  `.live_validity_days`, `.alal_validity_days`), since real-world
  requalification cadences differ per range type.
- **Commander approval gate on no-show/attendance edits**: rejected — the
  penalty decision rests with the duty manager; if a commander disagrees,
  that's an out-of-system conversation with the DM, not a software
  approval workflow. Access is restricted by DM scope level instead (see
  Permissions).
- **New exemption-mapping table for ranges** (like
  `ExemptionDutyTypeMap`): rejected in favor of a single new boolean
  column on `ExemptionType` (`forbids_weapons`), since range exemption
  only needs a yes/no per exemption type, not a many-to-many scope.

## Data model

**New enum `RangeType`**: `laser` (rank 1) < `live` (rank 2) < `alal`
(rank 3). A qualification at a higher rank satisfies eligibility for a
duty requiring a lower rank (used starting Phase 2; the rank ordering is
defined in Phase 1 since the enum and `SoldierRangeQualification` rows
need it from day one).

**New table `RangeEvent`**:
| column | type | notes |
|---|---|---|
| `id` | UUID pk | `gen_random_uuid()` |
| `hierarchy_node_id` | UUID FK → hierarchy_nodes.id | any level (platoon/squad/team/etc.) |
| `range_type` | Enum(`RangeType`) | |
| `date` | Date | |
| `start_time`, `end_time` | Text ("HH:MM") | mirrors `DutyAssignment` time fields |
| `location` | Text | |
| `arrival_instructions` | Text, nullable | |
| `contact_name`, `contact_phone` | Text, nullable | mirrors `DutyType` |
| `required_count` | Integer | n primary slots |
| `reserve_count` | Integer | m reserve slots |
| `status` | Enum: `planned`/`completed`/`cancelled` | |
| `created_by` | UUID FK → soldiers.id | |
| `notes` | Text, nullable | |
| `created_at`/`updated_at` | timestamptz | server default `now()` |

**New table `RangeAssignment`** (one row per assigned soldier):
| column | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `range_event_id` | UUID FK → range_events.id, `ondelete=CASCADE` | |
| `soldier_id` | UUID FK → soldiers.id | |
| `is_reserve` | Boolean | |
| `attendance_status` | Enum: `pending`/`present`/`no_show` | default `pending` |
| `marked_by` | UUID FK → soldiers.id, nullable | who last set attendance_status |
| `marked_at` | timestamptz, nullable | |
| `note` | Text, nullable | **required** when `attendance_status = no_show` (enforced in service, not DB) |
| `score_adjustment_id` | UUID FK → score_adjustments.id, nullable | set when a no_show penalty was applied |

Unique constraint on `(range_event_id, soldier_id)`.

**New table `SoldierRangeQualification`** (one row per soldier per
range type — normalized so each level's expiry is tracked
independently):
| column | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `soldier_id` | UUID FK → soldiers.id | |
| `range_type` | Enum(`RangeType`) | |
| `valid_until` | Date | |
| `source_range_assignment_id` | UUID FK → range_assignments.id, nullable | provenance |
| `updated_at` | timestamptz | |

Unique constraint on `(soldier_id, range_type)` — upserted whenever an
attendance mark sets `present` for that type.

**`DutyType`** — add:
```python
requires_weapon: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```
Drives the "not eligible for any weapon duty type" auto-exemption below.

**`ExemptionType`** — add:
```python
forbids_weapons: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

**Exemption rule** (computed, not stored): a soldier is exempt from a
specific `RangeEvent` if **either**:
1. They have an active `SoldierExemption` covering `event.date`
   (`start_date <= event.date` and (`end_date is null` or
   `end_date >= event.date`)) whose `ExemptionType` has `is_global=true`
   **or** `forbids_weapons=true`; **or**
2. They are structurally ineligible for *any* `DutyType` with
   `requires_weapon=true` (i.e. no such duty type's `eligible_node_ids`
   covers their hierarchy path) — same shape as existing duty-type
   eligibility checks used elsewhere.

**New `SystemSetting` keys**:
- `mitvachim.enabled` (bool) — subsystem kill switch.
- `mitvachim.laser_validity_days`, `mitvachim.live_validity_days`,
  `mitvachim.alal_validity_days` (int) — qualification duration per
  level.
- `mitvachim.attendance_edit_min_level` (string, default `"ענף"`) —
  minimum DM scope level (via `get_level_rank`) required to mark/correct
  attendance.

## Backend

**New action constants** (`backend/app/auth/authz.py`):
- `Action.RANGE_MANAGE` — create/edit `RangeEvent`, add/remove
  `RangeAssignment` rows. Bucketed as a regular DM action
  (`_DM_ACTIONS`), scoped to the event's `hierarchy_node_id` subtree via
  the existing `scope_root_ids()`/`_node_in_scope()` idiom.
- `Action.RANGE_ATTENDANCE_EDIT` — mark/correct `attendance_status`.
  Checked via `dm_scope_covers_level(scope_node, required_level_key=
  get_setting("mitvachim.attendance_edit_min_level"))`, i.e. the DM's own
  scope node (not just any ancestor covering the target) must itself be
  at `ענף` rank or higher. Commanders get **no** grant for this action
  regardless of rank — deliberately excluded per the rejected-approaches
  note above.

**New service `backend/app/services/ranges.py`**:
- `create_range_event(...)` — validates `hierarchy_node_id` exists,
  `required_count`/`reserve_count >= 0`.
- `add_range_assignment(event, soldier_id, is_reserve)` — rejects if the
  soldier is range-exempt (per the rule above) or outside
  `event.hierarchy_node_id`'s subtree; raises a validation error (not a
  silent skip).
- `remove_range_assignment(assignment)` — only while `event.status ==
  planned`.
- `mark_attendance(assignment, status, marked_by, note=None)`:
  - Rejects if `event.date` is in the future, if `event.status ==
    cancelled`, or (for `no_show`) if `note` is empty.
  - If flipping from a prior status, first reverses the old side effect:
    delete/void the linked `score_adjustment_id` if reversing a
    `no_show`, or delete the `SoldierRangeQualification` row's
    provenance update if reversing a `present` (recompute `valid_until`
    from the next-most-recent qualifying event, or delete the row if
    none exists).
  - Applies the new side effect: `present` → upsert
    `SoldierRangeQualification(soldier_id, event.range_type, valid_until
    = event.date + validity_days_for(event.range_type))`; `no_show` →
    `create_adjustment()` (mirroring `mark_no_show()`) + `write_audit()`
    + soldier notification.
  - Every transition writes a `write_audit()` entry (before/after JSON),
    mirroring the no-show audit pattern.
- `cancel_range_event(event)` — sets `status = cancelled`; blocks further
  `mark_attendance` calls (checked in `mark_attendance` itself).

**New routes** (`backend/app/routes/ranges.py`, prefix `/ranges`):
- `POST /ranges` (`RANGE_MANAGE`) — create event.
- `PATCH /ranges/{id}` (`RANGE_MANAGE`) — edit fields, cancel.
- `POST /ranges/{id}/assignments`, `DELETE /ranges/{id}/assignments/{id}`
  (`RANGE_MANAGE`).
- `PATCH /ranges/{id}/assignments/{id}/attendance`
  (`RANGE_ATTENDANCE_EDIT`) — body `{status, note?}`.
- `GET /ranges` (scoped list, filterable by node/date range — same
  shape as existing duty list endpoints) for calendar/homepage/planning
  page consumption.
- `GET /ranges/{id}` — event + roster + current qualification status per
  assigned soldier (for the commander read-only view).

All routes short-circuit with 404 if `mitvachim.enabled` is false (mirror
however `forced_callup.enabled` currently gates its routes).

## Frontend

- **Feature flag gate**: `App.tsx`/`Layout.tsx`/`UnifiedNav.tsx` add a
  `mitvachimEnabled = settings?.["mitvachim.enabled"] === true` check
  (same pattern as `hakpazaEnabled`), hiding all range nav/routes when
  off. `SystemSettingsPage.tsx` gets a new boolean toggle entry plus the
  three validity-days number settings and the min-level string setting.
- **Calendar/board**: `DutyCalendarWidget.tsx`/`UnitCalendarPage.tsx`
  render `RangeEvent`s alongside duty shifts with a distinct
  color/icon, scoped by hierarchy node the same way duty shifts already
  are.
- **Homepage**: `UpcomingDutiesWidget.tsx` extended (or a sibling
  widget) to list upcoming `RangeEvent`s the viewer is assigned to or
  manages, same closest-first ordering as duty.
- **Planning page** (new, under "תכנון"): create/edit range events,
  add/remove roster (primary + reserve), mirroring
  `DutyManagementPage.tsx`'s layout. Visible to `RANGE_MANAGE`-scoped
  users.
- **Commander page** (new): read-only roster + current qualification
  status per soldier, for commanders overseeing the event's subunit
  (view-only — no attendance edit controls rendered, per the permission
  split).
- **Attendance confirmation UI** (new, under the planning/DM area):
  for past events, list the roster with present/no-show toggles (note
  required for no-show), visible only to `RANGE_ATTENDANCE_EDIT`-scoped
  users; includes the ability to flip an already-marked row (the
  correction path).
- **New `frontend/src/api/ranges.ts`**: thin wrappers for the routes
  above, mirroring `api/notifications.ts` style.

## Testing

Backend (pytest, marker `misc` or a new `mitvachim` marker per the
per-area convention):
- Exemption rule: global exemption covering event date exempts;
  time-limited `forbids_weapons` exemption covering event date exempts;
  one that expired before `event.date` does not; structural
  no-weapon-duty-type ineligibility exempts.
- `add_range_assignment` rejects an exempt soldier and a soldier outside
  the event's subunit.
- `mark_attendance(present)` upserts `SoldierRangeQualification` with the
  correct `valid_until` per `range_type`'s configured validity days.
- `mark_attendance(no_show)` requires a note, creates a linked
  `ScoreAdjustment`, writes audit, notifies the soldier.
- Flipping `present → no_show` reverses the qualification update and
  applies the penalty; flipping back reverses the penalty and restores
  qualification.
- `mark_attendance` rejects when `event.date` is in the future or
  `event.status == cancelled`.
- `RANGE_ATTENDANCE_EDIT` authorization: DM at `ענף` rank or higher in
  scope → allowed; DM below that rank → denied; commander (any rank) →
  denied.
- All `/ranges/*` routes 404 when `mitvachim.enabled` is false.

Frontend (vitest):
- Nav/routes hidden when `mitvachim.enabled` is false.
- Calendar/homepage widgets render `RangeEvent`s distinctly from duty.
- Attendance UI enforces mandatory note on no-show; correction flip
  re-submits correctly.
- Planning page hidden from users without `RANGE_MANAGE`; attendance UI
  hidden from users without `RANGE_ATTENDANCE_EDIT`.
