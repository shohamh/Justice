# Personal-Constraint Manual-Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let duty managers manually assign a soldier who has an approved personal
constraint (אילוץ אישי), when a system setting allows it — showing a warning icon,
requiring a typed reason, notifying the soldier and their commander(s), and leaving
an audit trail — for both duty-shift and range manual assignment, while leaving the
CP-SAT solver's hard block on constraints completely untouched.

**Architecture:** One new boolean system setting gates the behavior everywhere.
Duty and range manual-assignment are two independent, pre-existing implementations
(no shared eligibility module) — each gets its own opt-in override parameter threaded
from route → service, so unrelated call sites (CP-SAT solver, swap eligibility) keep
their unconditional hard block by default. A new `personal_constraint_overrides`
table records every override for the constraint-detail view and the soldier
timeline; a new `NotificationType` fires once per overridden soldier.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript +
Vitest (frontend), pytest (backend tests).

**Spec:** [docs/superpowers/specs/2026-08-28-personal-constraint-manual-override-design.md](../specs/2026-08-28-personal-constraint-manual-override-design.md)

## Global Constraints

- New setting key: `constraints.allow_manual_override`, boolean, default `true`.
- Setting OFF → constraint overlap is a hard block for BOTH duty and range manual
  assignment (today range assignment never hard-blocks on constraints — this closes
  that gap).
- Setting ON → soldier stays selectable, warning icon shown, `override_reason`
  (non-empty string) required to actually assign; on success, one
  `personal_constraint_overrides` row is written per overridden soldier and one
  notification is sent per overridden soldier (to the soldier; commanders are
  cascaded automatically by `create_notification`).
- The CP-SAT solver (`app/algorithm/availability.py`, `app/algorithm/solver.py`) and
  swap-eligibility checks (`app/routes/swaps.py`, `app/routes/swaps_eligibility.py`)
  must NOT change behavior — they keep calling `check_soldier_for_assignment`
  without opting in to the override.
- Constrained-but-selectable candidates sort to the bottom of the selectable list in
  both `ShiftAssignModal.tsx` and `RangeEditAssignmentsModal.tsx` (secondary sort
  order — effort/rank — still applies within each group).
- Hebrew notification title: `אילוץ אישי נדרס בשיבוץ ל{תורנות|מטווח}` (duty/range
  word chosen by `assignment_kind`).
- Batch/multi-soldier submissions use ONE shared reason for the whole submission
  (not per-soldier).

---

## Task 1: `PersonalConstraintOverride` model + migration

**Files:**
- Modify: `backend/app/db/models.py` (add class after `PersonalConstraint`, ~line 694)
- Create: `backend/alembic/versions/d4e5f6a7b8c9_create_personal_constraint_overrides.py`
- Test: `backend/app/services/tests/test_personal_constraint_overrides_model.py`

**Interfaces:**
- Produces: `PersonalConstraintOverride` ORM class with columns `id`,
  `personal_constraint_id`, `soldier_id`, `overridden_by`, `assignment_kind`
  (`"duty"` | `"range"`), `reference_id`, `reason`, `overridden_at`. Every later
  backend task imports this from `app.db.models`.

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_personal_constraint_overrides_model.py
from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.db.models import PersonalConstraint, PersonalConstraintOverride, Soldier


def test_personal_constraint_override_round_trips(db_session, make_soldier):
    soldier: Soldier = make_soldier()
    overridden_by: Soldier = make_soldier()
    constraint = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=1),
        reason="בקשה אישית",
        status="approved",
    )
    db_session.add(constraint)
    db_session.flush()

    override = PersonalConstraintOverride(
        personal_constraint_id=constraint.id,
        soldier_id=soldier.id,
        overridden_by=overridden_by.id,
        assignment_kind="duty",
        reference_id=uuid.uuid4(),
        reason="צורך מבצעי דחוף",
    )
    db_session.add(override)
    db_session.flush()
    db_session.refresh(override)

    assert override.id is not None
    assert override.overridden_at is not None
    assert override.personal_constraint_id == constraint.id
    assert override.assignment_kind == "duty"
```

Check `backend/app/services/tests/conftest.py` (or the nearest shared conftest) for
the exact names of the `db_session` and `make_soldier` fixtures already used by
sibling tests such as `test_constraints.py` in the same directory — reuse them
as-is rather than redefining.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_personal_constraint_overrides_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'PersonalConstraintOverride'`

- [ ] **Step 3: Add the model**

In `backend/app/db/models.py`, immediately after the `PersonalConstraint` class
(after its closing blank line, before `class ExemptionRequest`):

