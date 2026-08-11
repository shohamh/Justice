# Range Eligibility: Drop Hard Constraint for אל"ל + Add "שים לב" Info Signal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the range-eligibility system in line with the intended design — validation is always reactive (never a scheduling hard-constraint) for duty types requiring אל"ל specifically, and add the missing "שים לב" (info) signal — badge + notification — for soldiers who have no currently-valid qualification but a scheduled primary range that will cover an upcoming duty.

**Architecture:** Two independent slices sharing the same eligibility data model (`weapon_eligibility.py` / `range_eligibility_projection.py`):
1. Exclude אל"ל-requiring duties from the CP-SAT solver's hard-block filter (`bulk_ineligible_duty_blocks`), so the algorithm can still assign a soldier to such a duty even with no valid/planned אל"ל — the RED warning still fires afterward via the existing reactive `duty_eligibility_watch` mechanism.
2. Add a persisted "info" cache (mirroring the existing `weapon_ineligible` cache) on `DutyAssignment`, driven by `project_duty_eligibility`'s `qualification_source == "planned_range"`, that (a) surfaces a blue badge in both `ShiftDetailPanel` and the `UnitCalendar` event tile, and (b) notifies the soldier + direct commander + duty managers in scope once when first detected and again if the covering range changes, using the same recipient fan-out as the existing red-warning notification.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend/app), React + TypeScript + i18next (frontend/src), pytest, vitest.

## Global Constraints

- Hard-block exclusion applies ONLY to duties whose `required_range_type == "alal"`. Duties requiring `"live"` or `"laser"` keep today's hard-constraint behavior unchanged.
- No notification is sent on the "good news" direction (info signal clearing, or clearing because the soldier is now covered by a current qualification) — mirrors the existing `weapon_ineligible` cache convention of silent clearing.
- Notification recipients for the new info signal are identical in shape to the existing `weapon_ineligible_detected` flow: soldier, direct commander (`commander_chain_for_soldier`), and all duty managers in scope (`notify_duty_managers_in_scope`) — confirmed correct as-is, do not narrow to "nearest only".
- Badge visibility for BOTH the existing red warning and the new blue info badge must be admin OR commander OR duty-manager — use `frontend/src/auth/permissions.ts`'s existing `canApprove()` semantics (`role === "admin" || is_commander || is_duty_manager"`), not the narrower `admin || is_duty_manager` check currently on the red badge (which incorrectly excludes commanders).
- All new Hebrew strings go in `frontend/src/i18n/he.json`; keep flat dotted key naming consistent with existing `range_qualification.*` and `type_*` keys.
- Follow existing Israeli date format `dd.mm.yyyy` for any new date rendering (backend notification body via `strftime('%d.%m.%Y')`, frontend via the existing local `formatDate` helpers already in scope).

---

### Task 1: Exclude אל"ל-requiring duties from the hard-constraint filter

**Files:**
- Modify: `backend/app/services/weapon_eligibility.py:291`
- Test: `backend/app/services/tests/test_weapon_eligibility.py`
- Test: `backend/app/algorithm/tests/test_weapon_eligibility_constraint.py`

**Interfaces:**
- Consumes: `DutyBlock.required_range_type: str | None` (`backend/app/algorithm/types.py:77`), `DutyBlock.id: uuid.UUID` (`types.py:55`).
- Produces: `bulk_ineligible_duty_blocks(...)` never includes a block id for a duty whose `required_range_type == "alal"` in its returned `{soldier_id: {block_id, ...}}` map — this is consumed unchanged by `algorithm/model.py:337` and `algorithm/solver.py:320,1365`.

- [ ] **Step 1: Write the failing test for the service layer**

Add to `backend/app/services/tests/test_weapon_eligibility.py` (near the other `bulk_ineligible_duty_blocks` tests — follow existing fixture patterns in that file for building a `DutyBlock` and a soldier with no qualifications):

