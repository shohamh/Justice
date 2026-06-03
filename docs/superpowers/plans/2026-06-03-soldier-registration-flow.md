# Soldier Registration Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Prerequisite:** `2026-06-03-dm-scoping.md` plan must be fully implemented first.

**Goal:** Self-service soldier registration with invite codes, 6-step wizard, holding node, enrollment approval by commanders/אחראי תורנויות, and Telegram setup gate.

**Architecture:** `POST /auth/register` (unauthenticated) creates soldier in holding node + enrollment request. Commander of chosen node gets notified. Approval moves soldier to real node. Frontend is a 6-step wizard at `/register`; after registration, a Telegram gate at `/setup/telegram` blocks app access until Telegram is linked (configurable via system setting).

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.x, Alembic, pytest + testcontainers, React/TypeScript, fuse.js, react-i18next

---

## File Map

| Action | Path |
|--------|------|
| Modify | `backend/app/db/models.py` |
| Create | `backend/alembic/versions/0033_enrollment_notification_types.py` |
| Create | `backend/alembic/versions/0034_registration_tables.py` |
| Modify | `backend/app/scripts/bootstrap.py` |
| Create | `backend/app/services/invite_codes.py` |
| Create | `backend/app/services/registration.py` |
| Create | `backend/app/services/enrollment.py` |
| Modify | `backend/app/routes/me.py` |
| Modify | `backend/app/routes/auth.py` |
| Create | `backend/app/routes/enrollment.py` |
| Create | `backend/app/routes/invite_codes.py` |
| Modify | `backend/app/main.py` |
| Create | `backend/app/services/tests/test_invite_codes.py` |
| Create | `backend/app/services/tests/test_registration.py` |
| Create | `backend/app/services/tests/test_enrollment.py` |
| Create | `backend/app/routes/tests/test_registration_routes.py` |
| Create | `backend/app/routes/tests/test_enrollment_routes.py` |
| Create | `backend/app/routes/tests/test_invite_code_routes.py` |
| Modify | `frontend/src/api/auth.ts` |
| Create | `frontend/src/api/enrollment.ts` |
| Create | `frontend/src/api/inviteCodes.ts` |
| Modify | `frontend/src/auth/AuthContext.tsx` |
| Modify | `frontend/src/auth/ProtectedRoute.tsx` |
| Modify | `frontend/src/App.tsx` |
| Modify | `frontend/src/i18n/he.json` |
| Modify | `frontend/src/pages/LoginPage.tsx` |
| Create | `frontend/src/pages/RegisterPage.tsx` |
| Create | `frontend/src/pages/TelegramSetupPage.tsx` |
| Modify | `frontend/src/pages/ApprovalsPage.tsx` |
| Create | `frontend/src/pages/AdminInviteCodesPage.tsx` |
| Modify | `frontend/src/components/UnifiedNav.tsx` |

---

## Task 1: DB models — RegistrationInviteCode, SoldierEnrollmentRequest, NotificationType values

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/services/tests/test_invite_codes.py` (import test only)

- [ ] **Step 1: Write failing import test**

Create `backend/app/services/tests/test_invite_codes.py`:

```python
from __future__ import annotations
import uuid
from tests.helpers import create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_registration_invite_code_model(admin_session):
    """RegistrationInviteCode can be inserted."""
    from app.db.models import RegistrationInviteCode
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = RegistrationInviteCode(code=f"TESTCD{_uid()[:2].upper()}", uses_left=5, created_by=admin.id)
    admin_session.add(code)
    admin_session.commit()
    admin_session.refresh(code)
    assert code.id is not None
    assert code.uses_left == 5


def test_soldier_enrollment_request_model(admin_session):
    """SoldierEnrollmentRequest can be inserted with status=pending."""
    from app.db.models import SoldierEnrollmentRequest
    from tests.helpers import create_node
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.id is not None
    assert req.status == "pending"
```

- [ ] **Step 2: Run — expect FAIL (models not defined)**

```
cd backend && uv run pytest app/services/tests/test_invite_codes.py -v
```

- [ ] **Step 3: Add models to `backend/app/db/models.py`**

Add after `TelegramOutbox`:

```python
class RegistrationInviteCode(Base):
    __tablename__ = "registration_invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    code: Mapped[str] = mapped_column(Text, unique=True)
    uses_left: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SoldierEnrollmentRequest(Base):
    __tablename__ = "soldier_enrollment_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    requested_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT")
    )
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

Also extend `NotificationType` enum — add three values after `algorithm_job_failed`:

```python
    enrollment_request_received = "enrollment_request_received"
    enrollment_approved = "enrollment_approved"
    enrollment_rejected = "enrollment_rejected"
```

- [ ] **Step 4: Run — still expect FAIL (tables not migrated yet)**

```
cd backend && uv run pytest app/services/tests/test_invite_codes.py -v
```
Expected: fail with `UndefinedTable` — migration not run yet. (OK — Task 2 will fix this.)

- [ ] **Step 5: Commit models only**

```
git add backend/app/db/models.py backend/app/services/tests/test_invite_codes.py
git commit -m "feat: add RegistrationInviteCode, SoldierEnrollmentRequest models and new NotificationType values"
```

---

## Task 2: Alembic migrations 0033 + 0034

**Files:**
- Create: `backend/alembic/versions/0033_enrollment_notification_types.py`
- Create: `backend/alembic/versions/0034_registration_tables.py`

- [ ] **Step 1: Create migration 0033**

Create `backend/alembic/versions/0033_enrollment_notification_types.py`:

```python
"""Add enrollment notification types to notification_type enum

Revision ID: 0033
Revises: 0032
Create Date: 2026-06-03
"""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'enrollment_request_received'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'enrollment_approved'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'enrollment_rejected'")


def downgrade() -> None:
    pass  # PostgreSQL does not support removing enum values
```

- [ ] **Step 2: Create migration 0034**

Create `backend/alembic/versions/0034_registration_tables.py`:

```python
"""registration_invite_codes and soldier_enrollment_requests tables

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_invite_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("uses_left", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["soldiers.id"], ondelete="SET NULL", name="fk_invite_code_creator"),
    )

    op.create_table(
        "soldier_enrollment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["soldier_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_enrollment_soldier"),
        sa.ForeignKeyConstraint(["requested_node_id"], ["hierarchy_nodes.id"], ondelete="RESTRICT", name="fk_enrollment_node"),
        sa.ForeignKeyConstraint(["decided_by"], ["soldiers.id"], ondelete="SET NULL", name="fk_enrollment_decider"),
    )
    op.create_index("ix_enrollment_requests_status", "soldier_enrollment_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_enrollment_requests_status", table_name="soldier_enrollment_requests")
    op.drop_table("soldier_enrollment_requests")
    op.drop_table("registration_invite_codes")
```

- [ ] **Step 3: Run tests from Task 1 — now expect PASS**

```
cd backend && uv run pytest app/services/tests/test_invite_codes.py -v
```

- [ ] **Step 4: Commit**

```
git add backend/alembic/versions/0033_enrollment_notification_types.py backend/alembic/versions/0034_registration_tables.py
git commit -m "feat: migrations 0033-0034 — enrollment notification types and registration tables"
```

---

## Task 3: Bootstrap holding node

**Files:**
- Modify: `backend/app/scripts/bootstrap.py`

- [ ] **Step 1: Replace `backend/app/scripts/bootstrap.py`**

```python
"""First-boot script: create initial admin + system holding node. Idempotent."""
from __future__ import annotations

import sys

from sqlalchemy import select

from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier, SystemSetting
from app.db.session import session_scope
from app.settings import get_settings


def _ensure_admin(session, settings) -> None:
    pn = settings.bootstrap_admin_personal_number
    fn = settings.bootstrap_admin_full_name
    pw = settings.bootstrap_admin_password
    if not (pn and fn and pw):
        print("bootstrap: BOOTSTRAP_ADMIN_* env vars not all set; skipping admin.")
        return
    existing = session.execute(
        select(Soldier).where(Soldier.role == "admin").limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        print("bootstrap: an admin already exists; skipping.")
        return
    admin = Soldier(
        personal_number=pn,
        full_name=fn,
        password_hash=hash_password(pw),
        role="admin",
        must_change_password=False,
    )
    session.add(admin)
    session.flush()
    print(f"bootstrap: created admin id={admin.id} personal_number={pn}")


def _ensure_holding_node(session) -> None:
    if session.get(SystemSetting, "system.holding_node_id") is not None:
        print("bootstrap: holding node already exists; skipping.")
        return
    node = HierarchyNode(
        level="division",
        name="מסגרת ממתינים לקליטה",
        parent_id=None,
        commander_id=None,
        path_ids=[],
    )
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.flush()
    session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    print(f"bootstrap: created holding node id={node.id}")


def main() -> int:
    settings = get_settings()
    with session_scope() as session:
        _ensure_admin(session, settings)
        _ensure_holding_node(session)
        session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Commit**

```
git add backend/app/scripts/bootstrap.py
git commit -m "feat: bootstrap creates holding node and stores ID in system_settings"
```

---

## Task 4: Invite codes service

**Files:**
- Create: `backend/app/services/invite_codes.py`
- Modify: `backend/app/services/tests/test_invite_codes.py`

- [ ] **Step 1: Write failing service tests**

Append to `backend/app/services/tests/test_invite_codes.py`:

```python
def test_create_invite_code_auto_generates_code(admin_session):
    from app.services.invite_codes import create_invite_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=3, actor_id=admin.id)
    admin_session.commit()
    assert len(code.code) == 8
    assert code.uses_left == 3


