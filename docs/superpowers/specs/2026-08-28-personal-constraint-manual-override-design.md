# Personal-constraint manual-override — design

## Background

`PersonalConstraint` rows (אילוץ אישי) record dates a soldier has requested
not to be assigned duties/ranges, approved through the existing
commander → duty-manager approval chain
([constraints.py](../../../backend/app/services/constraints.py)).

Today an **approved** constraint:
- Hard-blocks the soldier from duty assignment, both in the CP-SAT solver
  ([availability.py:27-65](../../../backend/app/algorithm/availability.py))
  and in manual assignment
  ([eligibility.py:290-298](../../../backend/app/services/eligibility.py)).
- Does **not** block range assignment at all — it only produces a
  conditional soft warning when the soldier also has a near-term weapon
  duty ([range_auto_assign.py:281-306](../../../backend/app/services/range_auto_assign.py)).

Personal constraints do **not** affect the `active_days` fairness/score
calculation ([scoring.py:327](../../../backend/app/services/scoring.py)); that
figure is driven solely by `SoldierExemption` full-coverage rows. This was
confirmed out of scope for this change — no code here touches
`active_days`.

## Goal

Let duty managers manually assign a soldier who has an approved personal
constraint, when a system setting allows it, while:
- always surfacing the constraint clearly in the assignment UI,
- requiring a stated reason for the override,
- notifying the soldier and their commander(s) of the override and why,
- keeping the automatic solver's hard block completely untouched,
- leaving a queryable audit trail.

## Non-goals

- No change to `active_days`/scoring.
- No change to CP-SAT solver behavior — it keeps its unconditional hard
  block on approved constraints.
- No change to the constraint approval workflow itself.

## 1. System setting

New boolean key `constraints.allow_manual_override`, default **on**,
admin-only. Added as a single `SettingDef` entry on
[SystemSettingsPage.tsx](../../../frontend/src/pages/SystemSettingsPage.tsx).
No Alembic migration needed — settings live in the existing EAV
`system_settings` table
([models.py:113-123](../../../backend/app/db/models.py)). Backend reads it
via `settings_loader.get_setting` with a `True` fallback on
`SettingNotFound`, matching the idiom at
[constraints.py:37](../../../backend/app/services/constraints.py).

Behavior:

| Setting | Duty manual assignment | Range manual assignment |
|---|---|---|
| ON | Selectable, warning icon, override reason required | Selectable, warning icon, override reason required |
| OFF | Hard-blocked (today's behavior, unchanged) | Hard-blocked (**new** — today ranges never hard-block) |

## 2. Backend eligibility changes

### Duties

[`check_soldier_for_assignment`](../../../backend/app/services/eligibility.py)
step 3 (personal-constraint check) becomes conditional on the setting:

- Setting ON: soldier remains eligible; the result carries a
  `personal_constraint_warning` payload: `reason`, `start_date`,
  `end_date`, `decided_by`, `decided_at` (pulled from the `PersonalConstraint`
  row — `decided_by`/`decided_at` already exist on that model).
- Setting OFF: unchanged — hard block with today's Hebrew reason string.

### Ranges

[`_bulk_eligibility`](../../../backend/app/services/range_auto_assign.py)
changes:

- Setting ON: any approved constraint overlap always attaches
  `personal_constraint_warning` (today it's conditional on a near-term
  weapon duty — that condition is dropped; the warning becomes
  unconditional, same shape as the duty side).
- Setting OFF: approved constraint overlap becomes a hard exclusion — new
  `ExcludedSoldier.reason` literal `"personal_constraint"`.
- [`_validate_and_build_assignment`](../../../backend/app/services/ranges.py:343)
  gains a server-side re-check of the setting + constraint overlap, so
  direct API calls can't bypass the UI-level block when the setting is OFF.

### Assignment write paths

Both the duty assignment endpoint and range's
[`AddAssignmentBody`](../../../backend/app/routes/ranges.py:101) /
batch-assign gain an optional `override_reason: str` field. Server-side
validation: if the request setting is ON and any target soldier currently
has a `personal_constraint_warning`, `override_reason` must be non-empty
or the request is rejected (400). If setting is OFF, the assignment
attempt itself is rejected before `override_reason` is even considered.

## 3. Audit trail

New table `personal_constraint_overrides`:

| column | type | notes |
|---|---|---|
| `id` | PK | |
| `personal_constraint_id` | FK → `personal_constraints` | |
| `soldier_id` | FK → `soldiers` | denormalized for query convenience |
| `overridden_by` | FK → users | the duty manager who performed the override |
| `overridden_at` | timestamptz | |
| `assignment_kind` | text (`"duty"` \| `"range"`) | |
| `reference_id` | int | id of the created duty/range assignment |
| `reason` | text | the (possibly shared-batch) reason text |

One row per overridden soldier per assignment action, even when the
UI reason was shared across a batch — so both the constraint detail view
and a soldier's history can each list only what's relevant to them.

Surfaced as a small read-only list:
- On the personal-constraint detail view (all overrides against that
  constraint).
- On the soldier's history/timeline (all overrides for that soldier,
  across constraints).

## 4. Notifications

New `NotificationType` (naming: `personal_constraint_overridden`). Fires
once per overridden soldier, even under a shared batch reason.

- Hebrew title: `אילוץ אישי נדרס בשיבוץ ל{תורנות|מטווח}` (duty/range wording
  chosen by `assignment_kind`).
- Body includes the reason text and the name of who overrode it.
- Delivery: `create_notification(soldier_id=...)` to the soldier, plus a
  cascade to their commander(s) — using the same chain-of-command cascade
  `constraints.py` already uses for its commander-approval step (**not**
  the duty-manager cascade used elsewhere in `notifications.py`), since
  the requirement is specifically "the user and their commander", not duty
  managers.

## 5. Frontend

- [`ShiftAssignModal.tsx`](../../../frontend/src/components/ShiftAssignModal.tsx)
  and
  [`RangeEditAssignmentsModal.tsx`](../../../frontend/src/components/ranges/RangeEditAssignmentsModal.tsx):
  a constrained-but-overridable candidate (setting ON) moves out of the
  disabled "חסומים" section into the normal selectable list, with a
  warning icon next to their name — same visual language as the existing
  `weapon_warning` amber icon.
- New shared component `ConstraintWarningIcon` (there is no existing
  popover component in the codebase to reuse — the only precedent is a
  native `title` tooltip on `weapon_warning`): hover shows a tooltip
  summary, click opens a small popover with reason, dates, `decided_by`,
  `decided_at`. Used by both modals.
- Setting OFF: unchanged from today — blocked candidates stay in the
  disabled "חסומים" section, no icon (ranges gain this blocked-section
  behavior for the first time, mirroring duties).
- On submit, if the selection includes any soldier carrying a
  `personal_constraint_warning`, a confirm modal opens first: one shared
  free-text reason field for the whole submission (required, non-empty),
  sent as `override_reason` on the assignment call. The actual
  assignment request only fires after this confirm.

## 6. Testing

- Backend: extend duty eligibility tests for the ON/OFF branches; extend
  `test_range_candidates.py`/range service tests for the new
  hard-block/unconditional-warning branches; new test for the
  `personal_constraint_overrides` audit table; a notification test
  asserting delivery to both the soldier and their commander(s).
- Frontend: extend `ShiftAssignModal` and `RangeEditAssignmentsModal` test
  suites for icon rendering, the override-reason confirm-modal gating, and
  the OFF-setting fallback to today's blocked-section behavior.