```python
def test_bulk_ineligible_duty_blocks_excludes_alal_duties(app_session, soldier_factory, duty_block_factory):
    soldier = soldier_factory()
    alal_block = duty_block_factory(required_range_type="alal")
    laser_block = duty_block_factory(required_range_type="laser")

    result = bulk_ineligible_duty_blocks(
        app_session,
        soldier_ids=[soldier.id],
        duties=[alal_block, laser_block],
    )

    # Soldier has no qualifications at all -- ineligible for both by the raw
    # data, but only the laser (non-alal) block should surface as a hard
    # block. The alal block must never appear.
    assert alal_block.id not in result.get(soldier.id, set())
    assert laser_block.id in result.get(soldier.id, set())
```

If this test file has no existing `duty_block_factory`/`soldier_factory` fixtures, use whatever helper the neighboring tests in the same file already use to construct a `DutyBlock` and a soldier with `mitvachim.enabled` + `weapon_qualification.enforce_eligibility` turned on (check the setup in the existing `test_bulk_ineligible_duty_blocks_*` tests in this file and copy their pattern exactly).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_weapon_eligibility.py -k alal -v`
Expected: FAIL — `laser_block.id in result` may pass but `alal_block.id not in result` fails because today's code includes both.

- [ ] **Step 3: Implement the fix**

In `backend/app/services/weapon_eligibility.py`, change line 291 from:

```python
    relevant = [d for d in duties if d.required_range_type is not None]
```

to:

```python
    # אל"ל eligibility is always reactive (warning-only) -- never a hard
    # scheduling constraint. Only live/laser requirements still hard-block
    # the (duty, soldier) pair from the solver's eligible set.
    relevant = [d for d in duties if d.required_range_type not in (None, "alal")]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_weapon_eligibility.py -k alal -v`
Expected: PASS

- [ ] **Step 5: Add an algorithm-level regression test**

In `backend/app/algorithm/tests/test_weapon_eligibility_constraint.py`, add a new test alongside the existing three (which all use `required_range_type="laser"` — read `test_hard_constraint_never_assigns_ineligible_soldier` at line 21 first to copy its exact soldier/duty construction pattern):

```python
def test_alal_requirement_never_hard_blocks_assignment():
    """Unlike live/laser, an alal requirement must never remove a soldier
    from the solver's eligible set, even when weapon-qualification
    enforcement is on and the soldier has no alal qualification at all."""
    # Build the same shape of soldier/duty fixtures as
    # test_hard_constraint_never_assigns_ineligible_soldier (line 21) but with
    # required_range_type="alal", and a SoldierInput whose
    # weapon_ineligible_duty_block_ids includes the alal duty's id (simulating
    # what bulk_ineligible_duty_blocks would have produced before this fix --
    # the solver itself doesn't recompute eligibility, it trusts the
    # pre-computed set passed in via SoldierInput).
    # Assert: the (duty, soldier) pair IS present in the solver's eligible
    # pairs / the solver DOES assign the soldier to the duty, because Task 1's
    # fix means an alal duty's id should never actually land in
    # weapon_ineligible_duty_block_ids in the first place -- so pass an EMPTY
    # weapon_ineligible_duty_block_ids for this test (reflecting the fixed
    # upstream behavior) and assert the assignment succeeds normally,
    # confirming enforce_weapon_qualification=True + alal + no ids in the set
    # produces a normal (non-excluded) assignment.
    ...