def test_consume_decrements_uses_left(admin_session):
    from app.services.invite_codes import create_invite_code, consume_invite_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=2, actor_id=admin.id)
    admin_session.commit()
    consume_invite_code(admin_session, code=code.code)
    admin_session.commit()
    admin_session.refresh(code)
    assert code.uses_left == 1


def test_consume_exhausted_raises(admin_session):
    import pytest
    from app.services.invite_codes import create_invite_code, consume_invite_code, InviteCodeError
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=1, actor_id=admin.id)
    admin_session.commit()
    consume_invite_code(admin_session, code=code.code)
    admin_session.commit()
    with pytest.raises(InviteCodeError, match="exhausted"):
        consume_invite_code(admin_session, code=code.code)


def test_consume_invalid_raises(admin_session):
    import pytest
    from app.services.invite_codes import consume_invite_code, InviteCodeError
    with pytest.raises(InviteCodeError, match="invalid"):
        consume_invite_code(admin_session, code="NOTEXIST")


def test_validate_code_true_for_valid(admin_session):
    from app.services.invite_codes import create_invite_code, validate_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=1, actor_id=admin.id)
    admin_session.commit()
    assert validate_code(admin_session, code=code.code) is True


def test_validate_code_false_for_exhausted(admin_session):
    from app.services.invite_codes import create_invite_code, consume_invite_code, validate_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=1, actor_id=admin.id)
    admin_session.commit()
    consume_invite_code(admin_session, code=code.code)
    admin_session.commit()
    assert validate_code(admin_session, code=code.code) is False
```

- [ ] **Step 2: Run — expect FAIL**

```
cd backend && uv run pytest app/services/tests/test_invite_codes.py -k "create_invite or consume or validate_code" -v
```

- [ ] **Step 3: Create `backend/app/services/invite_codes.py`**

```python
from __future__ import annotations

import secrets
import string
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RegistrationInviteCode


class InviteCodeError(Exception):
    pass


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def create_invite_code(
    session: Session, *, uses_left: int, actor_id: uuid.UUID | None
) -> RegistrationInviteCode:
    code = RegistrationInviteCode(code=_generate_code(), uses_left=uses_left, created_by=actor_id)
    session.add(code)
    session.flush()
    return code


def validate_code(session: Session, *, code: str) -> bool:
    row = session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == code)
    ).scalar_one_or_none()
    return row is not None and row.uses_left > 0


def consume_invite_code(session: Session, *, code: str) -> RegistrationInviteCode:
    row = session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == code)
    ).scalar_one_or_none()
    if row is None:
        raise InviteCodeError("invalid invite code")
    if row.uses_left <= 0:
        raise InviteCodeError("invite code exhausted")
    row.uses_left -= 1
    session.flush()
    return row
```

- [ ] **Step 4: Run — expect PASS**

```
cd backend && uv run pytest app/services/tests/test_invite_codes.py -v
```

- [ ] **Step 5: Commit**

```
git add backend/app/services/invite_codes.py backend/app/services/tests/test_invite_codes.py
git commit -m "feat: invite codes service — create, validate, consume with uses_left decrement"
```

---

## Task 5: Registration service

**Files:**
- Create: `backend/app/services/registration.py`
- Create: `backend/app/services/tests/test_registration.py`

- [ ] **Step 1: Write failing tests**

Create `backend/app/services/tests/test_registration.py`:

```python
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.models import HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _make_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.flush()
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _base(**overrides):
    return {
        "personal_number": f"pn_{_uid()}",
        "full_name": "Test Soldier",
        "password": "password-secure-1",
        "phone": "050-0000000",
        "gender": "male",
        "is_officer": False,
        "rank": "טוראי",
        "bahad1_graduate": False,
        "enlistment_date": date(2023, 1, 1),
        "mandatory_end_date": date(2025, 1, 1),
        "discharge_date": date(2026, 1, 1),
        "last_mitvahim_date": None,
        "last_alal_date": None,
        **overrides,
    }


def test_register_places_soldier_in_holding_node(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    soldier = register(
        admin_session, invite_code=invite.code, requested_node_id=node.id,
        exemption_requests=[], personal_constraints=[], **_base()
    )
    admin_session.commit()

    assert soldier.hierarchy_node_id == holding.id
    import sqlalchemy as sa
    req = admin_session.execute(
        sa.select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.soldier_id == soldier.id)
    ).scalar_one()
    assert req.status == "pending"
    assert req.requested_node_id == node.id


def test_register_decrements_invite_code(admin_session):
    _make_holding(admin_session)
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=2, actor_id=None)
    admin_session.commit()
    register(admin_session, invite_code=invite.code, requested_node_id=node.id,
             exemption_requests=[], personal_constraints=[], **_base())
    admin_session.commit()
    admin_session.refresh(invite)
    assert invite.uses_left == 1


def test_register_exhausted_code_raises(admin_session):
    _make_holding(admin_session)
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    from app.services.invite_codes import create_invite_code, InviteCodeError
    from app.services.registration import register
    invite = create_invite_code(admin_session, uses_left=0, actor_id=None)
    admin_session.commit()
    with pytest.raises(InviteCodeError):
        register(admin_session, invite_code=invite.code, requested_node_id=node.id,
                 exemption_requests=[], personal_constraints=[], **_base())


def test_register_duplicate_personal_number_raises(admin_session):
    _make_holding(admin_session)
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    pn = f"dup_{_uid()}"
    create_soldier(admin_session, personal_number=pn)
    from app.services.invite_codes import create_invite_code
    from app.services.registration import register, RegistrationError
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    with pytest.raises(RegistrationError, match="personal_number"):
        register(admin_session, invite_code=invite.code, requested_node_id=node.id,
                 exemption_requests=[], personal_constraints=[], **_base(personal_number=pn))
```

- [ ] **Step 2: Run — expect FAIL**

```
cd backend && uv run pytest app/services/tests/test_registration.py -v
```

- [ ] **Step 3: Create `backend/app/services/registration.py`**

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import (
    ExemptionRequest,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierEnrollmentRequest,
)
from app.services.invite_codes import InviteCodeError, consume_invite_code
from app.services.settings_loader import SettingNotFound, get_setting


class RegistrationError(Exception):
    pass


def register(
    session: Session,
    *,
    invite_code: str,
    personal_number: str,
    full_name: str,
    password: str,
    phone: str | None,
    gender: str | None,
    is_officer: bool | None,
    rank: str | None,
    bahad1_graduate: bool,
    enlistment_date: date | None,
    mandatory_end_date: date | None,
    discharge_date: date | None,
    last_mitvahim_date: date | None,
    last_alal_date: date | None,
    requested_node_id: uuid.UUID,
    exemption_requests: list[dict],
    personal_constraints: list[dict],
) -> Soldier:
    consume_invite_code(session, code=invite_code)

    if session.execute(
        select(Soldier.id).where(Soldier.personal_number == personal_number)
    ).first():
        raise RegistrationError("personal_number already exists")

    try:
        holding_node_id = uuid.UUID(get_setting(session, "system.holding_node_id"))
    except SettingNotFound as exc:
        raise RegistrationError("holding node not bootstrapped") from exc

    if session.get(HierarchyNode, requested_node_id) is None:
        raise RegistrationError("requested node not found")

    soldier = Soldier(
        personal_number=personal_number,
        full_name=full_name,
        password_hash=hash_password(password),
        role="soldier",
        hierarchy_node_id=holding_node_id,
        phone=phone,
        must_change_password=False,
        gender=gender,
        is_officer=is_officer,
        rank=rank,
        bahad1_graduate=bahad1_graduate,
        enlistment_date=enlistment_date,
        mandatory_end_date=mandatory_end_date,
        discharge_date=discharge_date,
        last_mitvahim_date=last_mitvahim_date,
        last_alal_date=last_alal_date,
    )
    session.add(soldier)
    session.flush()

    for er in exemption_requests:
        session.add(ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=er["exemption_type_id"],
            start_date=er["start_date"],
            end_date=er.get("end_date"),
            reason=er.get("reason"),
            status="pending",
        ))

    for pc in personal_constraints:
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc["reason"],
            status="pending",
        ))

    session.add(SoldierEnrollmentRequest(
        soldier_id=soldier.id,
        requested_node_id=requested_node_id,
        status="pending",
    ))
    session.flush()
    return soldier
```

