# Slice 3: Duty Configuration & Exemptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add duty-manager configuration (`duty_types`, `duty_locations`, `exemption_types`, `exemption_duty_type_map`) and the scoped exemption system (`soldier_exemptions`) on top of Slice 2, with full RBAC, audit, and Hebrew RTL UI.

**Architecture:** Global config tables are guarded by a coarse `require_roles("duty_manager","admin")` gate; per-soldier exemptions go through the existing `app/auth/authz.py` scope engine (two new actions). Pure service functions mutate + `write_audit` in one transaction and raise domain errors; thin routes parse → load → authorize → call service → return Pydantic. Frontend mirrors the Slice 2 axios/page/i18n patterns.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (MappedAsDataclass), Alembic, Pydantic v2, Postgres 16, pytest + testcontainers, React 18 + Vite + TS, react-i18next, axios, Playwright.

---

## Spec coverage

Implements `docs/superpowers/specs/2026-05-29-slice-3-duty-config-and-exemptions-design.md`: design-doc §4.1 tables `duty_types`, `duty_locations`, `exemption_types`, `exemption_duty_type_map`, `soldier_exemptions`; §5.2 rows for grant/revoke + view exemptions, edit duty-type scoring, edit exemption↔duty-type mapping. Out of scope: assignments, overrides, scoring, constraints, algorithm.

## Conventions

- Backend commands run from `backend/` with `uv`. **Use `git -C ..` for commits** so the shell stays in `backend/` (a bare `cd ..` leaves you where `uv run` finds no project).
- Frontend commands run from `frontend/` with `pnpm`.
- "Run X. Expected: Y." — actually run it and confirm before continuing.
- TDD: write the failing test, see it fail, implement, see it pass, commit. One small commit per task.
- Branch `slice-3-duty-config-and-exemptions` (already created off `slice-2-hierarchy-and-soldiers`). Migrations continue at `0007`.
- MappedAsDataclass ordering: fields **without** a default must precede fields **with** a default; `init=False` columns (PK, timestamps) are excluded from `__init__` so their position is free.

## File structure

```
backend/
├── alembic/versions/
│   ├── 0007_create_duty_types.py
│   ├── 0008_create_duty_locations.py
│   ├── 0009_create_exemption_types.py
│   ├── 0010_create_exemption_duty_type_map.py
│   └── 0011_create_soldier_exemptions.py
├── app/
│   ├── db/models.py                 # +DutyType, DutyLocation, ExemptionType, ExemptionDutyTypeMap, SoldierExemption
│   ├── auth/authz.py                # +EXEMPTION_GRANT/READ
│   ├── services/{duty_config,exemptions}.py
│   ├── routes/{duty_config,exemptions}.py
│   └── main.py                      # wire two routers
└── tests/
    ├── unit/{test_duty_config_service,test_exemptions_service}.py
    └── integration/{test_duty_config_api,test_exemptions_api,test_rbac_matrix(edit)}.py

frontend/
├── src/
│   ├── api/{dutyConfig,exemptions}.ts
│   ├── pages/DutyConfigPage.tsx
│   ├── components/{Layout(edit),ExemptionsPanel}.tsx
│   ├── pages/{ProfilePage,TeamHierarchyPage}(edit).tsx
│   ├── App.tsx(edit)
│   └── i18n/he.json(edit)
└── tests/e2e/{duty_config,exemptions}.spec.ts
```

---

## Phase A — Schema (migrations 0007–0011)

### Task 1: Migrations for the four global config tables

**Files:**
- Create: `backend/alembic/versions/0007_create_duty_types.py`
- Create: `backend/alembic/versions/0008_create_duty_locations.py`
- Create: `backend/alembic/versions/0009_create_exemption_types.py`
- Create: `backend/alembic/versions/0010_create_exemption_duty_type_map.py`

- [ ] **Step 1: Create `0007_create_duty_types.py`**

```python
"""create duty_types

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-29
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("score_per_day", sa.Numeric(6, 2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("duty_types")
```

- [ ] **Step 2: Create `0008_create_duty_locations.py`** (identical header pattern, `revision="0008"`, `down_revision="0007"`)

```python
def upgrade() -> None:
    op.create_table(
        "duty_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("duty_locations")
```

- [ ] **Step 3: Create `0009_create_exemption_types.py`** (`revision="0009"`, `down_revision="0008"`)

```python
def upgrade() -> None:
    op.create_table(
        "exemption_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("exemption_types")
```

- [ ] **Step 4: Create `0010_create_exemption_duty_type_map.py`** (`revision="0010"`, `down_revision="0009"`)

```python
def upgrade() -> None:
    op.create_table(
        "exemption_duty_type_map",
        sa.Column("exemption_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exemption_types.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("duty_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("duty_types.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("exemption_duty_type_map")
```

- [ ] **Step 5: Apply via the suite bootstrap**

Run: `uv run pytest tests/integration/test_audit_append_only.py -q`
Expected: `3 passed` (proves `alembic upgrade head` including 0007–0010 applies cleanly).

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/alembic/versions/0007_create_duty_types.py backend/alembic/versions/0008_create_duty_locations.py backend/alembic/versions/0009_create_exemption_types.py backend/alembic/versions/0010_create_exemption_duty_type_map.py
git -C .. commit -m "feat(db): duty_types, duty_locations, exemption_types, exemption_duty_type_map"
```

---

### Task 2: Migration 0011 — `soldier_exemptions`

**Files:**
- Create: `backend/alembic/versions/0011_create_soldier_exemptions.py`

- [ ] **Step 1: Create the migration** (`revision="0011"`, `down_revision="0010"`, same imports/header as 0007)

```python
def upgrade() -> None:
    op.create_table(
        "soldier_exemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exemption_type_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exemption_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("granted_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_soldier_exemptions_soldier_start", "soldier_exemptions", ["soldier_id", "start_date"])


def downgrade() -> None:
    op.drop_table("soldier_exemptions")
```

- [ ] **Step 2: Apply**

Run: `uv run pytest tests/integration/test_audit_append_only.py -q`
Expected: `3 passed`.

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/alembic/versions/0011_create_soldier_exemptions.py
git -C .. commit -m "feat(db): soldier_exemptions table"
```

---

## Phase B — ORM models

### Task 3: Add five ORM models to `models.py`

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Extend the imports**

Add `from decimal import Decimal` near the top imports, and add `Numeric` to the sqlalchemy import line:

```python
from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, Text, text
```

- [ ] **Step 2: Append the models** to the end of `backend/app/db/models.py`

```python
class DutyType(Base):
    __tablename__ = "duty_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text, unique=True)
    score_per_day: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyLocation(Base):
    __tablename__ = "duty_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text)
    base: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ExemptionType(Base):
    __tablename__ = "exemption_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ExemptionDutyTypeMap(Base):
    __tablename__ = "exemption_duty_type_map"

    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="CASCADE"), primary_key=True
    )
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="CASCADE"), primary_key=True
    )


class SoldierExemption(Base):
    __tablename__ = "soldier_exemptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 3: Verify the import graph**

Run: `uv run python -c "from app.db.models import DutyType, DutyLocation, ExemptionType, ExemptionDutyTypeMap, SoldierExemption; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/db/models.py
git -C .. commit -m "feat(db): ORM models for duty config + soldier exemptions"
```

---

## Phase C — Authorization extension

### Task 4: Add exemption actions to the authz engine

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/tests/unit/test_authz.py`

- [ ] **Step 1: Add failing tests** — append to `backend/tests/unit/test_authz.py`:

```python
def test_commander_can_grant_and_read_exemptions_in_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="7100001", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    assert authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots)
    assert authz.can(cmd, authz.Action.EXEMPTION_READ, target_node=b, roots=roots)
    assert not authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=other, roots=roots)


def test_duty_manager_can_grant_exemptions_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    dm = create_soldier(admin_session, personal_number="7100002", role="duty_manager", hierarchy_node_id=b.id)
    roots = _roots(admin_session, dm)
    assert authz.can(dm, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots)


def test_plain_soldier_cannot_grant_exemptions(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(admin_session, personal_number="7100003", role="soldier", hierarchy_node_id=d.id)
    roots = _roots(admin_session, s)
    assert not authz.can(s, authz.Action.EXEMPTION_GRANT, target_node=d, roots=roots)
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: EXEMPTION_GRANT`).

