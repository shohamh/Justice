# Potential Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the potential calculation engine, its data model, the audit-friendly modifier system, and the `/planning/potential` + דף מפקד UI surfaces, so duty managers and רסן+ commanders can see and audit each sub-unit's duty-eligible headcount as of any reference date.

**Architecture:** A pure `backend/app/services/potential.py` module computes potential live (no caching) for a given hierarchy node and reference date, walking soldiers by `path_ids`, applying rank/gender/service-type eligibility (mitvahim/alal ignored), subtracting duty types covered by active *regular* exemptions, and rolling up `PotentialModifier` deltas. A new FastAPI router exposes table/drill-down/export/modifier-CRUD endpoints gated by a new `POTENTIAL_READ`/`POTENTIAL_MODIFIER_MANAGE` permission pair. Frontend adds a `/planning/potential` page (following `ScoreAdjustmentPage.tsx` conventions) plus a summary panel on `CommandDashboardPage`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, React + TypeScript, existing `app.audit.writer.write_audit`, openpyxl (already used by `import_excel.py`) for Excel export.

**Depends on spec:** `docs/superpowers/specs/2026-07-03-potential-design.md`

---

### Task 1: Migration — schema changes

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_potential.py`

- [ ] **Step 1: Generate the migration file**

Run: `cd backend && alembic revision -m "add_potential"`

Note the generated revision id (referred to as `<REV>` below) and confirm `down_revision = '52cd8f7417e1'` (the current head).

- [ ] **Step 2: Write the migration**

```python
"""add_potential

Revision ID: <REV>
Revises: 52cd8f7417e1
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '<REV>'
down_revision: Union[str, Sequence[str], None] = '52cd8f7417e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exemption_types",
        sa.Column("is_commander_exemption", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("soldiers", sa.Column("next_rank_date", sa.Date(), nullable=True))
    op.create_table(
        "potential_modifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_potential_modifiers_node", "potential_modifiers", ["hierarchy_node_id"])


def downgrade() -> None:
    op.drop_index("ix_potential_modifiers_node", table_name="potential_modifiers")
    op.drop_table("potential_modifiers")
    op.drop_column("soldiers", "next_rank_date")
    op.drop_column("exemption_types", "is_commander_exemption")
```

- [ ] **Step 3: Apply the migration**

Run: `cd backend && alembic upgrade head`
Expected: no errors; `alembic current` shows `<REV> (head)`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/<REV>_add_potential.py
git commit -m "feat: add potential_modifiers table, is_commander_exemption, next_rank_date"
```

---

### Task 2: Model changes

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add `is_commander_exemption` to `ExemptionType`**

In the `ExemptionType` class (around line 194-208), add after `is_medical`:

```python
    is_commander_exemption: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
```

- [ ] **Step 2: Add `next_rank_date` to `Soldier`**

In the `Soldier` class, add after the existing `rank` field (around line 53):

```python
    next_rank_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
```

- [ ] **Step 3: Add the `PotentialModifier` model**

Add a new class after `ScoreAdjustment` (around line 611, after its closing block):

```python
class PotentialModifier(Base):
    __tablename__ = "potential_modifiers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT")
    )
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 4: Verify the app imports cleanly**

Run: `cd backend && python -c "import app.db.models"`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add PotentialModifier model and new soldier/exemption-type fields"
```

---

### Task 3: Potential calculation engine — eligible-soldier counting

**Files:**
- Create: `backend/app/services/potential.py`
- Test: `backend/app/services/tests/test_potential.py`

- [ ] **Step 1: Write the failing test for basic eligible counting**

```python
# backend/app/services/tests/test_potential.py
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import DutyType, HierarchyNode, Soldier
from app.services.potential import compute_potential
from app.services.hierarchy import create_node


def _make_soldier(session, *, node_id, rank="טוראי", left_at=None, gender="m"):
    s = Soldier(
        personal_number=str(uuid.uuid4())[:8],
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node_id,
        rank=rank,
        gender=gender,
        left_at=left_at,
    )
    session.add(s)
    session.flush()
    return s


def test_compute_potential_counts_eligible_soldiers(app_session):
    node = create_node(app_session, level="פלוגה", name="Test Co", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id)
    _make_soldier(app_session, node_id=node.id)
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))

    assert result.raw_eligible_count == 2
    assert result.final_potential == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_potential.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.potential'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/potential.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyType, ExemptionDutyTypeMap, ExemptionType, HierarchyNode,
    PotentialModifier, Soldier, SoldierExemption,
)
from app.services.eligibility import ALL_RANKS, DutyTypeRequirements


@dataclass
class SoldierPotentialDetail:
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None  # populated when counted is False


@dataclass
class ModifierDetail:
    id: uuid.UUID
    delta: int
    reason: str
    start_date: date
    end_date: date | None
    created_by: uuid.UUID | None


@dataclass
class PotentialResult:
    node_id: uuid.UUID
    as_of: date
    raw_eligible_count: int
    modifiers: list[ModifierDetail] = field(default_factory=list)
    final_potential: int = 0
    soldiers: list[SoldierPotentialDetail] = field(default_factory=list)


def _rank_as_of(soldier: Soldier, reference_date: date) -> str | None:
    """Resolve the soldier's rank as of reference_date, applying next_rank_date if reached."""
    if soldier.rank is None:
        return None
    if soldier.next_rank_date is not None and soldier.next_rank_date <= reference_date:
        from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS
        for track in (ENLISTED_RANKS, OFFICER_RANKS):
            if soldier.rank in track:
                idx = track.index(soldier.rank)
                if idx + 1 < len(track):
                    return track[idx + 1]
                return soldier.rank
        return soldier.rank
    return soldier.rank