```

Read the existing three tests in this file in full before writing this one — copy their exact `SoldierInput`/`DutyBlock`/`AlgorithmSettings` construction and solver invocation so the new test uses the same helpers and assertion style (e.g. checking `result.assignments` or calling the same `_eligible_pairs`/`build_model` helper they call). Do not invent a different test harness.

- [ ] **Step 6: Run the full weapon-eligibility test suite**

Run: `pytest backend/app/algorithm/tests/test_weapon_eligibility_constraint.py backend/app/services/tests/test_weapon_eligibility.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/weapon_eligibility.py backend/app/services/tests/test_weapon_eligibility.py backend/app/algorithm/tests/test_weapon_eligibility_constraint.py
git commit -m "fix: never hard-block duty assignment on missing אל\"ל qualification"
```

---

### Task 2: Add DutyAssignment info-signal cache columns + NotificationType

**Files:**
- Modify: `backend/app/db/models.py` (NotificationType enum near line 1227, `DutyAssignment` fields near line 384)
- Create: `backend/alembic/versions/<new_revision>_add_duty_assignment_range_info_cache.py`
- Test: `backend/app/db/tests/` — follow whatever existing pattern verifies new columns exist (check for a model/migration smoke test in that directory; if none exists for `weapon_ineligible`, skip a dedicated test here — the migration is exercised by Task 3's tests via `app_session`).

**Interfaces:**
- Produces: `DutyAssignment.range_info_active: bool`, `DutyAssignment.range_info_covered_by_date: date | None`, `DutyAssignment.range_info_covering_range_type: str | None`, `DutyAssignment.range_info_detected_at: datetime | None`; `NotificationType.range_covers_duty_info`. Consumed by Task 3.

- [ ] **Step 1: Add the NotificationType member**

In `backend/app/db/models.py`, right after line 1227 (`weapon_ineligible_detected = "weapon_ineligible_detected"`), add:

```python
    range_covers_duty_info = "range_covers_duty_info"
```

- [ ] **Step 2: Add the DutyAssignment cache fields**

In `backend/app/db/models.py`, right after line 384 (the end of the `weapon_ineligible_detected_at` column), add:

```python
    range_info_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    range_info_covered_by_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    range_info_covering_range_type: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    range_info_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