Run: `uv run pytest tests/unit/test_authz.py -q`

- [ ] **Step 3: Edit `backend/app/auth/authz.py`**

Add two attributes to `class Action`:

```python
    EXEMPTION_GRANT = "exemption.grant"
    EXEMPTION_READ = "exemption.read"
```

Add both to the DM set and the commander set:

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
}
_COMMANDER_ACTIONS = {
    Action.SOLDIER_READ,
    Action.HIERARCHY_READ,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
}
```

> Admin already returns `True` for every action via the `role == "admin"` short-circuit — no change needed there.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_authz.py -q`
Expected: all pass (the 4 pre-existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/auth/authz.py backend/tests/unit/test_authz.py
git -C .. commit -m "feat(authz): EXEMPTION_GRANT/READ actions for commander + duty_manager"
```

---

## Phase D — Duty config service (TDD)

### Task 5: duty type + location operations

**Files:**
- Create: `backend/app/services/duty_config.py`
- Create: `backend/tests/unit/test_duty_config_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_duty_config_service.py
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.duty_config import (
    DutyConfigError,
    create_duty_type,
    create_location,
    set_duty_type_active,
    update_duty_type,
)


def test_create_duty_type(admin_session):
    dt = create_duty_type(admin_session, name="שמירה", score_per_day=Decimal("1.50"), actor_id=None)
    admin_session.commit()
    assert dt.name == "שמירה"
    assert dt.active is True
    row = admin_session.execute(
        text("SELECT action FROM audit_log WHERE action='duty_type.create' LIMIT 1")
    ).first()
    assert row is not None


def test_create_duty_type_rejects_duplicate_name(admin_session):
    create_duty_type(admin_session, name="ניקיון", score_per_day=Decimal("1.00"), actor_id=None)
    admin_session.flush()
    with pytest.raises(DutyConfigError):
        create_duty_type(admin_session, name="ניקיון", score_per_day=Decimal("2.00"), actor_id=None)


def test_create_duty_type_rejects_negative_score(admin_session):
    with pytest.raises(DutyConfigError):
        create_duty_type(admin_session, name="x", score_per_day=Decimal("-1"), actor_id=None)


def test_update_and_deactivate_duty_type(admin_session):
    dt = create_duty_type(admin_session, name="מטבח", score_per_day=Decimal("1.00"), actor_id=None)
    admin_session.flush()
    update_duty_type(admin_session, duty_type=dt, name="מטבח לילה", score_per_day=Decimal("2.50"),
                     description="לילה", actor_id=None)
    set_duty_type_active(admin_session, duty_type=dt, active=False, actor_id=None)
    admin_session.commit()
    assert dt.name == "מטבח לילה"
    assert dt.score_per_day == Decimal("2.50")
    assert dt.active is False


def test_create_location(admin_session):
    loc = create_location(admin_session, name="עמדת שער", base="בסיס דרום", actor_id=None)
    admin_session.commit()
    assert loc.name == "עמדת שער"
    assert loc.base == "בסיס דרום"
    assert loc.active is True
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

Run: `uv run pytest tests/unit/test_duty_config_service.py -q`

- [ ] **Step 3: Create `backend/app/services/duty_config.py`**

```python
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyLocation, DutyType, ExemptionDutyTypeMap, ExemptionType, SoldierExemption


class DutyConfigError(Exception):
    """Raised on an invalid duty-config operation."""


def create_duty_type(
    session: Session, *, name: str, score_per_day: Decimal, description: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyType:
    if score_per_day < 0:
        raise DutyConfigError("score_per_day must be >= 0")
    if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
        raise DutyConfigError("name_taken")
    dt = DutyType(name=name, score_per_day=score_per_day, description=description)
    session.add(dt)
    session.flush()
    write_audit(session, actor_id=actor_id, action="duty_type.create", entity_type="duty_type",
                entity_id=dt.id, after={"name": name, "score_per_day": str(score_per_day)})
    return dt


def update_duty_type(
    session: Session, *, duty_type: DutyType, name: str | None, score_per_day: Decimal | None,
    description: str | None, actor_id: uuid.UUID | None = None,
) -> DutyType:
    before = {"name": duty_type.name, "score_per_day": str(duty_type.score_per_day),
              "description": duty_type.description}
    if score_per_day is not None:
        if score_per_day < 0:
            raise DutyConfigError("score_per_day must be >= 0")
        duty_type.score_per_day = score_per_day
    if name is not None and name != duty_type.name:
        if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
            raise DutyConfigError("name_taken")
        duty_type.name = name
    if description is not None:
        duty_type.description = description
    write_audit(session, actor_id=actor_id, action="duty_type.update", entity_type="duty_type",
                entity_id=duty_type.id, before=before,
                after={"name": duty_type.name, "score_per_day": str(duty_type.score_per_day),
                       "description": duty_type.description})
    return duty_type


def set_duty_type_active(
    session: Session, *, duty_type: DutyType, active: bool, actor_id: uuid.UUID | None = None
) -> DutyType:
    before = {"active": duty_type.active}
    duty_type.active = active
    write_audit(session, actor_id=actor_id, action="duty_type.set_active", entity_type="duty_type",
                entity_id=duty_type.id, before=before, after={"active": active})
    return duty_type


def create_location(
    session: Session, *, name: str, base: str | None = None, actor_id: uuid.UUID | None = None
) -> DutyLocation:
    loc = DutyLocation(name=name, base=base)
    session.add(loc)
    session.flush()
    write_audit(session, actor_id=actor_id, action="duty_location.create", entity_type="duty_location",
                entity_id=loc.id, after={"name": name, "base": base})
    return loc


def update_location(
    session: Session, *, location: DutyLocation, name: str | None, base: str | None,
    actor_id: uuid.UUID | None = None,
) -> DutyLocation:
    before = {"name": location.name, "base": location.base}
    if name is not None:
        location.name = name
    if base is not None:
        location.base = base
    write_audit(session, actor_id=actor_id, action="duty_location.update", entity_type="duty_location",
                entity_id=location.id, before=before, after={"name": location.name, "base": location.base})
    return location


def set_location_active(
    session: Session, *, location: DutyLocation, active: bool, actor_id: uuid.UUID | None = None
) -> DutyLocation:
    before = {"active": location.active}
    location.active = active
    write_audit(session, actor_id=actor_id, action="duty_location.set_active", entity_type="duty_location",
                entity_id=location.id, before=before, after={"active": active})
    return location
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_duty_config_service.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/duty_config.py backend/tests/unit/test_duty_config_service.py
git -C .. commit -m "feat(duty-config): duty type + location service ops"
```

---

### Task 6: exemption types + exemption↔duty-type map

**Files:**
- Modify: `backend/app/services/duty_config.py`
- Modify: `backend/tests/unit/test_duty_config_service.py`

- [ ] **Step 1: Add failing tests** — append:

```python
from decimal import Decimal as _D

from app.services.duty_config import (
    create_exemption_type,
    delete_exemption_type,
    map_exemption_to_duty_type,
    set_exemption_duty_types,
    unmap_exemption_from_duty_type,
)


def test_create_exemption_type_and_map(admin_session):
    et = create_exemption_type(admin_session, name="פטור רפואי", actor_id=None)
    dt = create_duty_type(admin_session, name="שמירה-מ", score_per_day=_D("1"), actor_id=None)
    admin_session.flush()
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None)
    # idempotent: second call does not raise or duplicate
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None)
    admin_session.commit()
    from app.db.models import ExemptionDutyTypeMap
    rows = admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id).all()
    assert len(rows) == 1


def test_set_exemption_duty_types_diffs(admin_session):
    et = create_exemption_type(admin_session, name="פטור גב", actor_id=None)
    d1 = create_duty_type(admin_session, name="ניקיון-מ", score_per_day=_D("1"), actor_id=None)
    d2 = create_duty_type(admin_session, name="מטבח-מ", score_per_day=_D("1"), actor_id=None)
    admin_session.flush()
    set_exemption_duty_types(admin_session, exemption_type_id=et.id, duty_type_ids=[d1.id], actor_id=None)
    set_exemption_duty_types(admin_session, exemption_type_id=et.id, duty_type_ids=[d2.id], actor_id=None)
    admin_session.commit()
    from app.db.models import ExemptionDutyTypeMap
    rows = {r.duty_type_id for r in admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id)}
    assert rows == {d2.id}


def test_delete_exemption_type_rejected_when_granted(admin_session):
    from tests.helpers import create_soldier
    from app.db.models import SoldierExemption
    from datetime import date
    et = create_exemption_type(admin_session, name="פטור בשימוש", actor_id=None)
    s = create_soldier(admin_session, personal_number="7200001")
    admin_session.flush()
    admin_session.add(SoldierExemption(soldier_id=s.id, exemption_type_id=et.id, start_date=date.today()))
    admin_session.flush()
    with pytest.raises(DutyConfigError):
        delete_exemption_type(admin_session, exemption_type=et, actor_id=None)
```

- [ ] **Step 2: Run — expect FAIL** (functions missing).

- [ ] **Step 3: Append to `backend/app/services/duty_config.py`**

```python
def create_exemption_type(
    session: Session, *, name: str, description: str | None = None, actor_id: uuid.UUID | None = None
) -> ExemptionType:
    if session.execute(select(ExemptionType.id).where(ExemptionType.name == name)).first():
        raise DutyConfigError("name_taken")
    et = ExemptionType(name=name, description=description)
    session.add(et)
    session.flush()
    write_audit(session, actor_id=actor_id, action="exemption_type.create", entity_type="exemption_type",
                entity_id=et.id, after={"name": name})
    return et


def update_exemption_type(
    session: Session, *, exemption_type: ExemptionType, name: str | None, description: str | None,
    actor_id: uuid.UUID | None = None,
) -> ExemptionType:
    before = {"name": exemption_type.name, "description": exemption_type.description}
    if name is not None and name != exemption_type.name:
        if session.execute(select(ExemptionType.id).where(ExemptionType.name == name)).first():
            raise DutyConfigError("name_taken")
        exemption_type.name = name
    if description is not None:
        exemption_type.description = description
    write_audit(session, actor_id=actor_id, action="exemption_type.update", entity_type="exemption_type",
                entity_id=exemption_type.id, before=before,
                after={"name": exemption_type.name, "description": exemption_type.description})
    return exemption_type


def delete_exemption_type(
    session: Session, *, exemption_type: ExemptionType, actor_id: uuid.UUID | None = None
) -> None:
    granted = session.execute(
        select(SoldierExemption.id).where(SoldierExemption.exemption_type_id == exemption_type.id).limit(1)
    ).first()
    if granted is not None:
        raise DutyConfigError("exemption_type_in_use")
    # map rows cascade via ON DELETE CASCADE
    write_audit(session, actor_id=actor_id, action="exemption_type.delete", entity_type="exemption_type",
                entity_id=exemption_type.id, before={"name": exemption_type.name})
    session.delete(exemption_type)


def map_exemption_to_duty_type(
    session: Session, *, exemption_type_id: uuid.UUID, duty_type_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    if session.get(ExemptionType, exemption_type_id) is None:
        raise DutyConfigError("exemption_type_not_found")
    if session.get(DutyType, duty_type_id) is None:
        raise DutyConfigError("duty_type_not_found")
    exists = session.get(ExemptionDutyTypeMap, (exemption_type_id, duty_type_id))
    if exists is not None:
        return  # idempotent
    session.add(ExemptionDutyTypeMap(exemption_type_id=exemption_type_id, duty_type_id=duty_type_id))
    write_audit(session, actor_id=actor_id, action="exemption_map.add", entity_type="exemption_type",
                entity_id=exemption_type_id, after={"duty_type_id": str(duty_type_id)})


def unmap_exemption_from_duty_type(
    session: Session, *, exemption_type_id: uuid.UUID, duty_type_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    row = session.get(ExemptionDutyTypeMap, (exemption_type_id, duty_type_id))
    if row is None:
        return  # idempotent
    session.delete(row)
    write_audit(session, actor_id=actor_id, action="exemption_map.remove", entity_type="exemption_type",
                entity_id=exemption_type_id, before={"duty_type_id": str(duty_type_id)})


def list_exemption_duty_type_ids(session: Session, *, exemption_type_id: uuid.UUID) -> list[uuid.UUID]:
    return list(session.execute(
        select(ExemptionDutyTypeMap.duty_type_id).where(
            ExemptionDutyTypeMap.exemption_type_id == exemption_type_id
        )
    ).scalars().all())


def set_exemption_duty_types(
    session: Session, *, exemption_type_id: uuid.UUID, duty_type_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> None:
    if session.get(ExemptionType, exemption_type_id) is None:
        raise DutyConfigError("exemption_type_not_found")
    desired = set(duty_type_ids)
    for dtid in desired:
        if session.get(DutyType, dtid) is None:
            raise DutyConfigError("duty_type_not_found")
    current = set(list_exemption_duty_type_ids(session, exemption_type_id=exemption_type_id))
    for dtid in desired - current:
        map_exemption_to_duty_type(session, exemption_type_id=exemption_type_id, duty_type_id=dtid, actor_id=actor_id)
    for dtid in current - desired:
        unmap_exemption_from_duty_type(session, exemption_type_id=exemption_type_id, duty_type_id=dtid, actor_id=actor_id)
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_duty_config_service.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/duty_config.py backend/tests/unit/test_duty_config_service.py
git -C .. commit -m "feat(duty-config): exemption types + exemption-duty-type map ops"
```

---

## Phase E — Exemptions service (TDD)

### Task 7: grant / revoke / list / active_exemptions

**Files:**
- Create: `backend/app/services/exemptions.py`
- Create: `backend/tests/unit/test_exemptions_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_exemptions_service.py
from datetime import date, timedelta

import pytest

from app.db.models import ExemptionType, SoldierExemption
from app.services.exemptions import (
    ExemptionError,
    active_exemptions,
    grant_exemption,
    list_exemptions,
    revoke_exemption,
)
from tests.helpers import create_soldier


def _et(session, name="פטור"):
    et = ExemptionType(name=name)
    session.add(et)
    session.flush()
    return et


def test_grant_exemption(admin_session):
    s = create_soldier(admin_session, personal_number="7300001")
    et = _et(admin_session, "פטור-1")
    ex = grant_exemption(admin_session, soldier_id=s.id, exemption_type_id=et.id,
                         start_date=date(2026, 1, 1), end_date=None, reason="גב", actor_id=None)
    admin_session.commit()
    assert ex.soldier_id == s.id
    assert ex.end_date is None


def test_grant_rejects_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number="7300002")
    et = _et(admin_session, "פטור-2")
    with pytest.raises(ExemptionError):
        grant_exemption(admin_session, soldier_id=s.id, exemption_type_id=et.id,
                        start_date=date(2026, 5, 1), end_date=date(2026, 4, 1), reason=None, actor_id=None)


def test_grant_rejects_unknown_soldier(admin_session):
    import uuid
    et = _et(admin_session, "פטור-3")
    with pytest.raises(ExemptionError):
        grant_exemption(admin_session, soldier_id=uuid.uuid4(), exemption_type_id=et.id,
                        start_date=date(2026, 1, 1), end_date=None, reason=None, actor_id=None)


def test_revoke_active_soft_sets_end_date_today(admin_session):
    s = create_soldier(admin_session, personal_number="7300004")
    et = _et(admin_session, "פטור-4")
    ex = grant_exemption(admin_session, soldier_id=s.id, exemption_type_id=et.id,
                         start_date=date.today() - timedelta(days=5), end_date=None, reason=None, actor_id=None)
    admin_session.flush()
    revoke_exemption(admin_session, exemption_id=ex.id, actor_id=None)
    admin_session.commit()
    refreshed = admin_session.get(SoldierExemption, ex.id)
    assert refreshed is not None
    assert refreshed.end_date == date.today()


def test_revoke_future_hard_deletes(admin_session):
    s = create_soldier(admin_session, personal_number="7300005")
    et = _et(admin_session, "פטור-5")
    ex = grant_exemption(admin_session, soldier_id=s.id, exemption_type_id=et.id,
                         start_date=date.today() + timedelta(days=10), end_date=None, reason=None, actor_id=None)
    admin_session.flush()
    ex_id = ex.id
    revoke_exemption(admin_session, exemption_id=ex_id, actor_id=None)
    admin_session.commit()
    assert admin_session.get(SoldierExemption, ex_id) is None


def test_active_exemptions_window(admin_session):
    s = create_soldier(admin_session, personal_number="7300006")
    et = _et(admin_session, "פטור-6")
    grant_exemption(admin_session, soldier_id=s.id, exemption_type_id=et.id,
                    start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), reason=None, actor_id=None)
    grant_exemption(admin_session, soldier_id=s.id, exemption_type_id=et.id,
                    start_date=date(2026, 3, 1), end_date=None, reason=None, actor_id=None)
    admin_session.flush()
    on_jan = active_exemptions(admin_session, soldier_id=s.id, on_date=date(2026, 1, 15))
    on_feb = active_exemptions(admin_session, soldier_id=s.id, on_date=date(2026, 2, 15))
    on_apr = active_exemptions(admin_session, soldier_id=s.id, on_date=date(2026, 4, 1))
    assert len(on_jan) == 1
    assert len(on_feb) == 0
    assert len(on_apr) == 1  # the open-ended one


def test_list_exemptions(admin_session):
    s = create_soldier(admin_session, personal_number="7300007")
    et = _et(admin_session, "פטור-7")
    grant_exemption(admin_session, soldier_id=s.id, exemption_type_id=et.id,
                    start_date=date(2026, 1, 1), end_date=None, reason=None, actor_id=None)
    admin_session.flush()
    assert len(list_exemptions(admin_session, soldier_id=s.id)) == 1
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

Run: `uv run pytest tests/unit/test_exemptions_service.py -q`

- [ ] **Step 3: Create `backend/app/services/exemptions.py`**

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import ExemptionType, Soldier, SoldierExemption


class ExemptionError(Exception):
    """Raised on an invalid exemption operation."""


def grant_exemption(
    session: Session, *, soldier_id: uuid.UUID, exemption_type_id: uuid.UUID,
    start_date: date, end_date: date | None, reason: str | None,
    actor_id: uuid.UUID | None = None,
) -> SoldierExemption:
    if session.get(Soldier, soldier_id) is None:
        raise ExemptionError("soldier_not_found")
    if session.get(ExemptionType, exemption_type_id) is None:
        raise ExemptionError("exemption_type_not_found")
    if end_date is not None and end_date < start_date:
        raise ExemptionError("bad_date_range")
    ex = SoldierExemption(
        soldier_id=soldier_id, exemption_type_id=exemption_type_id,
        start_date=start_date, end_date=end_date, reason=reason, granted_by=actor_id,
    )
    session.add(ex)
    session.flush()
    write_audit(session, actor_id=actor_id, action="exemption.grant", entity_type="soldier_exemption",
                entity_id=ex.id, after={"soldier_id": str(soldier_id),
                                        "exemption_type_id": str(exemption_type_id),
                                        "start_date": start_date.isoformat(),
                                        "end_date": end_date.isoformat() if end_date else None})
    return ex


def revoke_exemption(
    session: Session, *, exemption_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None:
        raise ExemptionError("exemption_not_found")
    today = date.today()
    if ex.start_date <= today:
        before = {"end_date": ex.end_date.isoformat() if ex.end_date else None}
        ex.end_date = today
        write_audit(session, actor_id=actor_id, action="exemption.revoke", entity_type="soldier_exemption",
                    entity_id=ex.id, before=before, after={"end_date": today.isoformat()})
    else:
        write_audit(session, actor_id=actor_id, action="exemption.revoke", entity_type="soldier_exemption",
                    entity_id=ex.id, before={"start_date": ex.start_date.isoformat()},
                    after={"deleted": True})
        session.delete(ex)


def list_exemptions(session: Session, *, soldier_id: uuid.UUID) -> list[SoldierExemption]:
    return list(session.execute(
        select(SoldierExemption).where(SoldierExemption.soldier_id == soldier_id)
        .order_by(SoldierExemption.start_date)
    ).scalars().all())


def active_exemptions(
    session: Session, *, soldier_id: uuid.UUID, on_date: date
) -> list[SoldierExemption]:
    return list(session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id == soldier_id,
            SoldierExemption.start_date <= on_date,
            or_(SoldierExemption.end_date.is_(None), SoldierExemption.end_date >= on_date),
        )
    ).scalars().all())
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_exemptions_service.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/exemptions.py backend/tests/unit/test_exemptions_service.py
git -C .. commit -m "feat(exemptions): grant/revoke/list/active_exemptions service"
```

---

## Phase F — API routes (TDD)

### Task 8: duty-config routes

**Files:**
- Create: `backend/app/routes/duty_config.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_duty_config_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_duty_config_api.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_admin_creates_and_lists_duty_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100001", role="admin")
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                    json={"name": "שמירה-א", "score_per_day": "1.50"})
    assert r.status_code == 201, r.text
    dt_id = r.json()["id"]
    r2 = client.get("/api/duty-config/duty-types", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert any(d["id"] == dt_id for d in r2.json())


def test_duty_manager_allowed(client: TestClient, admin_session: Session):
    dm = create_soldier(admin_session, personal_number="5100002", role="duty_manager")
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(dm),
                    json={"name": "ניקיון-א", "score_per_day": "1.00"})
    assert r.status_code == 201


def test_plain_soldier_forbidden(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5100003", role="soldier")
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(s),
                    json={"name": "x", "score_per_day": "1.00"})
    assert r.status_code == 403


def test_commander_forbidden(client: TestClient, admin_session: Session):
    c = create_soldier(admin_session, personal_number="5100004", role="commander")
    r = client.get("/api/duty-config/duty-types", headers=auth_headers(c))
    assert r.status_code == 403


def test_commander_can_list_exemption_types(client: TestClient, admin_session: Session):
    # Reference data is readable by any authenticated user (needed to fill the grant form).
    c = create_soldier(admin_session, personal_number="5100041", role="commander")
    assert client.get("/api/duty-config/exemption-types", headers=auth_headers(c)).status_code == 200


def test_duplicate_name_rejected(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100005", role="admin")
    client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                json={"name": "כפול-א", "score_per_day": "1.00"})
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                    json={"name": "כפול-א", "score_per_day": "2.00"})
    assert r.status_code == 400
    assert r.json()["detail"] == "name_taken"


def test_set_exemption_duty_types(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100006", role="admin")
    et = client.post("/api/duty-config/exemption-types", headers=auth_headers(admin),
                     json={"name": "פטור-א"}).json()
    dt = client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                     json={"name": "מטבח-א", "score_per_day": "1.00"}).json()
    r = client.put(f"/api/duty-config/exemption-types/{et['id']}/duty-types",
                   headers=auth_headers(admin), json={"duty_type_ids": [dt["id"]]})
    assert r.status_code == 200
    r2 = client.get(f"/api/duty-config/exemption-types/{et['id']}/duty-types", headers=auth_headers(admin))
    assert r2.json() == [dt["id"]]
```

- [ ] **Step 2: Run — expect FAIL** (404).

- [ ] **Step 3: Create `backend/app/routes/duty_config.py`**

```python
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed, require_roles
from app.db.models import DutyLocation, DutyType, ExemptionType, Soldier
from app.db.session import get_session
from app.services import duty_config as svc

router = APIRouter(prefix="/duty-config", tags=["duty-config"])


def require_config_manager(user: Soldier = Depends(require_roles("duty_manager", "admin"))) -> Soldier:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user


# ---- duty types ----
class DutyTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    score_per_day: Decimal
    description: str | None
    active: bool


class CreateDutyTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    score_per_day: Decimal = Field(ge=0)
    description: str | None = Field(default=None, max_length=1000)


class UpdateDutyTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    score_per_day: Decimal | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


def _dt_out(d: DutyType) -> DutyTypeOut:
    return DutyTypeOut(id=d.id, name=d.name, score_per_day=d.score_per_day,
                       description=d.description, active=d.active)


@router.get("/duty-types", response_model=list[DutyTypeOut])
def list_duty_types(session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)):
    return [_dt_out(d) for d in session.execute(select(DutyType)).scalars().all()]


@router.post("/duty-types", response_model=DutyTypeOut, status_code=status.HTTP_201_CREATED)
def create_duty_type(body: CreateDutyTypeRequest, session: Session = Depends(get_session),
                     user: Soldier = Depends(require_config_manager)):
    try:
        dt = svc.create_duty_type(session, name=body.name, score_per_day=body.score_per_day,
                                  description=body.description, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(dt)
    return _dt_out(dt)


@router.patch("/duty-types/{duty_type_id}", response_model=DutyTypeOut)
def update_duty_type(duty_type_id: uuid.UUID, body: UpdateDutyTypeRequest,
                     session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)):
    dt = session.get(DutyType, duty_type_id)
    if dt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.update_duty_type(session, duty_type=dt, name=body.name, score_per_day=body.score_per_day,
                             description=body.description, actor_id=user.id)
        if body.active is not None:
            svc.set_duty_type_active(session, duty_type=dt, active=body.active, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(dt)
    return _dt_out(dt)


# ---- locations ----
class LocationOut(BaseModel):
    id: uuid.UUID
    name: str
    base: str | None
    active: bool


class CreateLocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    base: str | None = Field(default=None, max_length=200)


class UpdateLocationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base: str | None = Field(default=None, max_length=200)
    active: bool | None = None


def _loc_out(loc: DutyLocation) -> LocationOut:
    return LocationOut(id=loc.id, name=loc.name, base=loc.base, active=loc.active)


@router.get("/locations", response_model=list[LocationOut])
def list_locations(session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)):
    return [_loc_out(loc) for loc in session.execute(select(DutyLocation)).scalars().all()]


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
def create_location(body: CreateLocationRequest, session: Session = Depends(get_session),
                    user: Soldier = Depends(require_config_manager)):
    loc = svc.create_location(session, name=body.name, base=body.base, actor_id=user.id)
    session.commit()
    session.refresh(loc)
    return _loc_out(loc)


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(location_id: uuid.UUID, body: UpdateLocationRequest,
                    session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)):
    loc = session.get(DutyLocation, location_id)
    if loc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.update_location(session, location=loc, name=body.name, base=body.base, actor_id=user.id)
    if body.active is not None:
        svc.set_location_active(session, location=loc, active=body.active, actor_id=user.id)
    session.commit()
    session.refresh(loc)
    return _loc_out(loc)


# ---- exemption types + map ----
class ExemptionTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None


class CreateExemptionTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class UpdateExemptionTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class SetDutyTypesRequest(BaseModel):
    duty_type_ids: list[uuid.UUID]


def _et_out(et: ExemptionType) -> ExemptionTypeOut:
    return ExemptionTypeOut(id=et.id, name=et.name, description=et.description)


@router.get("/exemption-types", response_model=list[ExemptionTypeOut])
def list_exemption_types(session: Session = Depends(get_session),
                         user: Soldier = Depends(require_password_changed)):
    # Reference data: any authenticated (password-changed) user may list exemption-type
    # names, because commanders need them to fill the grant form. Mutations stay gated.
    return [_et_out(et) for et in session.execute(select(ExemptionType)).scalars().all()]


@router.post("/exemption-types", response_model=ExemptionTypeOut, status_code=status.HTTP_201_CREATED)
def create_exemption_type(body: CreateExemptionTypeRequest, session: Session = Depends(get_session),
                          user: Soldier = Depends(require_config_manager)):
    try:
        et = svc.create_exemption_type(session, name=body.name, description=body.description, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(et)
    return _et_out(et)


@router.patch("/exemption-types/{exemption_type_id}", response_model=ExemptionTypeOut)
def update_exemption_type(exemption_type_id: uuid.UUID, body: UpdateExemptionTypeRequest,
                          session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)):
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.update_exemption_type(session, exemption_type=et, name=body.name,
                                  description=body.description, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(et)
    return _et_out(et)


@router.delete("/exemption-types/{exemption_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exemption_type(exemption_type_id: uuid.UUID, session: Session = Depends(get_session),
                          user: Soldier = Depends(require_config_manager)):
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.delete_exemption_type(session, exemption_type=et, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


@router.get("/exemption-types/{exemption_type_id}/duty-types", response_model=list[uuid.UUID])
def get_exemption_duty_types(exemption_type_id: uuid.UUID, session: Session = Depends(get_session),
                             user: Soldier = Depends(require_config_manager)):
    return svc.list_exemption_duty_type_ids(session, exemption_type_id=exemption_type_id)


@router.put("/exemption-types/{exemption_type_id}/duty-types", response_model=list[uuid.UUID])
def put_exemption_duty_types(exemption_type_id: uuid.UUID, body: SetDutyTypesRequest,
                             session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)):
    try:
        svc.set_exemption_duty_types(session, exemption_type_id=exemption_type_id,
                                     duty_type_ids=body.duty_type_ids, actor_id=user.id)
    except svc.DutyConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return svc.list_exemption_duty_type_ids(session, exemption_type_id=exemption_type_id)
```

- [ ] **Step 4: Wire the router** in `backend/app/main.py`

Add the import alongside the others:

```python
from app.routes import duty_config as duty_config_routes
```

Add the include after the soldiers router:

```python
    app.include_router(duty_config_routes.router, prefix="/api")
```

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/integration/test_duty_config_api.py -q`
Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/app/routes/duty_config.py backend/app/main.py backend/tests/integration/test_duty_config_api.py
git -C .. commit -m "feat(api): duty-config routes (types/locations/exemption-types/map)"
```

---

### Task 9: exemptions routes

**Files:**
- Create: `backend/app/routes/exemptions.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_exemptions_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_exemptions_api.py
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session, name):
    et = ExemptionType(name=name)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


def test_commander_grants_in_subtree(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="5200001", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200002", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-ר1")
    r = client.post(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(cmd),
                    json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "גב"})
    assert r.status_code == 201, r.text
    r2 = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(cmd))
    assert len(r2.json()) == 1


def test_commander_out_of_subtree_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="5200003", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200004", hierarchy_node_id=other.id)
    et = _et(admin_session, "פטור-ר2")
    r = client.post(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(cmd),
                    json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"})
    assert r.status_code == 403


def test_soldier_reads_own_but_cannot_grant(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5200005", role="soldier")
    et = _et(admin_session, "פטור-ר3")
    r = client.get(f"/api/soldiers/{s.id}/exemptions", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json() == []
    r2 = client.post(f"/api/soldiers/{s.id}/exemptions", headers=auth_headers(s),
                     json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"})
    assert r2.status_code == 403


def test_revoke_active_soft(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200006", role="admin")
    target = create_soldier(admin_session, personal_number="5200007")
    et = _et(admin_session, "פטור-ר4")
    ex = client.post(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin),
                     json={"exemption_type_id": str(et.id),
                           "start_date": (date.today() - timedelta(days=2)).isoformat()}).json()
    r = client.delete(f"/api/soldiers/{target.id}/exemptions/{ex['id']}", headers=auth_headers(admin))
    assert r.status_code == 204
    rows = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin)).json()
    assert rows[0]["end_date"] == date.today().isoformat()


def test_revoke_rejects_cross_soldier_id(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200008", role="admin")
    a = create_soldier(admin_session, personal_number="5200009")
    b = create_soldier(admin_session, personal_number="5200010")
    et = _et(admin_session, "פטור-ר5")
    ex = client.post(f"/api/soldiers/{a.id}/exemptions", headers=auth_headers(admin),
                     json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"}).json()
    r = client.delete(f"/api/soldiers/{b.id}/exemptions/{ex['id']}", headers=auth_headers(admin))
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL** (404).

- [ ] **Step 3: Create `backend/app/routes/exemptions.py`**

```python
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier, SoldierExemption
from app.db.session import get_session
from app.services import exemptions as svc

router = APIRouter(prefix="/soldiers/{soldier_id}/exemptions", tags=["exemptions"])


class ExemptionOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None
    reason: str | None
    granted_by: uuid.UUID | None


class GrantRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


def _out(ex: SoldierExemption) -> ExemptionOut:
    return ExemptionOut(id=ex.id, soldier_id=ex.soldier_id, exemption_type_id=ex.exemption_type_id,
                        start_date=ex.start_date, end_date=ex.end_date, reason=ex.reason,
                        granted_by=ex.granted_by)


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.get("", response_model=list[ExemptionOut])
def list_(soldier_id: uuid.UUID, session: Session = Depends(get_session),
          user: Soldier = Depends(require_password_changed)):
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, s))
    return [_out(ex) for ex in svc.list_exemptions(session, soldier_id=soldier_id)]