```python
class PersonalConstraintOverride(Base):
    __tablename__ = "personal_constraint_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    personal_constraint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_constraints.id", ondelete="CASCADE")
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    assignment_kind: Mapped[str] = mapped_column(Text)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text)
    overridden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 4: Write the migration**

```python
# backend/alembic/versions/d4e5f6a7b8c9_create_personal_constraint_overrides.py
"""create personal_constraint_overrides

Revision ID: d4e5f6a7b8c9
Revises: 366b35d4cff5
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "366b35d4cff5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_constraint_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "personal_constraint_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("personal_constraints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "overridden_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("assignment_kind", sa.Text(), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "overridden_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_pco_constraint", "personal_constraint_overrides", ["personal_constraint_id"]
    )
    op.create_index("idx_pco_soldier", "personal_constraint_overrides", ["soldier_id"])


def downgrade() -> None:
    op.drop_index("idx_pco_soldier", table_name="personal_constraint_overrides")
    op.drop_index("idx_pco_constraint", table_name="personal_constraint_overrides")
    op.drop_table("personal_constraint_overrides")
```

Run `alembic heads` first to confirm `366b35d4cff5` is still the sole head before
using it as `down_revision` — if another migration has landed on `dev` since this
plan was written, use the new head instead.

- [ ] **Step 5: Apply the migration and run the test**

Run: `alembic upgrade head` then `pytest backend/app/services/tests/test_personal_constraint_overrides_model.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/d4e5f6a7b8c9_create_personal_constraint_overrides.py backend/app/services/tests/test_personal_constraint_overrides_model.py
git commit -m "feat: add personal_constraint_overrides table"
```

---

## Task 2: `constraints.allow_manual_override` system setting

**Files:**
- Modify: `backend/app/services/settings_loader.py` (no structural change needed —
  reuse existing `get_setting`/`SettingNotFound`; this task just establishes the
  helper other tasks call)
- Create: `backend/app/services/constraint_override_settings.py`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `backend/app/services/tests/test_constraint_override_settings.py`

**Interfaces:**
- Produces: `constraint_override_settings.manual_override_allowed(session: Session) -> bool`.
  Every later backend eligibility/assignment task calls this instead of reading the
  setting key directly, so the default lives in exactly one place.

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_constraint_override_settings.py
from __future__ import annotations

from app.services.constraint_override_settings import manual_override_allowed
from app.services.settings_loader import set_setting


def test_defaults_to_allowed_when_unset(db_session):
    assert manual_override_allowed(db_session) is True


def test_reads_setting_when_present(db_session):
    set_setting(db_session, "constraints.allow_manual_override", False, actor_id=None)
    assert manual_override_allowed(db_session) is False

    set_setting(db_session, "constraints.allow_manual_override", True, actor_id=None)
    assert manual_override_allowed(db_session) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_constraint_override_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.constraint_override_settings'`

- [ ] **Step 3: Implement the helper**

```python
# backend/app/services/constraint_override_settings.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.settings_loader import SettingNotFound, get_setting

MANUAL_OVERRIDE_KEY = "constraints.allow_manual_override"


def manual_override_allowed(session: Session) -> bool:
    """True unless an admin has explicitly turned off manual overriding of
    approved personal constraints during duty/range manual assignment."""
    try:
        return bool(get_setting(session, MANUAL_OVERRIDE_KEY))
    except SettingNotFound:
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_constraint_override_settings.py -v`
Expected: PASS

- [ ] **Step 5: Add the admin-page toggle**

In `frontend/src/pages/SystemSettingsPage.tsx`, in the settings group that already
holds `constraints.require_commander_approval` / `constraints.require_duty_manager_approval`
(around line 72-73), add one more entry to that group's `settings` array:

```ts
{ key: "constraints.allow_manual_override", label: "אפשר עקיפת אילוצים בשיבוץ ידני", description: "האם אחראי תורנויות יכול לשבץ ידנית חייל עם אילוץ אישי מאושר, לאחר מתן נימוק", type: "boolean", defaultValue: true },
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/constraint_override_settings.py backend/app/services/tests/test_constraint_override_settings.py frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: add constraints.allow_manual_override system setting"
```

---

## Task 3: Override notification helper + `NotificationType`

**Files:**
- Modify: `backend/app/db/models.py` (add enum member to `NotificationType`, ~line 1417)
- Modify: `backend/app/services/notifications.py`
- Test: `backend/app/services/tests/test_constraint_override_notifications.py`

**Interfaces:**
- Consumes: `create_notification` (`notifications.py:316`, already cascades to
  commanders automatically for any non-announcement type — see its body: it calls
  `cascade_to_commanders(...)` itself, so callers must NOT call
  `notify_commanders_of_request` on top or the commander will be notified twice).
- Produces: `notify_personal_constraint_overridden(session, *, soldier_id, assignment_kind, reason, actor_id) -> None`.
  Later duty/range assignment tasks call this exact function after writing the
  audit row.

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_constraint_override_notifications.py
from __future__ import annotations

from app.db.models import CommanderNotificationScope, Notification, NotificationType
from app.services.notifications import notify_personal_constraint_overridden


def test_notifies_soldier_and_cascades_to_commander(db_session, make_soldier, make_hierarchy_node):
    commander = make_soldier()
    node = make_hierarchy_node(path_ids=["root"])
    soldier = make_soldier(hierarchy_node_id=node.id)
    db_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id))
    db_session.flush()

    notify_personal_constraint_overridden(
        db_session,
        soldier_id=soldier.id,
        assignment_kind="duty",
        reason="צורך מבצעי דחוף",
        actor_id=commander.id,
    )
    db_session.flush()

    soldier_notifs = db_session.query(Notification).filter(
        Notification.soldier_id == soldier.id,
        Notification.type == NotificationType.personal_constraint_overridden,
    ).all()
    assert len(soldier_notifs) == 1
    assert "אילוץ אישי נדרס בשיבוץ לתורנות" in soldier_notifs[0].title
    assert soldier_notifs[0].body == "צורך מבצעי דחוף"

    commander_notifs = db_session.query(Notification).filter(
        Notification.soldier_id == commander.id,
        Notification.type == NotificationType.personal_constraint_overridden,
    ).all()
    assert len(commander_notifs) == 1


def test_range_wording(db_session, make_soldier):
    soldier = make_soldier()
    notify_personal_constraint_overridden(
        db_session, soldier_id=soldier.id, assignment_kind="range", reason="r", actor_id=None,
    )
    db_session.flush()
    notif = db_session.query(Notification).filter(Notification.soldier_id == soldier.id).one()
    assert "אילוץ אישי נדרס בשיבוץ למטווח" in notif.title
```

Check the nearest existing test for `cascade_to_commanders` (e.g. in
`backend/app/services/tests/test_notifications.py` or `test_constraints.py`) for
the exact `make_hierarchy_node` fixture signature/name used elsewhere in this repo
— reuse it rather than inventing a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/app/services/tests/test_constraint_override_notifications.py -v`
Expected: FAIL — `ImportError: cannot import name 'notify_personal_constraint_overridden'`

- [ ] **Step 3: Add the enum member**

In `backend/app/db/models.py`, add to `NotificationType` (any position, grouped
near the other `constraint_*`/`range_*` members for readability — e.g. right after
`constraint_rejected` at line 1371):

```python
    personal_constraint_overridden = "personal_constraint_overridden"
```

- [ ] **Step 4: Implement the notification helper**

In `backend/app/services/notifications.py`, add near the bottom of the file:

```python
_ASSIGNMENT_KIND_LABEL = {"duty": "תורנות", "range": "מטווח"}


def notify_personal_constraint_overridden(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    assignment_kind: str,
    reason: str,
    actor_id: uuid.UUID | None,
) -> None:
    """Notify the soldier (and, via create_notification's built-in cascade, their
    commander(s)) that a duty manager overrode their approved personal constraint
    to manually assign them. One call per overridden soldier, even when the
    triggering UI action was a shared-reason batch submission."""
    kind_label = _ASSIGNMENT_KIND_LABEL[assignment_kind]
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.personal_constraint_overridden,
        title=f"אילוץ אישי נדרס בשיבוץ ל{kind_label}",
        body=reason,
        reference_type="personal_constraint",
        actor_id=actor_id,
    )
```

Also add `"personal_constraint_overridden": "/constraints"` to the `_FRONTEND_PATHS`
dict (~line 41, alongside the other `constraint_*` entries) so the notification is
clickable in the UI.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/app/services/tests/test_constraint_override_notifications.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/app/services/notifications.py backend/app/services/tests/test_constraint_override_notifications.py
git commit -m "feat: add personal_constraint_overridden notification"
```

---

## Task 4: Duty eligibility — opt-in override on `check_soldier_for_assignment`

**Files:**
- Modify: `backend/app/services/eligibility.py`
- Test: `backend/app/services/tests/test_eligibility.py` (extend; create if it
  doesn't already exist as a dedicated file — check first, since
  `check_soldier_for_assignment` may currently only be tested indirectly through
  `test_swaps*.py`)

**Interfaces:**
- Consumes: `constraint_override_settings.manual_override_allowed` (Task 2).
- Produces: `check_soldier_for_assignment(session, soldier_id, assignment_id, *, exclude_assignment_id=None, allow_constraint_override=False) -> tuple[bool, str | None, dict | None]`
  — return signature grows a third element, `constraint_warning`, which is `None`
  unless step 3 found an approved constraint AND `allow_constraint_override=True`,
  in which case it's `{"reason": str, "start_date": date, "end_date": date, "decided_by": str | None, "decided_at": datetime | None}`
  and the first two elements become `(True, None)`. **Every existing caller
  (`swaps.py:310`, `swaps.py:425`, `swaps_eligibility.py:49`) must be updated to
  unpack 3 values instead of 2** (they keep passing no `allow_constraint_override`,
  so their behavior is unchanged — they just need the extra `_` in the unpack).

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_eligibility.py (add if new, else append)
from __future__ import annotations

from datetime import date, timedelta

from app.db.models import DutyAssignment, PersonalConstraint
from app.services.eligibility import check_soldier_for_assignment


def _approved_constraint(db_session, soldier_id, start, end):
    c = PersonalConstraint(
        soldier_id=soldier_id, start_date=start, end_date=end,
        reason="r", status="approved",
    )
    db_session.add(c)
    db_session.flush()
    return c


def test_constraint_blocks_by_default(db_session, make_soldier, make_duty_assignment):
    soldier = make_soldier()
    assignment = make_duty_assignment(start_date=date.today(), end_date=date.today() + timedelta(days=1))
    _approved_constraint(db_session, soldier.id, date.today(), date.today() + timedelta(days=1))

    eligible, reason, warning = check_soldier_for_assignment(db_session, soldier.id, assignment.id)
    assert eligible is False
    assert reason == "אילוץ אישי מאושר בתאריך זה"
    assert warning is None


def test_constraint_blocks_even_with_override_flag_if_flag_false(db_session, make_soldier, make_duty_assignment):
    soldier = make_soldier()
    assignment = make_duty_assignment(start_date=date.today(), end_date=date.today() + timedelta(days=1))
    _approved_constraint(db_session, soldier.id, date.today(), date.today() + timedelta(days=1))

    eligible, reason, warning = check_soldier_for_assignment(
        db_session, soldier.id, assignment.id, allow_constraint_override=False,
    )
    assert eligible is False
    assert warning is None


def test_constraint_becomes_warning_when_override_allowed(db_session, make_soldier, make_duty_assignment):
    soldier = make_soldier()
    assignment = make_duty_assignment(start_date=date.today(), end_date=date.today() + timedelta(days=1))
    c = _approved_constraint(db_session, soldier.id, date.today(), date.today() + timedelta(days=1))

    eligible, reason, warning = check_soldier_for_assignment(
        db_session, soldier.id, assignment.id, allow_constraint_override=True,
    )
    assert eligible is True
    assert reason is None
    assert warning == {
        "reason": c.reason,
        "start_date": c.start_date,
        "end_date": c.end_date,
        "decided_by": None,
        "decided_at": c.decided_at,
    }
```

Check `test_eligibility.py`'s (or the nearest sibling test file's) existing
`make_duty_assignment` fixture name before reusing it — it may already exist under
a different name in this repo's shared conftest.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_eligibility.py -v`
Expected: FAIL — `TypeError: check_soldier_for_assignment() got an unexpected keyword argument 'allow_constraint_override'` (or a 2-vs-3-tuple unpack error)

- [ ] **Step 3: Implement**

In `backend/app/services/eligibility.py`, change the signature and step 3 body:

```python
def check_soldier_for_assignment(
    session: Session,
    soldier_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    exclude_assignment_id: uuid.UUID | None = None,
    allow_constraint_override: bool = False,
) -> tuple[bool, str | None, dict | None]:
    """Return (True, None, None) if eligible and available.
    Return (False, Hebrew reason, None) if blocked.
    Return (True, None, constraint_warning) if the only issue is an approved
    personal constraint AND allow_constraint_override=True — the caller is
    responsible for collecting an override reason before actually assigning."""
```

(keep the existing body through step 2 unchanged, then replace step 3):

```python
    # 3. Approved personal constraint overlapping the duty date range
    constraint = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status == "approved",
            PersonalConstraint.start_date < assignment.end_date,
            PersonalConstraint.end_date >= assignment.start_date,
        )
    ).scalar_one_or_none()
    if constraint is not None:
        if not allow_constraint_override:
            return False, "אילוץ אישי מאושר בתאריך זה", None
        decider = session.get(Soldier, constraint.decided_by) if constraint.decided_by else None
        constraint_warning = {
            "reason": constraint.reason,
            "start_date": constraint.start_date,
            "end_date": constraint.end_date,
            "decided_by": decider.full_name if decider else None,
            "decided_at": constraint.decided_at,
        }
```

Then update every remaining `return True, None` at the end of the function to
`return True, None, None`, and every remaining `return False, "..."` in steps 1/2/4
to `return False, "...", None`. Finally, change the function's terminal line
`return True, None` to `return True, None, constraint_warning if constraint is not None else None`
— i.e. hoist a `constraint_warning: dict | None = None` local above step 3 (set it
inside the `if constraint is not None` branch) and return it at the bottom, so the
warning survives past steps 4 without an early return.

- [ ] **Step 4: Fix the 2-value-unpack call sites**

In `backend/app/routes/swaps_eligibility.py:49`, `backend/app/routes/swaps.py:310`,
and `backend/app/routes/swaps.py:425`, change
`eligible, reason = check_soldier_for_assignment(...)` to
`eligible, reason, _warning = check_soldier_for_assignment(...)` (three call sites;
none of them pass `allow_constraint_override`, so their behavior — hard block —
is unchanged).

- [ ] **Step 5: Run the full test suite for this area**

Run: `pytest backend/app/services/tests/test_eligibility.py backend/tests/integration/test_swaps*.py -v`
Expected: PASS (all existing swap tests still pass with the hard block intact,
new eligibility tests pass)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/eligibility.py backend/app/routes/swaps_eligibility.py backend/app/routes/swaps.py backend/app/services/tests/test_eligibility.py
git commit -m "feat: add opt-in personal-constraint override to check_soldier_for_assignment"
```

---

## Task 5: Duty candidates endpoint — warning payload + bottom-sort

**Files:**
- Modify: `backend/app/routes/shifts.py` (`ShiftCandidateOut`, `get_shift_candidates`)
- Modify: `frontend/src/api/assignments.ts` (`ShiftCandidate`)
- Test: `backend/tests/integration/test_shift_candidates.py` (extend, or create if
  candidate-list behavior isn't already covered by a dedicated integration test —
  check first)

**Interfaces:**
- Consumes: `constraint_override_settings.manual_override_allowed` (Task 2).
- Produces: `ShiftCandidateOut.personal_constraint_warning: PersonalConstraintWarningOut | None`.
  When present, `blocked`/`blocked_reason` are `False`/`None` for that candidate
  (setting ON case) — Task 8 (frontend) reads this field to render the icon.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_shift_candidates.py (append or create)
def test_constrained_soldier_shows_warning_when_override_allowed(client, db_session, make_soldier, make_shift, auth_headers, approve_constraint):
    soldier = make_soldier()
    shift = make_shift()
    approve_constraint(soldier_id=soldier.id, start_date=shift.start_date, end_date=shift.end_date)
    # constraints.allow_manual_override defaults to True — no setup needed

    resp = client.get(f"/shifts/{shift.id}/candidates", headers=auth_headers)
    assert resp.status_code == 200
    row = next(c for c in resp.json() if c["soldier_id"] == str(soldier.id))
    assert row["blocked"] is False
    assert row["personal_constraint_warning"]["reason"] is not None


def test_constrained_soldier_stays_blocked_when_override_disallowed(client, db_session, make_soldier, make_shift, auth_headers, approve_constraint, set_system_setting):
    soldier = make_soldier()
    shift = make_shift()
    approve_constraint(soldier_id=soldier.id, start_date=shift.start_date, end_date=shift.end_date)
    set_system_setting("constraints.allow_manual_override", False)

    resp = client.get(f"/shifts/{shift.id}/candidates", headers=auth_headers)
    row = next(c for c in resp.json() if c["soldier_id"] == str(soldier.id))
    assert row["blocked"] is True
    assert row["blocked_reason"] == "constraint"
    assert row.get("personal_constraint_warning") is None


def test_constrained_candidates_sort_last(client, db_session, make_soldier, make_shift, auth_headers, approve_constraint):
    unconstrained = make_soldier()
    constrained = make_soldier()
    shift = make_shift()
    approve_constraint(soldier_id=constrained.id, start_date=shift.start_date, end_date=shift.end_date)

    resp = client.get(f"/shifts/{shift.id}/candidates", headers=auth_headers)
    ids = [c["soldier_id"] for c in resp.json()]
    assert ids.index(str(constrained.id)) > ids.index(str(unconstrained.id))
```

Check the surrounding test module (or `backend/tests/helpers.py`) for the actual
names of `client`, `make_shift`, `auth_headers`, `approve_constraint`, and
`set_system_setting` fixtures/helpers before using them verbatim — this repo has
established equivalents (e.g. `test_range_assignment_reasons.py` and
`test_constraints_api.py` already exercise similar setups); match their existing
names rather than inventing new ones.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_shift_candidates.py -v`
Expected: FAIL — `KeyError: 'personal_constraint_warning'` / blocked assertion mismatch

- [ ] **Step 3: Implement**

In `backend/app/routes/shifts.py`, add a schema and thread the setting through:

```python
class PersonalConstraintWarningOut(BaseModel):
    reason: str
    start_date: date
    end_date: date
    decided_by: str | None
    decided_at: datetime | None


class ShiftCandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    personal_number: str
    effort: float
    blocked: bool
    blocked_reason: str | None = None
    weapon_warning: bool = False
    hierarchy_path_ids: list[str] = []
    personal_constraint_warning: PersonalConstraintWarningOut | None = None
```

In `get_shift_candidates`, near the top (after `authorize(...)`), read the setting
once:

```python
    from app.services.constraint_override_settings import manual_override_allowed
    override_allowed = manual_override_allowed(session)
```

Replace the constraint block inside the `for si in soldier_inputs:` loop. Today it
is:

```python
        has_constraint = any(
            c_start < shift.end_date and c_end >= shift.start_date
            for c_start, c_end in si.approved_constraint_dates
        )
        blocked = exempted or has_constraint or si.id in blocked_by_assignment
        blocked_reason: str | None = None
        if exempted:
            blocked_reason = "ineligible"
        elif has_constraint:
            blocked_reason = "constraint"
        elif si.id in blocked_by_assignment:
            blocked_reason = "assignment"
```

Replace with:

```python
        has_constraint = any(
            c_start < shift.end_date and c_end >= shift.start_date
            for c_start, c_end in si.approved_constraint_dates
        )
        personal_constraint_warning: PersonalConstraintWarningOut | None = None
        if has_constraint and override_allowed:
            constraint_row = session.execute(
                select(PersonalConstraint).where(
                    PersonalConstraint.soldier_id == si.id,
                    PersonalConstraint.status == "approved",
                    PersonalConstraint.start_date < shift.end_date,
                    PersonalConstraint.end_date >= shift.start_date,
                )
            ).scalars().first()
            if constraint_row is not None:
                decider = session.get(Soldier, constraint_row.decided_by) if constraint_row.decided_by else None
                personal_constraint_warning = PersonalConstraintWarningOut(
                    reason=constraint_row.reason,
                    start_date=constraint_row.start_date,
                    end_date=constraint_row.end_date,
                    decided_by=decider.full_name if decider else None,
                    decided_at=constraint_row.decided_at,
                )
        effective_constraint_block = has_constraint and not override_allowed
        blocked = exempted or effective_constraint_block or si.id in blocked_by_assignment
        blocked_reason: str | None = None
        if exempted:
            blocked_reason = "ineligible"
        elif effective_constraint_block:
            blocked_reason = "constraint"
        elif si.id in blocked_by_assignment:
            blocked_reason = "assignment"
```

Add `PersonalConstraint` to the `from app.db.models import (...)` block at the top
of `shifts.py` if it isn't already imported (check first).

Add `personal_constraint_warning=personal_constraint_warning` to the
`ShiftCandidateOut(...)` construction a few lines below.

Change the sort key so constrained-but-selectable candidates sort after
unconstrained ones but before hard-`blocked` ones (which already sort last via the
existing `x.blocked` key):

```python
    result.sort(key=lambda x: (x.blocked, x.personal_constraint_warning is not None, x.weapon_warning, x.effort))
```

- [ ] **Step 4: Update the frontend type**

In `frontend/src/api/assignments.ts`, extend `ShiftCandidate`:

```ts
export interface PersonalConstraintWarning {
  reason: string;
  start_date: string;
  end_date: string;
  decided_by: string | null;
  decided_at: string | null;
}

export interface ShiftCandidate {
  soldier_id: string;
  full_name: string;
  personal_number: string;
  effort: number;
  blocked: boolean;
  blocked_reason: "constraint" | "assignment" | "ineligible" | null;
  weapon_warning: boolean;
  hierarchy_path_ids: string[];
  personal_constraint_warning: PersonalConstraintWarning | null;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/integration/test_shift_candidates.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/shifts.py frontend/src/api/assignments.ts backend/tests/integration/test_shift_candidates.py
git commit -m "feat: surface personal-constraint warning on shift candidates, sort last"
```

---

## Task 6: Duty assignment write path — override_reason, hard block, audit, notify

**Files:**
- Modify: `backend/app/services/assignments.py` (`create_assignment`)
- Modify: `backend/app/routes/assignments.py` (`CreateAssignmentRequest`)
- Modify: `backend/app/routes/shifts.py` (`BatchAssignRequest`, `assign_batch`)
- Modify: `frontend/src/api/shifts.ts` (`assignBatch`)
- Test: `backend/app/services/tests/test_assignments.py` (extend)

**Interfaces:**
- Consumes: `constraint_override_settings.manual_override_allowed` (Task 2),
  `notifications.notify_personal_constraint_overridden` (Task 3),
  `PersonalConstraintOverride` (Task 1).
- Produces: `create_assignment(..., override_reason: str | None = None)` raises
  `AssignmentError("personal_constraint_blocked")` or
  `AssignmentError("override_reason_required")` under the conditions below; on
  success with an override it writes one `PersonalConstraintOverride` row and
  calls the Task 3 notifier.

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_assignments.py (append)
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db.models import PersonalConstraint, PersonalConstraintOverride
from app.services.assignments import AssignmentError, create_assignment
from app.services.settings_loader import set_setting


def _approved_constraint(db_session, soldier_id, start, end):
    c = PersonalConstraint(soldier_id=soldier_id, start_date=start, end_date=end, reason="r", status="approved")
    db_session.add(c)
    db_session.flush()
    return c


def test_blocks_when_setting_off(db_session, make_soldier, make_duty_type, make_duty_location):
    soldier = make_soldier()
    dt = make_duty_type()
    loc = make_duty_location()
    start, end = date.today(), date.today() + timedelta(days=1)
    _approved_constraint(db_session, soldier.id, start, end)
    set_setting(db_session, "constraints.allow_manual_override", False, actor_id=None)

    with pytest.raises(AssignmentError, match="personal_constraint_blocked"):
        create_assignment(
            db_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=start, end_date=end,
        )


def test_requires_reason_when_setting_on(db_session, make_soldier, make_duty_type, make_duty_location):
    soldier = make_soldier()
    dt = make_duty_type()
    loc = make_duty_location()
    start, end = date.today(), date.today() + timedelta(days=1)
    _approved_constraint(db_session, soldier.id, start, end)

    with pytest.raises(AssignmentError, match="override_reason_required"):
        create_assignment(
            db_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=start, end_date=end,
        )


def test_succeeds_with_reason_and_writes_audit(db_session, make_soldier, make_duty_type, make_duty_location):
    soldier = make_soldier()
    dt = make_duty_type()
    loc = make_duty_location()
    start, end = date.today(), date.today() + timedelta(days=1)
    constraint = _approved_constraint(db_session, soldier.id, start, end)

    a = create_assignment(
        db_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start, end_date=end, override_reason="צורך מבצעי",
    )
    db_session.flush()

    override = db_session.query(PersonalConstraintOverride).filter(
        PersonalConstraintOverride.personal_constraint_id == constraint.id,
    ).one()
    assert override.soldier_id == soldier.id
    assert override.assignment_kind == "duty"
    assert override.reference_id == a.id
    assert override.reason == "צורך מבצעי"


def test_no_constraint_ignores_override_reason(db_session, make_soldier, make_duty_type, make_duty_location):
    soldier = make_soldier()
    dt = make_duty_type()
    loc = make_duty_location()
    start, end = date.today(), date.today() + timedelta(days=1)

    a = create_assignment(
        db_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start, end_date=end,
    )
    assert a.id is not None
```

Confirm `make_duty_type`/`make_duty_location` fixture names against the existing
top of `test_assignments.py` before use — reuse whatever is already there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_assignments.py -v`
Expected: FAIL — no `personal_constraint_blocked`/`override_reason_required` raised
today (there's currently no constraint check in `create_assignment` at all)

- [ ] **Step 3: Implement**

In `backend/app/services/assignments.py`, add `override_reason: str | None = None`
to `create_assignment`'s signature, and insert a new check after the existing
`_has_blocking_exemption` block (before `a = DutyAssignment(...)`):

```python
    from app.db.models import PersonalConstraint, PersonalConstraintOverride
    from app.services.constraint_override_settings import manual_override_allowed

    constraint = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status == "approved",
            PersonalConstraint.start_date < end_date,
            PersonalConstraint.end_date >= start_date,
        )
    ).scalar_one_or_none()
    if constraint is not None:
        if not manual_override_allowed(session):
            raise AssignmentError("personal_constraint_blocked")
        if not override_reason or not override_reason.strip():
            raise AssignmentError("override_reason_required")
```

(`select` is very likely already imported in this file for `_has_overlap`/similar
helpers — check first rather than adding a duplicate import.)

Then, after the existing `session.flush()` that follows `session.add(a)` (the one
right before the `create_notification(...)` call for `assignment_created`), add:

```python
    if constraint is not None:
        session.add(PersonalConstraintOverride(
            personal_constraint_id=constraint.id,
            soldier_id=soldier_id,
            overridden_by=actor_id,
            assignment_kind="duty",
            reference_id=a.id,
            reason=override_reason.strip(),
        ))
        from app.services.notifications import notify_personal_constraint_overridden
        notify_personal_constraint_overridden(
            session, soldier_id=soldier_id, assignment_kind="duty",
            reason=override_reason.strip(), actor_id=actor_id,
        )
```

- [ ] **Step 4: Thread `override_reason` through the routes**

In `backend/app/routes/assignments.py`, add `override_reason: str | None = Field(default=None, max_length=1000)`
to `CreateAssignmentRequest`, and pass `override_reason=body.override_reason` in
its call to `svc.create_assignment(...)`. Wrap that call site's existing exception
handling (or add it, if none exists) so `AssignmentError("personal_constraint_blocked")`
and `AssignmentError("override_reason_required")` map to
`HTTPException(status_code=400, detail=str(exc))` — check how the route already
handles other `AssignmentError`s (e.g. `"overlap"`) and follow the same pattern.

In `backend/app/routes/shifts.py`, add `override_reason: str | None = Field(default=None, max_length=1000)`
to `BatchAssignRequest`, and pass `override_reason=body.override_reason` to both
`asvc.create_assignment(...)` calls inside `assign_batch` (primaries and reserves
loops).

In `frontend/src/api/shifts.ts`, update `assignBatch`:

```ts
export async function assignBatch(
  shiftId: string,
  input: { primaries: string[]; reserves: string[]; override_reason?: string },
): Promise<{ primary_assignment_ids: string[]; reserve_assignment_ids: string[]; reserve_links_created: number }> {
  return (await api.post(`/shifts/${shiftId}/assign-batch`, input)).data;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_assignments.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/assignments.py backend/app/routes/assignments.py backend/app/routes/shifts.py frontend/src/api/shifts.ts backend/app/services/tests/test_assignments.py
git commit -m "feat: support overriding personal constraints on duty assignment"
```

---

## Task 7: Range eligibility — unconditional warning / hard exclude

**Files:**
- Modify: `backend/app/services/range_auto_assign.py` (`_bulk_eligibility`, `ExcludedSoldier`)
- Modify: `frontend/src/api/ranges.ts` (`RangeCandidate`, `ExcludedRangeCandidate`)
- Test: `backend/tests/unit/test_range_candidates.py` (extend)

**Interfaces:**
- Consumes: `constraint_override_settings.manual_override_allowed` (Task 2).
- Produces: `_bulk_eligibility(...)` now always attaches a constraint
  `conflict_warning` (dropping the near-duty condition) when the setting is ON, and
  adds `ExcludedSoldier(soldier_id, "personal_constraint")` when the setting is
  OFF. `ExcludedSoldier.reason`'s `Literal` gains `"personal_constraint"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_range_candidates.py (append)
from datetime import date, timedelta

from app.services.range_auto_assign import _bulk_eligibility
from app.services.settings_loader import set_setting


def test_constraint_warns_unconditionally_when_override_allowed(db_session, make_soldier, make_range_event, approve_constraint):
    soldier = make_soldier()
    event = make_range_event()
    approve_constraint(soldier_id=soldier.id, start_date=event.date, end_date=event.date)
    # no near-term weapon duty set up — today this soldier would get NO warning

    warnings, excluded = _bulk_eligibility(
        db_session, soldiers=[soldier], event=event, duty_start_by_soldier={},
    )
    assert soldier.id in warnings
    assert warnings[soldier.id] is not None
    assert excluded == []


def test_constraint_hard_excludes_when_override_disallowed(db_session, make_soldier, make_range_event, approve_constraint):
    soldier = make_soldier()
    event = make_range_event()
    approve_constraint(soldier_id=soldier.id, start_date=event.date, end_date=event.date)
    set_setting(db_session, "constraints.allow_manual_override", False, actor_id=None)

    warnings, excluded = _bulk_eligibility(
        db_session, soldiers=[soldier], event=event, duty_start_by_soldier={},
    )
    assert soldier.id not in warnings
    assert any(e.soldier_id == soldier.id and e.reason == "personal_constraint" for e in excluded)
```

Check `test_range_candidates.py`'s existing fixtures (`make_range_event`,
`approve_constraint` or equivalent) before use.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/unit/test_range_candidates.py -v`
Expected: FAIL — soldier gets neither a warning nor an exclusion today (constraint
without a near-term weapon duty is silently ignored)

- [ ] **Step 3: Implement**

In `backend/app/services/range_auto_assign.py`, widen the `ExcludedSoldier.reason`
`Literal`:

```python
@dataclass(frozen=True)
class ExcludedSoldier:
    soldier_id: uuid.UUID
    reason: Literal["weapon_exempt", "structurally_ineligible", "assigned_elsewhere_same_day", "personal_constraint"]
```

In `_bulk_eligibility`, near the top, read the setting once:

```python
    from app.services.constraint_override_settings import manual_override_allowed
    override_allowed = manual_override_allowed(session)
```

Replace the tail of the per-soldier loop (from `constraint = constraint_by_soldier.get(soldier.id)`
through the end of the `for soldier in soldiers:` block) with:

```python
        constraint = constraint_by_soldier.get(soldier.id)
        duty_conflict = duty_conflict_by_soldier.get(soldier.id)

        if constraint is not None and not override_allowed:
            excluded.append(ExcludedSoldier(soldier.id, "personal_constraint"))
            continue

        if constraint is None and duty_conflict is None:
            result[soldier.id] = None
            continue

        if constraint is not None:
            # Setting ON: always warn (dropping the previous near-duty gate).
            parts: list[str] = [
                f"אילוץ מאושר {constraint.start_date.strftime('%d.%m.%Y')}"
                f"–{constraint.end_date.strftime('%d.%m.%Y')}"
            ]
            if duty_conflict is not None:
                duty, duty_type_name = duty_conflict
                parts.append(f"משובץ לתורנות '{duty_type_name}' ב-{duty.start_date.strftime('%d.%m.%Y')}")
            result[soldier.id] = " · ".join(parts)
            continue

        # No constraint — keep the existing near-duty-gated duty_conflict warning.
        has_near_duty = any(
            start is not None and start <= near_duty_cutoff
            for start in (
                duty_start_by_soldier.get((soldier.id, False)),
                duty_start_by_soldier.get((soldier.id, True)),
            )
        )
        if not has_near_duty:
            continue
        duty, duty_type_name = duty_conflict
        result[soldier.id] = f"משובץ לתורנות '{duty_type_name}' ב-{duty.start_date.strftime('%d.%m.%Y')}"
```

Update the function's docstring (the paragraph starting "A soldier blocked only by
a personal constraint...") to describe the new behavior: constraint warnings are now
unconditional when overriding is allowed, and become a hard exclusion when it
isn't — only the plain duty-conflict-without-constraint case keeps the near-duty
gate.

- [ ] **Step 4: Update the frontend types**

In `frontend/src/api/ranges.ts`:

```ts
export interface ExcludedRangeCandidate { soldier_id:string; soldier_name:string; reason:"weapon_exempt"|"structurally_ineligible"|"assigned_elsewhere_same_day"|"personal_constraint"; }
```

(`RangeCandidate.conflict_warning` already exists and is reused as-is — no shape
change needed there.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/unit/test_range_candidates.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/range_auto_assign.py frontend/src/api/ranges.ts backend/tests/unit/test_range_candidates.py
git commit -m "feat: make range personal-constraint warning unconditional, hard-exclude when override disallowed"
```

---

## Task 8: Range assignment write path — override_reason, hard block, audit, notify

**Files:**
- Modify: `backend/app/services/ranges.py` (`_validate_and_build_assignment`, `add_range_assignment`, `assign_batch`)
- Modify: `backend/app/routes/ranges.py` (`AddAssignmentBody`, `BatchAssignBody`)
- Modify: `frontend/src/api/ranges.ts` (`batchAssignRange`)
- Test: `backend/tests/unit/test_ranges_service.py` (extend)

**Interfaces:**
- Consumes: `constraint_override_settings.manual_override_allowed` (Task 2),
  `notifications.notify_personal_constraint_overridden` (Task 3),
  `PersonalConstraintOverride` (Task 1).
- Produces: `_validate_and_build_assignment(..., override_reason: str | None = None)`
  raises `RangeValidationError("personal_constraint_blocked")` /
  `RangeValidationError("override_reason_required")`; returns the built (unsaved)
  `RangeAssignment` plus writes nothing itself — the audit row and notification are
  written by the two callers (`add_range_assignment`, `assign_batch`) after the row
  is flushed and has an id, mirroring how Task 6 handles duties.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_ranges_service.py (append)
from datetime import timedelta

import pytest

from app.db.models import PersonalConstraint, PersonalConstraintOverride
from app.services.ranges import RangeValidationError, add_range_assignment
from app.services.settings_loader import set_setting


def _approved_constraint(db_session, soldier_id, event_date):
    c = PersonalConstraint(
        soldier_id=soldier_id, start_date=event_date, end_date=event_date, reason="r", status="approved",
    )
    db_session.add(c)
    db_session.flush()
    return c


def test_range_assignment_blocked_when_setting_off(db_session, make_soldier, make_range_event):
    soldier = make_soldier()
    event = make_range_event()
    _approved_constraint(db_session, soldier.id, event.date)
    set_setting(db_session, "constraints.allow_manual_override", False, actor_id=None)

    with pytest.raises(RangeValidationError, match="personal_constraint_blocked"):
        add_range_assignment(db_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_range_assignment_requires_reason(db_session, make_soldier, make_range_event):
    soldier = make_soldier()
    event = make_range_event()
    _approved_constraint(db_session, soldier.id, event.date)

    with pytest.raises(RangeValidationError, match="override_reason_required"):
        add_range_assignment(db_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_range_assignment_succeeds_with_reason(db_session, make_soldier, make_range_event):
    soldier = make_soldier()
    event = make_range_event()
    constraint = _approved_constraint(db_session, soldier.id, event.date)

    assignment = add_range_assignment(
        db_session, event=event, soldier_id=soldier.id, is_reserve=False,
        override_reason="צורך מבצעי",
    )

    override = db_session.query(PersonalConstraintOverride).filter(
        PersonalConstraintOverride.personal_constraint_id == constraint.id,
    ).one()
    assert override.reference_id == assignment.id
    assert override.assignment_kind == "range"
```

Check `test_ranges_service.py`'s existing `make_range_event`/`make_soldier`
fixtures before use — reuse names already established there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/unit/test_ranges_service.py -v`
Expected: FAIL — `add_range_assignment` has no `override_reason` parameter and does
not check `PersonalConstraint` at all today

- [ ] **Step 3: Implement**

In `backend/app/services/ranges.py`, replace the entire
`_validate_and_build_assignment` function. It currently just returns the unsaved
`RangeAssignment` —
it doesn't have access to the row's id yet, so it can't write the audit row itself.
Change its signature and final return line to also hand back the `constraint`
object (or `None`) alongside the built assignment, so callers know whether to
audit/notify after flush:

```python
def _validate_and_build_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
    user: Soldier | None = None, override_reason: str | None = None,
) -> tuple[RangeAssignment, "PersonalConstraint | None"]:
    """Same validation as add_range_assignment (subtree membership, exemption,
    same-date conflict, personal constraint) but only constructs the row — does
    not add/commit/notify. Shared by add_range_assignment (single, notifies) and
    assign_batch (many, one commit + one notification pass at the end). Returns
    the built assignment plus the PersonalConstraint it overrode, if any — callers
    use the second element to decide whether to write an audit row and notify."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise RangeValidationError("soldier_not_found")
    node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    event_node = session.get(HierarchyNode, event.hierarchy_node_id)
    if node is None or event_node is None:
        raise RangeValidationError("soldier_outside_event_subunit")
    in_event_subtree = event.hierarchy_node_id in node.path_ids
    if not in_event_subtree and not _soldier_in_authorized_scope(session, node=node, user=user):
        raise RangeValidationError("soldier_outside_event_subunit")
    if is_range_exempt(session, soldier=soldier, event_date=event.date):
        raise RangeValidationError("soldier_range_exempt")
    existing_same_date = session.execute(
        select(RangeAssignment.id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeEvent.date == event.date,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing_same_date is not None:
        raise RangeValidationError("soldier_already_assigned_on_date")

    from app.db.models import PersonalConstraint
    from app.services.constraint_override_settings import manual_override_allowed

    constraint = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status == "approved",
            PersonalConstraint.start_date <= event.date,
            PersonalConstraint.end_date >= event.date,
        )
    ).scalar_one_or_none()
    if constraint is not None:
        if not manual_override_allowed(session):
            raise RangeValidationError("personal_constraint_blocked")
        if not override_reason or not override_reason.strip():
            raise RangeValidationError("override_reason_required")

    return RangeAssignment(range_event_id=event.id, soldier_id=soldier_id, is_reserve=is_reserve), constraint