def _base_eligible_duty_types(
    soldier: Soldier, rank: str | None, duty_types: list[DutyType],
) -> set[uuid.UUID]:
    """Duty types the soldier qualifies for by rank/gender/service-type/officer
    requirements, ignoring mitvahim/alal timing entirely (potential-specific rule)."""
    eligible: set[uuid.UUID] = set()
    for dt in duty_types:
        raw = dt.requirements or {}
        try:
            reqs = DutyTypeRequirements.model_validate(raw)
        except Exception:
            eligible.add(dt.id)
            continue
        if reqs.allowed_genders and (not soldier.gender or soldier.gender not in reqs.allowed_genders):
            continue
        if reqs.allowed_ranks and (not rank or rank not in reqs.allowed_ranks):
            continue
        if not reqs.officers_allowed and soldier.is_officer:
            continue
        if not reqs.enlisted_allowed and not soldier.is_officer:
            continue
        if reqs.requires_bahad1 and not soldier.bahad1_graduate:
            continue
        eligible.add(dt.id)
    return eligible


def compute_potential(session: Session, *, node_id: uuid.UUID, reference_date: date) -> PotentialResult:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise ValueError("hierarchy_node_not_found")

    soldiers = list(
        session.execute(
            select(Soldier).where(Soldier.hierarchy_node_id.isnot(None))
        ).scalars().all()
    )
    subtree_soldiers = [s for s in soldiers if s.hierarchy_node_id is not None]
    node_by_id = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    subtree_soldiers = [
        s for s in subtree_soldiers
        if s.hierarchy_node_id in node_by_id and node_id in node_by_id[s.hierarchy_node_id].path_ids
    ]

    duty_types = list(session.execute(select(DutyType).where(DutyType.active.is_(True))).scalars().all())
    active_dt_ids = {dt.id for dt in duty_types}

    etid_to_dtids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        etid_to_dtids.setdefault(etid, set()).add(dtid)
    regular_types = {
        et.id: et for et in session.execute(
            select(ExemptionType).where(ExemptionType.is_commander_exemption.is_(False))
        ).scalars().all()
    }
    for et in regular_types.values():
        if et.is_global:
            etid_to_dtids[et.id] = set(active_dt_ids)

    exemptions_by_soldier: dict[uuid.UUID, list[SoldierExemption]] = {}
    for ex in session.execute(select(SoldierExemption)).scalars().all():
        if ex.exemption_type_id in regular_types:
            exemptions_by_soldier.setdefault(ex.soldier_id, []).append(ex)

    details: list[SoldierPotentialDetail] = []
    raw_count = 0
    for s in subtree_soldiers:
        if s.left_at is not None and s.left_at <= reference_date:
            details.append(SoldierPotentialDetail(s.id, s.full_name, False, "discharged as of reference date"))
            continue
        rank = _rank_as_of(s, reference_date)
        base_eligible = _base_eligible_duty_types(s, rank, duty_types)
        excluded: set[uuid.UUID] = set()
        for ex in exemptions_by_soldier.get(s.id, []):
            if ex.start_date <= reference_date and (ex.end_date is None or ex.end_date >= reference_date):
                excluded |= etid_to_dtids.get(ex.exemption_type_id, set())
        remaining = base_eligible - excluded
        if remaining:
            details.append(SoldierPotentialDetail(s.id, s.full_name, True))
            raw_count += 1
        else:
            details.append(SoldierPotentialDetail(s.id, s.full_name, False, "no eligible duty types remain (rank/exemptions)"))

    modifier_rows = session.execute(
        select(PotentialModifier).where(
            PotentialModifier.hierarchy_node_id.in_(
                [n.id for n in node_by_id.values() if node_id in n.path_ids]
            )
        )
    ).scalars().all()
    active_modifiers = [
        m for m in modifier_rows
        if m.start_date <= reference_date and (m.end_date is None or m.end_date >= reference_date)
    ]
    modifier_details = [
        ModifierDetail(m.id, m.delta, m.reason, m.start_date, m.end_date, m.created_by)
        for m in active_modifiers
    ]
    modifier_sum = sum(m.delta for m in active_modifiers)

    return PotentialResult(
        node_id=node_id,
        as_of=reference_date,
        raw_eligible_count=raw_count,
        modifiers=modifier_details,
        final_potential=raw_count + modifier_sum,
        soldiers=details,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_potential.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/potential.py backend/app/services/tests/test_potential.py
git commit -m "feat: add compute_potential eligible-soldier counting"
```

---

### Task 4: Potential calculation — mitvahim/alal ignored, regular exemptions reduce, commander exemptions don't

**Files:**
- Modify: `backend/app/services/tests/test_potential.py`

- [ ] **Step 1: Write failing tests for exemption handling**

Append to `test_potential.py`:

```python
from app.db.models import ExemptionType, SoldierExemption


def test_regular_global_exemption_excludes_soldier(app_session):
    node = create_node(app_session, level="פלוגה", name="Test Co 2", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    et = ExemptionType(name="פטור רפואי מלא", is_global=True, is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 0
    assert result.soldiers[0].counted is False


def test_commander_exemption_does_not_exclude_soldier(app_session):
    node = create_node(app_session, level="פלוגה", name="Test Co 3", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    et = ExemptionType(name="פטור פיקודי כללי", is_global=True, is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 1


def test_mitvahim_alal_ignored_for_potential(app_session):
    node = create_node(app_session, level="פלוגה", name="Test Co 4", parent_id=None)
    app_session.flush()
    dt = DutyType(
        name="שמירה", score_per_day=Decimal("1.0"),
        requirements={"requires_mitvahim": True},
    )
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id)  # no last_mitvahim_date set at all
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 1
```

- [ ] **Step 2: Run tests to verify current pass/fail state**

Run: `cd backend && pytest app/services/tests/test_potential.py -v`
Expected: All PASS — `_base_eligible_duty_types` never checks `requires_mitvahim`/`requires_alal`, and the exemption-filtering logic already restricts to `is_commander_exemption=False` types. This confirms Task 3's implementation already satisfies these rules; no code change needed here, only the test coverage.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/tests/test_potential.py
git commit -m "test: cover mitvahim/alal exclusion and commander-vs-regular exemption rules for potential"
```

---

### Task 5: Rollup to ancestor nodes

**Files:**
- Modify: `backend/app/services/tests/test_potential.py`

- [ ] **Step 1: Write failing test for parent rollup**

```python
def test_potential_rolls_up_to_parent(app_session):
    parent = create_node(app_session, level="גדוד", name="Battalion", parent_id=None)
    app_session.flush()
    child_a = create_node(app_session, level="פלוגה", name="Co A", parent_id=parent.id)
    child_b = create_node(app_session, level="פלוגה", name="Co B", parent_id=parent.id)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=child_a.id)
    _make_soldier(app_session, node_id=child_a.id)
    _make_soldier(app_session, node_id=child_b.id)
    app_session.commit()

    result = compute_potential(app_session, node_id=parent.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 3
```

- [ ] **Step 2: Run test**

Run: `cd backend && pytest app/services/tests/test_potential.py::test_potential_rolls_up_to_parent -v`
Expected: PASS — the `path_ids` containment check in `compute_potential` already includes descendant soldiers since `create_node` sets each child's `path_ids` to include all ancestors.

- [ ] **Step 3: Write failing test for modifier rollup from a deep descendant**

```python
def test_modifier_deep_in_subtree_rolls_up(app_session):
    parent = create_node(app_session, level="גדוד", name="Battalion 2", parent_id=None)
    app_session.flush()
    child = create_node(app_session, level="פלוגה", name="Co C", parent_id=parent.id)
    app_session.flush()

    app_session.add(PotentialModifier(
        hierarchy_node_id=child.id, delta=-5, reason="external duty",
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=parent.id, reference_date=date(2026, 7, 3))
    assert result.final_potential == -5
```

Add `from app.db.models import PotentialModifier` to the test file's imports.

- [ ] **Step 4: Run test**

Run: `cd backend && pytest app/services/tests/test_potential.py::test_modifier_deep_in_subtree_rolls_up -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tests/test_potential.py
git commit -m "test: cover potential rollup to ancestor nodes"
```

---

### Task 6: Potential modifier CRUD service

**Files:**
- Modify: `backend/app/services/potential.py`
- Modify: `backend/app/services/tests/test_potential.py`

- [ ] **Step 1: Write failing tests**

Append to `test_potential.py`:

```python
from app.services.potential import PotentialModifierError, create_modifier, delete_modifier, list_modifiers


def test_create_modifier_requires_reason(app_session):
    node = create_node(app_session, level="פלוגה", name="Co D", parent_id=None)
    app_session.commit()
    try:
        create_modifier(app_session, hierarchy_node_id=node.id, delta=-10, reason="  ", start_date=date(2026, 1, 1))
        assert False, "expected PotentialModifierError"
    except PotentialModifierError as exc:
        assert "reason" in str(exc)


def test_create_and_list_modifier(app_session):
    node = create_node(app_session, level="פלוגה", name="Co E", parent_id=None)
    app_session.commit()
    m = create_modifier(
        app_session, hierarchy_node_id=node.id, delta=-60, reason="external duties not in system",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )
    app_session.commit()
    rows = list_modifiers(app_session, hierarchy_node_id=node.id)
    assert len(rows) == 1
    assert rows[0].id == m.id


def test_delete_modifier(app_session):
    node = create_node(app_session, level="פלוגה", name="Co F", parent_id=None)
    app_session.commit()
    m = create_modifier(app_session, hierarchy_node_id=node.id, delta=5, reason="temp boost", start_date=date(2026, 1, 1))
    app_session.commit()
    delete_modifier(app_session, modifier_id=m.id)
    app_session.commit()
    assert list_modifiers(app_session, hierarchy_node_id=node.id) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_potential.py -v -k modifier`
Expected: FAIL — `create_modifier`/`list_modifiers`/`delete_modifier`/`PotentialModifierError` not defined.

- [ ] **Step 3: Implement modifier CRUD**

Append to `backend/app/services/potential.py`:

```python
from app.audit.writer import write_audit


class PotentialModifierError(Exception):
    """Raised on an invalid potential-modifier operation."""


def create_modifier(
    session: Session,
    *,
    hierarchy_node_id: uuid.UUID,
    delta: int,
    reason: str,
    start_date: date,
    end_date: date | None = None,
    actor_id: uuid.UUID | None = None,
) -> PotentialModifier:
    if session.get(HierarchyNode, hierarchy_node_id) is None:
        raise PotentialModifierError("hierarchy_node_not_found")
    if not reason or not reason.strip():
        raise PotentialModifierError("reason_required")
    if end_date is not None and end_date < start_date:
        raise PotentialModifierError("end_date_before_start_date")
    m = PotentialModifier(
        hierarchy_node_id=hierarchy_node_id,
        delta=delta,
        reason=reason,
        start_date=start_date,
        end_date=end_date,
        created_by=actor_id,
    )
    session.add(m)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="potential_modifier.create",
        entity_type="potential_modifier",
        entity_id=m.id,
        after={"hierarchy_node_id": str(hierarchy_node_id), "delta": delta, "start_date": start_date.isoformat(), "end_date": end_date.isoformat() if end_date else None},
        context={"reason": reason},
    )
    return m


def list_modifiers(session: Session, *, hierarchy_node_id: uuid.UUID) -> list[PotentialModifier]:
    return list(
        session.execute(
            select(PotentialModifier)
            .where(PotentialModifier.hierarchy_node_id == hierarchy_node_id)
            .order_by(PotentialModifier.created_at)
        ).scalars().all()
    )


def delete_modifier(session: Session, *, modifier_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> None:
    m = session.get(PotentialModifier, modifier_id)
    if m is None:
        raise PotentialModifierError("modifier_not_found")
    before = {"hierarchy_node_id": str(m.hierarchy_node_id), "delta": m.delta, "reason": m.reason}
    session.delete(m)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="potential_modifier.delete",
        entity_type="potential_modifier",
        entity_id=modifier_id,
        before=before,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_potential.py -v -k modifier`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/potential.py backend/app/services/tests/test_potential.py
git commit -m "feat: add potential modifier create/list/delete with audit trail"
```

---

### Task 7: Permissions — `POTENTIAL_READ` / `POTENTIAL_MODIFIER_MANAGE`

**Files:**
- Modify: `backend/app/auth/authz.py`

- [ ] **Step 1: Add the new actions**

In the `Action` class (around line 39-56), add:

```python
    POTENTIAL_READ = "potential.read"
    POTENTIAL_MODIFIER_MANAGE = "potential.modifier_manage"
```

- [ ] **Step 2: Wire into the DM and commander action sets**

Add `Action.POTENTIAL_READ` and `Action.POTENTIAL_MODIFIER_MANAGE` to `_DM_ACTIONS` (any duty manager, scoped):

```python
_DM_ACTIONS = {
    Action.SOLDIER_CREATE,
    Action.SOLDIER_READ,
    Action.SOLDIER_UPDATE,
    Action.SOLDIER_RESET_PASSWORD,
    Action.SOLDIER_DELETE,
    Action.HIERARCHY_READ,
    Action.HIERARCHY_MANAGE,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.SWAP_APPROVE,
    Action.ASSIGNMENT_MANAGE,
    Action.SCORE_ADJUST,
    Action.ENROLLMENT_APPROVE,
    Action.POTENTIAL_READ,
    Action.POTENTIAL_MODIFIER_MANAGE,
}
```

For commanders, only רסן+ may see potential — this is a rank gate, not a plain scope gate, so it needs a dedicated branch in `can()` rather than membership in `_COMMANDER_ACTIONS` (which allows any rank). Modify the `can()` function:

```python
def can(
    user: Soldier,
    action: str,
    *,
    target_node: HierarchyNode | None,
    roots: set[uuid.UUID],
    is_commander: bool,
    is_duty_manager: bool,
) -> bool:
    if user.role == "admin":
        return True
    allowed = False
    if is_duty_manager:
        if action in _DM_GLOBAL_ACTIONS:
            return True
        if action in _DM_ACTIONS and _node_in_scope(target_node, roots):
            allowed = True
    if is_commander:
        if action in (Action.POTENTIAL_READ, Action.POTENTIAL_MODIFIER_MANAGE):
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action == Action.DM_SCOPE_MANAGE:
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots):
            allowed = True
    return allowed
```

Note `Action.POTENTIAL_READ`/`Action.POTENTIAL_MODIFIER_MANAGE` are already in `_DM_ACTIONS` so a duty manager reaches `allowed = True` via the first branch; the `is_commander` branch only matters for commander-role users, keeping the רסן+ gate specific to commanders.

- [ ] **Step 3: Write a unit test**

**Test:** `backend/app/services/tests/test_authz_potential.py`

```python
from __future__ import annotations

import uuid

from app.auth.authz import Action, can
from app.db.models import Soldier


def _soldier(rank=None, role="commander"):
    return Soldier(
        personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x",
        role=role, rank=rank,
    )


def test_commander_below_rasan_cannot_read_potential():
    s = _soldier(rank="סרן")
    node_id = uuid.uuid4()
    assert can(
        s, Action.POTENTIAL_READ, target_node=None, roots={node_id},
        is_commander=True, is_duty_manager=False,
    ) is False


def test_commander_rasan_and_above_can_read_potential():
    from app.db.models import HierarchyNode
    s = _soldier(rank="רסן")
    node = HierarchyNode(level="פלוגה", name="X", path_ids=[uuid.uuid4()])
    node.path_ids = [node.id] if node.id else [uuid.uuid4()]
    roots = {node.path_ids[0]}
    assert can(
        s, Action.POTENTIAL_READ, target_node=node, roots=roots,
        is_commander=True, is_duty_manager=False,
    ) is True


def test_duty_manager_can_read_potential_in_scope():
    from app.db.models import HierarchyNode
    s = _soldier(rank=None, role="duty_manager")
    node_id = uuid.uuid4()
    node = HierarchyNode(level="פלוגה", name="X", path_ids=[node_id])
    assert can(
        s, Action.POTENTIAL_READ, target_node=node, roots={node_id},
        is_commander=False, is_duty_manager=True,
    ) is True
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest app/services/tests/test_authz_potential.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth/authz.py backend/app/services/tests/test_authz_potential.py
git commit -m "feat: add POTENTIAL_READ/POTENTIAL_MODIFIER_MANAGE actions gated to DM + רסן+ commanders"
```

---

### Task 8: Potential routes — table view and drill-down

**Files:**
- Create: `backend/app/routes/potential.py`
- Modify: `backend/app/main.py`
- Test: `backend/app/routes/tests/test_potential_routes.py` (create dir if needed — check `backend/app/routes/tests/__init__.py` exists first; if `routes/tests` doesn't exist, use `backend/app/services/tests/test_potential_routes.py` instead to match this repo's convention of route tests co-located under `services/tests`)

- [ ] **Step 1: Check where existing route tests live**

Run: `cd backend && ls app/routes/tests 2>/dev/null || echo "no routes/tests dir"`

If it doesn't exist, place the test at `backend/app/services/tests/test_potential_routes.py` (this repo tests routes via the `client` fixture regardless of directory — confirm by checking an existing route test, e.g. `grep -rl "def client" app/services/tests/`).

- [ ] **Step 2: Write the failing route test**

```python
# backend/app/services/tests/test_potential_routes.py
from __future__ import annotations

import uuid

from app.db.models import DutyType, HierarchyNode, Soldier
from app.services.hierarchy import create_node


def test_get_potential_requires_auth(client):
    resp = client.get("/api/potential", params={"node_id": str(uuid.uuid4())})
    assert resp.status_code == 401


def test_get_potential_as_duty_manager(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Route Test Co", parent_id=None)
    admin_session.commit()

    from tests.conftest import make_authed_client  # reuse existing helper if present
```

Before finalizing this test, inspect an existing authenticated route test to copy its login/auth helper pattern exactly (e.g. `grep -n "def test_.*duty_manager\|login\|access_token" backend/app/services/tests/test_shift_quotas.py backend/app/routes/tests/*.py 2>/dev/null`), since this repo's `client` fixture likely requires a real login flow (JWT) rather than a `make_authed_client` shortcut — replace the import above with whatever pattern that inspection reveals, and finish `test_get_potential_as_duty_manager` to: log in as a seeded/created duty_manager, call `GET /api/potential?node_id=...&reference_date=2026-07-03`, and assert `resp.status_code == 200` and `resp.json()["final_potential"] == 0`.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_potential_routes.py -v`
Expected: FAIL (404, route doesn't exist yet)

- [ ] **Step 4: Implement the route**

```python
# backend/app/routes/potential.py
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import potential as svc

router = APIRouter(prefix="/potential", tags=["potential"])


class SoldierDetailOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None


class ModifierOut(BaseModel):
    id: uuid.UUID
    delta: int
    reason: str
    start_date: str
    end_date: str | None
    created_by: uuid.UUID | None


class PotentialOut(BaseModel):
    node_id: uuid.UUID
    as_of: str
    raw_eligible_count: int
    modifiers: list[ModifierOut]
    final_potential: int
    soldiers: list[SoldierDetailOut]


def _out(r: svc.PotentialResult) -> PotentialOut:
    return PotentialOut(
        node_id=r.node_id,
        as_of=r.as_of.isoformat(),
        raw_eligible_count=r.raw_eligible_count,
        modifiers=[
            ModifierOut(
                id=m.id, delta=m.delta, reason=m.reason,
                start_date=m.start_date.isoformat(),
                end_date=m.end_date.isoformat() if m.end_date else None,
                created_by=m.created_by,
            ) for m in r.modifiers
        ],
        final_potential=r.final_potential,
        soldiers=[
            SoldierDetailOut(soldier_id=s.soldier_id, full_name=s.full_name, counted=s.counted, reason=s.reason)
            for s in r.soldiers
        ],
    )


@router.get("", response_model=PotentialOut)
def get_potential(
    node_id: uuid.UUID,
    reference_date: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PotentialOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_READ, target_node=node)
    ref = date.fromisoformat(reference_date) if reference_date else date.today()
    result = svc.compute_potential(session, node_id=node_id, reference_date=ref)
    return _out(result)
```

- [ ] **Step 5: Register the router**

In `backend/app/main.py`, add near the other route imports (around line 28):

```python
from app.routes import potential as potential_routes
```

And near the other `include_router` calls (around line 151):

```python
    app.include_router(potential_routes.router, prefix="/api")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_potential_routes.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/potential.py backend/app/main.py backend/app/services/tests/test_potential_routes.py
git commit -m "feat: add GET /api/potential route with drill-down detail"
```

---

### Task 9: Potential modifier routes

**Files:**
- Modify: `backend/app/routes/potential.py`
- Modify: `backend/app/services/tests/test_potential_routes.py`

- [ ] **Step 1: Write failing tests**

Add to the route test file (following the auth pattern established in Task 8):

```python
def test_create_modifier_route_requires_reason(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Mod Route Co", parent_id=None)
    admin_session.commit()
    # (use the same authenticated-duty-manager client helper from Task 8)
    resp = authed_client.post("/api/potential/modifiers", json={
        "hierarchy_node_id": str(node.id), "delta": -10, "reason": "", "start_date": "2026-01-01",
    })
    assert resp.status_code == 400


def test_create_and_list_modifier_route(client, admin_session):
    node = create_node(admin_session, level="פלוגה", name="Mod Route Co 2", parent_id=None)
    admin_session.commit()
    resp = authed_client.post("/api/potential/modifiers", json={
        "hierarchy_node_id": str(node.id), "delta": -60, "reason": "external duties", "start_date": "2026-01-01", "end_date": None,
    })
    assert resp.status_code == 201
    resp2 = authed_client.get("/api/potential/modifiers", params={"hierarchy_node_id": str(node.id)})
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1
```

(Replace `authed_client` with whatever authenticated-request pattern Task 8 established.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_potential_routes.py -v -k modifier`
Expected: FAIL (404)

- [ ] **Step 3: Implement the routes**

Append to `backend/app/routes/potential.py`:

```python
class ModifierCreateIn(BaseModel):
    hierarchy_node_id: uuid.UUID
    delta: int
    reason: str
    start_date: str
    end_date: str | None = None


@router.get("/modifiers", response_model=list[ModifierOut])
def get_modifiers(
    hierarchy_node_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ModifierOut]:
    node = session.get(HierarchyNode, hierarchy_node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_READ, target_node=node)
    rows = svc.list_modifiers(session, hierarchy_node_id=hierarchy_node_id)
    return [
        ModifierOut(
            id=m.id, delta=m.delta, reason=m.reason,
            start_date=m.start_date.isoformat(),
            end_date=m.end_date.isoformat() if m.end_date else None,
            created_by=m.created_by,
        ) for m in rows
    ]


@router.post("/modifiers", response_model=ModifierOut, status_code=status.HTTP_201_CREATED)
def create_modifier_route(
    body: ModifierCreateIn,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ModifierOut:
    node = session.get(HierarchyNode, body.hierarchy_node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_MODIFIER_MANAGE, target_node=node)
    try:
        m = svc.create_modifier(
            session,
            hierarchy_node_id=body.hierarchy_node_id,
            delta=body.delta,
            reason=body.reason,
            start_date=date.fromisoformat(body.start_date),
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            actor_id=user.id,
        )
    except svc.PotentialModifierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return ModifierOut(
        id=m.id, delta=m.delta, reason=m.reason,
        start_date=m.start_date.isoformat(),
        end_date=m.end_date.isoformat() if m.end_date else None,
        created_by=m.created_by,
    )


@router.delete("/modifiers/{modifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_modifier_route(
    modifier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    from app.db.models import PotentialModifier
    m = session.get(PotentialModifier, modifier_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    node = session.get(HierarchyNode, m.hierarchy_node_id)
    authorize(session, user, Action.POTENTIAL_MODIFIER_MANAGE, target_node=node)
    svc.delete_modifier(session, modifier_id=modifier_id, actor_id=user.id)
    session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_potential_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/potential.py backend/app/services/tests/test_potential_routes.py
git commit -m "feat: add potential modifier CRUD routes"
```

---

### Task 10: Excel export endpoint

**Files:**
- Modify: `backend/app/routes/potential.py`
- Modify: `backend/app/services/potential.py`

- [ ] **Step 1: Check the existing Excel export pattern**

Run: `cd backend && grep -n "openpyxl\|StreamingResponse\|Workbook" app/routes/import_excel.py | head -20`

Confirm the library (`openpyxl`) and response pattern (likely `StreamingResponse` with `content-disposition` header) before writing the export.

- [ ] **Step 2: Add an export function to the service**

Append to `backend/app/services/potential.py`:

```python
def export_potential_table_xlsx(session: Session, *, root_node_id: uuid.UUID, reference_date: date) -> bytes:
    """Build an .xlsx snapshot of root_node_id and all its descendant nodes' potential."""
    import io
    from openpyxl import Workbook

    all_nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    node_by_id = {n.id: n for n in all_nodes}
    root = node_by_id.get(root_node_id)
    if root is None:
        raise ValueError("hierarchy_node_not_found")
    subtree = [n for n in all_nodes if root_node_id in n.path_ids]

    wb = Workbook()
    ws = wb.active
    ws.title = "Potential"
    ws.append(["Node", "Level", "Raw Eligible", "Modifiers Sum", "Final Potential", "As Of"])
    for n in subtree:
        r = compute_potential(session, node_id=n.id, reference_date=reference_date)
        mod_sum = sum(m.delta for m in r.modifiers)
        ws.append([n.name, n.level, r.raw_eligible_count, mod_sum, r.final_potential, reference_date.isoformat()])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 3: Add the export route**

Append to `backend/app/routes/potential.py`:

```python
from fastapi.responses import StreamingResponse
import io


@router.get("/export")
def export_potential(
    node_id: uuid.UUID,
    reference_date: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> StreamingResponse:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_READ, target_node=node)
    ref = date.fromisoformat(reference_date) if reference_date else date.today()
    content = svc.export_potential_table_xlsx(session, root_node_id=node_id, reference_date=ref)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="potential_{ref.isoformat()}.xlsx"'},
    )
```

- [ ] **Step 4: Write a test**

```python
# append to backend/app/services/tests/test_potential.py
def test_export_potential_table_xlsx_returns_bytes(app_session):
    node = create_node(app_session, level="פלוגה", name="Export Co", parent_id=None)
    app_session.commit()
    from app.services.potential import export_potential_table_xlsx
    content = export_potential_table_xlsx(app_session, root_node_id=node.id, reference_date=date(2026, 7, 3))
    assert content[:2] == b"PK"  # xlsx is a zip archive
```

- [ ] **Step 5: Run test**

Run: `cd backend && pytest app/services/tests/test_potential.py::test_export_potential_table_xlsx_returns_bytes -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/potential.py backend/app/routes/potential.py backend/app/services/tests/test_potential.py
git commit -m "feat: add potential table Excel export"
```

---

### Task 11: Frontend API client

**Files:**
- Create: `frontend/src/api/potential.ts`

- [ ] **Step 1: Write the client module**

```typescript
// frontend/src/api/potential.ts
import { api } from "./client";

export interface SoldierPotentialDetail {
  soldier_id: string;
  full_name: string;
  counted: boolean;
  reason: string | null;
}

export interface PotentialModifierDTO {
  id: string;
  delta: number;
  reason: string;
  start_date: string;
  end_date: string | null;
  created_by: string | null;
}

export interface PotentialResult {
  node_id: string;
  as_of: string;
  raw_eligible_count: number;
  modifiers: PotentialModifierDTO[];
  final_potential: number;
  soldiers: SoldierPotentialDetail[];
}

export async function getPotential(nodeId: string, referenceDate?: string): Promise<PotentialResult> {
  return (await api.get<PotentialResult>("/potential", {
    params: { node_id: nodeId, reference_date: referenceDate },
  })).data;
}

export async function listModifiers(nodeId: string): Promise<PotentialModifierDTO[]> {
  return (await api.get<PotentialModifierDTO[]>("/potential/modifiers", {
    params: { hierarchy_node_id: nodeId },
  })).data;
}

export async function createModifier(input: {
  hierarchy_node_id: string; delta: number; reason: string; start_date: string; end_date?: string | null;
}): Promise<PotentialModifierDTO> {
  return (await api.post<PotentialModifierDTO>("/potential/modifiers", input)).data;
}

export async function deleteModifier(modifierId: string): Promise<void> {
  await api.delete(`/potential/modifiers/${modifierId}`);
}

export function exportPotentialUrl(nodeId: string, referenceDate?: string): string {
  const params = new URLSearchParams({ node_id: nodeId });
  if (referenceDate) params.set("reference_date", referenceDate);
  return `/api/potential/export?${params.toString()}`;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npm run typecheck`
Expected: no new errors from this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/potential.ts
git commit -m "feat: add potential API client"
```

---

### Task 12: Planning nav entry and PotentialPage

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/pages/planning/PotentialPage.tsx`

- [ ] **Step 1: Add the nav entry**

In `UnifiedNav.tsx`, add to `planningItems` (around line 157-163):

```typescript
    { label: "פוטנציאל", to: "/planning/potential", testId: "nav-potential" },
```

- [ ] **Step 2: Add the route**

In `App.tsx`, add alongside the other planning routes (around line 78-82):

```tsx
            <Route path="/planning/potential" element={<AppGate><PotentialPage /></AppGate>} />
```

And import it near the other planning page imports.

- [ ] **Step 3: Write the page component**

```tsx
// frontend/src/pages/planning/PotentialPage.tsx
import { useEffect, useState } from "react";
import { getPotential, listModifiers, createModifier, deleteModifier, exportPotentialUrl, PotentialResult, PotentialModifierDTO } from "../../api/potential";
import { getHierarchyTree, HierarchyNodeDTO } from "../../api/hierarchy";

export default function PotentialPage() {
  const [rootId, setRootId] = useState<string | null>(null);
  const [nodes, setNodes] = useState<HierarchyNodeDTO[]>([]);
  const [referenceDate, setReferenceDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [results, setResults] = useState<Record<string, PotentialResult>>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [modifiers, setModifiers] = useState<PotentialModifierDTO[]>([]);
  const [newReason, setNewReason] = useState("");
  const [newDelta, setNewDelta] = useState(0);

  useEffect(() => {
    getHierarchyTree().then((tree) => {
      setNodes(tree);
      if (tree.length > 0) setRootId(tree[0].id);
    });
  }, []);

  useEffect(() => {
    if (nodes.length === 0) return;
    Promise.all(nodes.map((n) => getPotential(n.id, referenceDate))).then((all) => {
      const byId: Record<string, PotentialResult> = {};
      all.forEach((r, i) => { byId[nodes[i].id] = r; });
      setResults(byId);
    });
  }, [nodes, referenceDate]);

  useEffect(() => {
    if (selectedNodeId) listModifiers(selectedNodeId).then(setModifiers);
  }, [selectedNodeId]);

  async function handleAddModifier() {
    if (!selectedNodeId || !newReason.trim()) return;
    await createModifier({ hierarchy_node_id: selectedNodeId, delta: newDelta, reason: newReason, start_date: referenceDate });
    setModifiers(await listModifiers(selectedNodeId));
    setNewReason("");
    setNewDelta(0);
  }

  return (
    <div className="p-4 space-y-4" dir="rtl">
      <h1 className="text-xl font-bold">פוטנציאל</h1>
      <div className="flex gap-2 items-center">
        <label>תאריך ייחוס:</label>
        <input type="date" value={referenceDate} onChange={(e) => setReferenceDate(e.target.value)} className="border rounded p-1" />
        {rootId && (
          <a href={exportPotentialUrl(rootId, referenceDate)} className="text-blue-600 underline">
            ייצוא לאקסל
          </a>
        )}
      </div>
      <table className="w-full border-collapse" data-testid="potential-table">
        <thead>
          <tr>
            <th className="border p-2">יחידה</th>
            <th className="border p-2">כשירים</th>
            <th className="border p-2">התאמות</th>
            <th className="border p-2">פוטנציאל סופי</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((n) => {
            const r = results[n.id];
            return (
              <tr key={n.id} className="cursor-pointer hover:bg-gray-100" onClick={() => setSelectedNodeId(n.id)}>
                <td className="border p-2">{n.name}</td>
                <td className="border p-2">{r?.raw_eligible_count ?? "-"}</td>
                <td className="border p-2">{r ? r.modifiers.reduce((s, m) => s + m.delta, 0) : "-"}</td>
                <td className="border p-2">{r?.final_potential ?? "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {selectedNodeId && (
        <div className="border rounded p-3 space-y-2">
          <h2 className="font-semibold">פירוט וביקורת</h2>
          <ul>
            {results[selectedNodeId]?.soldiers.map((s) => (
              <li key={s.soldier_id}>
                {s.full_name} — {s.counted ? "נספר" : `לא נספר (${s.reason})`}
              </li>
            ))}
          </ul>
          <h3 className="font-semibold">התאמות ידניות</h3>
          <ul>
            {modifiers.map((m) => (
              <li key={m.id}>
                {m.delta > 0 ? "+" : ""}{m.delta} — {m.reason} ({m.start_date}
                {m.end_date ? ` עד ${m.end_date}` : ""})
                <button className="text-red-600 mr-2" onClick={async () => { await deleteModifier(m.id); setModifiers(await listModifiers(selectedNodeId)); }}>
                  מחק
                </button>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <input type="number" value={newDelta} onChange={(e) => setNewDelta(Number(e.target.value))} className="border rounded p-1 w-20" />
            <input type="text" value={newReason} onChange={(e) => setNewReason(e.target.value)} placeholder="סיבה (חובה)" className="border rounded p-1 flex-1" />
            <button onClick={handleAddModifier} className="bg-blue-600 text-white rounded px-3 py-1">הוסף</button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify the hierarchy API client exposes `getHierarchyTree`**

Run: `cd frontend && grep -n "export.*function\|export interface" src/api/hierarchy.ts | head -20`

If the actual exported function/type names differ (e.g. `HierarchyNode` instead of `HierarchyNodeDTO`, or a differently-named tree fetcher), update the imports in `PotentialPage.tsx` to match exactly.

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/planning/PotentialPage.tsx frontend/src/components/UnifiedNav.tsx frontend/src/App.tsx
git commit -m "feat: add /planning/potential page with table, drill-down, and modifier UI"
```

---

### Task 13: דף מפקד potential panel

**Files:**
- Modify: `frontend/src/pages/CommandDashboardPage.tsx`

- [ ] **Step 1: Inspect the existing panel pattern**

Run: `cd frontend && sed -n '1,80p' src/pages/CommandDashboardPage.tsx`

Identify how `SummaryCards` and `activePanel` are wired so the new panel follows the same "click a card to reveal a panel" convention already in use.

- [ ] **Step 2: Add a potential summary section**

Add a new section to `CommandDashboardPage.tsx` that calls `getPotential` for the commander's own scoped node(s) (reuse whatever the file already uses to resolve `scope_root_ids`-equivalent on the frontend — check how existing panels fetch commander-scoped data, e.g. `grep -n "scope\|commanded" src/pages/CommandDashboardPage.tsx`) and renders the same table row format as `PotentialPage.tsx`'s table body (node name / raw eligible / modifiers / final potential), read-only (no modifier CRUD here — that stays on the full Planning page).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/CommandDashboardPage.tsx
git commit -m "feat: show own-subunit potential on command dashboard"
```

---

### Task 14: Help modal documentation — פוטנציאל

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`

- [ ] **Step 1: Add the potential entry**

In the icon/title/desc array around line 146-152 (the algorithm-concepts list), add:

```typescript
          { icon: "📈", title: "פוטנציאל", desc: "מספר החיילים הכשירים לפחות לסוג תורנות אחד בכל תת-יחידה. פטורים רשמיים מפחיתים פוטנציאל אם הם מכסים את כל סוגי התורנות של החייל; פטורים פיקודיים ואילוצים אישיים לא משפיעים על הפוטנציאל. הפוטנציאל קובע את חלוקת האחריות היחסית בין תת-יחידות במשמרות חדשות, וניתן לבקר אותו לפי חייל ולראות התאמות ידניות מתועדות." },
```

- [ ] **Step 2: Verify the modal renders**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "docs: document פוטנציאל concept in help modal"
```

---

### Task 15: Full verification pass

- [ ] **Step 1: Run backend test suite for touched areas**

Run: `cd backend && pytest -m "hierarchy or misc" -q app/services/tests/test_potential.py app/services/tests/test_potential_routes.py app/services/tests/test_authz_potential.py -v`
Expected: All PASS.

- [ ] **Step 2: Run frontend checks**

Run: `cd frontend && npm run typecheck && npm run lint && npm test -- potential`
Expected: no errors; any new component tests (if added ad hoc during Task 12/13) pass.

- [ ] **Step 3: Manual smoke check**

Start the dev stack (`./dev.ps1` from repo root), log in as a duty manager, navigate to `/planning/potential`, confirm the table renders with real seeded data, click a row to see the drill-down, add a modifier with a reason, confirm it appears and affects `final_potential`, then delete it.

- [ ] **Step 4: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "fix: address issues found during potential-core verification pass"
```