@router.post("", response_model=ExemptionOut, status_code=status.HTTP_201_CREATED)
def grant(soldier_id: uuid.UUID, body: GrantRequest, session: Session = Depends(get_session),
          user: Soldier = Depends(require_password_changed)):
    s = _load_soldier(session, soldier_id)
    authorize(session, user, Action.EXEMPTION_GRANT, target_node=_node_of(session, s))
    try:
        ex = svc.grant_exemption(session, soldier_id=soldier_id, exemption_type_id=body.exemption_type_id,
                                 start_date=body.start_date, end_date=body.end_date, reason=body.reason,
                                 actor_id=user.id)
    except svc.ExemptionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(ex)
    return _out(ex)


@router.delete("/{exemption_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(soldier_id: uuid.UUID, exemption_id: uuid.UUID, session: Session = Depends(get_session),
           user: Soldier = Depends(require_password_changed)):
    s = _load_soldier(session, soldier_id)
    authorize(session, user, Action.EXEMPTION_GRANT, target_node=_node_of(session, s))
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None or ex.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.revoke_exemption(session, exemption_id=exemption_id, actor_id=user.id)
    session.commit()
```

> Authorization happens before the exemption-id existence check so an out-of-scope caller cannot probe ids. The `ex.soldier_id != soldier_id` guard rejects a valid id under the wrong soldier path.

- [ ] **Step 4: Wire the router** in `backend/app/main.py`

```python
from app.routes import exemptions as exemption_routes
```
```python
    app.include_router(exemption_routes.router, prefix="/api")