- [ ] **Step 4: Run — expect PASS**

```
cd backend && uv run pytest app/services/tests/test_registration.py -v
```

- [ ] **Step 5: Commit**

```
git add backend/app/services/registration.py backend/app/services/tests/test_registration.py
git commit -m "feat: registration service — invite code, soldier creation in holding node, enrollment request"
```

---

## Task 6: Enrollment service

**Files:**
- Create: `backend/app/services/enrollment.py`
- Create: `backend/app/services/tests/test_enrollment.py`

- [ ] **Step 1: Write failing tests**

Create `backend/app/services/tests/test_enrollment.py`:

```python
from __future__ import annotations

import uuid
import pytest

from app.db.models import HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _make_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.flush()
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _make_req(session, soldier, node):
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def test_approve_moves_soldier_to_requested_node(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import approve_enrollment
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert soldier.hierarchy_node_id == node.id
    assert req.status == "approved"
    assert req.decided_by == decider.id


def test_reject_leaves_soldier_in_holding(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import reject_enrollment
    reject_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note="not eligible")
    admin_session.commit()
    admin_session.refresh(soldier)
    admin_session.refresh(req)

    assert soldier.hierarchy_node_id == holding.id
    assert req.status == "rejected"
    assert req.decision_note == "not eligible"


def test_approve_already_decided_raises(admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import approve_enrollment, EnrollmentError
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()

    with pytest.raises(EnrollmentError, match="already decided"):
        approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)


def test_list_pending_scoped_to_node_ids(admin_session):
    holding = _make_holding(admin_session)
    node_a = create_node(admin_session, level="unit", name=f"a_{_uid()}", parent=holding)
    node_b = create_node(admin_session, level="unit", name=f"b_{_uid()}", parent=holding)
    s1 = create_soldier(admin_session, personal_number=f"s1_{_uid()}", hierarchy_node_id=holding.id)
    s2 = create_soldier(admin_session, personal_number=f"s2_{_uid()}", hierarchy_node_id=holding.id)
    _make_req(admin_session, s1, node_a)
    _make_req(admin_session, s2, node_b)

    from app.services.enrollment import list_pending_for_node_ids
    results = list_pending_for_node_ids(admin_session, {node_a.id})
    assert len(results) == 1
    assert results[0].soldier_id == s1.id
```

- [ ] **Step 2: Run — expect FAIL**

```
cd backend && uv run pytest app/services/tests/test_enrollment.py -v
```

- [ ] **Step 3: Create `backend/app/services/enrollment.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyNode, Soldier, SoldierEnrollmentRequest


class EnrollmentError(Exception):
    pass


def approve_enrollment(
    session: Session,
    *,
    request_id: uuid.UUID,
    decider_id: uuid.UUID,
    decision_note: str | None,
) -> SoldierEnrollmentRequest:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise EnrollmentError("enrollment request not found")
    if req.status != "pending":
        raise EnrollmentError("already decided")
    soldier = session.get(Soldier, req.soldier_id)
    assert soldier is not None
    soldier.hierarchy_node_id = req.requested_node_id
    req.status = "approved"
    req.decided_by = decider_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = decision_note
    session.flush()
    write_audit(session, actor_id=decider_id, action="enrollment.approve",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"soldier_id": str(req.soldier_id), "node_id": str(req.requested_node_id)})
    return req


def reject_enrollment(
    session: Session,
    *,
    request_id: uuid.UUID,
    decider_id: uuid.UUID,
    decision_note: str,
) -> SoldierEnrollmentRequest:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise EnrollmentError("enrollment request not found")
    if req.status != "pending":
        raise EnrollmentError("already decided")
    req.status = "rejected"
    req.decided_by = decider_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = decision_note
    session.flush()
    write_audit(session, actor_id=decider_id, action="enrollment.reject",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"decision_note": decision_note})
    return req


def list_pending_for_node_ids(
    session: Session, node_ids: set[uuid.UUID]
) -> list[SoldierEnrollmentRequest]:
    if not node_ids:
        return []
    all_pending = session.execute(
        select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.status == "pending")
    ).scalars().all()
    result = []
    for req in all_pending:
        target = session.get(HierarchyNode, req.requested_node_id)
        if target and any(r in target.path_ids for r in node_ids):
            result.append(req)
    return result
```

- [ ] **Step 4: Run — expect PASS**

```
cd backend && uv run pytest app/services/tests/test_enrollment.py -v
```

- [ ] **Step 5: Commit**

```
git add backend/app/services/enrollment.py backend/app/services/tests/test_enrollment.py
git commit -m "feat: enrollment service — approve, reject, list_pending_for_node_ids"
```

---

## Task 7: Extend /me endpoint

**Files:**
- Modify: `backend/app/routes/me.py`

- [ ] **Step 1: Replace `backend/app/routes/me.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.models import Soldier, TelegramLink
from app.db.session import get_session
from app.services.settings_loader import get_setting

router = APIRouter(prefix="/me", tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    must_change_password: bool
    hierarchy_node_id: uuid.UUID | None
    telegram_linked: bool
    telegram_required: bool


@router.get("", response_model=MeResponse)
def me(
    user: Soldier = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MeResponse:
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == user.id,
            TelegramLink.is_verified == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    try:
        telegram_required = bool(get_setting(session, "registration.telegram_required"))
    except Exception:
        telegram_required = True
    return MeResponse(
        id=user.id,
        personal_number=user.personal_number,
        full_name=user.full_name,
        role=user.role,
        must_change_password=user.must_change_password,
        hierarchy_node_id=user.hierarchy_node_id,
        telegram_linked=link is not None,
        telegram_required=telegram_required,
    )
```

- [ ] **Step 2: Run existing tests to confirm no regression**

```
cd backend && uv run pytest -v
```

- [ ] **Step 3: Commit**

```
git add backend/app/routes/me.py
git commit -m "feat: extend /me with telegram_linked and telegram_required fields"
```

---

## Task 8: Registration routes

**Files:**
- Modify: `backend/app/routes/auth.py`
- Create: `backend/app/routes/tests/test_registration_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `backend/app/routes/tests/test_registration_routes.py`:

```python
from __future__ import annotations

import uuid

from app.db.models import HierarchyNode, SystemSetting
from app.services.invite_codes import create_invite_code
from tests.helpers import create_node


def _uid():
    return uuid.uuid4().hex[:8]


def _setup_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _payload(invite_code, node_id, **overrides):
    return {
        "invite_code": invite_code,
        "personal_number": f"pn_{_uid()}",
        "full_name": "Test Soldier",
        "password": "secure-password-1",
        "phone": "050-1234567",
        "gender": "male",
        "is_officer": False,
        "rank": "טוראי",
        "bahad1_graduate": False,
        "enlistment_date": "2023-01-01",
        "mandatory_end_date": "2025-01-01",
        "discharge_date": "2026-01-01",
        "last_mitvahim_date": None,
        "last_alal_date": None,
        "requested_node_id": str(node_id),
        "exemption_requests": [],
        "personal_constraints": [],
        **overrides,
    }