```

This replaces the entire existing function body (the constraint check is new; the
rest is unchanged except the final `return` line and the two new parameters).

In `add_range_assignment`, thread `override_reason: str | None = None` through the
signature, update the call:

```python
    assignment, overridden_constraint = _validate_and_build_assignment(
        session, event=event, soldier_id=soldier_id, is_reserve=is_reserve, user=user,
        override_reason=override_reason,
    )
```

and after `session.flush()` (which already runs right after
`session.add(assignment)`), before `_notify_roster_change(...)`:

```python
    if overridden_constraint is not None:
        session.add(PersonalConstraintOverride(
            personal_constraint_id=overridden_constraint.id,
            soldier_id=soldier_id,
            overridden_by=user.id if user else None,
            assignment_kind="range",
            reference_id=assignment.id,
            reason=override_reason.strip(),
        ))
        from app.services.notifications import notify_personal_constraint_overridden
        notify_personal_constraint_overridden(
            session, soldier_id=soldier_id, assignment_kind="range",
            reason=override_reason.strip(), actor_id=user.id if user else None,
        )
```

In `assign_batch`, add `override_reason: str | None = None` to the signature
(applies to every soldier in the batch, per the spec's shared-reason decision) and
replace the row-building and post-flush notification sections:

```python
def assign_batch(
    session: Session, *, event: RangeEvent,
    primary_soldier_ids: list[uuid.UUID], reserve_soldier_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None, user: Soldier | None = None,
    override_reason: str | None = None,
) -> list[RangeAssignment]:
    """All-or-nothing: validates every soldier before adding any row, so a single
    invalid soldier in the batch fails the whole call with no partial writes.
    Deliberately simpler than shifts' assignBatch (which is partial-success/lenient) —
    the range candidate panel already is the review step, so failing fast on the
    first invalid soldier keeps this endpoint's contract simple."""
    _acquire_range_assignment_date_lock(session, event_date=event.date)
    session.refresh(event)
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    _check_capacity(
        session, event=event,
        new_primary=len(primary_soldier_ids),
        new_reserve=len(reserve_soldier_ids),
    )

    from app.services.range_auto_assign import _rank_candidate

    rows_with_constraints = [
        _validate_and_build_assignment(
            session, event=event, soldier_id=sid, is_reserve=False, user=user,
            override_reason=override_reason,
        )
        for sid in primary_soldier_ids
    ] + [
        _validate_and_build_assignment(
            session, event=event, soldier_id=sid, is_reserve=True, user=user,
            override_reason=override_reason,
        )
        for sid in reserve_soldier_ids
    ]
    for row, _constraint in rows_with_constraints:
        soldier = session.get(Soldier, row.soldier_id)
        _, reason_code, _explanation = _rank_candidate(session, soldier=soldier, event=event)
        row.assignment_reason_code = reason_code
        session.add(row)
    session.flush()
    for row, constraint in rows_with_constraints:
        _range_notification(
            session, soldier_id=row.soldier_id, type=NotificationType.range_assignment_confirmed,
            title="שובצת למטווח", body=_range_assignment_body(event),
            reference_type="range_event", reference_id=event.id,
        )
        if constraint is not None:
            session.add(PersonalConstraintOverride(
                personal_constraint_id=constraint.id,
                soldier_id=row.soldier_id,
                overridden_by=user.id if user else None,
                assignment_kind="range",
                reference_id=row.id,
                reason=override_reason.strip(),
            ))
            from app.services.notifications import notify_personal_constraint_overridden
            notify_personal_constraint_overridden(
                session, soldier_id=row.soldier_id, assignment_kind="range",
                reason=override_reason.strip(), actor_id=user.id if user else None,
            )
    session.commit()
    rows = [row for row, _constraint in rows_with_constraints]
    for row in rows:
        session.refresh(row)
    return rows