```

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/integration/test_exemptions_api.py -q`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/app/routes/exemptions.py backend/app/main.py backend/tests/integration/test_exemptions_api.py
git -C .. commit -m "feat(api): per-soldier exemption grant/revoke/list routes"
```

---

### Task 10: RBAC matrix extension + full backend run

**Files:**
- Modify: `backend/tests/integration/test_rbac_matrix.py`

- [ ] **Step 1: Append matrix cases** for the new surfaces

```python
def test_rbac_duty_config_role_gate(client, admin_session):
    from tests.helpers import auth_headers, create_soldier
    admin = create_soldier(admin_session, personal_number="5300001", role="admin")
    dm = create_soldier(admin_session, personal_number="5300002", role="duty_manager")
    cmd = create_soldier(admin_session, personal_number="5300003", role="commander")
    sol = create_soldier(admin_session, personal_number="5300004", role="soldier")
    payload = {"name": "rbac-dt", "score_per_day": "1.00"}
    assert client.post("/api/duty-config/duty-types", headers=auth_headers(admin), json=payload).status_code == 201
    assert client.post("/api/duty-config/duty-types", headers=auth_headers(dm),
                       json={"name": "rbac-dt2", "score_per_day": "1.00"}).status_code == 201
    assert client.get("/api/duty-config/duty-types", headers=auth_headers(cmd)).status_code == 403
    assert client.get("/api/duty-config/duty-types", headers=auth_headers(sol)).status_code == 403