def test_register_returns_access_token(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    resp = client.post("/api/auth/register", json=_payload(invite.code, node.id))
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_register_exhausted_code_returns_400(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=0, actor_id=None)
    admin_session.commit()

    resp = client.post("/api/auth/register", json=_payload(invite.code, node.id))
    assert resp.status_code == 400


def test_validate_code_endpoint(client, admin_session):
    invite = create_invite_code(admin_session, uses_left=3, actor_id=None)
    admin_session.commit()
    assert client.get(f"/api/auth/register/validate-code?code={invite.code}").json()["valid"] is True
    assert client.get("/api/auth/register/validate-code?code=INVALID1").json()["valid"] is False


def test_register_nodes_returns_list(client, admin_session):
    create_node(admin_session, level="division", name=f"div_{_uid()}")
    resp = client.get("/api/auth/register/nodes")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 2: Run — expect FAIL (routes not defined)**

```
cd backend && uv run pytest app/routes/tests/test_registration_routes.py -v
```

- [ ] **Step 3: Add to `backend/app/routes/auth.py`**

Add these imports at the top of auth.py (after existing imports):

```python
import uuid
from datetime import date

from app.db.models import HierarchyNode
from app.services import registration as reg_svc
from app.services.invite_codes import InviteCodeError, validate_code
from app.services.registration import RegistrationError
```

Add these Pydantic models after `ChangePasswordRequest`:

```python
class RegisterRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=20)
    personal_number: str = Field(min_length=1, max_length=20)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: date | None = None
    mandatory_end_date: date | None = None
    discharge_date: date | None = None
    last_mitvahim_date: date | None = None
    last_alal_date: date | None = None
    requested_node_id: uuid.UUID
    exemption_requests: list[dict] = []
    personal_constraints: list[dict] = []


class NodeOut(BaseModel):
    id: uuid.UUID
    name: str
    level: str
    path_ids: list[uuid.UUID]
    commander_name: str | None
    parent_id: uuid.UUID | None
```

Add these three handlers inside the router (after `change_password`):

```python
@router.post("/register", response_model=LoginResponse)
def register(
    body: RegisterRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()
    try:
        soldier = reg_svc.register(
            session,
            invite_code=body.invite_code,
            personal_number=body.personal_number,
            full_name=body.full_name,
            password=body.password,
            phone=body.phone,
            gender=body.gender,
            is_officer=body.is_officer,
            rank=body.rank,
            bahad1_graduate=body.bahad1_graduate,
            enlistment_date=body.enlistment_date,
            mandatory_end_date=body.mandatory_end_date,
            discharge_date=body.discharge_date,
            last_mitvahim_date=body.last_mitvahim_date,
            last_alal_date=body.last_alal_date,
            requested_node_id=body.requested_node_id,
            exemption_requests=body.exemption_requests,
            personal_constraints=body.personal_constraints,
        )
        session.commit()
    except (InviteCodeError, RegistrationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    refresh = issue_refresh_token(user_id=soldier.id)
    response.set_cookie(
        key="refresh_token", value=refresh,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True, secure=False, samesite="strict", path="/api/auth",
    )
    return LoginResponse(access_token=access, must_change_password=False)


@router.get("/register/nodes", response_model=list[NodeOut])
def register_nodes(session: Session = Depends(get_session)) -> list[NodeOut]:
    from sqlalchemy import select as sa_select
    nodes = session.execute(sa_select(HierarchyNode)).scalars().all()
    result = []
    for n in nodes:
        commander_name: str | None = None
        if n.commander_id:
            s = session.get(Soldier, n.commander_id)
            commander_name = s.full_name if s else None
        result.append(NodeOut(id=n.id, name=n.name, level=n.level,
                               path_ids=n.path_ids, commander_name=commander_name, parent_id=n.parent_id))
    return result


@router.get("/register/validate-code")
def validate_invite_code(code: str, session: Session = Depends(get_session)) -> dict:
    return {"valid": validate_code(session, code=code)}
```

- [ ] **Step 4: Run — expect PASS**

```
cd backend && uv run pytest app/routes/tests/test_registration_routes.py -v
```

- [ ] **Step 5: Commit**

```
git add backend/app/routes/auth.py backend/app/routes/tests/test_registration_routes.py
git commit -m "feat: POST /auth/register, GET /auth/register/nodes, GET /auth/register/validate-code"
```

---

## Task 9: Enrollment routes

**Files:**
- Create: `backend/app/routes/enrollment.py`
- Create: `backend/app/routes/tests/test_enrollment_routes.py`

- [ ] **Step 1: Write failing tests**

Create `backend/app/routes/tests/test_enrollment_routes.py`:

```python
from __future__ import annotations

import uuid

from app.db.models import HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from tests.helpers import auth_headers, create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _make_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _make_req(session, soldier, node):
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def test_admin_can_list_pending(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    _make_req(admin_session, soldier, node)

    resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_admin_can_approve(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/approve",
                       json={"decision_note": None}, headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_session.refresh(soldier)
    assert soldier.hierarchy_node_id == node.id


def test_admin_can_reject(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/reject",
                       json={"decision_note": "not eligible"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_session.refresh(soldier)
    assert soldier.hierarchy_node_id == holding.id


def test_reject_without_note_fails(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/reject",
                       json={"decision_note": ""}, headers=auth_headers(admin))
    assert resp.status_code == 422


def test_plain_soldier_cannot_approve(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    other = create_soldier(admin_session, personal_number=f"o_{_uid()}", role="soldier")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/approve",
                       json={"decision_note": None}, headers=auth_headers(other))
    assert resp.status_code == 403
```

- [ ] **Step 2: Run — expect FAIL**

```
cd backend && uv run pytest app/routes/tests/test_enrollment_routes.py -v
```

- [ ] **Step 3: Create `backend/app/routes/enrollment.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier, SoldierEnrollmentRequest
from app.db.session import get_session
from app.services import enrollment as svc

router = APIRouter(prefix="/enrollment-requests", tags=["enrollment"])


class EnrollmentRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    requested_node_id: uuid.UUID
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None


class DecisionBody(BaseModel):
    decision_note: str | None = None


@router.get("/pending", response_model=list[EnrollmentRequestOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EnrollmentRequestOut]:
    if user.role == "admin":
        reqs = session.execute(
            select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.status == "pending")
        ).scalars().all()
    else:
        roots = scope_root_ids(session, user)
        reqs = svc.list_pending_for_node_ids(session, roots)
    return [
        EnrollmentRequestOut(id=r.id, soldier_id=r.soldier_id, requested_node_id=r.requested_node_id,
                             status=r.status, decided_by=r.decided_by, decision_note=r.decision_note)
        for r in reqs
    ]


@router.post("/{request_id}/approve")
def approve(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.approve_enrollment(session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note)
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{request_id}/reject")
def reject(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not body.decision_note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="decision_note required")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.reject_enrollment(session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note)
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
```

- [ ] **Step 4: Run — still FAIL (router not wired). Move to Task 10.**

---

## Task 10: Invite codes routes + wire all routers

**Files:**
- Create: `backend/app/routes/invite_codes.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/routes/tests/test_invite_code_routes.py`

- [ ] **Step 1: Create `backend/app/routes/invite_codes.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import RegistrationInviteCode
from app.db.session import get_session
from app.services import invite_codes as svc

router = APIRouter(prefix="/admin/invite-codes", tags=["invite_codes"])


class CreateCodeRequest(BaseModel):
    uses_left: int


class InviteCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    uses_left: int
    created_by: uuid.UUID | None


@router.get("", response_model=list[InviteCodeOut])
def list_codes(
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> list[InviteCodeOut]:
    codes = session.execute(select(RegistrationInviteCode)).scalars().all()
    return [InviteCodeOut(id=c.id, code=c.code, uses_left=c.uses_left, created_by=c.created_by) for c in codes]


@router.post("", response_model=InviteCodeOut, status_code=status.HTTP_201_CREATED)
def create_code(
    body: CreateCodeRequest,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> InviteCodeOut:
    code = svc.create_invite_code(session, uses_left=body.uses_left, actor_id=user.id)
    session.commit()
    return InviteCodeOut(id=code.id, code=code.code, uses_left=code.uses_left, created_by=code.created_by)


@router.delete("/{code_id}")
def revoke_code(
    code_id: uuid.UUID,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> dict:
    code = session.get(RegistrationInviteCode, code_id)
    if code is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    session.delete(code)
    session.commit()
    return {"status": "ok"}
```

- [ ] **Step 2: Wire new routers in `backend/app/main.py`**

Add imports:
```python
from app.routes import enrollment as enrollment_routes
from app.routes import invite_codes as invite_code_routes
```

Add inside `create_app()` after `notification_routes`:
```python
app.include_router(enrollment_routes.router, prefix="/api")
app.include_router(invite_code_routes.router, prefix="/api")
```

- [ ] **Step 3: Write invite code route tests**

Create `backend/app/routes/tests/test_invite_code_routes.py`:

```python
from __future__ import annotations
import uuid
from tests.helpers import auth_headers, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_admin_creates_code(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    resp = client.post("/api/admin/invite-codes", json={"uses_left": 5}, headers=auth_headers(admin))
    assert resp.status_code == 201
    assert resp.json()["uses_left"] == 5
    assert len(resp.json()["code"]) == 8


def test_non_admin_forbidden(client, admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    resp = client.post("/api/admin/invite-codes", json={"uses_left": 1}, headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_admin_lists_codes(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    client.post("/api/admin/invite-codes", json={"uses_left": 1}, headers=auth_headers(admin))
    resp = client.get("/api/admin/invite-codes", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_admin_revokes_code(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    create_resp = client.post("/api/admin/invite-codes", json={"uses_left": 2}, headers=auth_headers(admin))
    code_id = create_resp.json()["id"]
    resp = client.delete(f"/api/admin/invite-codes/{code_id}", headers=auth_headers(admin))
    assert resp.status_code == 200
```

- [ ] **Step 4: Run all new route tests**

```
cd backend && uv run pytest app/routes/tests/test_enrollment_routes.py app/routes/tests/test_invite_code_routes.py app/routes/tests/test_registration_routes.py -v
```

- [ ] **Step 5: Run full suite**

```
cd backend && uv run pytest -v
```

- [ ] **Step 6: Commit**

```
git add backend/app/routes/enrollment.py backend/app/routes/invite_codes.py backend/app/main.py backend/app/routes/tests/test_enrollment_routes.py backend/app/routes/tests/test_invite_code_routes.py
git commit -m "feat: enrollment and invite code routes, wire all new routers in main.py"
```

---

## Task 11: Frontend — fuse.js + API clients

**Files:**
- Modify: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/enrollment.ts`
- Create: `frontend/src/api/inviteCodes.ts`

- [ ] **Step 1: Install fuse.js**

```
cd frontend && pnpm add fuse.js
```

- [ ] **Step 2: Replace `frontend/src/api/auth.ts`**

```typescript
import { api } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
}