```

- [ ] **Step 4: Thread `override_reason` through the routes**

In `backend/app/routes/ranges.py`, add `override_reason: str | None = Field(default=None, max_length=1000)`
to both `AddAssignmentBody` and `BatchAssignBody`, and pass it through in
`add_assignment` and `batch_assign`. Map `RangeValidationError("personal_constraint_blocked")`
and `RangeValidationError("override_reason_required")` the same way the route
already maps every other `RangeValidationError` (check the existing
`except svc.RangeValidationError as exc:` blocks — no new handling needed if they
already do a generic `str(exc)` → 400).

In `frontend/src/api/ranges.ts`:

```ts
export function batchAssignRange(eventId:string,input:{primaries:string[];reserves:string[];override_reason?:string}):Promise<RangeAssignment[]>{return api.post(`/ranges/${eventId}/assignments/batch`,input).then(r=>r.data);}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/unit/test_ranges_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ranges.py backend/app/routes/ranges.py frontend/src/api/ranges.ts backend/tests/unit/test_ranges_service.py
git commit -m "feat: support overriding personal constraints on range assignment"
```

---

## Task 9: Frontend `ConstraintWarningIcon` + `OverrideReasonModal` shared components

**Files:**
- Create: `frontend/src/components/ConstraintWarningIcon.tsx`
- Create: `frontend/src/components/ConstraintWarningIcon.test.tsx`
- Create: `frontend/src/components/OverrideReasonModal.tsx`
- Create: `frontend/src/components/OverrideReasonModal.test.tsx`

**Interfaces:**
- Consumes: `PersonalConstraintWarning` type (Task 5, `frontend/src/api/assignments.ts`).
- Produces: `<ConstraintWarningIcon warning={PersonalConstraintWarning} />` (hover
  tooltip + click popover) and `<OverrideReasonModal open count onCancel onConfirm={(reason: string) => void} />`.
  Tasks 10 and 11 import both from these two files.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/ConstraintWarningIcon.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ConstraintWarningIcon from "./ConstraintWarningIcon";

const warning = {
  reason: "בקשה אישית",
  start_date: "2026-09-01",
  end_date: "2026-09-05",
  decided_by: "רב\"ט כהן",
  decided_at: "2026-08-20T10:00:00Z",
};

describe("ConstraintWarningIcon", () => {
  it("shows a popover with reason and approver on click", () => {
    render(<ConstraintWarningIcon warning={warning} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("בקשה אישית")).toBeInTheDocument();
    expect(screen.getByText(/רב"ט כהן/)).toBeInTheDocument();
  });
});
```