def test_rbac_must_change_password_blocks_duty_config(client, admin_session):
    from tests.helpers import auth_headers, create_soldier
    dm = create_soldier(admin_session, personal_number="5300005", role="duty_manager",
                        must_change_password=True)
    r = client.get("/api/duty-config/duty-types", headers=auth_headers(dm))
    assert r.status_code == 403
    assert r.json()["detail"] == "must_change_password"
```

- [ ] **Step 2: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all pass (slice 1 + 2 + 3). If any pre-existing test references the new tables, fix forward.

- [ ] **Step 3: Lint, format, type-check** (matches slice 2's chore step)

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: clean. Fix any issues, then re-run.

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/tests/integration/test_rbac_matrix.py
git -C .. commit -m "test(rbac): duty-config gate + must-change-password blocking"
```

---

## Phase G — Frontend

### Task 11: API clients

**Files:**
- Create: `frontend/src/api/dutyConfig.ts`
- Create: `frontend/src/api/exemptions.ts`

- [ ] **Step 1: Create `frontend/src/api/dutyConfig.ts`**

```typescript
import { api } from "./client";

export interface DutyType {
  id: string;
  name: string;
  score_per_day: string;
  description: string | null;
  active: boolean;
}

export interface DutyLocation {
  id: string;
  name: string;
  base: string | null;
  active: boolean;
}

export interface ExemptionType {
  id: string;
  name: string;
  description: string | null;
}

export async function listDutyTypes(): Promise<DutyType[]> {
  return (await api.get<DutyType[]>("/duty-config/duty-types")).data;
}
export async function createDutyType(input: { name: string; score_per_day: string; description?: string | null }): Promise<DutyType> {
  return (await api.post<DutyType>("/duty-config/duty-types", input)).data;
}
export async function updateDutyType(id: string, input: Partial<{ name: string; score_per_day: string; description: string | null; active: boolean }>): Promise<DutyType> {
  return (await api.patch<DutyType>(`/duty-config/duty-types/${id}`, input)).data;
}

export async function listLocations(): Promise<DutyLocation[]> {
  return (await api.get<DutyLocation[]>("/duty-config/locations")).data;
}
export async function createLocation(input: { name: string; base?: string | null }): Promise<DutyLocation> {
  return (await api.post<DutyLocation>("/duty-config/locations", input)).data;
}
export async function updateLocation(id: string, input: Partial<{ name: string; base: string | null; active: boolean }>): Promise<DutyLocation> {
  return (await api.patch<DutyLocation>(`/duty-config/locations/${id}`, input)).data;
}

export async function listExemptionTypes(): Promise<ExemptionType[]> {
  return (await api.get<ExemptionType[]>("/duty-config/exemption-types")).data;
}
export async function createExemptionType(input: { name: string; description?: string | null }): Promise<ExemptionType> {
  return (await api.post<ExemptionType>("/duty-config/exemption-types", input)).data;
}
export async function deleteExemptionType(id: string): Promise<void> {
  await api.delete(`/duty-config/exemption-types/${id}`);
}
export async function getExemptionDutyTypes(id: string): Promise<string[]> {
  return (await api.get<string[]>(`/duty-config/exemption-types/${id}/duty-types`)).data;
}
export async function setExemptionDutyTypes(id: string, duty_type_ids: string[]): Promise<string[]> {
  return (await api.put<string[]>(`/duty-config/exemption-types/${id}/duty-types`, { duty_type_ids })).data;
}
```