export interface Me {
  id: string;
  personal_number: string;
  full_name: string;
  role: "soldier" | "commander" | "duty_manager" | "admin";
  must_change_password: boolean;
  hierarchy_node_id: string | null;
  telegram_linked: boolean;
  telegram_required: boolean;
}

export interface NodeOut {
  id: string;
  name: string;
  level: string;
  path_ids: string[];
  commander_name: string | null;
  parent_id: string | null;
}

export interface RegisterPayload {
  invite_code: string;
  personal_number: string;
  full_name: string;
  password: string;
  phone: string | null;
  gender: string | null;
  is_officer: boolean | null;
  rank: string | null;
  bahad1_graduate: boolean;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  requested_node_id: string;
  exemption_requests: object[];
  personal_constraints: object[];
}

export async function login(personal_number: string, password: string): Promise<LoginResponse> {
  const r = await api.post<LoginResponse>("/auth/login", { personal_number, password });
  return r.data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}

export async function fetchMe(): Promise<Me> {
  const r = await api.get<Me>("/me");
  return r.data;
}

export async function changePassword(current_password: string, new_password: string): Promise<void> {
  await api.post("/auth/change-password", { current_password, new_password });
}

export async function register(payload: RegisterPayload): Promise<LoginResponse> {
  const r = await api.post<LoginResponse>("/auth/register", payload);
  return r.data;
}

export async function fetchRegisterNodes(): Promise<NodeOut[]> {
  const r = await api.get<NodeOut[]>("/auth/register/nodes");
  return r.data;
}

export async function validateInviteCode(code: string): Promise<boolean> {
  const r = await api.get<{ valid: boolean }>(`/auth/register/validate-code?code=${encodeURIComponent(code)}`);
  return r.data.valid;
}
```

- [ ] **Step 3: Create `frontend/src/api/enrollment.ts`**

```typescript
import { api } from "./client";

export interface EnrollmentRequestDTO {
  id: string;
  soldier_id: string;
  requested_node_id: string;
  status: string;
  decided_by: string | null;
  decision_note: string | null;
}

export async function listPendingEnrollments(): Promise<EnrollmentRequestDTO[]> {
  const r = await api.get<EnrollmentRequestDTO[]>("/enrollment-requests/pending");
  return r.data;
}