```

(`Boolean`, `Text`, `Date`, `DateTime`, `text` are already imported in this file — confirm by checking the imports used by the neighboring `weapon_ineligible*` columns.)

- [ ] **Step 3: Generate and hand-write the migration**

Check the current alembic head first:

Run: `cd backend && .venv/Scripts/python.exe -m alembic heads` (or `.venv/bin/python -m alembic heads` on non-Windows)
Expected output at time of writing: `6fab7ceeba84 (head)` — if different, use whatever the actual head is as `down_revision`.

Create `backend/alembic/versions/<new_revision>_add_duty_assignment_range_info_cache.py` (pick a fresh random-looking hex revision id, same style as `a1e57979ac8e`), modeled directly on `backend/alembic/versions/a1e57979ac8e_add_duty_assignment_weapon_ineligible_.py`:

```python
"""add_duty_assignment_range_info_cache

Revision ID: <new_revision>
Revises: 6fab7ceeba84
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '<new_revision>'
down_revision: Union[str, Sequence[str], None] = '6fab7ceeba84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_covered_by_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_covering_range_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("range_info_detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_duty_assignments_range_info_active",
        "duty_assignments",
        ["id"],
        unique=False,
        postgresql_where=sa.text("range_info_active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_duty_assignments_range_info_active", table_name="duty_assignments")
    op.drop_column("duty_assignments", "range_info_detected_at")
    op.drop_column("duty_assignments", "range_info_covering_range_type")
    op.drop_column("duty_assignments", "range_info_covered_by_date")
    op.drop_column("duty_assignments", "range_info_active")
```

- [ ] **Step 4: Apply the migration locally**

Run: `cd backend && .venv/Scripts/python.exe -m alembic upgrade head`
Expected: no errors, new head is `<new_revision>`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/<new_revision>_add_duty_assignment_range_info_cache.py
git commit -m "feat: add range-info cache columns and notification type"
```

---

### Task 3: Reactive info-signal detection + notification in duty_eligibility_watch

**Files:**
- Modify: `backend/app/services/duty_eligibility_watch.py`
- Test: `backend/app/services/tests/test_duty_eligibility_watch.py`

**Interfaces:**
- Consumes: `project_duty_eligibility(session, *, soldier_ids, duty_ids, as_of=None) -> dict[tuple[uuid.UUID, uuid.UUID], DutyEligibilityFact]` from `backend/app/services/range_eligibility_projection.py:68` (fields: `.eligible`, `.qualification_source`, `.covered_by_range_date`, `.covering_range_type`); `DutyAssignment.range_info_active/covered_by_date/covering_range_type/detected_at` from Task 2; `commander_chain_for_soldier`, `notify_duty_managers_in_scope`, `_create_notif` (already imported in this file).
- Produces: `recheck_assignments(...)` now also maintains the info cache and fires `NotificationType.range_covers_duty_info` notifications; return value (count of red False→True transitions) is unchanged.

- [ ] **Step 1: Write the failing tests**

Read `backend/app/services/tests/test_duty_eligibility_watch.py` in full first — copy its exact fixture/session setup pattern (soldier, duty type with `required_range_type`, published `DutyAssignment`, `app_session`) for these new tests:

```python
def test_recheck_assignments_detects_new_info_signal(app_session):
    # Arrange: soldier has NO current qualification, but a future, primary
    # (is_reserve=False), planned RangeAssignment on a RangeEvent whose date +
    # validity window covers the DutyAssignment.start_date -- i.e. the exact
    # shape that makes project_duty_eligibility return
    # qualification_source == "planned_range" for this (soldier, duty) pair.
    # (Copy the "eligible via planned range" fixture setup from
    # backend/app/services/tests/test_range_eligibility_projection.py's
    # planned_range test -- same shape needed here.)
    assignment = ...  # published DutyAssignment for that soldier/duty

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert assignment.range_info_active is True
    assert assignment.range_info_covering_range_type is not None
    assert assignment.range_info_detected_at is not None

    notif_types = {
        n.type for n in app_session.query(Notification).filter_by(soldier_id=assignment.soldier_id)
    }
    assert NotificationType.range_covers_duty_info in notif_types


def test_recheck_assignments_does_not_renotify_when_covering_range_unchanged(app_session):
    assignment = ...  # same setup as above
    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    first_detected_at = assignment.range_info_detected_at
    notif_count_after_first = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()

    recheck_assignments(app_session, [assignment.id])  # nothing changed
    app_session.refresh(assignment)

    assert assignment.range_info_detected_at == first_detected_at
    notif_count_after_second = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()
    assert notif_count_after_second == notif_count_after_first


def test_recheck_assignments_renotifies_when_covering_range_changes(app_session):
    assignment = ...  # same setup as above, first recheck already run
    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    first_detected_at = assignment.range_info_detected_at

    # Cancel/replace the covering range assignment with a different future
    # primary RangeAssignment on a different date/type that still covers the
    # duty (e.g. move the soldier off the first RangeEvent's roster and onto
    # a second one whose window also covers the duty's start_date).
    ...

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert assignment.range_info_detected_at != first_detected_at
    notif_count = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()
    assert notif_count == 2


def test_recheck_assignments_clears_info_signal_silently_when_no_longer_covered(app_session):
    assignment = ...  # info-active from a prior recheck
    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    assert assignment.range_info_active is True

    # Remove the covering RangeAssignment entirely (soldier no longer has any
    # planned range covering the duty, and no current qualification either).
    ...

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert assignment.range_info_active is False
    assert assignment.range_info_covered_by_date is None
    assert assignment.range_info_covering_range_type is None
    # No NEW info notification should have been created for the clearing --
    # count stays at 1 (from the initial detection only).
    notif_count = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()
    assert notif_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_duty_eligibility_watch.py -k info_signal -v`
Expected: FAIL — `range_info_active` stays `False`/no notification created, since the behavior doesn't exist yet.

- [ ] **Step 3: Implement the info-signal pass**

In `backend/app/services/duty_eligibility_watch.py`, add the import and a title constant near the top:

```python
from app.services.range_eligibility_projection import project_duty_eligibility

_RANGE_INFO_TITLE = "מטווח מתוכנן יכסה תורנות"
```

Add a Hebrew label helper (mirrors `_RANGE_TYPE_HE` in `backend/app/services/ranges.py:64-68` — import it directly instead of duplicating):

```python
from app.services.ranges import _RANGE_TYPE_HE
from app.db.models import RangeType
```

Add a body-formatting helper next to `_reason_body`:

```python
def _info_body(soldier_name: str, duty_type_name: str, duty_date, range_type: str, range_date) -> str:
    range_label = _RANGE_TYPE_HE.get(RangeType(range_type), range_type)
    return (
        f"{soldier_name} משובץ/ת למטווח מתוכנן ({range_label}) בתאריך "
        f"{range_date.strftime('%d.%m.%Y')}, שיכסה את הדרישה לתורנות "
        f"'{duty_type_name}' בתאריך {duty_date.strftime('%d.%m.%Y')}."
    )
```

At the end of `recheck_assignments`, right before `session.commit()` (currently line 107), add a second pass over the same `assignments`/`types_by_id` already loaded in this function:

```python
    facts = project_duty_eligibility(
        session,
        soldier_ids=[a.soldier_id for a in assignments],
        duty_ids=[a.id for a in assignments],
    )
    for assignment in assignments:
        duty_type = types_by_id.get(assignment.duty_type_id)
        fact = facts.get((assignment.soldier_id, assignment.id))
        is_info = (
            duty_type is not None
            and duty_type.required_range_type is not None
            and fact is not None
            and fact.qualification_source == "planned_range"
        )
        if not is_info:
            if assignment.range_info_active:
                assignment.range_info_active = False
                assignment.range_info_covered_by_date = None
                assignment.range_info_covering_range_type = None
                assignment.range_info_detected_at = None
            continue

        covering_changed = (
            assignment.range_info_covered_by_date != fact.covered_by_range_date
            or assignment.range_info_covering_range_type != fact.covering_range_type
        )
        if assignment.range_info_active and not covering_changed:
            continue

        assignment.range_info_active = True
        assignment.range_info_covered_by_date = fact.covered_by_range_date
        assignment.range_info_covering_range_type = fact.covering_range_type
        assignment.range_info_detected_at = datetime.now(UTC)

        soldier = session.get(Soldier, assignment.soldier_id)
        soldier_name = soldier.full_name if soldier else ""
        body = _info_body(
            soldier_name, duty_type.name, assignment.start_date,
            fact.covering_range_type, fact.covered_by_range_date,
        )
        _create_notif(
            session, soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
            title=_RANGE_INFO_TITLE, body=body,
            reference_type="duty_assignment", reference_id=assignment.id,
            actor_id=None,
        )
        notified_ids = {assignment.soldier_id}
        chain = commander_chain_for_soldier(session, assignment.soldier_id)
        if chain:
            direct_commander_id = chain[0]
            if direct_commander_id not in notified_ids:
                _create_notif(
                    session, soldier_id=direct_commander_id,
                    type=NotificationType.range_covers_duty_info,
                    title=_RANGE_INFO_TITLE, body=body,
                    reference_type="duty_assignment", reference_id=assignment.id,
                    actor_id=None,
                )
                notified_ids.add(direct_commander_id)
        notify_duty_managers_in_scope(
            session, soldier_id=assignment.soldier_id,
            type=NotificationType.range_covers_duty_info,
            title=_RANGE_INFO_TITLE, body=body,
            reference_type="duty_assignment", reference_id=assignment.id,
            exclude_soldier_ids=notified_ids,
        )
```

Note: `project_duty_eligibility` internally re-derives `required_range_type` per duty from `DutyType` via its own query — it's safe to call unconditionally here even for assignments whose duty type has no range requirement (it simply won't produce a fact / the `is_info` guard filters those out).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_duty_eligibility_watch.py -v`
Expected: All PASS, including the 3 pre-existing tests in this file (make sure the red-warning behavior is untouched).

- [ ] **Step 5: Run the broader eligibility-watch and range-eligibility-projection suites**

Run: `pytest backend/app/services/tests/test_duty_eligibility_watch.py backend/app/services/tests/test_duty_eligibility_watch_broad_triggers.py backend/app/services/tests/test_duty_eligibility_watch_integration.py backend/app/services/tests/test_range_eligibility_projection.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/duty_eligibility_watch.py backend/app/services/tests/test_duty_eligibility_watch.py
git commit -m "feat: notify soldier/commander/duty-managers when a planned range will cover a duty"
```

---

### Task 4: Expose the info signal in the calendar API response and add i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/i18n/he.test.ts`

**Interfaces:**
- Consumes: nothing new — `CalendarShiftAssignee.range_eligibility.qualification_source` (`frontend/src/api/calendar.ts:52`, type `DutyEligibilityFact` in `frontend/src/api/ineligibleSoldiers.ts:19-29`) already carries `"planned_range"` end-to-end from `backend/app/services/calendar_shifts.py`'s `_attach_range_eligibility_facts` (lines 52-83) — confirmed no backend/API change needed for the badge (only for the notification, done in Task 3).
- Produces: `type_range_covers_duty_info` and `range_qualification.shiftDetail.info` / `range_qualification.calendarBadge.info` translation keys consumed by Tasks 5 and 6.

- [ ] **Step 1: Add the notification-type translation and coverage-test entry**

In `frontend/src/i18n/he.json`, near line 1173 (`"type_weapon_ineligible_detected"`), add:

```json
    "type_range_covers_duty_info": "מטווח מתוכנן יכסה תורנות",
```

In `frontend/src/i18n/he.test.ts`, add `"range_covers_duty_info"` to the `NOTIFICATION_TYPES` array (line 25, alongside `"weapon_ineligible_detected"`).

- [ ] **Step 2: Add the badge translation keys**

In `frontend/src/i18n/he.json`, inside the `"shiftDetail"` block (line 1374-1379, alongside `"warning"` and `"unavailable"`), add:

```json
      "info": "מטווח מתוכנן יכסה את התורנות"
```

Add a new `"calendarBadge"` block as a sibling of `"shiftDetail"` (same nesting level, under `range_qualification`):

```json
    "calendarBadge": {
      "info": "מטווח מתוכנן יכסה תורנות"
    },
```

- [ ] **Step 3: Run the i18n coverage test**

Run: `cd frontend && npm test -- he.test.ts`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/he.json frontend/src/i18n/he.test.ts
git commit -m "feat: add translations for planned-range info signal"
```

---

### Task 5: Info badge + corrected visibility gating in ShiftDetailPanel

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`
- Test: `frontend/src/components/ShiftDetailPanel.test.tsx`

**Interfaces:**
- Consumes: `assignee.range_eligibility.qualification_source` (already typed, see Task 4); `formatRangeEligibilityExplanation` (`frontend/src/utils/rangeEligibilityExplanation.ts:10`, already handles the `"planned_range"` case and produces the right Hebrew tooltip text — reuse as-is); `user.is_commander` (already on the `PermissionUser`/auth `user` object used elsewhere in this file at lines 255, 263, 273).
- Produces: a visible blue info badge next to each assignee with `qualification_source === "planned_range"`; both the existing red badge and the new blue badge gated on `user?.role === "admin" || user?.is_commander || user?.is_duty_manager`.

- [ ] **Step 1: Write the failing test**

Read `frontend/src/components/ShiftDetailPanel.test.tsx` in full first to copy its existing render/mock setup for the red-warning-badge test (search for a test asserting the ⚠️ badge renders for an ineligible assignee). Add:

```tsx
it("shows a blue info badge for an assignee covered only by a planned range", async () => {
  // Copy the exact render/mock-fetch setup from the existing weapon-ineligible
  // badge test, but with the mocked shift's assignee having
  // range_eligibility: { eligible: true, qualification_source: "planned_range",
  // covered_by_range_date: "2026-12-01", covering_range_type: "live",
  // projected_valid_until: "2027-06-01", required_range_type: "live",
  // reason: null, duty_type_name: "...", start_date: "..." }
  // and the viewing user mocked as a duty manager (or commander) so the
  // badge's visibility gate passes.
  ...
  expect(screen.getByLabelText(/מטווח מתוכנן יכסה/)).toBeInTheDocument();
});

it("hides both the red and blue eligibility badges from a plain soldier", async () => {
  // Same setup as above (or the existing red-badge test's setup) but with the
  // viewing user mocked as a plain soldier (role: "soldier",
  // is_commander: false, is_duty_manager: false).
  ...
  expect(screen.queryByLabelText(/חוסר כשירות מטווחים/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/מטווח מתוכנן יכסה/)).not.toBeInTheDocument();
});

it("shows the existing red badge to a commander who is not a duty manager", async () => {
  // Regression test for the visibility-gate fix: mock the viewing user as
  // role: "commander", is_commander: true, is_duty_manager: false, and an
  // assignee with range_eligibility.eligible === false.
  ...
  expect(screen.getByLabelText(/חוסר כשירות מטווחים/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ShiftDetailPanel.test.tsx -t "info badge|plain soldier|commander who is not"`
Expected: FAIL

- [ ] **Step 3: Implement**

In `frontend/src/components/ShiftDetailPanel.tsx`, replace the `rangeEligibilityIndicator` function (lines 147-166) with:

```tsx
  function rangeEligibilityIndicator(assignee: CalendarShiftAssignee): React.ReactNode {
    if (!shift.required_range_type) return null;
    const canSeeEligibility = user?.role === "admin" || user?.is_commander || user?.is_duty_manager;
    if (!canSeeEligibility) return null;
    if (!assignee.range_eligibility) {
      return (
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {t("range_qualification.shiftDetail.unavailable")}
        </span>
      );
    }
    if (!assignee.range_eligibility.eligible) {
      return (
        <span
          aria-label={t("range_qualification.shiftDetail.warning")}
          title={formatRangeEligibilityExplanation(assignee.range_eligibility, t)}
          className="inline-flex items-center rounded bg-red-100 px-1.5 py-0.5 text-red-700 dark:bg-red-950 dark:text-red-300"
        >
          ⚠️
        </span>
      );
    }
    if (assignee.range_eligibility.qualification_source === "planned_range") {
      return (
        <span
          aria-label={t("range_qualification.shiftDetail.info")}
          title={formatRangeEligibilityExplanation(assignee.range_eligibility, t)}
          className="inline-flex items-center rounded bg-blue-100 px-1.5 py-0.5 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
        >
          ℹ️
        </span>
      );
    }
    return null;
  }
```

Also fix the two other narrower gates in this same file that should include commanders per the same rule — lines 263 (dismiss button) and 273 (weapon-ineligible replace button) currently read `user?.role === "admin" || user?.is_duty_manager`. **Do not change these two** — they gate destructive actions (dismiss / remove assignment), which is a different, deliberately narrower permission than "can see the eligibility badge". Only the badge visibility gate uses the wider `canApprove`-equivalent check. Leave lines 263 and 273 exactly as they are.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- ShiftDetailPanel.test.tsx`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx frontend/src/components/ShiftDetailPanel.test.tsx
git commit -m "feat: show planned-range info badge; fix eligibility badge visibility for commanders"
```

---

### Task 6: Info indicator on the UnitCalendar event tile

**Files:**
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Test: `frontend/src/components/UnitCalendar.test.tsx`

**Interfaces:**
- Consumes: `shift.assignees[].range_eligibility.qualification_source` (already present on every `CalendarShift` returned by `getCalendarShifts`, per Task 4's confirmation — no new fetch needed); `useAuth` from `frontend/src/auth/AuthContext` (not currently imported in this file — needs adding).
- Produces: a small blue "ℹ️" indicator rendered inside the `eventContent` shift branch (next to the existing `swapCount` badge), visible only to admin/commander/duty-manager viewers.

- [ ] **Step 1: Write the failing test**

Read `frontend/src/components/UnitCalendar.test.tsx` in full first to copy its existing mock-data/render setup (look at how it mocks `getCalendarShifts` and asserts on rendered event content). Add:

```tsx
it("shows an info indicator on the event tile when an assignee is covered by a planned range", async () => {
  // Copy the existing render setup, mocking getCalendarShifts to return one
  // shift whose assignees include one with
  // range_eligibility: { eligible: true, qualification_source: "planned_range", ... }
  // and mock the viewing user as a duty manager.
  ...
  expect(screen.getByLabelText(/מטווח מתוכנן יכסה/)).toBeInTheDocument();
});

it("hides the info indicator from a plain soldier viewing the calendar", async () => {
  // Same shift/assignee mock as above, but viewing user mocked as role: "soldier".
  ...
  expect(screen.queryByLabelText(/מטווח מתוכנן יכסה/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- UnitCalendar.test.tsx -t "info indicator"`
Expected: FAIL

- [ ] **Step 3: Implement**

In `frontend/src/components/UnitCalendar.tsx`:

Add the import (near line 17, alongside the other component imports):

```tsx
import { useAuth } from "../auth/AuthContext";
```

Inside `export default function UnitCalendar(...)` (starting line 61), add near the other hooks (after line 63's `usePublicSettings()` call):

```tsx
  const { user } = useAuth();
  const canSeeRangeEligibilityBadges = user?.role === "admin" || user?.is_commander || user?.is_duty_manager;
```

In the `eventContent` callback's shift branch, inside the `<div className="flex items-center gap-1 w-full">` block (lines 352-359), add a sibling span next to the existing `swapCount` badge:

```tsx
                <div className="flex items-center gap-1 w-full">
                  <span className="font-semibold truncate flex-1">{shift.duty_type_name} — {shift.duty_location_name}</span>
                  {canSeeRangeEligibilityBadges && shift.assignees.some((a) => a.range_eligibility?.qualification_source === "planned_range") && (
                    <span
                      aria-label={t("range_qualification.calendarBadge.info")}
                      title={t("range_qualification.calendarBadge.info")}
                      className="bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 rounded-full px-1 text-[10px] leading-4 flex-shrink-0"
                    >
                      ℹ️
                    </span>
                  )}
                  {swapCount > 0 && (
                    <span className="bg-orange-500 text-white rounded-full px-1 text-[10px] leading-4 flex-shrink-0 min-w-[1.25rem] text-center">
                      {swapCount}
                    </span>
                  )}
                </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- UnitCalendar.test.tsx`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UnitCalendar.tsx frontend/src/components/UnitCalendar.test.tsx
git commit -m "feat: show planned-range info indicator on unit calendar event tiles"
```

---

### Task 7: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend fast suite**

Run: `cd backend && pytest -q`
Expected: PASS (note: this project's `addopts` already bakes in `-n auto` per `CLAUDE.md`)

- [ ] **Step 2: Run the backend algorithm marker suite specifically (covers Task 1's solver-level change)**

Run: `cd backend && pytest -m algorithm -q`
Expected: PASS

- [ ] **Step 3: Run frontend unit tests, lint, and typecheck**

Run: `cd frontend && npm test`
Run: `cd frontend && npm run lint`
Run: `cd frontend && npm run typecheck`
Expected: All PASS / zero warnings

- [ ] **Step 4: Manually verify in the running dev stack**

Start `.\dev.ps1` from the repo root. In the browser:
1. As an admin, create a duty type with `required_range_type = "alal"`, assign a soldier with no אל"ל qualification and no scheduled אל"ל to it, then run the algorithm for a period covering that duty — confirm the soldier CAN be assigned (no longer hard-blocked), and that the shift then shows the existing red warning badge (to a duty manager/commander/admin viewer) once published.
2. Schedule a soldier onto a future, primary (non-reserve) range whose date + validity window covers one of their upcoming duties requiring that range type (and the soldier has no other current qualification) — confirm: the blue info badge appears in both the `UnitCalendar` event tile and the `ShiftDetailPanel` modal (to a duty-manager/commander/admin viewer, NOT to the soldier themself viewing their own shift), and that the soldier + their direct commander + duty managers in scope each received a `range_covers_duty_info` notification.
3. Change which range covers that duty (e.g. cancel the original range assignment and add the soldier to a different future primary range that still covers the duty) — confirm a second `range_covers_duty_info` notification fires.

No screenshot artifact needed — this is an internal army-duty tool behind auth; confirm behavior via the browser preview tools directly and report pass/fail per scenario.

- [ ] **Step 5: Commit (only if Step 4 surfaced any fixes)**

If manual verification required any follow-up code changes, commit them individually with descriptive messages before considering this plan complete.