- [ ] **Step 2: Create `frontend/src/api/exemptions.ts`**

```typescript
import { api } from "./client";

export interface Exemption {
  id: string;
  soldier_id: string;
  exemption_type_id: string;
  start_date: string;
  end_date: string | null;
  reason: string | null;
  granted_by: string | null;
}

export async function listExemptions(soldierId: string): Promise<Exemption[]> {
  return (await api.get<Exemption[]>(`/soldiers/${soldierId}/exemptions`)).data;
}
export async function grantExemption(soldierId: string, input: { exemption_type_id: string; start_date: string; end_date?: string | null; reason?: string | null }): Promise<Exemption> {
  return (await api.post<Exemption>(`/soldiers/${soldierId}/exemptions`, input)).data;
}
export async function revokeExemption(soldierId: string, exemptionId: string): Promise<void> {
  await api.delete(`/soldiers/${soldierId}/exemptions/${exemptionId}`);
}
```

- [ ] **Step 3: Type-check**

Run (from `frontend/`): `pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git -C .. add frontend/src/api/dutyConfig.ts frontend/src/api/exemptions.ts
git -C .. commit -m "feat(frontend): duty-config + exemptions api clients"
```

---

### Task 12: DutyConfigPage + route + sidebar + i18n

**Files:**
- Create: `frontend/src/pages/DutyConfigPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n strings** — add a `duty_config` block and a `nav.duty_config` key to `frontend/src/i18n/he.json`:

```json
  "nav": {
    "home": "ראשי",
    "team_hierarchy": "אנשי צוות והיררכיה",
    "duty_config": "הגדרות תורנויות",
    "profile": "פרופיל"
  },
  "duty_config": {
    "title": "הגדרות תורנויות",
    "duty_types": "סוגי תורנויות",
    "locations": "מיקומים",
    "exemption_types": "סוגי פטור",
    "name": "שם",
    "score_per_day": "ניקוד ליום",
    "base": "בסיס",
    "active": "פעיל",
    "add": "הוסף",
    "save": "שמור",
    "exempts_from": "פוטר מ-",
    "delete": "מחק"
  },
  "exemptions": {
    "title": "פטורים",
    "type": "סוג פטור",
    "start_date": "מתאריך",
    "end_date": "עד תאריך",
    "reason": "סיבה",
    "grant": "הענק פטור",
    "revoke": "בטל",
    "none": "אין פטורים",
    "forever": "ללא הגבלה"
  }
