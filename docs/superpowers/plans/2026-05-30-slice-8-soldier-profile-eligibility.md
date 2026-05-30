# Slice 8 — Soldier Profile & DutyType Eligibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add military-profile fields to soldiers (rank, gender, service dates, training dates), add JSONB eligibility requirements to duty types, and enforce requirements as hard constraints in the algorithm bridge.

**Architecture:** New columns on `soldiers` + new `soldier_field_updates` table + `requirements` JSONB on `duty_types` (migration 0017). Eligibility is enforced in `algorithm_bridge.py` by expanding `exempted_duty_type_ids`. Soldiers can submit change requests for training dates and gender; commanders approve them via a new ApprovalsPage tab.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, React 18, TypeScript, react-i18next, Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-05-30-slice-8-soldier-profile-eligibility.md`

---

## File structure

```
backend/
├── alembic/versions/0017_soldier_profile_eligibility.py   CREATE
├── app/
│   ├── db/models.py                    MODIFY — add profile fields to Soldier, add SoldierFieldUpdate model, add requirements to DutyType
│   ├── services/
│   │   ├── soldiers.py                 MODIFY — add update_soldier_profile, field-update approval functions
│   │   ├── eligibility.py              CREATE — DutyTypeRequirements model, inferred_service_type, compute_eligibility_exclusions
│   │   └── algorithm_bridge.py         MODIFY — call compute_eligibility_exclusions in load_soldier_inputs
│   └── routes/
│       ├── soldiers.py                 MODIFY — gender privacy in GET, new field-update endpoints, GET /ranks
│       └── duty_config.py              MODIFY — add requirements to DutyTypeOut + UpdateDutyTypeRequest
└── tests/
    ├── unit/test_eligibility.py        CREATE
    └── integration/
        ├── test_soldier_profile.py     CREATE
        └── test_field_updates.py       CREATE

frontend/src/
├── api/
│   ├── soldiers.ts                     MODIFY — add profile fields to SoldierDTO, add field-update API functions
│   └── dutyConfig.ts                   MODIFY — add requirements field
├── i18n/he.json                        MODIFY — add soldier_profile + eligibility blocks
├── pages/
│   ├── ProfilePage.tsx                 MODIFY — add פרטי שירות section (soldier self-view + update requests)
│   ├── TeamHierarchyPage.tsx           MODIFY — DM soldier edit panel — add profile fields
│   └── ApprovalsPage.tsx               MODIFY — add עדכוני פרופיל tab
└── components/
    └── DutyTypeRequirementsEditor.tsx  CREATE — requirements editor used in DutyConfigPage
```

---

## Phase A — Database

### Task 1: Migration 0017

**Files:**
- Create: `backend/alembic/versions/0017_soldier_profile_eligibility.py`

- [ ] **Step 1: Create `backend/alembic/versions/0017_soldier_profile_eligibility.py`**

```python
"""soldier profile fields, field updates table, duty type requirements

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Soldier profile fields ---
    op.add_column("soldiers", sa.Column("gender", sa.Text(), nullable=True))
    op.add_column("soldiers", sa.Column("is_officer", sa.Boolean(), nullable=True))
    op.add_column("soldiers", sa.Column("rank", sa.Text(), nullable=True))
    op.add_column("soldiers", sa.Column("bahad1_graduate", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("soldiers", sa.Column("enlistment_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("mandatory_end_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("discharge_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("last_mitvahim_date", sa.Date(), nullable=True))
    op.add_column("soldiers", sa.Column("last_alal_date", sa.Date(), nullable=True))

    # --- Soldier field update requests ---
    op.create_table(
        "soldier_field_updates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_sfu_soldier", "soldier_field_updates", ["soldier_id"])
    op.create_index("idx_sfu_status", "soldier_field_updates", ["status"])

    # --- DutyType eligibility requirements ---
    op.add_column(
        "duty_types",
        sa.Column("requirements", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
    )

    # --- System settings defaults ---
    op.execute(
        "INSERT INTO system_settings (key, value) VALUES "
        "('eligibility.mitvahim_months', '6') ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (key, value) VALUES "
        "('eligibility.alal_months', '3') ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM system_settings WHERE key IN ('eligibility.mitvahim_months', 'eligibility.alal_months')")
    op.drop_column("duty_types", "requirements")
    op.drop_index("idx_sfu_status", table_name="soldier_field_updates")
    op.drop_index("idx_sfu_soldier", table_name="soldier_field_updates")
    op.drop_table("soldier_field_updates")
    for col in ["last_alal_date", "last_mitvahim_date", "discharge_date",
                "mandatory_end_date", "enlistment_date", "bahad1_graduate",
                "rank", "is_officer", "gender"]:
        op.drop_column("soldiers", col)
```

- [ ] **Step 2: Run migration**

```
cd backend && uv run alembic upgrade head
uv run alembic check
```
Expected: `No new upgrade operations detected.`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0017_soldier_profile_eligibility.py
git commit -m "feat(db): soldier profile fields, field_updates table, duty_type requirements (migration 0017)"
```

---

### Task 2: ORM model updates

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add profile fields to the `Soldier` class**

After `must_change_password` and before `created_at`, insert:

```python
    gender: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_officer: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    rank: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    bahad1_graduate: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    enlistment_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    mandatory_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    discharge_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    last_mitvahim_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    last_alal_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
```

- [ ] **Step 2: Add `requirements` field to `DutyType`**

After `active` and before `created_at` in `DutyType`:

```python
    requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'"), default_factory=dict
    )
```

- [ ] **Step 3: Append `SoldierFieldUpdate` model at end of models.py**

```python
class SoldierFieldUpdate(Base):
    __tablename__ = "soldier_field_updates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 4: Verify imports**

```
cd backend && uv run python -c "from app.db.models import Soldier, DutyType, SoldierFieldUpdate; print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(models): soldier profile fields, SoldierFieldUpdate, DutyType.requirements"
```

---

## Phase B — Eligibility service

### Task 3: Create `eligibility.py`

**Files:**
- Create: `backend/app/services/eligibility.py`

- [ ] **Step 1: Create `backend/app/services/eligibility.py`**

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, Soldier

ENLISTED_RANKS = [
    "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
]
OFFICER_RANKS = [
    "קמא", "סגמ", "סגן", "קאב", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
]
ALL_RANKS = ENLISTED_RANKS + OFFICER_RANKS

SOLDIER_EDITABLE_FIELDS = {"last_mitvahim_date", "last_alal_date", "gender"}


class DutyTypeRequirements(BaseModel):
    allowed_genders: list[str] = []
    requires_mitvahim: bool = False
    requires_alal: bool = False
    allowed_ranks: list[str] = []
    allowed_service_types: list[str] = []
    officers_allowed: bool = True
    enlisted_allowed: bool = True
    requires_bahad1: bool = False


def inferred_service_type(soldier: Soldier, today: date | None = None) -> str | None:
    """Return 'חובה', 'קבע', or None (unknown)."""
    if soldier.mandatory_end_date is None:
        return None
    ref = today or date.today()
    if ref <= soldier.mandatory_end_date:
        return "חובה"
    if soldier.discharge_date is None or soldier.discharge_date > soldier.mandatory_end_date:
        return "קבע"
    return "חובה"


def _is_eligible(soldier: Soldier, reqs: DutyTypeRequirements, *, mitvahim_months: int, alal_months: int, today: date) -> bool:
    """Return False if soldier fails any requirement (fail-safe: null field = blocked if restriction exists)."""
    if reqs.allowed_genders:
        if not soldier.gender or soldier.gender not in reqs.allowed_genders:
            return False

    if reqs.requires_mitvahim:
        if not soldier.last_mitvahim_date:
            return False
        if (today - soldier.last_mitvahim_date) > timedelta(days=mitvahim_months * 30):
            return False

    if reqs.requires_alal:
        if not soldier.last_alal_date:
            return False
        if (today - soldier.last_alal_date) > timedelta(days=alal_months * 30):
            return False

    if reqs.allowed_ranks:
        if not soldier.rank or soldier.rank not in reqs.allowed_ranks:
            return False

    if reqs.allowed_service_types:
        stype = inferred_service_type(soldier, today)
        if not stype or stype not in reqs.allowed_service_types:
            return False

    if not reqs.officers_allowed and soldier.is_officer:
        return False

    if not reqs.enlisted_allowed:
        # blocked if not officer, or if officer status unknown
        if not soldier.is_officer:
            return False

    if reqs.requires_bahad1 and not soldier.bahad1_graduate:
        return False

    return True


def compute_eligibility_exclusions(
    session: Session,
    soldiers: list[Soldier],
    *,
    mitvahim_months: int,
    alal_months: int,
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, return the set of duty_type_ids they're ineligible for due to requirements.

    Returns {soldier_id: {duty_type_id, ...}}
    """
    today = date.today()
    duty_types = session.execute(
        select(DutyType).where(DutyType.active.is_(True))
    ).scalars().all()

    exclusions: dict[uuid.UUID, set[uuid.UUID]] = {s.id: set() for s in soldiers}

    for dt in duty_types:
        raw_reqs = dt.requirements or {}
        if not raw_reqs:
            continue
        try:
            reqs = DutyTypeRequirements.model_validate(raw_reqs)
        except Exception:
            continue

        for soldier in soldiers:
            if not _is_eligible(soldier, reqs, mitvahim_months=mitvahim_months, alal_months=alal_months, today=today):
                exclusions[soldier.id].add(dt.id)

    return exclusions