```tsx
// frontend/src/components/OverrideReasonModal.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OverrideReasonModal from "./OverrideReasonModal";

describe("OverrideReasonModal", () => {
  it("disables confirm until a reason is typed, then calls onConfirm with it", () => {
    const onConfirm = vi.fn();
    render(<OverrideReasonModal open count={2} onCancel={() => {}} onConfirm={onConfirm} />);

    const confirmButton = screen.getByRole("button", { name: /אישור/ });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "צורך מבצעי" } });
    expect(confirmButton).not.toBeDisabled();

    fireEvent.click(confirmButton);
    expect(onConfirm).toHaveBeenCalledWith("צורך מבצעי");
  });
});
```

Check any existing modal test in this repo (e.g. `RangeCancelDialog.tsx`'s test)
for the project's established `@testing-library/react` import conventions/setup
before assuming the above imports are complete.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- ConstraintWarningIcon OverrideReasonModal`
Expected: FAIL — modules don't exist yet

- [ ] **Step 3: Implement `ConstraintWarningIcon`**

```tsx
// frontend/src/components/ConstraintWarningIcon.tsx
import { useState } from "react";
import type { PersonalConstraintWarning } from "../api/assignments";
import { formatDate } from "../utils/formatDate";

interface Props {
  warning: PersonalConstraintWarning;
}

export default function ConstraintWarningIcon({ warning }: Props) {
  const [open, setOpen] = useState(false);
  const summary = `אילוץ אישי מאושר ${formatDate(warning.start_date)}–${formatDate(warning.end_date)}`;

  return (
    <span className="relative inline-block mr-1">
      <button
        type="button"
        title={summary}
        aria-label={summary}
        onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
        className="text-amber-500 dark:text-amber-400"
      >
        ⚠️
      </button>
      {open && (
        <div
          dir="rtl"
          onClick={(e) => e.stopPropagation()}
          className="absolute z-10 mt-1 w-56 rounded border bg-white p-2 text-xs shadow-lg dark:border-gray-600 dark:bg-gray-800"
        >
          <p className="font-medium">{summary}</p>
          <p className="mt-1 text-gray-600 dark:text-gray-300">{warning.reason}</p>
          {warning.decided_by && (
            <p className="mt-1 text-gray-400 dark:text-gray-500">
              אושר ע&quot;י {warning.decided_by}
              {warning.decided_at ? ` · ${formatDate(warning.decided_at)}` : ""}
            </p>
          )}
        </div>
      )}
    </span>
  );
}
```

Check `frontend/src/utils/formatDate.ts` for the exact exported function name
(`formatDate` is used elsewhere in this repo, e.g. `RangeEditAssignmentsModal.tsx`
line 8) before assuming its signature accepts an ISO datetime string as well as a
plain date string.

- [ ] **Step 4: Implement `OverrideReasonModal`**

```tsx
// frontend/src/components/OverrideReasonModal.tsx
import { useState } from "react";

interface Props {
  open: boolean;
  count: number;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}

export default function OverrideReasonModal({ open, count, onCancel, onConfirm }: Props) {
  const [reason, setReason] = useState("");
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-[60]" onClick={onCancel}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <h4 className="text-sm font-semibold mb-2">
          {count === 1 ? "שיבוץ עם אילוץ אישי מאושר" : `שיבוץ ${count} חיילים עם אילוץ אישי מאושר`}
        </h4>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          נדרש נימוק לעקיפת האילוץ. הנימוק יישלח לחייל/ים ולמפקדם.
        </p>
        <textarea
          className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          rows={3}
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="נימוק העקיפה..."
        />
        <div className="flex justify-end gap-2 mt-3">
          <button type="button" onClick={onCancel} className="px-3 py-1.5 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
            ביטול
          </button>
          <button
            type="button"
            onClick={() => onConfirm(reason.trim())}
            disabled={!reason.trim()}
            className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            אישור
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- ConstraintWarningIcon OverrideReasonModal`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConstraintWarningIcon.tsx frontend/src/components/ConstraintWarningIcon.test.tsx frontend/src/components/OverrideReasonModal.tsx frontend/src/components/OverrideReasonModal.test.tsx
git commit -m "feat: add ConstraintWarningIcon and OverrideReasonModal components"
```

---

## Task 10: Wire override flow into `ShiftAssignModal.tsx`

**Files:**
- Modify: `frontend/src/components/ShiftAssignModal.tsx`
- Modify: `frontend/src/components/ShiftAssignModal.test.tsx` (extend; check it
  exists first — if not, this task also creates it)

**Interfaces:**
- Consumes: `ConstraintWarningIcon`, `OverrideReasonModal` (Task 9);
  `ShiftCandidate.personal_constraint_warning` (Task 5); `assignBatch(..., { override_reason })` (Task 6).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ShiftAssignModal.test.tsx (append; adapt imports/mocks
// to match this file's existing mock-setup conventions for getShiftCandidates/assignBatch)
it("shows a warning icon for a constrained candidate and requires a reason before assigning them", async () => {
  mockedGetShiftCandidates.mockResolvedValue([
    {
      soldier_id: "s1", full_name: "חייל אחד", personal_number: "1111111", effort: 0.2,
      blocked: false, blocked_reason: null, weapon_warning: false, hierarchy_path_ids: [],
      personal_constraint_warning: {
        reason: "בקשה אישית", start_date: "2026-09-01", end_date: "2026-09-05",
        decided_by: "רב\"ט כהן", decided_at: "2026-08-20T10:00:00Z",
      },
    },
  ]);

  render(<ShiftAssignModal shift={shift} dutyTypes={[]} onSaved={onSaved} onClose={() => {}} />);
  await screen.findByText("חייל אחד");

  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText(/שבץ/));

  expect(await screen.findByText(/נדרש נימוק/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "צורך מבצעי" } });
  fireEvent.click(screen.getByRole("button", { name: /אישור/ }));

  await waitFor(() => expect(mockedAssignBatch).toHaveBeenCalledWith(
    shift.id, expect.objectContaining({ override_reason: "צורך מבצעי" }),
  ));
});
```

Check the existing top of `ShiftAssignModal.test.tsx` for how `getShiftCandidates`
and `assignBatch` are already mocked (vi.mock target paths, mock variable names)
and match that pattern exactly rather than introducing a second mocking style.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ShiftAssignModal`
Expected: FAIL — no override-reason modal exists yet, `assignBatch` is called
without `override_reason`

- [ ] **Step 3: Implement**

In `ShiftAssignModal.tsx`:

1. Import the two new components and sort constrained candidates last within the
   unblocked group. Change:

```ts
  const unblockedCandidates = useMemo(() => candidates.filter(c => !c.blocked), [candidates]);
```

to:

```ts
  const unblockedCandidates = useMemo(
    () => [...candidates.filter(c => !c.blocked)].sort(
      (a, b) => Number(!!a.personal_constraint_warning) - Number(!!b.personal_constraint_warning)
    ),
    [candidates]
  );
```

(a stable sort by a 0/1 key preserves the existing relative order within each
group, matching how the backend already pre-sorts by effort).

Apply the equivalent change inside the `reserveCandidates` `useMemo` — sort
`withDist` by `(dist, personal_constraint_warning-present, effort)` instead of just
`(dist, effort)`:

```ts
    withDist.sort((a, b) => {
      if (a.dist !== b.dist) return a.dist - b.dist;
      const aWarn = Number(!!a.personal_constraint_warning);
      const bWarn = Number(!!b.personal_constraint_warning);
      if (aWarn !== bWarn) return aWarn - bWarn;
      return a.effort - b.effort;
    });
```

2. Add state for the confirm modal:

```ts
  const [pendingOverride, setPendingOverride] = useState<{ primaries: string[]; reserves: string[] } | null>(null);
```

3. Replace `handleAssign`'s body: extract the actual submit into a new
   `doAssign(overrideReason?: string)` that does today's try/catch block (using
   `assignBatch(shift.id, { primaries: [...primarySelected], reserves: [...reserveSelected], override_reason: overrideReason })`),
   and have `handleAssign` check for constrained selections first:

```ts
  async function handleAssign() {
    if (primarySelected.size === 0 && reserveSelected.size === 0) return;
    const selectedIds = new Set([...primarySelected, ...reserveSelected]);
    const hasWeaponWarning = candidates.some(c => selectedIds.has(c.soldier_id) && c.weapon_warning);
    if (hasWeaponWarning) {
      const confirmed = window.confirm(
        "חלק מהחיילים שנבחרו אינם כשירים מבחינת הכשרת נשק לתורנות זו. לשבץ בכל זאת?"
      );
      if (!confirmed) return;
    }
    const hasConstraintWarning = candidates.some(c => selectedIds.has(c.soldier_id) && c.personal_constraint_warning);
    if (hasConstraintWarning) {
      setPendingOverride({ primaries: [...primarySelected], reserves: [...reserveSelected] });
      return;
    }
    await doAssign();
  }

  async function doAssign(overrideReason?: string) {
    setSaving(true);
    setError(null);
    try {
      await assignBatch(shift.id, {
        primaries: [...primarySelected],
        reserves: [...reserveSelected],
        ...(overrideReason ? { override_reason: overrideReason } : {}),
      });
      onSaved();
    } catch (e: unknown) {
      setError(translateApiError(e, t, "שגיאה בשיבוץ"));
      setSaving(false);
    }
  }
```