```

> Keep the existing `team`, `profile`, etc. blocks. Replace only the `nav` block and add the two new blocks.

- [ ] **Step 2: Create `frontend/src/pages/DutyConfigPage.tsx`**

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import {
  DutyLocation,
  DutyType,
  ExemptionType,
  createDutyType,
  createExemptionType,
  createLocation,
  getExemptionDutyTypes,
  listDutyTypes,
  listExemptionTypes,
  listLocations,
  setExemptionDutyTypes,
  updateDutyType,
} from "../api/dutyConfig";

export default function DutyConfigPage() {
  const { t } = useTranslation();
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [exTypes, setExTypes] = useState<ExemptionType[]>([]);
  const [dtName, setDtName] = useState("");
  const [dtScore, setDtScore] = useState("1.00");
  const [locName, setLocName] = useState("");
  const [exName, setExName] = useState("");
  const [mapSel, setMapSel] = useState<Record<string, string[]>>({});

  async function refresh() {
    const [dts, locs, ets] = await Promise.all([listDutyTypes(), listLocations(), listExemptionTypes()]);
    setDutyTypes(dts);
    setLocations(locs);
    setExTypes(ets);
    const sel: Record<string, string[]> = {};
    for (const et of ets) sel[et.id] = await getExemptionDutyTypes(et.id);
    setMapSel(sel);
  }
  useEffect(() => { void refresh(); }, []);

  async function addDutyType(e: FormEvent) {
    e.preventDefault();
    await createDutyType({ name: dtName, score_per_day: dtScore });
    setDtName(""); setDtScore("1.00");
    await refresh();
  }
  async function addLocation(e: FormEvent) {
    e.preventDefault();
    await createLocation({ name: locName });
    setLocName("");
    await refresh();
  }
  async function addExType(e: FormEvent) {
    e.preventDefault();
    await createExemptionType({ name: exName });
    setExName("");
    await refresh();
  }
  async function toggleMap(etId: string, dtId: string) {
    const current = mapSel[etId] ?? [];
    const next = current.includes(dtId) ? current.filter((x) => x !== dtId) : [...current, dtId];
    await setExemptionDutyTypes(etId, next);
    setMapSel({ ...mapSel, [etId]: next });
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-8" data-testid="duty-config-page">
        <h2 className="text-xl font-semibold">{t("duty_config.title")}</h2>

        <div data-testid="duty-types-section">
          <h3 className="font-medium mb-2">{t("duty_config.duty_types")}</h3>
          <form onSubmit={addDutyType} className="flex items-end gap-2 mb-2" data-testid="duty-type-form">
            <label className="block"><span className="text-xs">{t("duty_config.name")}</span>
              <input className="block border rounded p-1" value={dtName} onChange={(e) => setDtName(e.target.value)} required data-testid="dt-name" /></label>
            <label className="block"><span className="text-xs">{t("duty_config.score_per_day")}</span>
              <input className="block border rounded p-1 w-24" value={dtScore} onChange={(e) => setDtScore(e.target.value)} data-testid="dt-score" /></label>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="dt-submit">{t("duty_config.add")}</button>
          </form>
          <ul className="text-sm" data-testid="duty-type-list">
            {dutyTypes.map((d) => (
              <li key={d.id} data-testid={`dt-row-${d.name}`} className="flex items-center gap-2">
                <span>{d.name} — {d.score_per_day}</span>
                <button className="text-xs text-indigo-600" onClick={() => updateDutyType(d.id, { active: !d.active }).then(refresh)} data-testid={`dt-toggle-${d.name}`}>
                  {d.active ? t("duty_config.active") : "—"}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div data-testid="locations-section">
          <h3 className="font-medium mb-2">{t("duty_config.locations")}</h3>
          <form onSubmit={addLocation} className="flex items-end gap-2 mb-2" data-testid="location-form">
            <input className="border rounded p-1" value={locName} onChange={(e) => setLocName(e.target.value)} required data-testid="loc-name" placeholder={t("duty_config.name")} />
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="loc-submit">{t("duty_config.add")}</button>
          </form>
          <ul className="text-sm" data-testid="location-list">
            {locations.map((l) => <li key={l.id} data-testid={`loc-row-${l.name}`}>{l.name}</li>)}
          </ul>
        </div>

        <div data-testid="exemption-types-section">
          <h3 className="font-medium mb-2">{t("duty_config.exemption_types")}</h3>
          <form onSubmit={addExType} className="flex items-end gap-2 mb-2" data-testid="exemption-type-form">
            <input className="border rounded p-1" value={exName} onChange={(e) => setExName(e.target.value)} required data-testid="et-name" placeholder={t("duty_config.name")} />
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="et-submit">{t("duty_config.add")}</button>
          </form>
          <ul className="text-sm space-y-2" data-testid="exemption-type-list">
            {exTypes.map((et) => (
              <li key={et.id} data-testid={`et-row-${et.name}`}>
                <div>{et.name}</div>
                <div className="text-xs text-gray-500">{t("duty_config.exempts_from")}:</div>
                <div className="flex flex-wrap gap-2">
                  {dutyTypes.map((d) => (
                    <label key={d.id} className="text-xs flex items-center gap-1">
                      <input type="checkbox" checked={(mapSel[et.id] ?? []).includes(d.id)}
                             onChange={() => toggleMap(et.id, d.id)}
                             data-testid={`map-${et.name}-${d.name}`} />
                      {d.name}
                    </label>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </Layout>
  );
}
```

- [ ] **Step 3: Add the sidebar entry** in `frontend/src/components/Layout.tsx`

Add after the `canManageTeam` line:

```tsx
  const canManageDuties = role === "duty_manager" || role === "admin";
```

Add a nav `Link` after the `/team` link block:

```tsx
        {canManageDuties && (
          <Link to="/duty-config" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-duty-config">{t("nav.duty_config")}</Link>
        )}
```

- [ ] **Step 4: Add the route** in `frontend/src/App.tsx`

Add the import:

```tsx
import DutyConfigPage from "./pages/DutyConfigPage";
```

Add the route inside the protected block:

```tsx
          <Route path="/duty-config" element={<ForcedPasswordGate><DutyConfigPage /></ForcedPasswordGate>} />
```

- [ ] **Step 5: Type-check + build**

Run (from `frontend/`): `pnpm tsc --noEmit && pnpm build`
Expected: success.

- [ ] **Step 6: Commit**

```bash
git -C .. add frontend/src/pages/DutyConfigPage.tsx frontend/src/App.tsx frontend/src/components/Layout.tsx frontend/src/i18n/he.json
git -C .. commit -m "feat(frontend): duty-config page + route + sidebar entry"
```

---

### Task 13: Exemptions UI — `ExemptionsPanel` (profile read-only + team management)

