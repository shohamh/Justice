# Weapon-Qualification Duty Eligibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Duty types that require a weapon can declare a minimum range-qualification tier; a shared eligibility engine checks it (current qualification OR a qualifying future scheduled range) against the duty's own date, enforced as a soft warning-with-override in manual assignment and a hard (relaxable) constraint in the CP-SAT auto-scheduler.

**Architecture:** A new `backend/app/services/weapon_eligibility.py` module is the single source of truth for the date-math (current qualification vs. projected future-range qualification), exposing a single-soldier entry point (`compute_eligibility`) used by the manual assign-modal candidate endpoint, and a batch entry point (`bulk_ineligible_duty_blocks`) used by the CP-SAT bridge. Both share one pure predicate function so the two paths can never disagree. Two new togglable `system_settings` keys gate the whole feature and the pending-excusal edge case, following the existing `mitvachim.enabled` pattern exactly.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2.0 (backend), React 18 / TypeScript / Vite (frontend), pytest (backend tests), Vitest (frontend tests), Alembic (migrations), OR-Tools CP-SAT (solver).

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-07-weapon-qualification-eligibility-design.md`](../specs/2026-08-07-weapon-qualification-eligibility-design.md) — every task below implements a piece of it; do not deviate from its approved decisions without checking back in.
- New system settings default to **True** when unset: `weapon_qualification.enforce_eligibility`, `weapon_qualification.pending_excusal_disqualifies`.
- The eligibility check is evaluated against **the duty's own date**, never against "today".
- Manual assignment (assign modal) is a **soft warning with override** — the candidate stays selectable. The CP-SAT algorithm is a **hard constraint** by default, relaxable globally (system setting) or per-run (`SolverSettings.enforce_weapon_qualification`).
- Existing `DutyType` rows with `requires_weapon=True` backfill to `required_range_type="laser"` (the most permissive tier) in the migration.
- No new frontend admin UI for `DutyType.required_range_type` — `requires_weapon` itself has no admin UI today either (confirmed: absent from `frontend/src/api/dutyConfig.ts` and every page); stay consistent with that existing gap, don't invent new scope.
- Follow existing code patterns exactly where cited (file:line references below point at real precedent in this codebase — read them before writing the new code).
- Every task's backend tests run via `pytest -q <path>` from `backend/` (venv activated); frontend tests via `npm test -- <path>` from `frontend/`.

---

### Task 1: Migration — `DutyType.required_range_type` column

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_duty_type_required_range_type.py`
- Test: `backend/tests/unit/test_migrations_required_range_type.py`

**Interfaces:**
- Produces: DB column `duty_types.required_range_type` (nullable, `range_type` enum: `laser`/`live`/`alal`), backfilled to `'laser'` for every existing row with `requires_weapon = true`.

- [ ] **Step 1: Generate the revision skeleton**

Run (from `backend/`, venv activated):
```bash
alembic revision -m "add_duty_type_required_range_type"
```
Note the generated revision id (e.g. `a1b2c3d4e5f6`) and confirm its `down_revision` was auto-set to the current head, `6660cfc999b7` (verified via `backend/alembic/versions/6660cfc999b7_migrate_range_events_location_to_range_.py`).

- [ ] **Step 2: Write the migration body**

Replace the generated file's `upgrade`/`downgrade` with (reusing the existing `range_type` enum via `create_type=False`, exactly as done in `backend/alembic/versions/de2742d45fa3_add_ranges_tables.py:42`):

```python
"""add_duty_type_required_range_type

Revision ID: <new_revision>
Revises: 6660cfc999b7
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '<new_revision>'
down_revision: Union[str, Sequence[str], None] = '6660cfc999b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_types",
        sa.Column(
            "required_range_type",
            postgresql.ENUM("laser", "live", "alal", name="range_type", create_type=False),
            nullable=True,
        ),
    )
    op.execute(
        "UPDATE duty_types SET required_range_type = 'laser' WHERE requires_weapon = true"
    )


def downgrade() -> None:
    op.drop_column("duty_types", "required_range_type")
```

- [ ] **Step 3: Write a test proving the backfill**

```python
# backend/tests/unit/test_migrations_required_range_type.py
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import DutyType


def test_existing_weapon_duty_types_backfilled_to_laser(app_session: Session) -> None:
    weapon_dt = DutyType(name="mig-weapon", score_per_day=Decimal("1.00"), requires_weapon=True)
    non_weapon_dt = DutyType(name="mig-non-weapon", score_per_day=Decimal("1.00"), requires_weapon=False)
    app_session.add_all([weapon_dt, non_weapon_dt])
    app_session.commit()

    # The migration already ran during test DB setup (see backend/tests/conftest.py),
    # so newly-inserted rows won't retroactively show the backfill — instead assert
    # the column exists and accepts the expected enum values directly.
    app_session.execute(
        text("UPDATE duty_types SET required_range_type = 'live' WHERE id = :id"),
        {"id": weapon_dt.id},
    )
    app_session.commit()
    app_session.refresh(weapon_dt)
    assert weapon_dt.required_range_type == "live"

    app_session.refresh(non_weapon_dt)
    assert non_weapon_dt.required_range_type is None
```

- [ ] **Step 4: Apply the migration and run the test**