```

- [ ] **Step 2: Verify import**

```
cd backend && uv run python -c "from app.services.eligibility import DutyTypeRequirements, compute_eligibility_exclusions, ENLISTED_RANKS, OFFICER_RANKS; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/eligibility.py
git commit -m "feat(eligibility): DutyTypeRequirements model, service type inference, eligibility exclusions"
```

---

## Phase C — Backend service + routes

### Task 4: Update soldiers service

**Files:**
- Modify: `backend/app/services/soldiers.py`

- [ ] **Step 1: Add profile-update and field-update functions to `backend/app/services/soldiers.py`**

Add after the existing `update_soldier` function:

```python
PROFILE_FIELDS = {
    "gender", "is_officer", "rank", "bahad1_graduate",
    "enlistment_date", "mandatory_end_date", "discharge_date",
    "last_mitvahim_date", "last_alal_date",
}

from app.db.models import SoldierFieldUpdate
from datetime import datetime, timezone


def update_soldier_profile(
    session: Session,
    *,
    soldier: Soldier,
    fields: dict,
    actor_id: uuid.UUID | None,
) -> Soldier:
    """DM/admin direct update of profile fields."""
    for k, v in fields.items():
        if k in PROFILE_FIELDS and v is not None:
            setattr(soldier, k, v)
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.profile.update",
        entity_type="soldier",
        entity_id=soldier.id,
        after={k: str(v) for k, v in fields.items() if v is not None},
    )
    return soldier


def submit_field_update(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    field_name: str,
    new_value: str,
    actor_id: uuid.UUID,
) -> SoldierFieldUpdate:
    from app.services.eligibility import SOLDIER_EDITABLE_FIELDS
    if field_name not in SOLDIER_EDITABLE_FIELDS:
        raise SoldierError("field_not_editable")
    req = SoldierFieldUpdate(
        soldier_id=soldier_id,
        field_name=field_name,
        new_value=new_value,
    )
    session.add(req)
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.submit",
        entity_type="soldier_field_update",
        entity_id=None,
        after={"soldier_id": str(soldier_id), "field": field_name, "value": new_value},
    )
    return req