4. Render the modal near the bottom of the component, alongside the existing
   `error` block:

```tsx
        <OverrideReasonModal
          open={pendingOverride !== null}
          count={pendingOverride ? pendingOverride.primaries.length + pendingOverride.reserves.length : 0}
          onCancel={() => setPendingOverride(null)}
          onConfirm={(reason) => { setPendingOverride(null); void doAssign(reason); }}
        />
```

5. In `PrimaryTable` and `ReserveTable`, render the icon next to the name for
   unblocked rows, alongside the existing `weapon_warning` icon:

```tsx
              <td className="p-2">
                {c.full_name}
                {c.weapon_warning && (
                  <span title={WEAPON_WARNING_LABEL} className="mr-1 text-amber-500 dark:text-amber-400">⚠️</span>
                )}
                {c.personal_constraint_warning && (
                  <ConstraintWarningIcon warning={c.personal_constraint_warning} />
                )}
              </td>
```

(apply this to both tables' unblocked-row `<td>` — two edit sites total).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- ShiftAssignModal`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ShiftAssignModal.tsx frontend/src/components/ShiftAssignModal.test.tsx
git commit -m "feat: wire personal-constraint override flow into ShiftAssignModal"
```

---

## Task 11: Wire override flow into `RangeEditAssignmentsModal.tsx`

**Files:**
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx` (extend)

**Interfaces:**
- Consumes: `ConstraintWarningIcon`, `OverrideReasonModal` (Task 9);
  `RangeCandidate.conflict_warning` (reused, Task 7);
  `batchAssignRange(..., { override_reason })` (Task 8).

This modal doesn't have a `personal_constraint_warning`-shaped field — it reuses
the pre-existing free-text `conflict_warning` string, which after Task 7 is always
populated for a constrained soldier when overriding is allowed. Since it's a plain
string (not a structured object with dates/decided_by like the duty side), reuse
today's `title`/`⚠️` rendering as-is for the icon — **do not** force this modal to
adopt `ConstraintWarningIcon` (which expects the richer duty-side shape) — but DO
reuse `OverrideReasonModal` for the confirm step, since the reason-collection UX
should be identical.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx (append; adapt
// mocks to this file's existing conventions for getRangeCandidates/batchAssignRange)
it("requires an override reason before batch-assigning a soldier with a conflict_warning", async () => {
  mockedGetRangeCandidates.mockResolvedValue({
    candidates: [{ soldier_id: "s1", full_name: "חייל אחד", personal_number: "1111111", reason_code: "manual", explanation: "", conflict_warning: "אילוץ מאושר 01.09.2026–05.09.2026" }],
    excluded: [],
  });

  render(<RangeEditAssignmentsModal open event={event} soldiers={soldiers} canManage onClose={() => {}} onChanged={onChanged} />);
  await screen.findByText("חייל אחד");

  fireEvent.click(screen.getByTestId(/primary-candidate-s1|s1/));
  fireEvent.click(screen.getByText(/שמור|הוסף/));

  expect(await screen.findByText(/נדרש נימוק/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "צורך מבצעי" } });
  fireEvent.click(screen.getByRole("button", { name: /אישור/ }));

  await waitFor(() => expect(mockedBatchAssignRange).toHaveBeenCalledWith(
    event.id, expect.objectContaining({ override_reason: "צורך מבצעי" }),
  ));
});
```

Read the actual save-button label/testid and candidate-row testid from the current
`RangeEditAssignmentsModal.tsx` (the file itself, around the "save"/batch-submit
handler you're about to modify in Step 3) before finalizing this test — the
placeholder selectors above (`/שמור|הוסף/`, `/primary-candidate-s1|s1/`) must be
replaced with whatever this component's actual save button text and
`data-testid={`${testIdPrefix}-${c.soldier_id}`}` pattern (seen at line 463 of the
component) resolve to.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- RangeEditAssignmentsModal`
Expected: FAIL — no override-reason modal exists yet in this component

- [ ] **Step 3: Implement**

Find this component's existing save/batch-submit handler (the function that calls
`batchAssignRange`, likely named something like `handleSave`) and apply the same
split pattern as Task 10 step 3: rename the body that calls `batchAssignRange` to
`doSave(overrideReason?: string)`, and have the button's `onClick` handler call a
new `handleSave()` that first checks:

```ts
  const [pendingOverride, setPendingOverride] = useState<{ primaries: string[]; reserves: string[] } | null>(null);

  function handleSave() {
    const selectedIds = new Set([...primarySelected, ...reserveSelected]);
    const hasConflictWarning = rangeCandidates.some(c => selectedIds.has(c.soldier_id) && c.conflict_warning);
    if (hasConflictWarning) {
      setPendingOverride({ primaries: [...primarySelected], reserves: [...reserveSelected] });
      return;
    }
    void doSave();
  }
```

and update `doSave` to accept and forward `overrideReason`:

```ts
  async function doSave(overrideReason?: string) {
    // ...existing body, but the batchAssignRange(...) call becomes:
    await batchAssignRange(event.id, {
      primaries: [...primarySelected],
      reserves: [...reserveSelected],
      ...(overrideReason ? { override_reason: overrideReason } : {}),
    });
    // ...rest unchanged
  }
```

Render `OverrideReasonModal` near the component's other modals/dialogs:

```tsx
      <OverrideReasonModal
        open={pendingOverride !== null}
        count={pendingOverride ? pendingOverride.primaries.length + pendingOverride.reserves.length : 0}
        onCancel={() => setPendingOverride(null)}
        onConfirm={(reason) => { setPendingOverride(null); void doSave(reason); }}
      />
```