**Files:**
- Create: `frontend/src/components/ExemptionsPanel.tsx`
- Modify: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`

A single reusable panel renders a soldier's exemptions. With `canManage={false}` (profile) it is read-only; with `canManage` true (team page, for commander/duty_manager/admin) it shows the grant form and revoke buttons. Exemption-type names are always loaded for display because `GET /api/duty-config/exemption-types` is relaxed to any password-changed user (see Task 8).

- [ ] **Step 1: Create `frontend/src/components/ExemptionsPanel.tsx`**

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ExemptionType, listExemptionTypes } from "../api/dutyConfig";
import { Exemption, grantExemption, listExemptions, revokeExemption } from "../api/exemptions";

export default function ExemptionsPanel({ soldierId, canManage }: { soldierId: string; canManage: boolean }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<Exemption[]>([]);
  const [types, setTypes] = useState<ExemptionType[]>([]);
  const [typeId, setTypeId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");

  async function refresh() {
    setItems(await listExemptions(soldierId));
  }
  useEffect(() => {
    void refresh();
    listExemptionTypes().then(setTypes);
  }, [soldierId]);

  const typeName = (id: string) => types.find((tp) => tp.id === id)?.name ?? id;

  async function onGrant(e: FormEvent) {
    e.preventDefault();
    await grantExemption(soldierId, {
      exemption_type_id: typeId,
      start_date: start,
      end_date: end || null,
      reason: reason || null,
    });
    setTypeId(""); setStart(""); setEnd(""); setReason("");
    await refresh();
  }

  async function onRevoke(id: string) {
    if (!confirm(t("exemptions.revoke") + "?")) return;
    await revokeExemption(soldierId, id);
    await refresh();
  }

  return (
    <div data-testid="exemptions-panel" className="space-y-3">
      <h3 className="font-medium">{t("exemptions.title")}</h3>
      {items.length === 0 && (
        <p className="text-sm text-gray-500" data-testid="exemptions-empty">{t("exemptions.none")}</p>
      )}
      <ul className="text-sm space-y-1" data-testid="exemptions-list">
        {items.map((ex) => (
          <li key={ex.id} className="flex items-center gap-2" data-testid={`exemption-row-${ex.id}`}>
            <span>{typeName(ex.exemption_type_id)}</span>
            <span className="text-gray-400">{ex.start_date} → {ex.end_date ?? t("exemptions.forever")}</span>
            {canManage && (
              <button className="text-rejected text-xs" onClick={() => onRevoke(ex.id)} data-testid={`revoke-${ex.id}`}>
                {t("exemptions.revoke")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {canManage && (
        <form onSubmit={onGrant} className="flex flex-wrap items-end gap-2" data-testid="grant-form">
          <select className="border rounded p-1" value={typeId} onChange={(e) => setTypeId(e.target.value)} required data-testid="grant-type">
            <option value="">{t("exemptions.type")}</option>
            {types.map((tp) => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
          </select>
          <input type="date" className="border rounded p-1" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="grant-start" />
          <input type="date" className="border rounded p-1" value={end} onChange={(e) => setEnd(e.target.value)} data-testid="grant-end" />
          <input className="border rounded p-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("exemptions.reason")} data-testid="grant-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="grant-submit">{t("exemptions.grant")}</button>
        </form>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Integrate read-only panel into `frontend/src/pages/ProfilePage.tsx`**

Add the import at the top:

```tsx
import ExemptionsPanel from "../components/ExemptionsPanel";
```

Add the panel inside the `<section>`, after the change-password `Link` (only when a user id is present):

```tsx
        {user?.id && (
          <div className="pt-4 border-t">
            <ExemptionsPanel soldierId={user.id} canManage={false} />
          </div>
        )}
```

- [ ] **Step 3: Integrate management panel into `frontend/src/pages/TeamHierarchyPage.tsx`**

Add the import at the top:

```tsx
import ExemptionsPanel from "../components/ExemptionsPanel";
```

Add a selected-soldier state next to the other `useState` calls:

```tsx
  const [selected, setSelected] = useState<SoldierDTO | null>(null);
  const canManageExemptions = user?.role === "admin" || user?.role === "commander" || user?.role === "duty_manager";
```

Add a "manage exemptions" button to each soldier row's action cell (inside the existing `<td className="space-x-2 space-x-reverse">`, after the remove button):

```tsx
                  <button onClick={() => setSelected(s)} className="text-indigo-600" data-testid={`exemptions-${s.personal_number}`}>{t("exemptions.title")}</button>
```

Add the panel after the `</table>`, before `</section>`:

```tsx
        {selected && canManageExemptions && (
          <div className="border-t pt-4" data-testid="manage-exemptions">
            <div className="text-sm text-gray-500">{selected.full_name} ({selected.personal_number})</div>
            <ExemptionsPanel soldierId={selected.id} canManage={true} />
          </div>
        )}
```

- [ ] **Step 4: Type-check + build**

Run (from `frontend/`): `pnpm tsc --noEmit && pnpm build`
Expected: success.

- [ ] **Step 5: Commit**

```bash
git -C .. add frontend/src/components/ExemptionsPanel.tsx frontend/src/pages/ProfilePage.tsx frontend/src/pages/TeamHierarchyPage.tsx
git -C .. commit -m "feat(frontend): exemptions panel (profile read-only + team management)"
```

---

### Task 14: Playwright e2e — duty config + exemptions

**Files:**
- Create: `frontend/tests/e2e/duty_config.spec.ts`
- Create: `frontend/tests/e2e/exemptions.spec.ts`

Each spec is self-contained: the bootstrap admin logs in for the first time, is forced to change the password, then performs the flow. This mirrors `frontend/tests/e2e/admin_flow.spec.ts` (no cross-spec state dependency). Unique names use `Date.now()` so reruns against the same DB don't collide on the `name UNIQUE` constraints.

- [ ] **Step 1: Create `frontend/tests/e2e/duty_config.spec.ts`**

```typescript
import { test, expect } from "@playwright/test";

async function loginAsAdmin(page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/change-password$/);
  await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("new-password").fill("AdminNewPassw0rd");
  await page.getByTestId("change-password-submit").click();
  await expect(page).toHaveURL("/");
}

test("admin configures a duty type, location, and exemption type with mapping", async ({ page }) => {
  await loginAsAdmin(page);

  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/duty-config$/);

  const suffix = `${Date.now() % 100000}`;
  const dtName = `שמירה-${suffix}`;
  const locName = `מוצב-${suffix}`;
  const etName = `פטור-${suffix}`;

  // Duty type.
  await page.getByTestId("dt-name").fill(dtName);
  await page.getByTestId("dt-score").fill("1.50");
  await page.getByTestId("dt-submit").click();
  await expect(page.getByTestId(`dt-row-${dtName}`)).toBeVisible();

  // Location.
  await page.getByTestId("loc-name").fill(locName);
  await page.getByTestId("loc-submit").click();
  await expect(page.getByTestId(`loc-row-${locName}`)).toBeVisible();

  // Exemption type.
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  // Map the exemption type to the duty type via the checkbox.
  const cb = page.getByTestId(`map-${etName}-${dtName}`);
  await cb.check();
  await expect(cb).toBeChecked();
});
```

- [ ] **Step 2: Create `frontend/tests/e2e/exemptions.spec.ts`**

```typescript
import { test, expect } from "@playwright/test";

test("admin onboards a soldier, grants an exemption, then revokes it", async ({ page }) => {
  // First login + forced password change.
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/change-password$/);
  await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("new-password").fill("AdminNewPassw0rd");
  await page.getByTestId("change-password-submit").click();
  await expect(page).toHaveURL("/");

  const suffix = `${Date.now() % 100000}`;
  const etName = `פטור-${suffix}`;

  // Create an exemption type to grant.
  await page.getByTestId("nav-duty-config").click();
  await expect(page).toHaveURL(/\/duty-config$/);
  await page.getByTestId("et-name").fill(etName);
  await page.getByTestId("et-submit").click();
  await expect(page.getByTestId(`et-row-${etName}`)).toBeVisible();

  // Onboard a soldier.
  await page.getByTestId("nav-team").click();
  await expect(page).toHaveURL(/\/team$/);
  const pn = `92${Date.now() % 100000}`;
  await page.getByTestId("onboard-pn").fill(pn);
  await page.getByTestId("onboard-name").fill("חייל פטור");
  await page.getByTestId("onboard-submit").click();
  await expect(page.getByTestId(`soldier-row-${pn}`)).toBeVisible();

  // Open the manage-exemptions panel for that soldier.
  await page.getByTestId(`exemptions-${pn}`).click();
  await expect(page.getByTestId("manage-exemptions")).toBeVisible();

  // Grant an exemption.
  await page.getByTestId("grant-type").selectOption({ label: etName });
  await page.getByTestId("grant-start").fill("2026-06-01");
  await page.getByTestId("grant-reason").fill("בדיקה");
  await page.getByTestId("grant-submit").click();

  // It appears in the list; revoke it.
  const row = page.getByTestId("exemptions-list").getByText(etName);
  await expect(row).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await page.locator('[data-testid^="revoke-"]').first().click();
  // After a future-dated grant is revoked it is hard-deleted, so the list empties.
  await expect(page.getByTestId("exemptions-empty")).toBeVisible();
});
```

- [ ] **Step 3: Run the e2e suite**

Run (from `frontend/`): `pnpm test:e2e`
Expected: all specs pass (existing `admin_flow` + new `duty_config` + `exemptions`).

- [ ] **Step 4: Commit**

```bash
git -C .. add frontend/tests/e2e/duty_config.spec.ts frontend/tests/e2e/exemptions.spec.ts
git -C .. commit -m "test(e2e): duty-config flow + exemption grant/revoke"
```

---

## Done

All five tables, services, routes, RBAC, audit, and Hebrew RTL UI for Slice 3 are now implemented and tested. The branch holds one self-contained slice ready for a single PR onto Slice 2.