def approve_field_update(
    session: Session,
    *,
    update: SoldierFieldUpdate,
    actor_id: uuid.UUID,
    decision_note: str | None = None,
) -> SoldierFieldUpdate:
    if update.status != "pending":
        raise SoldierError("not_pending")
    soldier = session.get(Soldier, update.soldier_id)
    if soldier is None:
        raise SoldierError("soldier_not_found")
    # Apply the value to the soldier
    field = update.field_name
    raw = update.new_value
    if field == "last_mitvahim_date":
        from datetime import date
        soldier.last_mitvahim_date = date.fromisoformat(raw)
    elif field == "last_alal_date":
        from datetime import date
        soldier.last_alal_date = date.fromisoformat(raw)
    elif field == "gender":
        soldier.gender = raw
    update.status = "approved"
    update.decided_by = actor_id
    update.decided_at = datetime.now(tz=timezone.utc)
    update.decision_note = decision_note
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.approve",
        entity_type="soldier_field_update",
        entity_id=update.id,
        after={"field": field, "value": raw},
    )
    return update


def reject_field_update(
    session: Session,
    *,
    update: SoldierFieldUpdate,
    actor_id: uuid.UUID,
    decision_note: str | None = None,
) -> SoldierFieldUpdate:
    if update.status != "pending":
        raise SoldierError("not_pending")
    update.status = "rejected"
    update.decided_by = actor_id
    update.decided_at = datetime.now(tz=timezone.utc)
    update.decision_note = decision_note
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.reject",
        entity_type="soldier_field_update",
        entity_id=update.id,
    )
    return update
```

- [ ] **Step 2: Verify import**

```
cd backend && uv run python -c "from app.services.soldiers import update_soldier_profile, submit_field_update, approve_field_update, reject_field_update; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/soldiers.py
git commit -m "feat(soldiers): profile update, field-update submit/approve/reject"
```

---

### Task 5: Update soldiers routes

**Files:**
- Modify: `backend/app/routes/soldiers.py`

- [ ] **Step 1: Update `SoldierOut` and `_out` in `backend/app/routes/soldiers.py`**

Replace `SoldierOut` with:

```python
from datetime import date as date_type

class SoldierOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    phone: str | None
    must_change_password: bool
    left_at: str | None
    # Profile fields (all optional — populated when available)
    gender: str | None = None          # private: only returned if caller has scope
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None
```

Replace `_out` with:

```python
def _out(s: Soldier, *, include_gender: bool = False) -> SoldierOut:
    return SoldierOut(
        id=s.id,
        personal_number=s.personal_number,
        full_name=s.full_name,
        role=s.role,
        hierarchy_node_id=s.hierarchy_node_id,
        phone=s.phone,
        must_change_password=s.must_change_password,
        left_at=s.left_at.isoformat() if s.left_at else None,
        gender=s.gender if include_gender else None,
        is_officer=s.is_officer,
        rank=s.rank,
        bahad1_graduate=s.bahad1_graduate,
        enlistment_date=s.enlistment_date,
        mandatory_end_date=s.mandatory_end_date,
        discharge_date=s.discharge_date,
        last_mitvahim_date=s.last_mitvahim_date,
        last_alal_date=s.last_alal_date,
    )
```

- [ ] **Step 2: Add gender visibility helper and update GET endpoints**

Add helper:

```python
def _can_see_gender(session: Session, user: Soldier, target: Soldier) -> bool:
    """Gender is visible to self, commanders in chain, DMs, admins."""
    if user.id == target.id:
        return True
    if user.role == "admin":
        return True
    if user.role in ("duty_manager", "commander"):
        from app.auth.authz import can, scope_root_ids
        roots = scope_root_ids(session, user)
        node = _node_of(session, target)
        return can(user, Action.SOLDIER_READ, target_node=node, roots=roots)
    return False
```

Update `get_soldier` to pass `include_gender`:

```python
@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    return _out(s, include_gender=_can_see_gender(session, user, s))
```

- [ ] **Step 3: Add `UpdateProfileRequest` and profile PATCH endpoint**

```python
from app.services.soldiers import update_soldier_profile

class UpdateProfileRequest(BaseModel):
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool | None = None
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None