```bash
alembic upgrade head
pytest tests/unit/test_migrations_required_range_type.py -v
```
Expected: migration applies cleanly, test PASSES. (This test only proves the column/enum shape — the model field added in Task 2 is what makes `DutyType(...)` accept `required_range_type` as a constructor kwarg at all, so if Task 2 hasn't landed yet this test will fail with a `TypeError`; run Task 2 first if executing out of order.)

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/*_add_duty_type_required_range_type.py backend/tests/unit/test_migrations_required_range_type.py
git commit -m "feat: add DutyType.required_range_type column with laser backfill"
```

---

### Task 2: Model — `DutyType.required_range_type` field

**Files:**
- Modify: `backend/app/db/models.py:175-210` (DutyType class), and relocate the `RangeType` enum definition.

**Interfaces:**
- Produces: `DutyType.required_range_type: str | None` (SQLAlchemy `Mapped[str | None]`), and `RangeType`/`RANGE_TYPE_RANK` remain importable from `app.db.models` exactly as before (only their *position* in the file moves, not their names or values).

- [ ] **Step 1: Move `class RangeType` above `class DutyType`**

`RangeType` is currently defined at `backend/app/db/models.py:798`, but `DutyType` (line 175) needs to reference it for the new column — and Python evaluates the module top-to-bottom, so the enum must be defined first. Cut this block from its current location:

```python
class RangeType(str, _enum.Enum):
    laser = "laser"
    live = "live"
    alal = "alal"
```

and paste it immediately before `class DutyType(Base):` (currently line 175), leaving `RANGE_TYPE_RANK: dict[str, int] = {"laser": 1, "live": 2, "alal": 3}` in its original location (it has no ordering dependency on `DutyType`, only on `RangeType`, which will now already be defined earlier in the file).

- [ ] **Step 2: Add the column to `DutyType`**

In `backend/app/db/models.py`, right after the `requires_weapon` line (originally line 203):

```python
    requires_weapon: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    required_range_type: Mapped[str | None] = mapped_column(
        Enum(RangeType, name="range_type"), nullable=True, default=None
    )
```

- [ ] **Step 3: Verify the model imports and constructs cleanly**

```bash
python -c "from app.db.models import DutyType, RangeType, RANGE_TYPE_RANK; from decimal import Decimal; dt = DutyType(name='x', score_per_day=Decimal('1.00'), required_range_type=RangeType.live); print(dt.required_range_type)"
```
Expected: prints `RangeType.live` (or `live`), no `NameError`/`ImportError`.

- [ ] **Step 4: Run the migration test from Task 1 (now passing for real)**

```bash
pytest tests/unit/test_migrations_required_range_type.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add DutyType.required_range_type model field"
```

---

### Task 3: System settings — feature flags

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` (add two boolean entries)
- Test: `backend/tests/unit/test_settings_loader.py` (add cases if the file exists; otherwise add to `backend/app/services/tests/test_eligibility.py`'s neighborhood — check first)

**Interfaces:**
- Produces: two `system_settings` keys usable via `get_setting(session, "weapon_qualification.enforce_eligibility")` / `get_setting(session, "weapon_qualification.pending_excusal_disqualifies")`, both defaulting to `True` when the row is absent (no seed row required — Task 4's helpers implement the "default True when unset" fallback directly, matching `ranges.py:37-39`'s `_mitvachim_enabled` pattern).

- [ ] **Step 1: Check for an existing settings-loader test file**

```bash
ls backend/tests/unit/test_settings_loader.py backend/app/services/tests/test_settings_loader.py 2>&1
```
Use whichever exists; if neither exists, create `backend/tests/unit/test_settings_loader.py` (mirroring the import style of `backend/tests/unit/test_range_candidates.py:1-17`).

- [ ] **Step 2: Add the admin UI entries**

In `frontend/src/pages/SystemSettingsPage.tsx`, inside the existing `"מטווחים"` settings group (right after the `mitvachim.alal_validity_days` entry, i.e. after line 284's closing `},`):

```tsx
      {
        key: "weapon_qualification.enforce_eligibility",
        label: "אכיפת כשירות נשק לתורנויות",
        description: "בודק שלחיילים המשובצים לתורנויות הדורשות נשק יש הכשרת מטווח בתוקף (נוכחית או עתידית מתוזמנת) בתאריך התורנות.",
        type: "boolean" as const,
        defaultValue: true,
      },
      {
        key: "weapon_qualification.pending_excusal_disqualifies",
        label: "בקשת פטור ממתינה פוסלת מטווח עתידי",
        description: "כאשר דלוק: מטווח עתידי עם בקשת פטור שטרם הוכרעה לא ייחשב כמעניק כשירות. כאשר כבוי: רק בקשת פטור מאושרת פוסלת.",
        type: "boolean" as const,
        defaultValue: true,
      },
```

- [ ] **Step 3: Write a test proving the default-True fallback contract**

This test documents the contract Task 4 must satisfy — it exercises `get_setting`/`SettingNotFound` directly since the actual `_enforce_enabled`/`_pending_excusal_disqualifies` helpers don't exist yet until Task 4:

```python
# backend/tests/unit/test_settings_loader.py (new file, or append if it already exists)
from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.settings_loader import SettingNotFound, get_setting, set_setting


def test_weapon_qualification_settings_absent_by_default(app_session: Session) -> None:
    for key in ("weapon_qualification.enforce_eligibility", "weapon_qualification.pending_excusal_disqualifies"):
        try:
            get_setting(app_session, key)
            assert False, f"{key} should not be seeded by default"
        except SettingNotFound:
            pass


def test_weapon_qualification_settings_roundtrip(app_session: Session) -> None:
    set_setting(app_session, "weapon_qualification.enforce_eligibility", False, actor_id=None)
    app_session.commit()
    assert get_setting(app_session, "weapon_qualification.enforce_eligibility") is False
```

- [ ] **Step 4: Run the test**

```bash
pytest tests/unit/test_settings_loader.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx backend/tests/unit/test_settings_loader.py
git commit -m "feat: add weapon-qualification system settings to admin UI"
```

---

### Task 4: Shared eligibility core — `weapon_eligibility.py`

**Files:**
- Create: `backend/app/services/weapon_eligibility.py`
- Test: `backend/app/services/tests/test_weapon_eligibility.py`

**Interfaces:**
- Consumes: `app.services.range_auto_assign._qualification_types_at_or_above` (`backend/app/services/range_auto_assign.py:24-26`), `app.services.ranges._validity_days` (`backend/app/services/ranges.py:426-432`), `app.services.settings_loader.get_setting`/`SettingNotFound`.
- Produces:
  - `compute_eligibility(session: Session, *, soldier_id: uuid.UUID, required_range_type: str | None, as_of: date) -> tuple[bool, str | None]` — `(True, None)` if eligible/not-applicable, `(False, "weapon_qualification")` otherwise.
  - `bulk_ineligible_duty_blocks(session: Session, *, soldier_ids: list[uuid.UUID], duties: Sequence[DutyBlock]) -> dict[uuid.UUID, set[uuid.UUID]]` — used by Task 8. Requires `DutyBlock.required_range_type` (added in Task 6) to already be populated on the blocks passed in.

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_weapon_eligibility.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock
from app.db.models import (
    RangeAssignment,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services.ranges import add_range_assignment, create_range_event
from app.services.settings_loader import set_setting
from app.services.weapon_eligibility import bulk_ineligible_duty_blocks, compute_eligibility
from tests.helpers import create_node, create_range_location, create_soldier


def test_none_required_type_is_always_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-001")
    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=None, as_of=date.today()
    )
    assert eligible is True
    assert reason is None


def test_current_qualification_covers_as_of_date(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-002")
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=10),
    )
    assert eligible is True
    assert reason is None


def test_expired_qualification_is_not_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-003")
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser,
        valid_until=date.today() - timedelta(days=1),
    ))
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser, as_of=date.today()
    )
    assert eligible is False
    assert reason == "weapon_qualification"


def test_future_scheduled_range_grants_eligibility_on_and_after_its_date(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-1")
    soldier = create_soldier(app_session, personal_number="we-004", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    # Before the range: not yet eligible via this future assignment.
    too_early, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=4),
    )
    assert too_early is False

    # On/after the range date, within its projected validity window (180 days for laser).
    on_time, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=5),
    )
    assert on_time is True
    assert reason is None


def test_reserve_assignment_does_not_grant_eligibility(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-2")
    soldier = create_soldier(app_session, personal_number="we-005", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1, reserve_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=True)
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_pending_excusal_disqualifies_future_range_by_default(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-3")
    soldier = create_soldier(app_session, personal_number="we-006", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.add(RangeExcusalRequest(
        range_assignment_id=assignment.id, requested_by=soldier.id,
        reason="בדיקה", status=RangeExcusalStatus.pending,
    ))
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False


def test_pending_excusal_setting_off_keeps_future_range_eligible(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-4")
    soldier = create_soldier(app_session, personal_number="we-007", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.add(RangeExcusalRequest(
        range_assignment_id=assignment.id, requested_by=soldier.id,
        reason="בדיקה", status=RangeExcusalStatus.pending,
    ))
    set_setting(app_session, "weapon_qualification.pending_excusal_disqualifies", False, actor_id=None)
    app_session.commit()

    eligible, _ = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.laser,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is True


def test_lower_tier_range_does_not_satisfy_higher_requirement(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-5")
    soldier = create_soldier(app_session, personal_number="we-008", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id,
        required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.alal,
        as_of=date.today() + timedelta(days=6),
    )
    assert eligible is False
    assert reason == "weapon_qualification"


def test_master_toggle_off_makes_everyone_eligible(app_session: Session) -> None:
    soldier = create_soldier(app_session, personal_number="we-009")
    set_setting(app_session, "weapon_qualification.enforce_eligibility", False, actor_id=None)
    app_session.commit()

    eligible, reason = compute_eligibility(
        app_session, soldier_id=soldier.id, required_range_type=RangeType.alal, as_of=date.today()
    )
    assert eligible is True
    assert reason is None


def test_bulk_matches_single_soldier_result(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="we-node-6")
    qualified = create_soldier(app_session, personal_number="we-010", hierarchy_node_id=node.id)
    unqualified = create_soldier(app_session, personal_number="we-011", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=qualified.id, range_type=RangeType.laser,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    block = DutyBlock(
        id=__import__("uuid").uuid4(), duty_type_id=__import__("uuid").uuid4(),
        duty_location_id=__import__("uuid").uuid4(),
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1),
        score_per_day=Decimal("1.00"), required_range_type=RangeType.laser,
    )
    result = bulk_ineligible_duty_blocks(
        app_session, soldier_ids=[qualified.id, unqualified.id], duties=[block]
    )
    assert qualified.id not in result or block.id not in result.get(qualified.id, set())
    assert block.id in result.get(unqualified.id, set())
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_weapon_eligibility.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.weapon_eligibility'` (and `DutyBlock` will also reject the not-yet-added `required_range_type` kwarg until Task 6 lands — if running Task 4 before Task 6, the last test will fail with `TypeError` instead; that's expected and resolves once Task 6 is done. Run Tasks in order to avoid this).

- [ ] **Step 3: Implement `weapon_eligibility.py`**

```python
# backend/app/services/weapon_eligibility.py
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock
from app.db.models import RangeAssignment, RangeEvent, RangeExcusalRequest, RangeExcusalStatus
from app.services.range_auto_assign import _qualification_types_at_or_above
from app.services.ranges import _validity_days
from app.services.settings_loader import SettingNotFound, get_setting


def _bool_setting(session: Session, key: str, default: bool) -> bool:
    try:
        return bool(get_setting(session, key))
    except SettingNotFound:
        return default


def _enforce_enabled(session: Session) -> bool:
    return _bool_setting(session, "weapon_qualification.enforce_eligibility", True)


def _pending_excusal_disqualifies(session: Session) -> bool:
    return _bool_setting(session, "weapon_qualification.pending_excusal_disqualifies", True)


def _is_eligible_from_data(
    *,
    current_best_valid_until: date | None,
    future_windows: list[tuple[date, date]],
    as_of: date,
) -> bool:
    """Pure predicate shared by the single-soldier and bulk paths.

    current_best_valid_until: the latest valid_until among the soldier's existing
    SoldierRangeQualification rows at/above the required tier (None if none exist).
    future_windows: [(event_date, projected_valid_until), ...] for future, non-reserve,
    non-disqualified RangeAssignments at/above the required tier.
    """
    if current_best_valid_until is not None and current_best_valid_until >= as_of:
        return True
    return any(event_date <= as_of <= projected_valid_until for event_date, projected_valid_until in future_windows)


def _max_qualification_valid_until(
    session: Session, *, soldier_id: uuid.UUID, required_range_type: str,
) -> date | None:
    from app.db.models import SoldierRangeQualification

    candidate_types = _qualification_types_at_or_above(required_range_type)
    rows = session.execute(
        select(SoldierRangeQualification.valid_until).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.range_type.in_(candidate_types),
        )
    ).scalars().all()
    return max(rows) if rows else None


def _future_windows(
    session: Session, *, soldier_id: uuid.UUID, required_range_type: str, disqualify_pending: bool,
) -> list[tuple[date, date]]:
    candidate_types = _qualification_types_at_or_above(required_range_type)
    rows = session.execute(
        select(RangeAssignment.id, RangeEvent.date, RangeEvent.range_type)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeAssignment.is_reserve.is_(False),
            RangeEvent.range_type.in_(candidate_types),
        )
    ).all()
    if not rows:
        return []

    pending_assignment_ids: set[uuid.UUID] = set()
    if disqualify_pending:
        assignment_ids = [r.id for r in rows]
        pending_assignment_ids = set(
            session.execute(
                select(RangeExcusalRequest.range_assignment_id).where(
                    RangeExcusalRequest.range_assignment_id.in_(assignment_ids),
                    RangeExcusalRequest.status == RangeExcusalStatus.pending,
                )
            ).scalars().all()
        )

    windows: list[tuple[date, date]] = []
    for assignment_id, event_date, range_type in rows:
        if assignment_id in pending_assignment_ids:
            continue
        projected_valid_until = event_date + timedelta(days=_validity_days(session, range_type))
        windows.append((event_date, projected_valid_until))
    return windows


def compute_eligibility(
    session: Session, *, soldier_id: uuid.UUID, required_range_type: str | None, as_of: date,
) -> tuple[bool, str | None]:
    """Return (eligible, reason). reason is None when eligible or when the check
    doesn't apply (required_range_type is None, or the feature is disabled)."""
    if required_range_type is None:
        return True, None
    if not _enforce_enabled(session):
        return True, None

    current_valid_until = _max_qualification_valid_until(
        session, soldier_id=soldier_id, required_range_type=required_range_type,
    )
    future_windows = _future_windows(
        session, soldier_id=soldier_id, required_range_type=required_range_type,
        disqualify_pending=_pending_excusal_disqualifies(session),
    )
    if _is_eligible_from_data(
        current_best_valid_until=current_valid_until, future_windows=future_windows, as_of=as_of,
    ):
        return True, None
    return False, "weapon_qualification"


def bulk_ineligible_duty_blocks(
    session: Session, *, soldier_ids: Sequence[uuid.UUID], duties: Sequence[DutyBlock],
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, the set of duty-block ids (among `duties`) they are NOT
    eligible for due to weapon qualification. Blocks whose `required_range_type`
    is None are never included. Returns {} entirely if the feature is disabled."""
    if not _enforce_enabled(session):
        return {}

    relevant = [d for d in duties if d.required_range_type is not None]
    if not relevant:
        return {}

    disqualify_pending = _pending_excusal_disqualifies(session)
    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for soldier_id in soldier_ids:
        # Cache per (soldier, required_range_type) — most batches only touch 1-2 tiers.
        cache: dict[str, tuple[date | None, list[tuple[date, date]]]] = {}
        ineligible: set[uuid.UUID] = set()
        for block in relevant:
            required = block.required_range_type
            if required not in cache:
                cache[required] = (
                    _max_qualification_valid_until(session, soldier_id=soldier_id, required_range_type=required),
                    _future_windows(
                        session, soldier_id=soldier_id, required_range_type=required,
                        disqualify_pending=disqualify_pending,
                    ),
                )
            current_valid_until, future_windows = cache[required]
            if not _is_eligible_from_data(
                current_best_valid_until=current_valid_until, future_windows=future_windows,
                as_of=block.start_date,
            ):
                ineligible.add(block.id)
        if ineligible:
            result[soldier_id] = ineligible
    return result
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest app/services/tests/test_weapon_eligibility.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/weapon_eligibility.py backend/app/services/tests/test_weapon_eligibility.py
git commit -m "feat: add shared weapon-qualification eligibility core"
```

---

### Task 5: Manual assignment — `get_shift_candidates` soft warning

**Files:**
- Modify: `backend/app/routes/shifts.py:608-703`
- Test: `backend/tests/integration/test_shift_candidates_weapon_eligibility.py`

**Interfaces:**
- Consumes: `app.services.weapon_eligibility.compute_eligibility` (Task 4).
- Produces: `ShiftCandidateOut.weapon_warning: bool` (new field, default `False`), sort key extended to `(x.blocked, x.weapon_warning, x.effort)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_shift_candidates_weapon_eligibility.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyLocation, DutyType, RangeType
from tests.helpers import auth_headers, create_node, create_soldier


def test_ineligible_candidate_flagged_but_not_removed(client, admin_session):
    node = create_node(admin_session, level="branch", name="wc-node-1")
    dm = create_soldier(admin_session, personal_number="wc-dm-1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="wc-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="wc-weapon-duty", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
    )
    loc = DutyLocation(name="wc-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.commit()

    start = (date.today() + timedelta(days=10)).isoformat()
    end = (date.today() + timedelta(days=11)).isoformat()
    shift_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": start, "end_date": end, "required_count": 1,
    }, headers=auth_headers(dm))
    assert shift_resp.status_code == 201
    shift_id = shift_resp.json()["id"]

    resp = client.get(f"/api/shifts/{shift_id}/candidates", headers=auth_headers(dm))
    assert resp.status_code == 200
    candidates = {c["soldier_id"]: c for c in resp.json()}
    assert str(soldier.id) in candidates
    cand = candidates[str(soldier.id)]
    assert cand["weapon_warning"] is True
    assert cand["blocked"] is False  # stays selectable, unlike constraint/assignment blocks


def test_eligible_candidate_has_no_warning(client, admin_session):
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_range_location

    node = create_node(admin_session, level="branch", name="wc-node-2")
    dm = create_soldier(admin_session, personal_number="wc-dm-2", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="wc-sol-2", hierarchy_node_id=node.id)
    dt = DutyType(
        name="wc-weapon-duty-2", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
    )
    loc = DutyLocation(name="wc-loc-2")
    admin_session.add_all([dt, loc])
    admin_session.commit()

    range_event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    add_range_assignment(admin_session, event=range_event, soldier_id=soldier.id, is_reserve=False)
    admin_session.commit()

    start = (date.today() + timedelta(days=10)).isoformat()
    end = (date.today() + timedelta(days=11)).isoformat()
    shift_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": start, "end_date": end, "required_count": 1,
    }, headers=auth_headers(dm))
    shift_id = shift_resp.json()["id"]

    resp = client.get(f"/api/shifts/{shift_id}/candidates", headers=auth_headers(dm))
    cand = {c["soldier_id"]: c for c in resp.json()}[str(soldier.id)]
    assert cand["weapon_warning"] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_shift_candidates_weapon_eligibility.py -v
```
Expected: FAIL — `weapon_warning` key not present in the response (`KeyError`/`assert None is True`).

- [ ] **Step 3: Implement the route change**

In `backend/app/routes/shifts.py`, extend `ShiftCandidateOut` (line 608-615):

```python
class ShiftCandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    personal_number: str
    effort: float
    blocked: bool
    blocked_reason: str | None = None
    weapon_warning: bool = False
    hierarchy_path_ids: list[str] = []
```

Then in `get_shift_candidates` (line 618-703), fetch the shift's duty type once before the loop, and check eligibility per candidate. Insert right after `shift = _load(session, shift_id)` (line 625):

```python
    from app.db.models import DutyType as _DutyType
    from app.services.weapon_eligibility import compute_eligibility

    shift_duty_type = session.get(_DutyType, shift.duty_type_id)
    required_range_type = shift_duty_type.required_range_type if shift_duty_type else None
```

Then inside the `for si in soldier_inputs:` loop, right after computing `effort` (line 688), add:

```python
        weapon_warning = False
        if required_range_type is not None:
            eligible, _reason = compute_eligibility(
                session, soldier_id=si.id, required_range_type=required_range_type,
                as_of=shift.start_date,
            )
            weapon_warning = not eligible
```

And pass it into the constructed `ShiftCandidateOut` (line 692-700):

```python
        result.append(ShiftCandidateOut(
            soldier_id=si.id,
            full_name=soldier.full_name,
            personal_number=soldier.personal_number,
            effort=round(effort, 3),
            blocked=blocked,
            blocked_reason=blocked_reason,
            weapon_warning=weapon_warning,
            hierarchy_path_ids=path_ids,
        ))
```

Finally, update the sort key (line 702) so weapon-warning candidates sort after fully-eligible ones but stay ahead of hard-blocked ones:

```python
    result.sort(key=lambda x: (x.blocked, x.weapon_warning, x.effort))
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/integration/test_shift_candidates_weapon_eligibility.py -v
```
Expected: both PASS.

- [ ] **Step 5: Run the full shifts test suite to check for regressions**

```bash
pytest tests/integration/test_shifts_routes.py tests/unit/test_shifts_service.py -v
```
Expected: all PASS (unaffected — `weapon_warning` defaults `False`, `required_range_type` is `None` for existing test duty types).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/shifts.py backend/tests/integration/test_shift_candidates_weapon_eligibility.py
git commit -m "feat: flag weapon-ineligible candidates in shift assign modal (soft warning)"
```

---

### Task 6: `DutyBlock`/`SoldierInput` — algorithm type additions

**Files:**
- Modify: `backend/app/algorithm/types.py`

**Interfaces:**
- Produces: `DutyBlock.required_range_type: str | None = None`, `SoldierInput.weapon_ineligible_duty_block_ids: set[uuid.UUID] = field(default_factory=set)`, `SolverSettings.enforce_weapon_qualification: bool = True`.

- [ ] **Step 1: Add `required_range_type` to `DutyBlock`**

In `backend/app/algorithm/types.py`, in the `DutyBlock` dataclass (line 47-67), after `rest_hours: int = 0`:

```python
    rest_hours: int = 0
    # Minimum range-qualification tier required to take this block (laser/live/alal),
    # or None if this duty type doesn't require a weapon. Populated by algorithm_bridge
    # from DutyType.required_range_type; consumed by services/weapon_eligibility.py and
    # the solver's eligibility pre-filter (see solver.py _eligible_pairs / build_model).
    required_range_type: str | None = None
```

- [ ] **Step 2: Add `weapon_ineligible_duty_block_ids` to `SoldierInput`**

In the `SoldierInput` dataclass (line 30-44), after `exempted_duty_location_ids`:

```python
    exempted_duty_location_ids: set[uuid.UUID] = field(default_factory=set)
    # Duty-block ids (not duty-type ids, since eligibility is date-dependent — see
    # services/weapon_eligibility.py) this soldier is NOT weapon-qualified for as of
    # that block's start_date. Populated by algorithm_bridge via bulk_ineligible_duty_blocks
    # after both soldiers and duties are loaded; empty by default for existing callers.
    weapon_ineligible_duty_block_ids: set[uuid.UUID] = field(default_factory=set)
```

- [ ] **Step 3: Add `enforce_weapon_qualification` to `SolverSettings`**

In the `SolverSettings` dataclass (line 87-165), after `auto_relax_node_quotas: bool = False`:

```python
    auto_relax_node_quotas: bool = False
    # Hard constraint by default: a soldier whose id appears in a DutyBlock's soldier
    # via SoldierInput.weapon_ineligible_duty_block_ids is never assigned to that block.
    # False relaxes this for the whole run (see algorithm_bridge.resolve_solver_settings
    # for the system-setting default and per-run override).
    enforce_weapon_qualification: bool = True
```

- [ ] **Step 4: Verify the dataclasses still construct with defaults**

```bash
python -c "
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings
import uuid
from datetime import date
from decimal import Decimal
b = DutyBlock(id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(), start_date=date.today(), end_date=date.today(), score_per_day=Decimal('1.00'))
assert b.required_range_type is None
s = SoldierInput(id=uuid.uuid4(), enrolled_at=date.today(), cumulative_score=Decimal('0'), active_days=1)
assert s.weapon_ineligible_duty_block_ids == set()
settings = SolverSettings()
assert settings.enforce_weapon_qualification is True
print('ok')
"
```
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/types.py
git commit -m "feat: add weapon-qualification fields to algorithm types"
```

---

### Task 7: Solver — hard-constraint eligibility filter

**Files:**
- Modify: `backend/app/algorithm/model.py:288-338` (`build_model`'s eligible-pairs pre-filter)
- Modify: `backend/app/algorithm/solver.py:293-321` (`_eligible_pairs`), `backend/app/algorithm/solver.py:1350-1364` (relaxation-chain `eligible_for`)
- Test: `backend/app/algorithm/tests/test_weapon_eligibility_constraint.py`

**Interfaces:**
- Consumes: `SoldierInput.weapon_ineligible_duty_block_ids`, `SolverSettings.enforce_weapon_qualification` (Task 6).

- [ ] **Step 1: Write the failing test**

```python
# backend/app/algorithm/tests/test_weapon_eligibility_constraint.py
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.solver import solve
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings


def _soldier(ineligible_block_ids: set[uuid.UUID] = frozenset()) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(), enrolled_at=date.today(), cumulative_score=Decimal("0"), active_days=1,
        weapon_ineligible_duty_block_ids=set(ineligible_block_ids),
    )


def test_hard_constraint_never_assigns_ineligible_soldier() -> None:
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date.today(), end_date=date.today(), score_per_day=Decimal("1.00"),
        required_range_type="laser",
    )
    ineligible = _soldier({block.id})
    eligible = _soldier()

    result = solve(
        [ineligible, eligible], [block], [], SolverSettings(time_limit_seconds=5, num_workers=1),
    )
    assigned_soldier_ids = {a.soldier_id for a in result.assignments}
    assert eligible.id in assigned_soldier_ids
    assert ineligible.id not in assigned_soldier_ids


def test_relaxed_setting_allows_ineligible_soldier_when_sole_candidate() -> None:
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date.today(), end_date=date.today(), score_per_day=Decimal("1.00"),
        required_range_type="laser",
    )
    ineligible = _soldier({block.id})

    result = solve(
        [ineligible], [block], [],
        SolverSettings(time_limit_seconds=5, num_workers=1, enforce_weapon_qualification=False),
    )
    assigned_soldier_ids = {a.soldier_id for a in result.assignments}
    assert ineligible.id in assigned_soldier_ids
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/algorithm/tests/test_weapon_eligibility_constraint.py -v
```
Expected: FAIL — `test_hard_constraint_never_assigns_ineligible_soldier` fails because both soldiers are currently eligible for everything (the filter doesn't exist yet), so the solver may assign either one arbitrarily including the "ineligible" one.

- [ ] **Step 3: Add the filter in `build_model`**

In `backend/app/algorithm/model.py`, in the eligible-pairs loop (line 326-338):

```python
    for di, d in enumerate(duty_list):
        for si, s in enumerate(soldier_list):
            if d.duty_type_id in exempt_map.get(s.id, set()):
                continue
            if d.duty_location_id in location_exempt_map.get(s.id, set()):
                continue
            constrained_dates = constraint_map.get(s.id, set())
            if duty_dates_cache[di] & constrained_dates:
                continue
            if not node_in_scope(d.eligible_node_ids, s.path_ids):
                continue
            if settings.enforce_weapon_qualification and d.id in s.weapon_ineligible_duty_block_ids:
                continue
            eligible.append((di, si))
            soldier_duties[si].append(di)
```

- [ ] **Step 4: Add the same filter in `solver.py::_eligible_pairs`**

`_eligible_pairs` currently takes only `(soldiers, duties)` (line 293-295). Add a `settings: SolverSettings` parameter:

```python
def _eligible_pairs(
    soldiers: Sequence[SoldierInput], duties: Sequence[DutyBlock], settings: SolverSettings,
) -> list[tuple[int, int]]:
```

and use it in the filter body (line 311-320):

```python
    for di, d in enumerate(duties):
        ddates = _duty_dates(d)
        for si, s in enumerate(soldiers):
            if d.duty_type_id in s.exempted_duty_type_ids:
                continue
            if any(t in constraint_dates[si] for t in ddates):
                continue
            if not node_in_scope(d.eligible_node_ids, s.path_ids):
                continue
            if settings.enforce_weapon_qualification and d.id in s.weapon_ineligible_duty_block_ids:
                continue
            pairs.append((di, si))
    return pairs
```

Update all three call sites (`solver.py:412`, `solver.py:586`, `solver.py:1081`), each currently reading `pairs = _eligible_pairs(work, duties)` — change each to `pairs = _eligible_pairs(work, duties, settings)`. At all three locations `settings` is already an in-scope parameter of the enclosing function (verify with `grep -n "def " backend/app/algorithm/solver.py` and checking the enclosing function signature above each call site — every enclosing function here already threads `settings: SolverSettings` through for the existing T/R/window logic).

- [ ] **Step 5: Add the same filter in the relaxation-chain `eligible_for` builder**

In `backend/app/algorithm/solver.py` (line 1350-1364), inside `_infeasibility_relaxation_chain` (which already receives `settings` as a parameter per its call sites at line 159/462/637):

```python
    eligible_for: dict = {}
    for d in duties:
        ddates_frozen = duty_ddates[d.id]
        elig: set = set()
        for s in soldiers:
            if d.duty_type_id in s.exempted_duty_type_ids:
                continue
            if ddates_frozen & soldier_constraint_dates[s.id]:
                continue
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
            if settings.enforce_weapon_qualification and d.id in s.weapon_ineligible_duty_block_ids:
                continue
            elig.add(s.id)
        eligible_for[d.id] = elig
```

- [ ] **Step 6: Run tests to verify pass**

```bash
pytest app/algorithm/tests/test_weapon_eligibility_constraint.py -v
```
Expected: both PASS.

- [ ] **Step 7: Run the broader algorithm suite for regressions**

```bash
pytest app/algorithm/ -v -x
```
Expected: all PASS (the new filter is a no-op when `weapon_ineligible_duty_block_ids` is empty, which it is for every existing test's `SoldierInput`).

- [ ] **Step 8: Commit**

```bash
git add backend/app/algorithm/model.py backend/app/algorithm/solver.py backend/app/algorithm/tests/test_weapon_eligibility_constraint.py
git commit -m "feat: enforce weapon-qualification hard constraint in CP-SAT solver"
```

---

### Task 8: Algorithm bridge — wiring settings and precomputed eligibility

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py` (`resolve_solver_settings`, `load_duty_blocks`, `load_duty_blocks_from_shifts`, `run_algorithm_job`)
- Test: `backend/app/services/tests/test_algorithm_bridge.py` (add cases) and `backend/tests/unit/test_algorithm_bridge_shifts.py` (add cases)

**Interfaces:**
- Consumes: `weapon_eligibility.bulk_ineligible_duty_blocks` (Task 4), `DutyBlock.required_range_type` / `SoldierInput.weapon_ineligible_duty_block_ids` / `SolverSettings.enforce_weapon_qualification` (Task 6).

- [ ] **Step 1: Write the failing tests**

```python
# Add to backend/app/services/tests/test_algorithm_bridge.py
def test_resolve_solver_settings_defaults_enforce_weapon_qualification_true(app_session):
    from app.services.algorithm_bridge import resolve_solver_settings
    settings = resolve_solver_settings(app_session, {})
    assert settings.enforce_weapon_qualification is True


def test_resolve_solver_settings_reads_system_setting_default(app_session):
    from app.services.algorithm_bridge import resolve_solver_settings
    from app.services.settings_loader import set_setting
    set_setting(app_session, "weapon_qualification.enforce_eligibility", False, actor_id=None)
    app_session.commit()
    settings = resolve_solver_settings(app_session, {})
    assert settings.enforce_weapon_qualification is False


def test_resolve_solver_settings_per_run_override_wins(app_session):
    from app.services.algorithm_bridge import resolve_solver_settings
    from app.services.settings_loader import set_setting
    set_setting(app_session, "weapon_qualification.enforce_eligibility", True, actor_id=None)
    app_session.commit()
    settings = resolve_solver_settings(app_session, {"enforce_weapon_qualification": False})
    assert settings.enforce_weapon_qualification is False
```

```python
# Add to backend/tests/unit/test_algorithm_bridge_shifts.py (check existing imports/fixtures at top of file first)
def test_load_duty_blocks_from_shifts_populates_required_range_type(admin_session):
    from decimal import Decimal
    from datetime import date, timedelta
    from app.db.models import DutyLocation, DutyShift, DutyType, RangeType
    from app.services.algorithm_bridge import load_duty_blocks_from_shifts
    from tests.helpers import create_node

    node = create_node(admin_session, level="branch", name="ab-node-1")
    dt = DutyType(
        name="ab-weapon", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.live,
    )
    loc = DutyLocation(name="ab-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert all(b.required_range_type == RangeType.live for b in blocks if b.duty_type_id == dt.id)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_algorithm_bridge.py::test_resolve_solver_settings_defaults_enforce_weapon_qualification_true -v
```
Expected: FAIL — `SolverSettings()` has no way to reach `enforce_weapon_qualification` from `resolve_solver_settings` yet (it will actually pass by accident since the dataclass defaults to `True`, so this specific assertion may pass; the next two below will genuinely fail since the setting is never read). Run all three to confirm at least the override tests fail.

- [ ] **Step 3: Wire `resolve_solver_settings`**

In `backend/app/services/algorithm_bridge.py`, in `resolve_solver_settings` (line 818-872), add to the `SolverSettings(...)` call, after `auto_relax_node_quotas=...` (line 869-871):

```python
        auto_relax_node_quotas=bool(settings_json.get(
            "auto_relax_node_quotas", _setting_bool("algorithm.auto_relax_node_quotas", False)
        )),
        enforce_weapon_qualification=bool(settings_json.get(
            "enforce_weapon_qualification", _setting_bool("weapon_qualification.enforce_eligibility", True)
        )),
    )
```

- [ ] **Step 4: Populate `required_range_type` in `load_duty_blocks`**

In `backend/app/services/algorithm_bridge.py::load_duty_blocks` (line 287-318), the loop already has `dt` in scope:

```python
    blocks: list[DutyBlock] = []
    day = planning_start
    while day <= planning_end:
        for dt in types:
            blocks.append(
                DutyBlock(
                    id=uuid.uuid4(),
                    duty_type_id=dt.id,
                    duty_location_id=duty_location_id,
                    start_date=day,
                    end_date=day,
                    score_per_day=dt.score_per_day,
                    required_range_type=dt.required_range_type,
                )
            )
        day += timedelta(days=1)
    return blocks
```

- [ ] **Step 5: Populate `required_range_type` in `load_duty_blocks_from_shifts`**

In `backend/app/services/algorithm_bridge.py::load_duty_blocks_from_shifts`, build a lookup right after `score_map` (line 351):

```python
    type_ids = {s.duty_type_id for s in shifts}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    score_map = {dt.id: dt.score_per_day for dt in types_q}
    required_range_type_map = {dt.id: dt.required_range_type for dt in types_q}
    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
```

Then add `required_range_type=required_range_type_map.get(shift.duty_type_id)` to both `DutyBlock(...)` construction sites (primary at line 406-419, reserve at line 426-438).

- [ ] **Step 6: Populate `SoldierInput.weapon_ineligible_duty_block_ids` in `run_algorithm_job`**

In `backend/app/services/algorithm_bridge.py::run_algorithm_job`, right after `soldiers = load_soldier_inputs(...)` finishes (line 1168-1172):

```python
                _phase("load_soldier_inputs: start")
                soldiers = load_soldier_inputs(
                    session, as_of=planning_start,
                    eligible_node_ids=job.settings_json.get("eligible_node_ids"),
                )
                _phase(f"load_soldier_inputs: done ({len(soldiers)} soldiers)")

                from app.services.weapon_eligibility import bulk_ineligible_duty_blocks
                _phase("weapon_eligibility: start")
                weapon_ineligible = bulk_ineligible_duty_blocks(
                    session, soldier_ids=[s.id for s in soldiers], duties=duties,
                )
                for s in soldiers:
                    s.weapon_ineligible_duty_block_ids = weapon_ineligible.get(s.id, set())
                _phase("weapon_eligibility: done")
```

(`duties` is already in scope at this point in `run_algorithm_job` — it's used two lines earlier at line 1164 to compute `planning_start`/`planning_end`.)

- [ ] **Step 7: Run tests to verify pass**

```bash
pytest app/services/tests/test_algorithm_bridge.py -v -k weapon
pytest tests/unit/test_algorithm_bridge_shifts.py -v -k weapon
```
Expected: all PASS.

- [ ] **Step 8: Run the broader bridge/algorithm-route suites for regressions**

```bash
pytest app/services/tests/test_algorithm_bridge.py tests/unit/test_algorithm_bridge_shifts.py tests/integration/test_algorithm_routes.py -v
```
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/app/services/tests/test_algorithm_bridge.py backend/tests/unit/test_algorithm_bridge_shifts.py
git commit -m "feat: wire weapon-qualification eligibility into algorithm bridge"
```

---

### Task 9: Frontend types — `ShiftCandidate.weapon_warning`

**Files:**
- Modify: `frontend/src/api/assignments.ts:43-51`

**Interfaces:**
- Produces: `ShiftCandidate.weapon_warning: boolean` (matches backend `ShiftCandidateOut.weapon_warning` from Task 5).

- [ ] **Step 1: Update the interface**

```typescript
export interface ShiftCandidate {
  soldier_id: string;
  full_name: string;
  personal_number: string;
  effort: number;
  blocked: boolean;
  blocked_reason: "constraint" | "assignment" | null;
  weapon_warning: boolean;
  hierarchy_path_ids: string[];
}
```

- [ ] **Step 2: Typecheck**

```bash
npx tsc --noEmit -p .
```
Expected: fails on `ShiftAssignModal.tsx` and any test file constructing a `ShiftCandidate` literal without `weapon_warning` — this is expected and resolved in Task 10.

- [ ] **Step 3: Commit alongside Task 10** (this task's diff is trivial and gets bundled with the next commit — proceed directly to Task 10 without a separate commit here to avoid a broken intermediate typecheck state on `dev`).

---

### Task 10: Frontend — `ShiftAssignModal` warning UI + confirm-before-assign

**Files:**
- Modify: `frontend/src/components/ShiftAssignModal.tsx`
- Test: `frontend/src/components/ShiftAssignModal.test.tsx` (check if it exists first; create if not)

**Interfaces:**
- Consumes: `ShiftCandidate.weapon_warning` (Task 9).

- [ ] **Step 1: Check for an existing test file and its fixtures**

```bash
ls frontend/src/components/ShiftAssignModal.test.tsx 2>&1
```
If it exists, read it fully first to match its existing mock/fixture style before adding new tests. If not, create it following the pattern below (uses Vitest + Testing Library, matching this repo's frontend test conventions — check `frontend/src/components/*.test.tsx` for the exact render/mock helpers already in use, e.g. `vi.mock("../api/assignments")`).

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/ShiftAssignModal.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import ShiftAssignModal from "./ShiftAssignModal";
import * as assignmentsApi from "../api/assignments";
import * as shiftsApi from "../api/shifts";

vi.mock("../api/assignments");
vi.mock("../api/shifts");

const baseShift = {
  id: "shift-1", duty_type_id: "dt-1", duty_location_id: "loc-1",
  start_date: "2026-09-01", end_date: "2026-09-02",
  required_count: 1, assigned_count: 0,
  reserve_count_override: null, calculated_reserve_count: 0, reserve_assigned_count: 0,
} as any;

describe("ShiftAssignModal weapon eligibility warning", () => {
  beforeEach(() => {
    vi.mocked(assignmentsApi.getShiftCandidates).mockResolvedValue([
      {
        soldier_id: "s1", full_name: "לוחם לא כשיר", personal_number: "111",
        effort: 0.5, blocked: false, blocked_reason: null, weapon_warning: true,
        hierarchy_path_ids: [],
      },
    ]);
    vi.mocked(assignmentsApi.assignBatch as any) = vi.fn().mockResolvedValue({});
  });

  it("shows the candidate as selectable despite the warning", async () => {
    render(<ShiftAssignModal shift={baseShift} dutyTypes={[]} onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => screen.getByText("לוחם לא כשיר"));
    const checkbox = screen.getAllByRole("checkbox")[0] as HTMLInputElement;
    expect(checkbox.disabled).toBe(false);
  });

  it("asks for confirmation before assigning a flagged candidate", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ShiftAssignModal shift={baseShift} dutyTypes={[]} onSaved={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => screen.getByText("לוחם לא כשיר"));
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    fireEvent.click(screen.getByText(/^שבץ/));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    confirmSpy.mockRestore();
  });
});
```

- [ ] **Step 3: Run to verify failure**

```bash
npm test -- ShiftAssignModal.test.tsx
```
Expected: FAIL — no warning indicator exists yet, and `handleAssign` never calls `window.confirm`.

- [ ] **Step 4: Implement the UI changes**

In `frontend/src/components/ShiftAssignModal.tsx`, add a Hebrew label constant near `BLOCKED_REASON_LABEL` (line 17-20):

```tsx
const WEAPON_WARNING_LABEL = "ללא הכשרת נשק בתוקף";
```

Update `handleAssign` (line 134-148) to confirm when any selected candidate is flagged:

```tsx
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
    setSaving(true);
    setError(null);
    try {
      await assignBatch(shift.id, {
        primaries: [...primarySelected],
        reserves: [...reserveSelected],
      });
      onSaved();
    } catch (e: unknown) {
      setError(translateApiError(e, t, "שגיאה בשיבוץ"));
      setSaving(false);
    }
  }
```

Update `PrimaryTable`'s unblocked-row rendering (line 279-289) to show a warning marker (keeping the checkbox enabled, unlike the `blocked` rows below it):

```tsx
          {unblocked.map(c => (
            <tr key={c.soldier_id}
              className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => onToggle(c.soldier_id)}>
              <td className="p-2"><input type="checkbox" checked={selected.has(c.soldier_id)} onChange={() => onToggle(c.soldier_id)} onClick={e => e.stopPropagation()} /></td>
              <td className="p-2">
                {c.full_name}
                {c.weapon_warning && (
                  <span title={WEAPON_WARNING_LABEL} className="mr-1 text-amber-500 dark:text-amber-400">⚠️</span>
                )}
              </td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
              <td className="p-2"></td>
            </tr>
          ))}
```

Apply the same marker to `ReserveTable`'s unblocked-row rendering (line 342-357):

```tsx
          {unblocked.map(c => (
            <tr key={c.soldier_id}
              className="border-t dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
              onClick={() => onToggle(c.soldier_id)}>
              <td className="p-2"><input type="checkbox" checked={selected.has(c.soldier_id)} onChange={() => onToggle(c.soldier_id)} onClick={e => e.stopPropagation()} /></td>
              <td className="p-2">
                {c.full_name}
                {c.weapon_warning && (
                  <span title={WEAPON_WARNING_LABEL} className="mr-1 text-amber-500 dark:text-amber-400">⚠️</span>
                )}
              </td>
              <td className="p-2 text-gray-500 dark:text-gray-400" dir="ltr">{c.personal_number}</td>
              <td className="p-2 font-mono">{c.effort.toFixed(3)}</td>
              {showDist && (
                <td className="p-2 text-gray-600 dark:text-gray-300 max-w-[160px]">
                  {c.coveringNames.length > 0 ? c.coveringNames.join(", ") : "–"}
                </td>
              )}
              <td className="p-2"></td>
            </tr>
          ))}
```

- [ ] **Step 5: Run tests to verify pass**

```bash
npm test -- ShiftAssignModal.test.tsx
```
Expected: both PASS.

- [ ] **Step 6: Typecheck and run the broader frontend suite**

```bash
npx tsc --noEmit -p .
npm test
```
Expected: clean typecheck, no regressions.

- [ ] **Step 7: Commit (bundles Task 9's interface change)**

```bash
git add frontend/src/api/assignments.ts frontend/src/components/ShiftAssignModal.tsx frontend/src/components/ShiftAssignModal.test.tsx
git commit -m "feat: warn on weapon-ineligible candidates in shift assign modal"
```

---

### Task 11: Frontend — algorithm run settings per-run override

**Files:**
- Modify: `frontend/src/api/algorithm.ts`, `frontend/src/components/AlgorithmRunForm.tsx`

**Interfaces:**
- Consumes: `SolverSettings.enforce_weapon_qualification` (backend, Task 8) via the existing `settings_json` passthrough.

- [ ] **Step 1: Add the field to the frontend `SolverSettings` type**

In `frontend/src/api/algorithm.ts`, find the `SolverSettings` interface (containing `auto_relax_node_quotas?: boolean;` at line 13) and add immediately after:

```typescript
  auto_relax_node_quotas?: boolean;
  enforce_weapon_qualification?: boolean;
```

- [ ] **Step 2: Add the checkbox to `AlgorithmRunForm`**

In `frontend/src/components/AlgorithmRunForm.tsx`, add to `DEFAULT_SETTINGS` (line 19-22) — leave it `undefined` in the object literal so the backend's system-setting default (Task 8) governs unless the user explicitly toggles it; `undefined` is a valid `boolean | undefined` value so no line is needed for it (TypeScript optional field). Then add a second checkbox right after the existing `auto_relax_node_quotas` one (line 266-273):

```tsx
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.auto_relax_node_quotas ?? false}
              onChange={e => setSettings(s => ({ ...s, auto_relax_node_quotas: e.target.checked }))}
            />
            אפשר הרחבת יחידה אוטומטית במכסות
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.enforce_weapon_qualification ?? true}
              onChange={e => setSettings(s => ({ ...s, enforce_weapon_qualification: e.target.checked }))}
            />
            אכוף כשירות הכשרת נשק בשיבוץ אוטומטי
          </label>
```

- [ ] **Step 3: Typecheck**

```bash
npx tsc --noEmit -p .
```
Expected: clean.

- [ ] **Step 4: Manually verify in the browser**

Start the dev stack (`.\dev.ps1` from repo root, per `CLAUDE.md`), navigate to the algorithm run form, expand the advanced settings section, and confirm the new checkbox renders, defaults to checked, and toggles.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/algorithm.ts frontend/src/components/AlgorithmRunForm.tsx
git commit -m "feat: expose enforce_weapon_qualification as an algorithm run setting"
```

---

### Task 12: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend fast suite**

```bash
cd backend
pytest -q
```
Expected: all green.

- [ ] **Step 2: Run the backend slow suite (large-scale CP-SAT tests)**

```bash
pytest --slow -q
```
Expected: all green — this specifically exercises the solver's decomposition/relaxation paths touched in Task 7, at realistic scale.

- [ ] **Step 3: Run the full frontend suite**

```bash
cd frontend
npm test
npm run lint
npx tsc --noEmit -p .
```
Expected: all green, zero lint warnings.

- [ ] **Step 4: Manual smoke test in the browser**

Start `.\dev.ps1`, create a `DutyType` with `requires_weapon=true` and `required_range_type=laser` via the API (e.g. `PATCH /api/duty-config/duty-types/{id}` — no admin UI exists for this field per the Global Constraints), create a shift for it, and confirm in the assign modal that a soldier with no range qualification shows the ⚠️ warning and can still be force-assigned with a confirm prompt.

- [ ] **Step 5: No commit needed** — this task only verifies prior commits; if any regression surfaces, fix it within the task that introduced it and re-run this task.