export async function approveEnrollment(id: string, decision_note?: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/approve`, { decision_note: decision_note ?? null });
}

export async function rejectEnrollment(id: string, decision_note: string): Promise<void> {
  await api.post(`/enrollment-requests/${id}/reject`, { decision_note });
}
```

- [ ] **Step 4: Create `frontend/src/api/inviteCodes.ts`**

```typescript
import { api } from "./client";

export interface InviteCodeDTO {
  id: string;
  code: string;
  uses_left: number;
  created_by: string | null;
}

export async function listInviteCodes(): Promise<InviteCodeDTO[]> {
  const r = await api.get<InviteCodeDTO[]>("/admin/invite-codes");
  return r.data;
}

export async function createInviteCode(uses_left: number): Promise<InviteCodeDTO> {
  const r = await api.post<InviteCodeDTO>("/admin/invite-codes", { uses_left });
  return r.data;
}

export async function revokeInviteCode(id: string): Promise<void> {
  await api.delete(`/admin/invite-codes/${id}`);
}
```

- [ ] **Step 5: Commit**

```
git add frontend/src/api/auth.ts frontend/src/api/enrollment.ts frontend/src/api/inviteCodes.ts
git commit -m "feat: add fuse.js; extend Me type; add register, enrollment, inviteCodes API clients"
```

---

## Task 12: AuthContext + ProtectedRoute + App.tsx

**Files:**
- Modify: `frontend/src/auth/AuthContext.tsx`
- Modify: `frontend/src/auth/ProtectedRoute.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Replace `frontend/src/auth/AuthContext.tsx`**

```typescript
import { createContext, useCallback, useContext, useMemo, useState, ReactNode } from "react";
import { changePassword as apiChangePassword, fetchMe, login as apiLogin, logout as apiLogout, Me } from "../api/auth";
import { setAccessToken } from "../api/client";

interface AuthContextValue {
  user: Me | null;
  loggedIn: boolean;
  mustChangePassword: boolean;
  telegramLinked: boolean;
  telegramRequired: boolean;
  login: (personal_number: string, password: string) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);

  const login = useCallback(async (personal_number: string, password: string) => {
    const r = await apiLogin(personal_number, password);
    setAccessToken(r.access_token);
    setUser(await fetchMe());
  }, []);

  const loginWithToken = useCallback(async (token: string) => {
    setAccessToken(token);
    setUser(await fetchMe());
  }, []);

  const logout = useCallback(async () => {
    try { await apiLogout(); } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const changePassword = useCallback(async (current: string, next: string) => {
    await apiChangePassword(current, next);
    setUser(await fetchMe());
  }, []);

  const refreshMe = useCallback(async () => {
    setUser(await fetchMe());
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user, loggedIn: user !== null,
      mustChangePassword: user?.must_change_password ?? false,
      telegramLinked: user?.telegram_linked ?? false,
      telegramRequired: user?.telegram_required ?? false,
      login, loginWithToken, logout, changePassword, refreshMe,
    }),
    [user, login, loginWithToken, logout, changePassword, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth used outside AuthProvider");
  return ctx;
}
```

- [ ] **Step 2: ProtectedRoute is unchanged** — leave as-is (it only checks `loggedIn`).

- [ ] **Step 3: Replace `frontend/src/App.tsx`**

```typescript
import { Navigate, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { SoldierModalProvider } from "./contexts/SoldierModalContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import ApprovalsPage from "./pages/ApprovalsPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import DutyConfigPage from "./pages/DutyConfigPage";
import DutyManagementPage from "./pages/DutyManagementPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MyDutiesPage from "./pages/MyDutiesPage";
import MyRequestsPage from "./pages/MyRequestsPage";
import NotificationsPage from "./pages/NotificationsPage";
import ProfilePage from "./pages/ProfilePage";
import TeamHierarchyPage from "./pages/TeamHierarchyPage";
import ShiftsPage from "./pages/ShiftsPage";
import ShiftTemplatesPage from "./pages/ShiftTemplatesPage";
import SwapsPage from "./pages/SwapsPage";
import TransparencyPage from "./pages/TransparencyPage";
import UnitCalendarPage from "./pages/UnitCalendarPage";
import CommandDashboardPage from "./pages/CommandDashboardPage";
import AlgorithmPage from "./pages/AlgorithmPage";
import RegisterPage from "./pages/RegisterPage";
import TelegramSetupPage from "./pages/TelegramSetupPage";
import AdminInviteCodesPage from "./pages/AdminInviteCodesPage";

function ForcedPasswordGate({ children }: { children: ReactElement }) {
  const { mustChangePassword } = useAuth();
  if (mustChangePassword) return <Navigate to="/change-password" replace />;
  return children;
}

function TelegramGate({ children }: { children: ReactElement }) {
  const { telegramRequired, telegramLinked } = useAuth();
  if (telegramRequired && !telegramLinked) return <Navigate to="/setup/telegram" replace />;
  return children;
}

function AppGate({ children }: { children: ReactElement }) {
  return <ForcedPasswordGate><TelegramGate>{children}</TelegramGate></ForcedPasswordGate>;
}

export default function App() {
  return (
    <AuthProvider>
      <SoldierModalProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route path="/setup/telegram" element={<TelegramSetupPage />} />
            <Route path="/" element={<AppGate><HomePage /></AppGate>} />
            <Route path="/team" element={<AppGate><TeamHierarchyPage /></AppGate>} />
            <Route path="/duty-config" element={<AppGate><DutyConfigPage /></AppGate>} />
            <Route path="/duty-management" element={<AppGate><DutyManagementPage /></AppGate>} />
            <Route path="/transparency" element={<AppGate><TransparencyPage /></AppGate>} />
            <Route path="/my-duties" element={<AppGate><MyDutiesPage /></AppGate>} />
            <Route path="/my-requests" element={<AppGate><MyRequestsPage /></AppGate>} />
            <Route path="/approvals" element={<AppGate><ApprovalsPage /></AppGate>} />
            <Route path="/unit-calendar" element={<AppGate><UnitCalendarPage /></AppGate>} />
            <Route path="/shifts" element={<AppGate><ShiftsPage /></AppGate>} />
            <Route path="/shift-templates" element={<AppGate><ShiftTemplatesPage /></AppGate>} />
            <Route path="/swaps" element={<AppGate><SwapsPage /></AppGate>} />
            <Route path="/profile" element={<AppGate><ProfilePage /></AppGate>} />
            <Route path="/command-dashboard" element={<AppGate><CommandDashboardPage /></AppGate>} />
            <Route path="/notifications" element={<AppGate><NotificationsPage /></AppGate>} />
            <Route path="/algorithm" element={<AppGate><AlgorithmPage /></AppGate>} />
            <Route path="/admin/invite-codes" element={<AppGate><AdminInviteCodesPage /></AppGate>} />
          </Route>
        </Routes>
      </SoldierModalProvider>
    </AuthProvider>
  );
}
```

- [ ] **Step 4: Commit**

```
git add frontend/src/auth/AuthContext.tsx frontend/src/App.tsx
git commit -m "feat: add TelegramGate, loginWithToken, refreshMe to AuthContext; add /register and /setup/telegram routes"
```

---

## Task 13: i18n keys + LoginPage הרשמה button

**Files:**
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/pages/LoginPage.tsx`

- [ ] **Step 1: Add keys to `frontend/src/i18n/he.json`**

Add these top-level keys inside the root JSON object (before the closing `}`):

```json
,
"register": {
  "title": "הרשמה",
  "signup_button": "הרשמה לחייל חדש",
  "step_invite": "קוד הזמנה",
  "step_personal": "פרטים אישיים",
  "step_exemptions": "בקשות פטור",
  "step_constraints": "אילוצים אישיים",
  "step_commander": "בחירת מסגרת",
  "step_review": "סקירה ואישור",
  "invite_code_label": "קוד הזמנה",
  "invite_code_invalid": "קוד שגוי או מוצה",
  "next": "הבא",
  "back": "חזור",
  "skip": "דלג",
  "submit": "הרשם",
  "submitting": "נרשם...",
  "search_commander": "חפש מסגרת או מפקד",
  "no_results": "לא נמצאו תוצאות",
  "selected_node": "מסגרת נבחרת",
  "commander_label": "מפקד",
  "add_exemption": "הוסף פטור",
  "add_constraint": "הוסף אילוץ",
  "remove": "הסר",
  "reason": "סיבה",
  "errors": {
    "invite_code_exhausted": "קוד ההזמנה מוצה",
    "personal_number_exists": "מספר אישי כבר קיים במערכת",
    "network": "שגיאת רשת. נסה שוב."
  }
},
"telegram_setup": {
  "title": "חיבור טלגרם",
  "instructions": "שלח את הקוד הבא לבוט שלנו כדי לקשר את החשבון:",
  "check_button": "בדוק אימות",
  "checking": "בודק...",
  "verified": "החשבון אומת בהצלחה!",
  "bot_link": "פתח את הבוט",
  "skip_for_now": "דלג כרגע"
},
"enrollment": {
  "tab": "הצטרפות",
  "none": "אין בקשות הצטרפות ממתינות",
  "requested_node": "מסגרת מבוקשת",
  "approve": "אשר",
  "reject": "דחה",
  "decision_note_placeholder": "הערת החלטה (חובה לדחייה)"
},
"invite_codes": {
  "title": "קודי הזמנה",
  "create": "צור קוד",
  "uses_left": "שימושים שנותרו",
  "revoke": "בטל",
  "create_dialog_title": "קוד הזמנה חדש",
  "uses_left_label": "מספר שימושים"
}
```

- [ ] **Step 2: Add הרשמה link to `frontend/src/pages/LoginPage.tsx`**

After the closing `</button>` of the submit button, add:

```tsx
<p className="text-center text-sm text-gray-500 mt-2">
  <a href="/register" className="text-indigo-600 hover:underline">
    {t("register.signup_button")}
  </a>
</p>
```

- [ ] **Step 3: Commit**

```
git add frontend/src/i18n/he.json frontend/src/pages/LoginPage.tsx
git commit -m "feat: add i18n keys for register/telegram/enrollment/invite_codes; add signup link to login page"
```

---

## Task 14: RegisterPage wizard

**Files:**
- Create: `frontend/src/pages/RegisterPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/RegisterPage.tsx`**

```tsx
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Fuse from "fuse.js";
import { validateInviteCode, fetchRegisterNodes, register, NodeOut } from "../api/auth";
import { useAuth } from "../auth/AuthContext";

const ALL_RANKS = [
  "טוראי","רבט","סמל","סמר","רסל","רסר","רסמ","רסב","רנג",
  "קמא","סגמ","סגן","קאב","סרן","רסן","סאל","אלמ","תאל","אלוף","רב אלוף",
];

interface ExemptionRow { exemption_type_id: string; start_date: string; end_date: string; reason: string; }
interface ConstraintRow { start_date: string; end_date: string; reason: string; }
interface FormData {
  invite_code: string; personal_number: string; full_name: string;
  password: string; confirm_password: string; phone: string;
  gender: string; is_officer: boolean; rank: string; bahad1_graduate: boolean;
  enlistment_date: string; mandatory_end_date: string; discharge_date: string;
  last_mitvahim_date: string; last_alal_date: string;
  requested_node_id: string;
  exemption_requests: ExemptionRow[];
  personal_constraints: ConstraintRow[];
}

const INITIAL: FormData = {
  invite_code: "", personal_number: "", full_name: "", password: "",
  confirm_password: "", phone: "", gender: "", is_officer: false, rank: "",
  bahad1_graduate: false, enlistment_date: "", mandatory_end_date: "",
  discharge_date: "", last_mitvahim_date: "", last_alal_date: "",
  requested_node_id: "", exemption_requests: [], personal_constraints: [],
};

export default function RegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { loginWithToken } = useAuth();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<FormData>(INITIAL);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [nodes, setNodes] = useState<NodeOut[]>([]);
  const [nodeSearch, setNodeSearch] = useState("");
  const [codeValid, setCodeValid] = useState<boolean | null>(null);

  useEffect(() => { fetchRegisterNodes().then(setNodes).catch(() => {}); }, []);

  const fuse = new Fuse(nodes, { keys: ["name", "commander_name"], threshold: 0.4 });
  const searchResults = nodeSearch ? fuse.search(nodeSearch).map(r => r.item) : nodes.slice(0, 20);

  function set<K extends keyof FormData>(key: K, value: FormData[K]) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  async function checkCode() {
    const valid = await validateInviteCode(form.invite_code);
    setCodeValid(valid);
    return valid;
  }

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);
    try {
      const resp = await register({
        invite_code: form.invite_code,
        personal_number: form.personal_number,
        full_name: form.full_name,
        password: form.password,
        phone: form.phone || null,
        gender: form.gender || null,
        is_officer: form.is_officer,
        rank: form.rank || null,
        bahad1_graduate: form.bahad1_graduate,
        enlistment_date: form.enlistment_date || null,
        mandatory_end_date: form.mandatory_end_date || null,
        discharge_date: form.discharge_date || null,
        last_mitvahim_date: form.last_mitvahim_date || null,
        last_alal_date: form.last_alal_date || null,
        requested_node_id: form.requested_node_id,
        exemption_requests: form.exemption_requests,
        personal_constraints: form.personal_constraints,
      });
      await loginWithToken(resp.access_token);
      navigate("/setup/telegram", { replace: true });
    } catch {
      setError(t("register.errors.network"));
    } finally {
      setSubmitting(false);
    }
  }

  const selectedNode = nodes.find(n => n.id === form.requested_node_id);

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-lg bg-white shadow rounded-lg p-6 space-y-4">
        <h1 className="text-2xl font-bold text-center">{t("register.title")}</h1>
        <div className="flex gap-1 justify-center">
          {[1,2,3,4,5,6].map(s => (
            <span key={s} className={`px-2 py-1 rounded text-xs ${step === s ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-400"}`}>{s}</span>
          ))}
        </div>
        {error && <div className="text-red-600 text-sm">{error}</div>}

        {step === 1 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_invite")}</h2>
            <label className="block text-sm">{t("register.invite_code_label")}
              <input className="mt-1 block w-full border rounded p-2" value={form.invite_code}
                onChange={e => { set("invite_code", e.target.value); setCodeValid(null); }} />
            </label>
            {codeValid === false && <p className="text-red-600 text-sm">{t("register.invite_code_invalid")}</p>}
            <button className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
              onClick={async () => { if (await checkCode()) setStep(2); }} disabled={!form.invite_code}>
              {t("register.next")}
            </button>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-2">
            <h2 className="font-semibold">{t("register.step_personal")}</h2>
            {([["personal_number","מספר אישי","text"],["full_name","שם מלא","text"],["phone","טלפון","tel"],
               ["enlistment_date","תאריך גיוס","date"],["mandatory_end_date","סיום חובה","date"],
               ["discharge_date","שחרור","date"],["last_mitvahim_date","מטווח אחרון","date"],
               ["last_alal_date","אל\"ל אחרון","date"]] as [keyof FormData, string, string][]).map(([key, label, type]) => (
              <label key={key as string} className="block text-sm">{label}
                <input type={type} className="mt-1 block w-full border rounded p-2"
                  value={form[key] as string}
                  onChange={e => set(key, e.target.value as any)} />
              </label>
            ))}
            <label className="block text-sm">מגדר
              <select className="mt-1 block w-full border rounded p-2" value={form.gender} onChange={e => set("gender", e.target.value)}>
                <option value="">בחר</option><option value="male">זכר</option><option value="female">נקבה</option>
              </select>
            </label>
            <label className="block text-sm">דרגה
              <select className="mt-1 block w-full border rounded p-2" value={form.rank} onChange={e => set("rank", e.target.value)}>
                <option value="">בחר</option>
                {ALL_RANKS.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.is_officer} onChange={e => set("is_officer", e.target.checked)} /> קצין
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.bahad1_graduate} onChange={e => set("bahad1_graduate", e.target.checked)} /> בוגר בה"ד 1
            </label>
            <label className="block text-sm">סיסמה
              <input type="password" className="mt-1 block w-full border rounded p-2" value={form.password} onChange={e => set("password", e.target.value)} />
            </label>
            <label className="block text-sm">אימות סיסמה
              <input type="password" className="mt-1 block w-full border rounded p-2" value={form.confirm_password} onChange={e => set("confirm_password", e.target.value)} />
            </label>
            {form.confirm_password && form.password !== form.confirm_password && (
              <p className="text-red-600 text-sm">הסיסמאות אינן תואמות</p>
            )}
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(1)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={!form.personal_number || !form.full_name || form.password.length < 10 || form.password !== form.confirm_password}
                onClick={() => setStep(3)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_exemptions")}</h2>
            {form.exemption_requests.map((er, i) => (
              <div key={i} className="border rounded p-2 space-y-1 text-sm">
                <input placeholder="מזהה סוג פטור (UUID)" className="block w-full border rounded p-1" value={er.exemption_type_id}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], exemption_type_id: e.target.value}; set("exemption_requests", rows); }} />
                <input type="date" className="block w-full border rounded p-1" value={er.start_date}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], start_date: e.target.value}; set("exemption_requests", rows); }} />
                <input type="date" className="block w-full border rounded p-1" value={er.end_date}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], end_date: e.target.value}; set("exemption_requests", rows); }} />
                <input placeholder={t("register.reason")} className="block w-full border rounded p-1" value={er.reason}
                  onChange={e => { const rows = [...form.exemption_requests]; rows[i] = {...rows[i], reason: e.target.value}; set("exemption_requests", rows); }} />
                <button className="text-red-600 text-xs" onClick={() => set("exemption_requests", form.exemption_requests.filter((_,j) => j !== i))}>{t("register.remove")}</button>
              </div>
            ))}
            <button className="text-indigo-600 text-sm"
              onClick={() => set("exemption_requests", [...form.exemption_requests, {exemption_type_id:"",start_date:"",end_date:"",reason:""}])}>
              + {t("register.add_exemption")}
            </button>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(2)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded" onClick={() => setStep(4)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_constraints")}</h2>
            {form.personal_constraints.map((pc, i) => (
              <div key={i} className="border rounded p-2 space-y-1 text-sm">
                <input type="date" className="block w-full border rounded p-1" value={pc.start_date}
                  onChange={e => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], start_date: e.target.value}; set("personal_constraints", rows); }} />
                <input type="date" className="block w-full border rounded p-1" value={pc.end_date}
                  onChange={e => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], end_date: e.target.value}; set("personal_constraints", rows); }} />
                <input placeholder={t("register.reason")} className="block w-full border rounded p-1" value={pc.reason}
                  onChange={e => { const rows = [...form.personal_constraints]; rows[i] = {...rows[i], reason: e.target.value}; set("personal_constraints", rows); }} />
                <button className="text-red-600 text-xs" onClick={() => set("personal_constraints", form.personal_constraints.filter((_,j) => j !== i))}>{t("register.remove")}</button>
              </div>
            ))}
            <button className="text-indigo-600 text-sm"
              onClick={() => set("personal_constraints", [...form.personal_constraints, {start_date:"",end_date:"",reason:""}])}>
              + {t("register.add_constraint")}
            </button>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(3)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded" onClick={() => setStep(5)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_commander")}</h2>
            <input className="block w-full border rounded p-2 text-sm" placeholder={t("register.search_commander")}
              value={nodeSearch} onChange={e => setNodeSearch(e.target.value)} />
            <div className="max-h-52 overflow-y-auto border rounded divide-y text-sm">
              {searchResults.length === 0 && <p className="p-2 text-gray-400">{t("register.no_results")}</p>}
              {searchResults.map(n => (
                <button key={n.id}
                  className={`w-full text-right p-2 hover:bg-indigo-50 ${form.requested_node_id === n.id ? "bg-indigo-100 font-semibold" : ""}`}
                  onClick={() => set("requested_node_id", n.id)}>
                  <span>{n.name}</span>
                  {n.commander_name && <span className="text-gray-400 text-xs mr-2">({n.commander_name})</span>}
                  <span className="text-gray-300 text-xs mr-1">{n.level}</span>
                </button>
              ))}
            </div>
            {selectedNode && (
              <p className="text-sm text-indigo-700">
                {t("register.selected_node")}: <strong>{selectedNode.name}</strong>
                {selectedNode.commander_name && <> · {t("register.commander_label")}: {selectedNode.commander_name}</>}
              </p>
            )}
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(4)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={!form.requested_node_id} onClick={() => setStep(6)}>{t("register.next")}</button>
            </div>
          </div>
        )}

        {step === 6 && (
          <div className="space-y-3">
            <h2 className="font-semibold">{t("register.step_review")}</h2>
            <dl className="divide-y text-sm">
              <div className="py-1 flex justify-between"><dt className="text-gray-500">מספר אישי</dt><dd>{form.personal_number}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">שם מלא</dt><dd>{form.full_name}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">דרגה</dt><dd>{form.rank}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">מסגרת מבוקשת</dt><dd>{selectedNode?.name ?? "—"}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">בקשות פטור</dt><dd>{form.exemption_requests.length}</dd></div>
              <div className="py-1 flex justify-between"><dt className="text-gray-500">אילוצים</dt><dd>{form.personal_constraints.length}</dd></div>
            </dl>
            <div className="flex gap-2">
              <button className="flex-1 border py-2 rounded" onClick={() => setStep(5)}>{t("register.back")}</button>
              <button className="flex-1 bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
                disabled={submitting} onClick={handleSubmit}>
                {submitting ? t("register.submitting") : t("register.submit")}
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/pages/RegisterPage.tsx
git commit -m "feat: 6-step registration wizard with fuse.js node search"
```

---

## Task 15: TelegramSetupPage

**Files:**
- Create: `frontend/src/pages/TelegramSetupPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/TelegramSetupPage.tsx`**

```tsx
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { generateTelegramCode, getTelegramStatus, GenerateCodeResult } from "../api/telegram";
import { useAuth } from "../auth/AuthContext";

export default function TelegramSetupPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refreshMe, telegramRequired } = useAuth();
  const [codeInfo, setCodeInfo] = useState<GenerateCodeResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [verified, setVerified] = useState(false);

  useEffect(() => { generateTelegramCode().then(setCodeInfo).catch(() => {}); }, []);

  async function checkVerification() {
    setChecking(true);
    try {
      const status = await getTelegramStatus();
      if (status.is_verified) {
        setVerified(true);
        await refreshMe();
        setTimeout(() => navigate("/", { replace: true }), 1200);
      }
    } finally {
      setChecking(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6" dir="rtl">
      <div className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4 text-center">
        <h1 className="text-2xl font-bold">{t("telegram_setup.title")}</h1>
        {verified ? (
          <p className="text-green-600 font-semibold">{t("telegram_setup.verified")}</p>
        ) : (
          <>
            <p className="text-sm text-gray-600">{t("telegram_setup.instructions")}</p>
            {codeInfo && (
              <>
                <div className="bg-gray-100 rounded p-3 font-mono text-xl tracking-widest select-all">
                  {codeInfo.code}
                </div>
                {codeInfo.bot_username && (
                  <a href={`https://t.me/${codeInfo.bot_username}`} target="_blank" rel="noreferrer"
                    className="text-indigo-600 text-sm underline block">
                    {t("telegram_setup.bot_link")}
                  </a>
                )}
              </>
            )}
            <button className="w-full bg-indigo-600 text-white py-2 rounded disabled:opacity-50"
              onClick={checkVerification} disabled={checking}>
              {checking ? t("telegram_setup.checking") : t("telegram_setup.check_button")}
            </button>
            {!telegramRequired && (
              <button className="w-full text-gray-400 text-sm py-1"
                onClick={() => navigate("/", { replace: true })}>
                {t("telegram_setup.skip_for_now")}
              </button>
            )}
          </>
        )}
      </div>
    </main>
  );
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/pages/TelegramSetupPage.tsx
git commit -m "feat: TelegramSetupPage with verification code display and polling"
```

---

## Task 16: ApprovalsPage enrollment tab + AdminInviteCodesPage + UnifiedNav

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Create: `frontend/src/pages/AdminInviteCodesPage.tsx`
- Modify: `frontend/src/components/UnifiedNav.tsx`

- [ ] **Step 1: Add enrollment tab to ApprovalsPage**

In `frontend/src/pages/ApprovalsPage.tsx`, make these changes:

**Add imports** (after existing imports):
```tsx
import { EnrollmentRequestDTO, listPendingEnrollments, approveEnrollment, rejectEnrollment } from "../api/enrollment";
```

**Change Tab type:**
```tsx
type Tab = "constraints" | "exemptions" | "field_updates" | "swaps" | "enrollment";
```

**Add state** (inside component, after existing state declarations):
```tsx
const [enrollItems, setEnrollItems] = useState<EnrollmentRequestDTO[]>([]);
const [enrollRejectNotes, setEnrollRejectNotes] = useState<Record<string, string>>({});
```

**Add to refresh callback** (after `setSwapItems(...)`):
```tsx
setEnrollItems(await listPendingEnrollments());
```

**Add handlers** (after `onSwapReject`):
```tsx
async function onEnrollApprove(id: string) {
  await approveEnrollment(id);
  await refresh();
}
async function onEnrollReject(id: string) {
  const note = enrollRejectNotes[id];
  if (!note) return;
  await rejectEnrollment(id, note);
  const next = { ...enrollRejectNotes };
  delete next[id];
  setEnrollRejectNotes(next);
  await refresh();
}
```

**Update total count:**
```tsx
const total = items.length + erItems.length + fuItems.length + swapItems.length + enrollItems.length;
```

**Add tab button** (after the swaps tab button):
```tsx
<button
  className={`pb-2 text-sm ${tab === "enrollment" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
  onClick={() => setTab("enrollment")}
  data-testid="approvals-tab-enrollment"
>
  {t("enrollment.tab")}{enrollItems.length > 0 ? ` (${enrollItems.length})` : ""}
</button>
```

**Add tab panel** (before the closing `</section>`):
```tsx
{tab === "enrollment" && (
  <div className="space-y-3" dir="rtl">
    {enrollItems.length === 0 && <p className="text-gray-500 text-sm">{t("enrollment.none")}</p>}
    {enrollItems.map(req => {
      const sd = soldierDisplay(req.soldier_id);
      const nodeName = nodeMap.get(req.requested_node_id)?.name ?? req.requested_node_id.slice(0, 8);
      return (
        <div key={req.id} className="border rounded p-3 text-sm space-y-2">
          <div className="flex items-center gap-2">
            <strong><SoldierLink id={req.soldier_id} name={sd.name} /></strong>
            {sd.node && <span className="text-xs text-gray-400">{sd.node}</span>}
          </div>
          <p className="text-gray-500">{t("enrollment.requested_node")}: <strong>{nodeName}</strong></p>
          <div className="flex gap-2 items-center">
            <button onClick={() => onEnrollApprove(req.id)}
              className="bg-green-600 text-white px-2 py-1 rounded text-xs">
              {t("enrollment.approve")}
            </button>
            <input
              placeholder={t("enrollment.decision_note_placeholder")}
              value={enrollRejectNotes[req.id] ?? ""}
              onChange={e => setEnrollRejectNotes(prev => ({ ...prev, [req.id]: e.target.value }))}
              className="border rounded p-1 text-xs flex-1"
            />
            <button onClick={() => onEnrollReject(req.id)}
              disabled={!enrollRejectNotes[req.id]}
              className="bg-red-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
              {t("enrollment.reject")}
            </button>
          </div>
        </div>
      );
    })}
  </div>
)}
```

- [ ] **Step 2: Create `frontend/src/pages/AdminInviteCodesPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import { InviteCodeDTO, listInviteCodes, createInviteCode, revokeInviteCode } from "../api/inviteCodes";

export default function AdminInviteCodesPage() {
  const { t } = useTranslation();
  const [codes, setCodes] = useState<InviteCodeDTO[]>([]);
  const [usesLeft, setUsesLeft] = useState(5);
  const [creating, setCreating] = useState(false);

  async function refresh() { setCodes(await listInviteCodes()); }
  useEffect(() => { void refresh(); }, []);

  async function handleCreate() {
    setCreating(true);
    try { await createInviteCode(usesLeft); await refresh(); } finally { setCreating(false); }
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" dir="rtl">
        <h2 className="text-xl font-semibold">{t("invite_codes.title")}</h2>
        <div className="flex gap-2 items-end">
          <label className="text-sm">{t("invite_codes.uses_left_label")}
            <input type="number" min={1} className="mt-1 block w-24 border rounded p-2"
              value={usesLeft} onChange={e => setUsesLeft(Number(e.target.value))} />
          </label>
          <button className="bg-indigo-600 text-white px-4 py-2 rounded disabled:opacity-50"
            onClick={handleCreate} disabled={creating}>
            {t("invite_codes.create")}
          </button>
        </div>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-gray-500 text-right">
              <th className="py-2">קוד</th>
              <th className="py-2">{t("invite_codes.uses_left")}</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {codes.map(c => (
              <tr key={c.id} className={`border-b ${c.uses_left === 0 ? "opacity-40" : ""}`}>
                <td className="py-2 font-mono">{c.code}</td>
                <td className="py-2">{c.uses_left}</td>
                <td className="py-2">
                  <button className="text-red-600 text-xs hover:underline"
                    onClick={async () => { await revokeInviteCode(c.id); await refresh(); }}>
                    {t("invite_codes.revoke")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Layout>
  );
}
```

- [ ] **Step 3: Add invite codes link to UnifiedNav**

In `frontend/src/components/UnifiedNav.tsx`, find the section that renders admin-only nav links (search for `role === "admin"` or `"admin"`) and add alongside existing admin links:

```tsx
{user?.role === "admin" && (
  <NavLink to="/admin/invite-codes">{t("invite_codes.title")}</NavLink>
)}
```

- [ ] **Step 4: Run frontend type check**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 5: Commit**

```
git add frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/AdminInviteCodesPage.tsx frontend/src/components/UnifiedNav.tsx
git commit -m "feat: enrollment approvals tab, AdminInviteCodesPage, invite codes nav link"
```

---

## Final verification

- [ ] **Run full backend test suite**

```
cd backend && uv run pytest -v
```
Expected: all PASS.

- [ ] **Run frontend type check**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Smoke test the full flow**

Start servers:
```
# Terminal 1 — backend
cd backend && uv run uvicorn app.main:app --reload

# Terminal 2 — frontend
cd frontend && pnpm dev
```

Walk through:
1. `/login` → click "הרשמה לחייל חדש" → `/register`
2. Enter valid invite code → advance through all 6 steps → submit
3. Redirected to `/setup/telegram` — code shown
4. Admin visits `/approvals` → "הצטרפות" tab shows pending request
5. Admin approves → soldier now in their requested node
6. Admin visits `/admin/invite-codes` via nav → creates and revokes codes