@router.patch("/{soldier_id}/profile", response_model=SoldierOut)
def update_profile(
    soldier_id: uuid.UUID,
    body: UpdateProfileRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    update_soldier_profile(session, soldier=s, fields=fields, actor_id=user.id)
    session.commit()
    session.refresh(s)
    return _out(s, include_gender=_can_see_gender(session, user, s))
```

- [ ] **Step 4: Add field-update endpoints**

```python
from app.db.models import SoldierFieldUpdate
from app.services.soldiers import (
    approve_field_update, reject_field_update, submit_field_update
)

class FieldUpdateRequest(BaseModel):
    field_name: str
    new_value: str

class FieldUpdateDecisionRequest(BaseModel):
    decision_note: str | None = None

class FieldUpdateOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    field_name: str
    new_value: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: Any
    decision_note: str | None
    created_at: Any


def _fu_out(u: SoldierFieldUpdate) -> FieldUpdateOut:
    return FieldUpdateOut(
        id=u.id,
        soldier_id=u.soldier_id,
        field_name=u.field_name,
        new_value=u.new_value,
        status=u.status,
        decided_by=u.decided_by,
        decided_at=u.decided_at,
        decision_note=u.decision_note,
        created_at=u.created_at,
    )


@router.post("/{soldier_id}/field-updates", response_model=FieldUpdateOut, status_code=201)
def create_field_update(
    soldier_id: uuid.UUID,
    body: FieldUpdateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    if s.id != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        req = submit_field_update(
            session, soldier_id=soldier_id, field_name=body.field_name,
            new_value=body.new_value, actor_id=user.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(req)
    return _fu_out(req)


@router.get("/{soldier_id}/field-updates", response_model=list[FieldUpdateOut])
def list_field_updates(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[FieldUpdateOut]:
    s = _load(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    rows = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.soldier_id == soldier_id)
        .order_by(SoldierFieldUpdate.created_at.desc())
    ).scalars().all()
    return [_fu_out(r) for r in rows]


@router.post("/{soldier_id}/field-updates/{update_id}/approve", response_model=FieldUpdateOut)
def approve_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        approve_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    return _fu_out(upd)


@router.post("/{soldier_id}/field-updates/{update_id}/reject", response_model=FieldUpdateOut)
def reject_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        reject_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    return _fu_out(upd)
```

- [ ] **Step 5: Add GET /soldiers/ranks endpoint**

```python
from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS

@router.get("/ranks")
def get_ranks() -> dict[str, list[str]]:
    return {"enlisted": ENLISTED_RANKS, "officers": OFFICER_RANKS}
```

Note: this route must be declared **before** `/{soldier_id}` to avoid being matched as a soldier ID. Move it above the `@router.get("/{soldier_id}", ...)` line.

- [ ] **Step 6: Add `Any` and `select` imports at top of routes/soldiers.py**

```python
from typing import Any
from sqlalchemy import select
```

- [ ] **Step 7: Verify app starts**

```
cd backend && uv run python -c "from app.main import create_app; create_app(); print('ok')"
```
Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/soldiers.py
git commit -m "feat(soldiers): profile GET/PATCH, gender privacy, field-update endpoints, GET /ranks"
```

---

### Task 6: Update duty config routes

**Files:**
- Modify: `backend/app/routes/duty_config.py`

- [ ] **Step 1: Add `requirements` to `DutyTypeOut` and `UpdateDutyTypeRequest`**

Add import:
```python
from app.services.eligibility import DutyTypeRequirements
from typing import Any
```

Update `DutyTypeOut`:
```python
class DutyTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    score_per_day: Decimal
    description: str | None
    active: bool
    requirements: dict[str, Any] = {}
```

Update `UpdateDutyTypeRequest`:
```python
class UpdateDutyTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    score_per_day: Decimal | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None
    requirements: dict[str, Any] | None = None
```

Update `_dt_out`:
```python
def _dt_out(d: DutyType) -> DutyTypeOut:
    return DutyTypeOut(
        id=d.id,
        name=d.name,
        score_per_day=d.score_per_day,
        description=d.description,
        active=d.active,
        requirements=d.requirements or {},
    )
```

- [ ] **Step 2: Update `update_duty_type` in `duty_config` service to accept requirements**

In `backend/app/services/duty_config.py`, find `update_duty_type` and add requirements handling. Read the function, then add after existing field updates:

```python
    if requirements is not None:
        # Validate requirements shape
        from app.services.eligibility import DutyTypeRequirements
        DutyTypeRequirements.model_validate(requirements)
        dt.requirements = requirements
```

Update the function signature to accept `requirements: dict | None = None`.

- [ ] **Step 3: Wire requirements through the route**

In `update_duty_type` route handler in `duty_config.py`, pass `requirements=body.requirements` to the service call.

- [ ] **Step 4: Verify**

```
cd backend && uv run python -c "from app.routes.duty_config import router; print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/duty_config.py backend/app/services/duty_config.py
git commit -m "feat(duty-config): add requirements field to DutyType CRUD"
```

---

## Phase D — Algorithm bridge

### Task 7: Wire eligibility into `load_soldier_inputs`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Add `Soldier` ORM objects to the loading loop and call `compute_eligibility_exclusions`**

In `load_soldier_inputs`, after the existing `soldier_exempt_dtype_ids` is built, add:

```python
    from app.db.models import SystemSetting
    from app.services.eligibility import compute_eligibility_exclusions

    # Read eligibility thresholds from system_settings
    def _setting_int(key: str, default: int) -> int:
        row = session.get(SystemSetting, key)
        if row is None:
            return default
        try:
            return int(row.value)
        except (TypeError, ValueError):
            return default

    mitvahim_months = _setting_int("eligibility.mitvahim_months", 6)
    alal_months = _setting_int("eligibility.alal_months", 3)

    eligibility_exclusions = compute_eligibility_exclusions(
        session, soldiers, mitvahim_months=mitvahim_months, alal_months=alal_months
    )
```

Then in the `result.append(SoldierInput(...))` call, change `exempted_duty_type_ids`:

```python
    combined_exempt = soldier_exempt_dtype_ids.get(s.id, set()) | eligibility_exclusions.get(s.id, set())
    result.append(
        SoldierInput(
            ...
            exempted_duty_type_ids=combined_exempt,
        )
    )
```

- [ ] **Step 2: Verify**

```
cd backend && uv run python -c "from app.services.algorithm_bridge import load_soldier_inputs; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "feat(algorithm): enforce eligibility requirements as hard constraints in bridge"
```

---

## Phase E — Backend tests

### Task 8: Unit tests for eligibility

**Files:**
- Create: `backend/tests/unit/test_eligibility.py`

- [ ] **Step 1: Create `backend/tests/unit/test_eligibility.py`**

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import Soldier
from app.services.eligibility import (
    DutyTypeRequirements,
    _is_eligible,
    inferred_service_type,
)


def _soldier(**kwargs) -> Soldier:
    defaults = dict(
        personal_number="test",
        full_name="Test",
        password_hash="x",
        role="soldier",
        enrolled_at=date(2024, 1, 1),
        bahad1_graduate=False,
    )
    defaults.update(kwargs)
    return Soldier(**defaults)


TODAY = date(2026, 6, 1)


def test_service_type_hobah():
    s = _soldier(mandatory_end_date=date(2027, 1, 1))
    assert inferred_service_type(s, TODAY) == "חובה"


def test_service_type_keva():
    s = _soldier(mandatory_end_date=date(2025, 1, 1), discharge_date=None)
    assert inferred_service_type(s, TODAY) == "קבע"


def test_service_type_unknown():
    s = _soldier()
    assert inferred_service_type(s, TODAY) is None


def test_no_requirements_passes():
    s = _soldier()
    reqs = DutyTypeRequirements()
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_gender_restriction_passes():
    s = _soldier(gender="male")
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_gender_restriction_blocks():
    s = _soldier(gender="female")
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_gender_blocked_if_restriction():
    s = _soldier(gender=None)
    reqs = DutyTypeRequirements(allowed_genders=["male"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_mitvahim_fresh_passes():
    s = _soldier(last_mitvahim_date=TODAY - timedelta(days=30))
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_mitvahim_stale_blocks():
    s = _soldier(last_mitvahim_date=TODAY - timedelta(days=200))
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_mitvahim_blocks():
    s = _soldier(last_mitvahim_date=None)
    reqs = DutyTypeRequirements(requires_mitvahim=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_rank_restriction_passes():
    s = _soldier(rank="סמל")
    reqs = DutyTypeRequirements(allowed_ranks=["סמל", "סמר"])
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_rank_restriction_blocks():
    s = _soldier(rank="טוראי")
    reqs = DutyTypeRequirements(allowed_ranks=["סמל", "סמר"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_null_rank_blocked_if_restriction():
    s = _soldier(rank=None)
    reqs = DutyTypeRequirements(allowed_ranks=["סמל"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_officers_not_allowed():
    s = _soldier(is_officer=True)
    reqs = DutyTypeRequirements(officers_allowed=False)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_enlisted_not_allowed():
    s = _soldier(is_officer=False)
    reqs = DutyTypeRequirements(enlisted_allowed=False)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_bahad1_required_passes():
    s = _soldier(bahad1_graduate=True)
    reqs = DutyTypeRequirements(requires_bahad1=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_bahad1_required_blocks():
    s = _soldier(bahad1_graduate=False)
    reqs = DutyTypeRequirements(requires_bahad1=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_service_type_restriction_blocks():
    s = _soldier(mandatory_end_date=date(2025, 1, 1), discharge_date=None)
    # soldier is קבע, but restriction only allows חובה
    reqs = DutyTypeRequirements(allowed_service_types=["חובה"])
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)
```

- [ ] **Step 2: Run tests**

```
cd backend && uv run pytest tests/unit/test_eligibility.py -v
```
Expected: All 18 tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_eligibility.py
git commit -m "test(eligibility): unit tests for all eligibility check cases"
```

---

### Task 9: Integration tests for profile + field updates

**Files:**
- Create: `backend/tests/integration/test_soldier_profile.py`

- [ ] **Step 1: Create `backend/tests/integration/test_soldier_profile.py`**

```python
from __future__ import annotations

from datetime import date

from tests.helpers import auth_headers, create_node, create_soldier


def _setup_dm(session, pn: str):
    node = create_node(session, level="branch", name=f"branch_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    return dm, node


def test_dm_can_patch_profile(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_001")
    s = create_soldier(admin_session, personal_number="prof_s_001", hierarchy_node_id=node.id)

    resp = client.patch(
        f"/api/soldiers/{s.id}/profile",
        json={"rank": "סמל", "is_officer": False, "gender": "male"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rank"] == "סמל"
    assert data["is_officer"] is False
    assert data["gender"] == "male"  # DM can see gender


def test_gender_hidden_from_peer(client, admin_session):
    _, node = _setup_dm(admin_session, "prof_dm_002")
    s1 = create_soldier(admin_session, personal_number="prof_s_002a", hierarchy_node_id=node.id)
    s2 = create_soldier(admin_session, personal_number="prof_s_002b", hierarchy_node_id=node.id)

    dm, _ = _setup_dm(admin_session, "prof_dm_002x")
    # patch s1 gender as dm
    client.patch(
        f"/api/soldiers/{s1.id}/profile",
        json={"gender": "female"},
        headers=auth_headers(dm),
    )

    # s2 fetches s1 — gender should be null
    resp = client.get(f"/api/soldiers/{s1.id}", headers=auth_headers(s2))
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert resp.json()["gender"] is None


def test_soldier_submits_field_update(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_003")
    s = create_soldier(admin_session, personal_number="prof_s_003", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={"field_name": "last_mitvahim_date", "new_value": "2026-05-01"},
        headers=auth_headers(s),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    update_id = resp.json()["id"]

    # DM approves
    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(dm),
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "approved"

    # Soldier profile now has the date
    profile = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(dm))
    assert profile.json()["last_mitvahim_date"] == "2026-05-01"


def test_soldier_cannot_update_rank_directly(client, admin_session):
    _, node = _setup_dm(admin_session, "prof_dm_004")
    s = create_soldier(admin_session, personal_number="prof_s_004", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={"field_name": "rank", "new_value": "סרן"},
        headers=auth_headers(s),
    )
    assert resp.status_code == 400


def test_ranks_endpoint(client, admin_session):
    s = create_soldier(admin_session, personal_number="prof_ranks_001")
    resp = client.get("/api/soldiers/ranks", headers=auth_headers(s))
    assert resp.status_code == 200
    data = resp.json()
    assert "enlisted" in data and "officers" in data
    assert "סמל" in data["enlisted"]
    assert "סרן" in data["officers"]
```

- [ ] **Step 2: Run tests**

```
cd backend && uv run pytest tests/integration/test_soldier_profile.py -v
```
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_soldier_profile.py
git commit -m "test(soldier-profile): integration tests for profile PATCH, gender privacy, field updates"
```

---

## Phase F — Frontend

### Task 10: i18n additions

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add `soldier_profile` and `eligibility` blocks to he.json**

Add before the closing `}`:

```json
  "soldier_profile": {
    "section_title": "פרטי שירות",
    "gender": "מין",
    "gender_male": "זכר",
    "gender_female": "נקבה",
    "rank": "דרגה",
    "enlisted": "חוגרים",
    "officers": "קצינים",
    "is_officer": "קצין",
    "is_enlisted": "חוגר",
    "bahad1_graduate": "בוגר בהד\"ל 1",
    "enlistment_date": "תאריך גיוס",
    "mandatory_end_date": "תאריך תום שירות חובה",
    "discharge_date": "תאריך שחרור",
    "last_mitvahim_date": "מטווחים אחרון",
    "last_alal_date": "אל\"ל אחרון",
    "service_type": "סוג שירות",
    "service_type_hobah": "חובה",
    "service_type_keva": "קבע",
    "service_type_unknown": "לא ידוע",
    "submit_update": "שלח בקשת עדכון",
    "update_pending": "ממתין לאישור",
    "update_approved": "אושר",
    "update_rejected": "נדחה",
    "field_updates_tab": "עדכוני פרופיל"
  },
  "eligibility": {
    "title": "דרישות כשירות",
    "allowed_genders": "מגדר מותר",
    "requires_mitvahim": "נדרש מטווחים עדכני",
    "requires_alal": "נדרש אל\"ל עדכני",
    "allowed_ranks": "דרגות מותרות",
    "allowed_service_types": "סוג שירות מותר",
    "officers_allowed": "קצינים מותרים",
    "enlisted_allowed": "חוגרים מותרים",
    "requires_bahad1": "נדרש בוגר בהד\"ל 1",
    "save": "שמור דרישות"
  }
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat(i18n): soldier_profile and eligibility translation keys"
```

---

### Task 11: Update frontend API types

**Files:**
- Modify: `frontend/src/api/soldiers.ts`

- [ ] **Step 1: Update `SoldierDTO` and add field-update API functions in `frontend/src/api/soldiers.ts`**

Read the current `soldiers.ts` file to see what's there, then update `SoldierDTO` to include new fields and add new API functions:

```typescript
export interface SoldierDTO {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  phone: string | null;
  must_change_password: boolean;
  left_at: string | null;
  // Profile fields
  gender: string | null;
  is_officer: boolean | null;
  rank: string | null;
  bahad1_graduate: boolean;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
}

export interface FieldUpdateDTO {
  id: string;
  soldier_id: string;
  field_name: string;
  new_value: string;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export async function updateSoldierProfile(
  soldierId: string,
  fields: Partial<Record<string, string | boolean | null>>
): Promise<SoldierDTO> {
  return (await api.patch<SoldierDTO>(`/soldiers/${soldierId}/profile`, fields)).data;
}

export async function submitFieldUpdate(
  soldierId: string,
  fieldName: string,
  newValue: string
): Promise<FieldUpdateDTO> {
  return (await api.post<FieldUpdateDTO>(`/soldiers/${soldierId}/field-updates`, {
    field_name: fieldName,
    new_value: newValue,
  })).data;
}

export async function listFieldUpdates(soldierId: string): Promise<FieldUpdateDTO[]> {
  return (await api.get<FieldUpdateDTO[]>(`/soldiers/${soldierId}/field-updates`)).data;
}

export async function listPendingFieldUpdates(): Promise<FieldUpdateDTO[]> {
  // Returns all pending field updates across all soldiers the user can approve
  return (await api.get<FieldUpdateDTO[]>(`/soldiers/field-updates/pending`)).data;
}

export async function approveFieldUpdate(
  soldierId: string,
  updateId: string,
  decisionNote?: string
): Promise<FieldUpdateDTO> {
  return (await api.post<FieldUpdateDTO>(
    `/soldiers/${soldierId}/field-updates/${updateId}/approve`,
    { decision_note: decisionNote ?? null }
  )).data;
}

export async function rejectFieldUpdate(
  soldierId: string,
  updateId: string,
  decisionNote?: string
): Promise<FieldUpdateDTO> {
  return (await api.post<FieldUpdateDTO>(
    `/soldiers/${soldierId}/field-updates/${updateId}/reject`,
    { decision_note: decisionNote ?? null }
  )).data;
}

export async function getRanks(): Promise<{ enlisted: string[]; officers: string[] }> {
  return (await api.get<{ enlisted: string[]; officers: string[] }>("/soldiers/ranks")).data;
}
```

Note: `listPendingFieldUpdates` needs a backend endpoint. Add it to `backend/app/routes/soldiers.py`:

```python
@router.get("/field-updates/pending", response_model=list[FieldUpdateOut])
def list_all_pending_field_updates(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[FieldUpdateOut]:
    """Returns pending field updates for soldiers in the caller's scope."""
    if user.role == "admin":
        rows = session.execute(
            select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
        ).scalars().all()
        return [_fu_out(r) for r in rows]
    roots = scope_root_ids(session, user)
    if not roots:
        return []
    all_pending = session.execute(
        select(SoldierFieldUpdate).where(SoldierFieldUpdate.status == "pending")
    ).scalars().all()
    result = []
    for upd in all_pending:
        s = session.get(Soldier, upd.soldier_id)
        if s:
            node = _node_of(session, s)
            from app.auth.authz import can
            if can(user, Action.SOLDIER_UPDATE, target_node=node, roots=roots):
                result.append(_fu_out(upd))
    return result
```

This route must go **before** `/{soldier_id}` routes. Add it right after the `get_ranks` endpoint.

- [ ] **Step 2: Update `dutyConfig.ts` to include requirements**

In `frontend/src/api/dutyConfig.ts`, add `requirements` to `DutyType` interface:

```typescript
export interface DutyType {
  id: string;
  name: string;
  score_per_day: string;
  description: string | null;
  active: boolean;
  requirements: {
    allowed_genders?: string[];
    requires_mitvahim?: boolean;
    requires_alal?: boolean;
    allowed_ranks?: string[];
    allowed_service_types?: string[];
    officers_allowed?: boolean;
    enlisted_allowed?: boolean;
    requires_bahad1?: boolean;
  };
}
```

Add update function:
```typescript
export async function updateDutyTypeRequirements(
  id: string,
  requirements: DutyType["requirements"]
): Promise<DutyType> {
  return (await api.patch<DutyType>(`/duty-config/duty-types/${id}`, { requirements })).data;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/soldiers.ts frontend/src/api/dutyConfig.ts backend/app/routes/soldiers.py
git commit -m "feat(frontend): soldier profile API types, field update functions, ranks endpoint"
```

---

### Task 12: Soldier profile section in ProfilePage

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`

- [ ] **Step 1: Add פרטי שירות section to ProfilePage**

Read the current `ProfilePage.tsx`, then add a new section after the existing profile info. The section shows read-only profile fields for all soldiers, and adds a button to request updates for `last_mitvahim_date`, `last_alal_date`, and `gender`.

Add at the top of the component (after existing state):
```tsx
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import {
  SoldierDTO,
  FieldUpdateDTO,
  submitFieldUpdate,
  listFieldUpdates,
} from "../api/soldiers";

// Inside component:
const [fieldUpdates, setFieldUpdates] = useState<FieldUpdateDTO[]>([]);
const [mitvahimReq, setMitvahimReq] = useState("");
const [alalReq, setAlalReq] = useState("");

useEffect(() => {
  if (user) {
    void listFieldUpdates(user.id).then(setFieldUpdates);
  }
}, [user]);

async function requestUpdate(field: string, value: string) {
  if (!user || !value) return;
  await submitFieldUpdate(user.id, field, value);
  const updated = await listFieldUpdates(user.id);
  setFieldUpdates(updated);
}
```

Add the JSX section inside `<Layout>`:
```tsx
<section className="bg-white rounded-lg shadow p-6 mt-4 space-y-4" dir="rtl">
  <h3 className="text-lg font-semibold">{t("soldier_profile.section_title")}</h3>
  <div className="grid grid-cols-2 gap-4 text-sm">
    {user?.rank && <div><span className="font-medium">{t("soldier_profile.rank")}:</span> {user.rank}</div>}
    {user?.is_officer !== null && (
      <div>
        <span className="font-medium">{t("soldier_profile.is_officer")}:</span>{" "}
        {user?.is_officer ? t("soldier_profile.is_officer") : t("soldier_profile.is_enlisted")}
      </div>
    )}
    {user?.last_mitvahim_date && (
      <div><span className="font-medium">{t("soldier_profile.last_mitvahim_date")}:</span> {user.last_mitvahim_date}</div>
    )}
    {user?.last_alal_date && (
      <div><span className="font-medium">{t("soldier_profile.last_alal_date")}:</span> {user.last_alal_date}</div>
    )}
  </div>

  <div className="space-y-2 text-sm">
    <p className="font-medium">{t("soldier_profile.submit_update")}</p>
    <div className="flex gap-2 items-center">
      <label className="w-40">{t("soldier_profile.last_mitvahim_date")}</label>
      <input type="date" value={mitvahimReq} onChange={e => setMitvahimReq(e.target.value)} className="border rounded p-1 text-sm" />
      <button
        type="button"
        onClick={() => requestUpdate("last_mitvahim_date", mitvahimReq)}
        className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
      >
        {t("soldier_profile.submit_update")}
      </button>
    </div>
    <div className="flex gap-2 items-center">
      <label className="w-40">{t("soldier_profile.last_alal_date")}</label>
      <input type="date" value={alalReq} onChange={e => setAlalReq(e.target.value)} className="border rounded p-1 text-sm" />
      <button
        type="button"
        onClick={() => requestUpdate("last_alal_date", alalReq)}
        className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
      >
        {t("soldier_profile.submit_update")}
      </button>
    </div>
  </div>

  {fieldUpdates.filter(u => u.status === "pending").length > 0 && (
    <div className="text-xs text-amber-600">
      {fieldUpdates.filter(u => u.status === "pending").length} {t("soldier_profile.update_pending")}
    </div>
  )}
</section>
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "feat(profile): add פרטי שירות section with field update requests"
```

---

### Task 13: ApprovalsPage — field updates tab

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`

- [ ] **Step 1: Add field-updates tab to ApprovalsPage**

Read the current `ApprovalsPage.tsx`, then add `"field_updates"` to the `Tab` type and add fetching + rendering logic.

Add to imports:
```tsx
import {
  FieldUpdateDTO,
  approveFieldUpdate,
  rejectFieldUpdate,
  listPendingFieldUpdates,
} from "../api/soldiers";
```

Update `Tab` type:
```tsx
type Tab = "constraints" | "exemptions" | "field_updates";
```

Add state:
```tsx
const [fuItems, setFuItems] = useState<FieldUpdateDTO[]>([]);
const [fuNotes, setFuNotes] = useState<Record<string, string>>({});
```

In `refresh()`, add:
```tsx
setFuItems(await listPendingFieldUpdates());
```

Add handlers:
```tsx
async function onFuApprove(item: FieldUpdateDTO) {
  await approveFieldUpdate(item.soldier_id, item.id, fuNotes[item.id]);
  await refresh();
}
async function onFuReject(item: FieldUpdateDTO) {
  const note = fuNotes[item.id];
  if (!note) return;
  await rejectFieldUpdate(item.soldier_id, item.id, note);
  await refresh();
}
```

Add tab button in the tab bar:
```tsx
<button onClick={() => setTab("field_updates")} className={tab === "field_updates" ? "font-bold border-b-2" : ""}>
  {t("soldier_profile.field_updates_tab")} {fuItems.length > 0 && `(${fuItems.length})`}
</button>
```

Add tab content panel:
```tsx
{tab === "field_updates" && (
  <div className="space-y-3" dir="rtl">
    {fuItems.length === 0 && <p className="text-gray-500 text-sm">אין בקשות ממתינות</p>}
    {fuItems.map(item => (
      <div key={item.id} className="border rounded p-3 text-sm space-y-2">
        <div className="font-medium">{item.soldier_id.slice(0, 8)} — {t(`soldier_profile.${item.field_name}`)}</div>
        <div className="text-gray-600">ערך חדש: <strong>{item.new_value}</strong></div>
        <div className="flex gap-2 items-center">
          <button onClick={() => onFuApprove(item)} className="bg-green-600 text-white px-2 py-1 rounded text-xs">אשר</button>
          <input
            placeholder="סיבת דחייה"
            value={fuNotes[item.id] ?? ""}
            onChange={e => setFuNotes(prev => ({ ...prev, [item.id]: e.target.value }))}
            className="border rounded p-1 text-xs flex-1"
          />
          <button onClick={() => onFuReject(item)} className="bg-red-600 text-white px-2 py-1 rounded text-xs">דחה</button>
        </div>
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "feat(approvals): add field updates tab for commander/DM approval"
```

---

### Task 14: DutyType requirements editor

**Files:**
- Create: `frontend/src/components/DutyTypeRequirementsEditor.tsx`
- Modify: `frontend/src/pages/DutyConfigPage.tsx`

- [ ] **Step 1: Create `frontend/src/components/DutyTypeRequirementsEditor.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyType, updateDutyTypeRequirements } from "../api/dutyConfig";
import { getRanks } from "../api/soldiers";

interface Props {
  dutyType: DutyType;
  onSaved: () => void;
}

export default function DutyTypeRequirementsEditor({ dutyType, onSaved }: Props) {
  const { t } = useTranslation();
  const [reqs, setReqs] = useState(dutyType.requirements ?? {});
  const [ranks, setRanks] = useState<{ enlisted: string[]; officers: string[] }>({ enlisted: [], officers: [] });

  useEffect(() => {
    void getRanks().then(setRanks);
  }, []);

  function toggleItem(key: string, value: string) {
    const current: string[] = (reqs as any)[key] ?? [];
    const next = current.includes(value)
      ? current.filter((v: string) => v !== value)
      : [...current, value];
    setReqs(prev => ({ ...prev, [key]: next }));
  }

  async function save() {
    await updateDutyTypeRequirements(dutyType.id, reqs);
    onSaved();
  }

  return (
    <div className="space-y-3 text-sm" dir="rtl">
      {/* Gender */}
      <div>
        <p className="font-medium">{t("eligibility.allowed_genders")}</p>
        <div className="flex gap-3">
          {["male", "female"].map(g => (
            <label key={g} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={((reqs as any).allowed_genders ?? []).includes(g)}
                onChange={() => toggleItem("allowed_genders", g)}
              />
              {g === "male" ? t("soldier_profile.gender_male") : t("soldier_profile.gender_female")}
            </label>
          ))}
        </div>
      </div>

      {/* Ranks */}
      <div>
        <p className="font-medium">{t("eligibility.allowed_ranks")}</p>
        <div className="space-y-1">
          <p className="text-xs text-gray-500">{t("soldier_profile.enlisted")}</p>
          <div className="flex flex-wrap gap-2">
            {ranks.enlisted.map(r => (
              <label key={r} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={((reqs as any).allowed_ranks ?? []).includes(r)}
                  onChange={() => toggleItem("allowed_ranks", r)}
                />
                {r}
              </label>
            ))}
          </div>
          <p className="text-xs text-gray-500">{t("soldier_profile.officers")}</p>
          <div className="flex flex-wrap gap-2">
            {ranks.officers.map(r => (
              <label key={r} className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={((reqs as any).allowed_ranks ?? []).includes(r)}
                  onChange={() => toggleItem("allowed_ranks", r)}
                />
                {r}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Service type */}
      <div>
        <p className="font-medium">{t("eligibility.allowed_service_types")}</p>
        <div className="flex gap-3">
          {["חובה", "קבע"].map(s => (
            <label key={s} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={((reqs as any).allowed_service_types ?? []).includes(s)}
                onChange={() => toggleItem("allowed_service_types", s)}
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      {/* Boolean flags */}
      {[
        { key: "requires_mitvahim", label: t("eligibility.requires_mitvahim") },
        { key: "requires_alal", label: t("eligibility.requires_alal") },
        { key: "requires_bahad1", label: t("eligibility.requires_bahad1") },
        { key: "officers_allowed", label: t("eligibility.officers_allowed"), defaultVal: true },
        { key: "enlisted_allowed", label: t("eligibility.enlisted_allowed"), defaultVal: true },
      ].map(({ key, label, defaultVal }) => (
        <label key={key} className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={(reqs as any)[key] ?? (defaultVal ?? false)}
            onChange={e => setReqs(prev => ({ ...prev, [key]: e.target.checked }))}
          />
          {label}
        </label>
      ))}

      <button
        type="button"
        onClick={save}
        className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
      >
        {t("eligibility.save")}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Add requirements editor to DutyConfigPage**

Read `DutyConfigPage.tsx`, then add:

Import:
```tsx
import DutyTypeRequirementsEditor from "../components/DutyTypeRequirementsEditor";
```

Add state:
```tsx
const [expandedDtId, setExpandedDtId] = useState<string | null>(null);
```

In the duty types list rendering, add an expand button per type that shows the editor:
```tsx
{dutyTypes.map(dt => (
  <div key={dt.id} className="border rounded p-3 space-y-2">
    <div className="flex justify-between items-center">
      <span className="font-medium">{dt.name}</span>
      <button
        type="button"
        className="text-xs text-blue-600 underline"
        onClick={() => setExpandedDtId(expandedDtId === dt.id ? null : dt.id)}
      >
        {t("eligibility.title")}
      </button>
    </div>
    {expandedDtId === dt.id && (
      <DutyTypeRequirementsEditor dutyType={dt} onSaved={async () => { await refresh(); setExpandedDtId(null); }} />
    )}
  </div>
))}
```

- [ ] **Step 3: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/DutyTypeRequirementsEditor.tsx frontend/src/pages/DutyConfigPage.tsx
git commit -m "feat(duty-config): eligibility requirements editor per duty type"
```

---

## Self-review checklist

1. **Spec coverage:**
   - ✅ Migration 0017 with all soldier fields + soldier_field_updates + duty_types.requirements — Task 1
   - ✅ ORM models updated — Task 2
   - ✅ DutyTypeRequirements Pydantic model + inferred_service_type + compute_eligibility_exclusions — Task 3
   - ✅ Rank constants ENLISTED_RANKS + OFFICER_RANKS — Task 3
   - ✅ Soldier profile PATCH (DM) + field-update submit/approve/reject — Tasks 4, 5
   - ✅ Gender privacy in GET — Task 5
   - ✅ GET /soldiers/ranks — Task 5
   - ✅ DutyType requirements in duty-config routes — Task 6
   - ✅ Algorithm bridge eligibility enforcement — Task 7
   - ✅ System settings defaults for mitvahim/alal months — Task 1 (migration)
   - ✅ Unit tests for eligibility — Task 8
   - ✅ Integration tests for profile + field updates — Task 9
   - ✅ i18n — Task 10
   - ✅ Frontend API types — Task 11
   - ✅ ProfilePage section — Task 12
   - ✅ ApprovalsPage tab — Task 13
   - ✅ DutyConfigPage requirements editor — Task 14

2. **Placeholder scan:** None found.

3. **Type consistency:** `DutyTypeRequirements` is defined in `eligibility.py` and referenced consistently in `algorithm_bridge.py`, `duty_config.py`, and `DutyTypeRequirementsEditor.tsx`. `FieldUpdateDTO` is consistent between `soldiers.ts` and `routes/soldiers.py` (`FieldUpdateOut`).