Wire the component's save button's `onClick` from whatever currently calls the
save handler directly, to `handleSave` instead.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- RangeEditAssignmentsModal`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ranges/RangeEditAssignmentsModal.tsx frontend/src/components/ranges/RangeEditAssignmentsModal.test.tsx
git commit -m "feat: wire personal-constraint override flow into RangeEditAssignmentsModal"
```

---

## Task 12: Surface the audit trail — constraint detail + soldier timeline

**Files:**
- Modify: `backend/app/routes/constraints.py` (`ConstraintOut`, `_out`)
- Modify: `backend/app/services/duty_history.py` (new `TimelineEvent` block)
- Modify: `frontend/src/api/constraints.ts` (`PersonalConstraint`)
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx` (constraints tab render)
- Modify: `frontend/src/components/DutyHistoryPanel.tsx` (new event-type filter/color)
- Test: `backend/app/services/tests/test_constraints.py` (extend),
  `backend/app/services/tests/test_duty_history.py` (extend; create if this exact
  filename doesn't exist — check what file currently covers `duty_history.py`
  first)

**Interfaces:**
- Consumes: `PersonalConstraintOverride` (Task 1).
- Produces: `ConstraintOut.overrides: list[ConstraintOverrideOut]`;
  `TimelineEvent(event_type="personal_constraint_override", ...)` entries in the
  soldier's history.

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_constraints.py (append)
from app.db.models import PersonalConstraintOverride


def test_constraint_out_includes_overrides(client, db_session, make_soldier, auth_headers, approve_constraint):
    soldier = make_soldier()
    overrider = make_soldier()
    constraint = approve_constraint(soldier_id=soldier.id)
    db_session.add(PersonalConstraintOverride(
        personal_constraint_id=constraint.id, soldier_id=soldier.id,
        overridden_by=overrider.id, assignment_kind="duty",
        reference_id=constraint.id, reason="צורך מבצעי",
    ))
    db_session.commit()

    resp = client.get(f"/soldiers/{soldier.id}/constraints", headers=auth_headers)
    row = next(c for c in resp.json() if c["id"] == str(constraint.id))
    assert len(row["overrides"]) == 1
    assert row["overrides"][0]["reason"] == "צורך מבצעי"
    assert row["overrides"][0]["assignment_kind"] == "duty"
```

```python
# backend/app/services/tests/test_duty_history.py (append or create)
from app.db.models import PersonalConstraintOverride
from app.services.duty_history import get_soldier_duty_history  # confirm exact function name first


def test_timeline_includes_constraint_override(db_session, make_soldier, approve_constraint):
    soldier = make_soldier()
    overrider = make_soldier()
    constraint = approve_constraint(soldier_id=soldier.id)
    db_session.add(PersonalConstraintOverride(
        personal_constraint_id=constraint.id, soldier_id=soldier.id,
        overridden_by=overrider.id, assignment_kind="range",
        reference_id=constraint.id, reason="צורך מבצעי",
    ))
    db_session.commit()

    events = get_soldier_duty_history(db_session, soldier_id=soldier.id, include_sensitive=True)
    override_events = [e for e in events if e.event_type == "personal_constraint_override"]
    assert len(override_events) == 1
    assert override_events[0].description == "צורך מבצעי"
```

Confirm `get_soldier_duty_history`'s exact name/signature (including the
`include_sensitive` parameter name) by reading the top of
`backend/app/services/duty_history.py` and its existing route caller in
`backend/app/routes/` before writing this test — the function shown reading
`PersonalConstraint` at line 682 lives inside some enclosing function; use its
real name.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_constraints.py backend/app/services/tests/test_duty_history.py -v`
Expected: FAIL — `overrides` key missing from response; no
`personal_constraint_override` event type emitted

- [ ] **Step 3: Implement the constraint-detail side**

In `backend/app/routes/constraints.py`, add a nested output schema and field to
`ConstraintOut`:

```python
class ConstraintOverrideOut(BaseModel):
    id: uuid.UUID
    overridden_by: PersonRefOut | None = None
    assignment_kind: str
    reason: str
    overridden_at: datetime


class ConstraintOut(BaseModel):
    # ...existing fields...
    overrides: list[ConstraintOverrideOut] = []
```

In `_out(...)`, add a parameter `overrides: list[ConstraintOverrideOut] | None = None`
and pass `overrides=overrides or []` into the returned `ConstraintOut`. At each of
`_out`'s call sites (the module has several — grep `_out(` in this file), fetch and
pass the overrides for that constraint:

```python
    override_rows = session.execute(
        select(PersonalConstraintOverride).where(
            PersonalConstraintOverride.personal_constraint_id == c.id
        ).order_by(PersonalConstraintOverride.overridden_at.desc())
    ).scalars().all()
    overrides = [
        ConstraintOverrideOut(
            id=o.id,
            overridden_by=person_ref(session, o.overridden_by),
            assignment_kind=o.assignment_kind,
            reason=o.reason,
            overridden_at=o.overridden_at,
        )
        for o in override_rows
    ]
```

Since several call sites build lists of `_out(...)` results in a loop (e.g. the
route that lists a soldier's constraints), batch-fetch all overrides for the
constraint ids in that page in one query rather than one query per constraint —
follow this file's existing `audit_times` parameter (already threaded through
`_out` as a batch-fetched dict, per its signature at line 120) as the precedent for
this exact pattern; build an equivalent `overrides_by_constraint: dict[uuid.UUID, list[ConstraintOverrideOut]]`
the same way `audit_times` is built, and pass `overrides=overrides_by_constraint.get(c.id, [])`
at each call site instead of querying per-row.

Add `PersonalConstraintOverride` to this file's `from app.db.models import (...)`
block.

- [ ] **Step 4: Implement the timeline side**

In `backend/app/services/duty_history.py`, add `PersonalConstraintOverride` to the
`from app.db.models import (...)` block, then add a new block right after the
existing `# --- PersonalConstraint events ---` block (after its closing
`events.append(...)`, before the final `# Sort:` comment):

```python
    # --- PersonalConstraintOverride events ---
    overrides = list(
        session.execute(
            select(PersonalConstraintOverride).where(PersonalConstraintOverride.soldier_id == soldier_id)
        ).scalars().all()
    )
    for o in overrides:
        overrider = session.get(Soldier, o.overridden_by) if o.overridden_by else None
        kind_label = "תורנות" if o.assignment_kind == "duty" else "מטווח"
        events.append(
            TimelineEvent(
                id=o.id,
                event_type="personal_constraint_override",
                date=o.overridden_at.date().isoformat(),
                end_date=None,
                title=f"אילוץ אישי נדרס בשיבוץ ל{kind_label}",
                description=o.reason if include_sensitive else None,
                status=None,
                metadata={"overridden_by_name": overrider.full_name if overrider else None} if include_sensitive else {},
                created_at=o.overridden_at.isoformat(),
            )
        )
```

- [ ] **Step 5: Frontend — constraints tab and timeline**

In `frontend/src/api/constraints.ts`, add:

```ts
export interface ConstraintOverride {
  id: string;
  overridden_by: SoldierRef | null;
  assignment_kind: "duty" | "range";
  reason: string;
  overridden_at: string;
}

export interface PersonalConstraint {
  // ...existing fields...
  overrides: ConstraintOverride[];
}
```

In `UnifiedSoldierModal.tsx`'s constraints-tab render (where the `constraints`
state array is mapped to rows — locate via the existing `constraints.map(` call),
render each constraint's `overrides` list underneath it, e.g.:

```tsx
              {c.overrides.length > 0 && (
                <ul className="mt-1 text-xs text-amber-600 dark:text-amber-400 space-y-0.5">
                  {c.overrides.map(o => (
                    <li key={o.id}>
                      נדרס ע&quot;י {o.overridden_by?.name ?? "?"} · {o.reason}
                    </li>
                  ))}
                </ul>
              )}
```

In `DutyHistoryPanel.tsx`, add a new filter entry to `EVENT_TYPE_FILTER_KEYS` and
`TYPE_COLORS`:

```ts
  { type: "personal_constraint_override", i18nKey: "duty_history.filter_constraint_overrides" },
```

```ts
  personal_constraint_override: "border-amber-400 bg-amber-50 dark:bg-amber-950",
```

Add `"personal_constraint_override"` to the `EventTypeFilter` union type at the top
of the file. Add the matching i18n key `duty_history.filter_constraint_overrides`
(Hebrew: `"עקיפת אילוץ אישי"`) to `frontend/src/i18n/he.json`, alongside the
existing `duty_history.filter_constraints` key.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_constraints.py backend/app/services/tests/test_duty_history.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/constraints.py backend/app/services/duty_history.py frontend/src/api/constraints.ts frontend/src/components/UnifiedSoldierModal.tsx frontend/src/components/DutyHistoryPanel.tsx frontend/src/i18n/he.json backend/app/services/tests/test_constraints.py backend/app/services/tests/test_duty_history.py
git commit -m "feat: surface personal-constraint overrides on constraint detail and soldier timeline"
```

---

## Final verification

After Task 12, run the full suites before considering the plan complete:

```bash
pytest -q
```

```bash
npm run lint
npm run typecheck
npm test
```

Then use the project's `merge-worktree-to-dev` skill to integrate this branch into
`dev` — do not merge directly into `master` per this repo's branch workflow.
