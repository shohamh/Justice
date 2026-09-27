# HR Activation Codes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a commander at a configurable hierarchy level generate a one-time, soldier-bound activation code for an HR-created profile; let the soldier activate by entering that code as their password on the normal login screen; force a real password and collect Justice-only fields (food, mitvahim/alal, exemptions, constraints) before the account is usable.

**Architecture:** A new `soldier_activation_codes` table (modeled on the existing `PasswordResetToken`, not the unrelated `RegistrationInviteCode`), a small service module (`app/services/hr_activation.py`) for generation/consumption reusing the existing `dm_scope_covers_target`/`scope_root_ids` RBAC-scope helpers, an additive patch to the existing `/auth/login` route so an activation code is tried as a password-verification fallback, a new `require_hr_onboarding_complete` FastAPI dependency, and a new first-login onboarding route that mirrors `registration.register()`'s exact field-collection/validation logic for the Justice-only fields.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (`MappedAsDataclass`), Alembic, pytest, testcontainers-backed Postgres.

**Spec:** [docs/superpowers/specs/2026-09-24-hr-activation-codes-design.md](../specs/2026-09-24-hr-activation-codes-design.md)

## Global Constraints

- `SoldierActivationCode` is modeled on `PasswordResetToken`'s shape (soldier-bound FK, `used_at` single-use marker, `expires_at` time limit, plaintext `code` lookup — no hashing, matching `PasswordResetToken.token`'s precedent for a short-lived single-use secret) — not `RegistrationInviteCode`'s shape (unbound counter), which stays completely untouched.
- Code format: 8-char uppercase+digits via `secrets.choice`, same generator shape as `invite_codes._generate_code` — human-typeable, not a long hex token.
- Generating a new code for a soldier invalidates (marks `used_at`) any prior unused code for that same soldier — at most one live code per soldier.
- Code generation eligibility: target must have a linked `SoldierHrProfile` (`SoldierHrProfile.soldier_id == target.id` exists) **and** `Soldier.hr_onboarding_completed_at IS NULL`. This is the security boundary — anyone else is rejected, so this never becomes a general "reset anyone's password" tool.
- Code generation authorization: `admin`, or a commander whose scope (`scope_root_ids`) covers the target's `hierarchy_node_id` at or above `hr_activation.min_commander_level` (new `SystemSetting`, default fallback `"group"`, read the same try/except-`SettingNotFound` pattern as `authority.py`'s existing `_commander_exemption_min_level` — no migration-time seed row, matching that module's convention of code-level fallback constants).
- Code expiry: `hr_activation.code_expiry_days` (new `SystemSetting`, default `7`, read via the existing `get_setting_int(session, key, default)` helper).
- Login integration is additive to the existing `/auth/login` route — the existing password-check, lockout, JWT-issuance, and audit-logging logic is unchanged; an activation code is only ever tried as a fallback after `verify_password` fails, and a wrong/expired/used code counts as a normal failed login attempt (same lockout counter, no new rate-limiting mechanism).
- `require_hr_onboarding_complete` is implemented and independently tested as a reusable dependency in this plan, but **retrofitting it onto the ~38 existing routes that already use `require_password_changed` is explicitly out of scope for this plan** — that is a large, mechanical, cross-cutting change better done as a focused follow-up, not bundled into this subsystem. State this plainly; it is a deliberate scope boundary, not an oversight.
- First-login onboarding's `exemption_requests`/`personal_constraints` are created as `status="pending_commander"` rows (still require commander approval) — never auto-granted — mirroring `registration.register()`'s exact inline creation/validation logic verbatim (reusing `validate_personal_constraint` from `app.services.registration`, not reimplementing it).
- Current Alembic head at plan-authoring time: `20260925_hr_person_sync`. Confirm this is still current (`python -m alembic heads` from `backend/`) before writing the new migration's `down_revision`.
- Docker/Postgres is expected to be available — DB-layer tasks should run for real against live Postgres, with `DATABASE_URL`/`DB_ADMIN_URL` host rewritten from `db` to `localhost` (this shell isn't under `dev.ps1`).
- Target: 100% test coverage of `app/services/hr_activation.py` and the new onboarding service logic.

---

## Task 1: Schema — `SoldierActivationCode`, `Soldier.hr_onboarding_completed_at`, migration

**Files:**
- Modify: `backend/app/db/models.py` (add `SoldierActivationCode`; add `hr_onboarding_completed_at` to `Soldier`)
- Create: `backend/alembic/versions/20260926_hr_activation_codes.py`
- Test: `backend/tests/unit/test_soldier_activation_code_model.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SoldierActivationCode` model (`id`, `soldier_id`, `code`, `expires_at`, `used_at`, `created_by`, `created_at`); `Soldier.hr_onboarding_completed_at: datetime | None` — consumed by Task 2 (service), Task 4 (login), Task 5 (dependency), Task 6 (onboarding).

- [ ] **Step 1: Confirm the current Alembic head**

Run (from `backend/`, venv active): `python -m alembic heads`. If it is not `20260925_hr_person_sync`, use the actual head as this migration's `down_revision`.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/unit/test_soldier_activation_code_model.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import SoldierActivationCode
from tests.helpers import create_soldier


def test_create_soldier_activation_code(admin_session):
    soldier = create_soldier(admin_session, personal_number="act-model-1")
    commander = create_soldier(admin_session, personal_number="act-model-cmd")

    code = SoldierActivationCode(
        soldier_id=soldier.id,
        code="AB12CD34",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=7),
        created_by=commander.id,
    )
    admin_session.add(code)
    admin_session.commit()
    admin_session.refresh(code)

    assert code.id is not None
    assert code.soldier_id == soldier.id
    assert code.code == "AB12CD34"
    assert code.used_at is None
    assert code.created_by == commander.id
    assert code.created_at is not None


def test_soldier_activation_code_code_is_unique(admin_session):
    from sqlalchemy.exc import IntegrityError
    import pytest

    s1 = create_soldier(admin_session, personal_number="act-model-2")
    s2 = create_soldier(admin_session, personal_number="act-model-3")
    now = datetime.now(tz=timezone.utc)

    admin_session.add(SoldierActivationCode(soldier_id=s1.id, code="DUPCODE1", expires_at=now + timedelta(days=1)))
    admin_session.commit()

    admin_session.add(SoldierActivationCode(soldier_id=s2.id, code="DUPCODE1", expires_at=now + timedelta(days=1)))
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()


def test_soldier_hr_onboarding_completed_at_defaults_none(admin_session):
    soldier = create_soldier(admin_session, personal_number="act-model-4")
    assert soldier.hr_onboarding_completed_at is None

    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()
    admin_session.refresh(soldier)
    assert soldier.hr_onboarding_completed_at is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_soldier_activation_code_model.py -v` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'SoldierActivationCode' from 'app.db.models'`.

- [ ] **Step 4: Add the model and column**

In `backend/app/db/models.py`, add this class directly after `PasswordResetToken`:

```python
class SoldierActivationCode(Base):
    __tablename__ = "soldier_activation_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

In `backend/app/db/models.py`, find the `Soldier` class and add this column directly after `profile_picture_url` (the last field before `created_at`/`updated_at`):

```python
    hr_onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/20260926_hr_activation_codes.py` (adjust `down_revision` per Step 1 if needed):

```python
"""Add soldier_activation_codes table and hr_onboarding_completed_at

Revision ID: 20260926_hr_activation_codes
Revises: 20260925_hr_person_sync
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260926_hr_activation_codes"
down_revision = "20260925_hr_person_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "soldiers", sa.Column("hr_onboarding_completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "soldier_activation_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "soldier_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("soldier_activation_codes")
    op.drop_column("soldiers", "hr_onboarding_completed_at")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/test_soldier_activation_code_model.py -v` (from `backend/`, with `DATABASE_URL`/`DB_ADMIN_URL` rewritten to `localhost`)
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260926_hr_activation_codes.py backend/tests/unit/test_soldier_activation_code_model.py
git commit -m "feat: add soldier_activation_codes table and hr_onboarding_completed_at"
```

---

## Task 2: Activation code service — generate/consume/authorize

**Files:**
- Create: `backend/app/services/hr_activation.py`
- Test: `backend/tests/unit/test_hr_activation_service.py`

**Interfaces:**
- Consumes: `dm_scope_covers_target` from `app.services.authority`; `scope_root_ids` from `app.auth.authz`; `get_setting`/`get_setting_int`/`SettingNotFound` from `app.services.settings_loader`; `SoldierActivationCode`, `Soldier`, `SoldierHrProfile`, `HierarchyNode` from `app.db.models` (Task 1).
- Produces: `ActivationCodeError`, `can_generate_activation_code(session, *, actor, target) -> bool`, `generate_activation_code(session, *, target_soldier_id, actor) -> SoldierActivationCode`, `consume_activation_code(session, *, soldier_id, code) -> bool` — consumed by Task 3 (route) and Task 4 (login).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_hr_activation_service.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import SoldierActivationCode, SoldierHrProfile
from app.services.hr_activation import (
    ActivationCodeError,
    can_generate_activation_code,
    consume_activation_code,
    generate_activation_code,
)
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_soldier


def _hr_linked_soldier(session, *, personal_number: str, hierarchy_node_id=None):
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=hierarchy_node_id)
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.commit()
    return soldier


def test_admin_can_generate_code_for_hr_linked_soldier(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-1", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-1")

    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    assert code.soldier_id == target.id
    assert len(code.code) == 8
    assert code.code.isupper() or code.code.isdigit() or code.code.isalnum()
    assert code.used_at is None
    assert code.created_by == admin.id


def test_commander_at_configured_level_with_scope_can_generate(admin_session):
    node = create_node(admin_session, level="group", name="hract_mador")
    commander = create_soldier(admin_session, personal_number="hract-cmd-1", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    admin_session.commit()
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-2", hierarchy_node_id=node.id)

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is True
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=commander)
    admin_session.commit()
    assert code.soldier_id == target.id


def test_commander_below_configured_level_cannot_generate(admin_session):
    node = create_node(admin_session, level="team", name="hract_team")
    commander = create_soldier(admin_session, personal_number="hract-cmd-2", role="commander", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    admin_session.commit()
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-3", hierarchy_node_id=node.id)

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is False
    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=commander)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "forbidden"


def test_commander_outside_scope_cannot_generate(admin_session):
    node_a = create_node(admin_session, level="group", name="hract_mador_a")
    node_b = create_node(admin_session, level="group", name="hract_mador_b")
    commander = create_soldier(admin_session, personal_number="hract-cmd-3", role="commander", hierarchy_node_id=node_a.id)
    node_a.commander_id = commander.id
    admin_session.commit()
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-4", hierarchy_node_id=node_b.id)

    assert can_generate_activation_code(admin_session, actor=commander, target=target) is False


def test_generate_rejects_soldier_with_no_hr_profile(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-2", role="admin")
    target = create_soldier(admin_session, personal_number="hract-target-5")

    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "not_hr_linked"


def test_generate_rejects_already_onboarded_soldier(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-3", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-6")
    target.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()

    try:
        generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
        assert False, "expected ActivationCodeError"
    except ActivationCodeError as exc:
        assert str(exc) == "already_activated"


def test_generate_invalidates_prior_unused_code(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-4", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-7")

    first = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()
    first_code = first.code

    second = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    admin_session.refresh(first)
    assert first.used_at is not None
    assert second.used_at is None
    assert second.code != first_code


def test_generate_uses_configured_expiry_days_setting(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-5", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-8")
    set_setting(admin_session, "hr_activation.code_expiry_days", 30, actor_id=None)
    admin_session.commit()

    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    delta = code.expires_at - datetime.now(tz=timezone.utc)
    assert 29 <= delta.days <= 30


def test_consume_activation_code_success(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-6", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-9")
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    consumed = consume_activation_code(admin_session, soldier_id=target.id, code=code.code)
    admin_session.commit()

    assert consumed is True
    admin_session.refresh(code)
    assert code.used_at is not None


def test_consume_activation_code_wrong_code_fails(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-7", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-10")
    generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=target.id, code="WRONGCOD") is False


def test_consume_activation_code_expired_fails(admin_session):
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-11")
    admin_session.add(SoldierActivationCode(
        soldier_id=target.id, code="EXPIRED1",
        expires_at=datetime.now(tz=timezone.utc) - timedelta(days=1),
    ))
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=target.id, code="EXPIRED1") is False


def test_consume_activation_code_already_used_fails(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-8", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-12")
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()
    consume_activation_code(admin_session, soldier_id=target.id, code=code.code)
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=target.id, code=code.code) is False


def test_consume_activation_code_wrong_soldier_fails(admin_session):
    admin = create_soldier(admin_session, personal_number="hract-admin-9", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hract-target-13")
    other = _hr_linked_soldier(admin_session, personal_number="hract-target-14")
    code = generate_activation_code(admin_session, target_soldier_id=target.id, actor=admin)
    admin_session.commit()

    assert consume_activation_code(admin_session, soldier_id=other.id, code=code.code) is False
```

(`create_node`/`create_soldier` are the existing helpers in `backend/tests/helpers.py`, already used throughout this project's test suite.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_activation_service.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr_activation'`.

- [ ] **Step 3: Implement `app/services/hr_activation.py`**

Create `backend/app/services/hr_activation.py`:

```python
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.auth.authz import scope_root_ids
from app.db.models import HierarchyNode, Soldier, SoldierActivationCode, SoldierHrProfile
from app.services.authority import dm_scope_covers_target
from app.services.settings_loader import SettingNotFound, get_setting, get_setting_int

# Fallback default if no setting is configured; seeded key for מדור —
# get_level_rank matches HierarchyLevelType.key, not .label.
HR_ACTIVATION_MIN_LEVEL_KEY = "group"
HR_ACTIVATION_CODE_EXPIRY_DAYS_DEFAULT = 7


class ActivationCodeError(Exception):
    pass


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _hr_activation_min_commander_level(session: Session) -> str:
    try:
        value = get_setting(session, "hr_activation.min_commander_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return HR_ACTIVATION_MIN_LEVEL_KEY


def can_generate_activation_code(session: Session, *, actor: Soldier, target: Soldier) -> bool:
    if actor.role == "admin":
        return True
    if target.hierarchy_node_id is None:
        return False
    target_node = session.get(HierarchyNode, target.hierarchy_node_id)
    if target_node is None:
        return False
    required_level = _hr_activation_min_commander_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=scope_root_ids(session, actor), target_node=target_node,
        required_level_key=required_level,
    )


def generate_activation_code(
    session: Session, *, target_soldier_id: uuid.UUID, actor: Soldier,
) -> SoldierActivationCode:
    target = session.get(Soldier, target_soldier_id)
    if target is None:
        raise ActivationCodeError("soldier_not_found")
    if not can_generate_activation_code(session, actor=actor, target=target):
        raise ActivationCodeError("forbidden")

    profile = session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.soldier_id == target.id)
    ).scalar_one_or_none()
    if profile is None:
        raise ActivationCodeError("not_hr_linked")
    if target.hr_onboarding_completed_at is not None:
        raise ActivationCodeError("already_activated")

    now = datetime.now(tz=timezone.utc)
    session.execute(
        sa_update(SoldierActivationCode)
        .where(SoldierActivationCode.soldier_id == target.id, SoldierActivationCode.used_at.is_(None))
        .values(used_at=now)
    )

    expiry_days = get_setting_int(
        session, "hr_activation.code_expiry_days", HR_ACTIVATION_CODE_EXPIRY_DAYS_DEFAULT
    )
    code = SoldierActivationCode(
        soldier_id=target.id,
        code=_generate_code(),
        expires_at=now + timedelta(days=expiry_days),
        created_by=actor.id,
    )
    session.add(code)
    session.flush()
    return code


def consume_activation_code(session: Session, *, soldier_id: uuid.UUID, code: str) -> bool:
    """Atomically consume an unexpired, unused activation code for this
    soldier. Returns True if consumed (a valid activation attempt), False
    otherwise — callers should treat False as 'not an activation code',
    not raise."""
    now = datetime.now(tz=timezone.utc)
    result = session.execute(
        sa_update(SoldierActivationCode)
        .where(
            SoldierActivationCode.soldier_id == soldier_id,
            SoldierActivationCode.code == code,
            SoldierActivationCode.used_at.is_(None),
            SoldierActivationCode.expires_at > now,
        )
        .values(used_at=now)
        .returning(SoldierActivationCode.id)
    )
    row = result.first()
    return row is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_activation_service.py -v` (from `backend/`)
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr_activation.py backend/tests/unit/test_hr_activation_service.py
git commit -m "feat: add HR activation code generate/consume/authorize service"
```

---

## Task 3: Generation route — `POST /soldiers/{soldier_id}/activation-code`

**Files:**
- Create: `backend/app/routes/hr_activation.py`
- Modify: `backend/app/main.py` (register the new router)
- Test: `backend/tests/integration/test_hr_activation_route.py`

**Interfaces:**
- Consumes: `generate_activation_code`, `ActivationCodeError` from `app.services.hr_activation` (Task 2); `get_current_user`, `require_password_changed` from `app.auth.deps`.
- Produces: `POST /api/soldiers/{soldier_id}/activation-code` — not consumed by any other task in this plan (a terminal HTTP endpoint), but its existence is what a future admin UI (subsystem 6, not yet planned) will call.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_hr_activation_route.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import SoldierHrProfile
from tests.helpers import auth_headers, create_node, create_soldier


def _hr_linked_soldier(session, *, personal_number: str, hierarchy_node_id=None):
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=hierarchy_node_id)
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.commit()
    return soldier


def test_admin_can_generate_activation_code(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="hractrt-admin-1", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hractrt-target-1")

    r = client.post(
        f"/api/soldiers/{target.id}/activation-code", headers=auth_headers(admin),
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["code"]) == 8
    assert "expires_at" in body


def test_plain_soldier_cannot_generate_activation_code(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="hractrt-soldier-1")
    target = _hr_linked_soldier(admin_session, personal_number="hractrt-target-2")

    r = client.post(
        f"/api/soldiers/{target.id}/activation-code", headers=auth_headers(soldier),
    )
    assert r.status_code == 403


def test_generate_for_soldier_with_no_hr_profile_returns_404(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="hractrt-admin-2", role="admin")
    target = create_soldier(admin_session, personal_number="hractrt-target-3")

    r = client.post(
        f"/api/soldiers/{target.id}/activation-code", headers=auth_headers(admin),
    )
    assert r.status_code == 404
```

(`auth_headers` is the existing helper in `backend/tests/helpers.py` used throughout the integration test suite — check its exact signature in that file before use; it issues a bearer token for the given `Soldier`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_hr_activation_route.py -v` (from `backend/`)
Expected: FAIL — 404 for all routes (router not registered / route doesn't exist).

- [ ] **Step 3: Implement the route**

Create `backend/app/routes/hr_activation.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services.hr_activation import ActivationCodeError, generate_activation_code

router = APIRouter(prefix="/soldiers", tags=["hr_activation"])


class ActivationCodeOut(BaseModel):
    code: str
    expires_at: datetime


@router.post("/{soldier_id}/activation-code", response_model=ActivationCodeOut)
def create_activation_code(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
) -> ActivationCodeOut:
    try:
        code = generate_activation_code(session, target_soldier_id=soldier_id, actor=actor)
    except ActivationCodeError as exc:
        session.rollback()
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail in ("soldier_not_found", "not_hr_linked") else (
            status.HTTP_409_CONFLICT if detail == "already_activated" else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    session.commit()
    return ActivationCodeOut(code=code.code, expires_at=code.expires_at)
```

In `backend/app/main.py`:
1. Add the import near the other `from app.routes import X as X_routes` lines: `from app.routes import hr_activation as hr_activation_routes`.
2. Add the registration near the other `app.include_router(...)` calls: `app.include_router(hr_activation_routes.router, prefix="/api")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_hr_activation_route.py -v` (from `backend/`)
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/hr_activation.py backend/app/main.py backend/tests/integration/test_hr_activation_route.py
git commit -m "feat: add activation code generation route"
```

---

## Task 4: Login integration

**Files:**
- Modify: `backend/app/routes/auth.py` (patch `login()`)
- Modify: `backend/tests/integration/test_login.py` (append tests)

**Interfaces:**
- Consumes: `consume_activation_code` from `app.services.hr_activation` (Task 2).
- Produces: no new public interface — this task modifies the existing `POST /auth/login` route's behavior in place.

- [ ] **Step 1: Read the current `login()` function**

Open `backend/app/routes/auth.py` and locate `login()` (currently starts around line 181). Note the exact structure of the `if not verify_password(...)` block (the failure path, currently lines ~212-243) and the "successful login" code that follows it (currently lines ~245-271) — you'll be restructuring the boundary between these two, not rewriting either's internals.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/integration/test_login.py`:

```python
from datetime import datetime, timedelta, timezone

from app.db.models import SoldierActivationCode, SoldierHrProfile


def _hr_linked_soldier_with_code(session, *, personal_number: str, code: str = "ACTV1234"):
    from app.auth.password import hash_password

    soldier = Soldier(
        personal_number=personal_number,
        full_name=f"Test {personal_number}",
        password_hash=hash_password("placeholder-nobody-knows-this"),
        must_change_password=True,
    )
    session.add(soldier)
    session.flush()
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.add(SoldierActivationCode(
        soldier_id=soldier.id, code=code,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=7),
    ))
    session.commit()
    session.refresh(soldier)
    return soldier


def test_login_with_valid_activation_code_succeeds(client: TestClient, admin_session: Session):
    soldier = _hr_linked_soldier_with_code(admin_session, personal_number="actlogin-1")

    r = client.post(
        "/api/auth/login", json={"personal_number": "actlogin-1", "password": "ACTV1234"}
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["must_change_password"] is True


def test_login_consumes_activation_code_so_it_cannot_be_reused(client: TestClient, admin_session: Session):
    _hr_linked_soldier_with_code(admin_session, personal_number="actlogin-2")

    first = client.post(
        "/api/auth/login", json={"personal_number": "actlogin-2", "password": "ACTV1234"}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/auth/login", json={"personal_number": "actlogin-2", "password": "ACTV1234"}
    )
    assert second.status_code == 401


def test_login_with_expired_activation_code_fails(client: TestClient, admin_session: Session):
    soldier = _hr_linked_soldier_with_code(admin_session, personal_number="actlogin-3")
    code = admin_session.execute(
        select(SoldierActivationCode).where(SoldierActivationCode.soldier_id == soldier.id)
    ).scalar_one()
    code.expires_at = datetime.now(tz=timezone.utc) - timedelta(days=1)
    admin_session.commit()

    r = client.post(
        "/api/auth/login", json={"personal_number": "actlogin-3", "password": "ACTV1234"}
    )
    assert r.status_code == 401


def test_login_with_wrong_activation_code_fails_normally(client: TestClient, admin_session: Session):
    _hr_linked_soldier_with_code(admin_session, personal_number="actlogin-4")

    r = client.post(
        "/api/auth/login", json={"personal_number": "actlogin-4", "password": "WRONGCOD"}
    )
    assert r.status_code == 401
    assert r.json()["detail"]["detail"] == "invalid_credentials"
```

Add `from sqlalchemy import select` and `from app.db.models import Soldier` to the top of `test_login.py` if not already present (check first — `Soldier` is already imported per the file's existing `_create_soldier` helper; `select` likely needs adding).

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/integration/test_login.py -v -k activation` (from `backend/`)
Expected: FAIL — the activation-code login attempt gets a 401 (falls through to the existing failure path, since the code isn't checked yet).

- [ ] **Step 4: Patch `login()`**

In `backend/app/routes/auth.py`, add the import: `from app.services.hr_activation import consume_activation_code` (alongside the other `from app.services import ...` imports near the top).

Restructure the password-check block. The current code is:

```python
    if not verify_password(body.password, soldier.password_hash):
        new_count = soldier.failed_login_count + 1
        ... (failure handling, unchanged) ...
        raise HTTPException(...)

    # Successful login — reset lockout state
    soldier.failed_login_count = 0
    ...
```

Change it to:

```python
    password_ok = verify_password(body.password, soldier.password_hash)
    activation_consumed = False
    if not password_ok:
        activation_consumed = consume_activation_code(session, soldier_id=soldier.id, code=body.password)

    if not password_ok and not activation_consumed:
        new_count = soldier.failed_login_count + 1
        ... (failure handling, unchanged) ...
        raise HTTPException(...)

    # Successful login (real password or a valid activation code) — reset lockout state
    soldier.failed_login_count = 0
    ...
```

Do not otherwise change the failure-handling block's internals (the `sa_update`/lockout/audit-log logic) or the success block's internals (JWT issuance, cookie-setting, `LoginResponse` construction) — this is purely a condition restructuring around the existing two blocks.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/integration/test_login.py -v` (from `backend/`)
Expected: all tests in the file pass, including the 4 new ones and the pre-existing ones (confirming no regression to normal password login).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/auth.py backend/tests/integration/test_login.py
git commit -m "feat: let activation codes work as a password fallback on login"
```

---

## Task 5: `require_hr_onboarding_complete` dependency

**Files:**
- Modify: `backend/app/auth/deps.py` (add the dependency)
- Test: `backend/tests/unit/test_require_hr_onboarding_complete.py`

**Interfaces:**
- Consumes: `Soldier`, `SoldierHrProfile` from `app.db.models`; `get_session`; `require_password_changed` (existing, same file).
- Produces: `require_hr_onboarding_complete(session, user) -> Soldier` — consumed by Task 6's onboarding-gated routes (i.e., every OTHER protected route would use it too, per the spec, but retrofitting the ~38 existing routes that use `require_password_changed` is explicitly out of scope for this plan — see Global Constraints).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_require_hr_onboarding_complete.py`:

```python
from __future__ import annotations

from fastapi import HTTPException
import pytest

from app.auth.deps import require_hr_onboarding_complete
from app.db.models import SoldierHrProfile
from tests.helpers import create_soldier


def test_blocks_hr_linked_soldier_with_incomplete_onboarding(admin_session):
    soldier = create_soldier(admin_session, personal_number="reqonb-1")
    admin_session.add(SoldierHrProfile(personal_number="reqonb-1", raw_dto={}, soldier_id=soldier.id))
    admin_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        require_hr_onboarding_complete(session=admin_session, user=soldier)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "hr_onboarding_incomplete"


def test_allows_hr_linked_soldier_with_completed_onboarding(admin_session):
    from datetime import datetime, timezone

    soldier = create_soldier(admin_session, personal_number="reqonb-2")
    admin_session.add(SoldierHrProfile(personal_number="reqonb-2", raw_dto={}, soldier_id=soldier.id))
    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()

    result = require_hr_onboarding_complete(session=admin_session, user=soldier)
    assert result is soldier


def test_allows_soldier_with_no_hr_profile_regardless_of_flag(admin_session):
    soldier = create_soldier(admin_session, personal_number="reqonb-3")

    result = require_hr_onboarding_complete(session=admin_session, user=soldier)
    assert result is soldier
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_require_hr_onboarding_complete.py -v` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'require_hr_onboarding_complete' from 'app.auth.deps'`.

- [ ] **Step 3: Implement the dependency**

In `backend/app/auth/deps.py`, add this function directly after `require_password_changed`:

```python
def require_hr_onboarding_complete(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Soldier:
    """Block a soldier who came through HR activation from using protected
    endpoints until they've completed the first-login intake form. A soldier
    with no linked SoldierHrProfile (self-registered, Excel-imported, etc.)
    is never blocked here — the flag is simply irrelevant to them."""
    from app.db.models import SoldierHrProfile

    profile = session.execute(
        select(SoldierHrProfile.id).where(SoldierHrProfile.soldier_id == user.id)
    ).first()
    if profile is not None and user.hr_onboarding_completed_at is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="hr_onboarding_incomplete")
    return user
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_require_hr_onboarding_complete.py -v` (from `backend/`)
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth/deps.py backend/tests/unit/test_require_hr_onboarding_complete.py
git commit -m "feat: add require_hr_onboarding_complete dependency"
```

---

## Task 6: First-login onboarding — service + route

**Files:**
- Create: `backend/app/services/hr_onboarding.py`
- Create: `backend/app/routes/hr_onboarding.py`
- Modify: `backend/app/main.py` (register the new router)
- Test: `backend/tests/unit/test_hr_onboarding_service.py`
- Test: `backend/tests/integration/test_hr_onboarding_route.py`

**Interfaces:**
- Consumes: `validate_personal_constraint` from `app.services.registration`; `Soldier`, `ExemptionRequest`, `ExemptionType`, `PersonalConstraint` from `app.db.models`; `require_password_changed` from `app.auth.deps`.
- Produces: `complete_first_login_onboarding(session, *, soldier, food_type, food_constraints, last_mitvahim_date, last_alal_date, exemption_requests, personal_constraints) -> Soldier`; `POST /api/auth/first-login-onboarding` — terminal for this plan.

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/unit/test_hr_onboarding_service.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from app.db.models import ExemptionRequest, ExemptionType, PersonalConstraint
from app.services.hr_onboarding import OnboardingError, complete_first_login_onboarding
from tests.helpers import create_soldier


def _exemption_type(session, *, name: str = "פטור בדיקה", is_commander_exemption: bool = False) -> ExemptionType:
    et = ExemptionType(name=name, is_commander_exemption=is_commander_exemption, is_global=True)
    session.add(et)
    session.flush()
    return et


def test_sets_direct_fields_and_marks_completed(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-1")

    result = complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type="vegetarian", food_constraints="no nuts",
        last_mitvahim_date=date(2026, 1, 1), last_alal_date=date(2026, 2, 1),
        exemption_requests=[], personal_constraints=[],
    )
    admin_session.commit()

    assert result.food_type == "vegetarian"
    assert result.food_constraints == "no nuts"
    assert result.last_mitvahim_date == date(2026, 1, 1)
    assert result.last_alal_date == date(2026, 2, 1)
    assert result.hr_onboarding_completed_at is not None


def test_creates_pending_exemption_requests(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-2")
    et = _exemption_type(admin_session)
    admin_session.commit()

    complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
        exemption_requests=[{"exemption_type_id": str(et.id), "reason": "test reason"}],
        personal_constraints=[],
    )
    admin_session.commit()

    rows = admin_session.query(ExemptionRequest).filter_by(soldier_id=soldier.id).all()
    assert len(rows) == 1
    assert rows[0].status == "pending_commander"
    assert rows[0].exemption_type_id == et.id


def test_rejects_commander_exemption_type(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-3")
    et = _exemption_type(admin_session, is_commander_exemption=True)
    admin_session.commit()

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": str(et.id)}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "commander_exemption_not_requestable"


def test_creates_pending_personal_constraints(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-4")

    complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
        exemption_requests=[],
        personal_constraints=[{"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 5), "reason": "test"}],
    )
    admin_session.commit()

    rows = admin_session.query(PersonalConstraint).filter_by(soldier_id=soldier.id).all()
    assert len(rows) == 1
    assert rows[0].status == "pending_commander"


def test_rejects_invalid_personal_constraint(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-5")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[],
            personal_constraints=[{"start_date": date(2026, 1, 1), "end_date": None, "reason": ""}],
        )
    assert str(exc_info.value) == "constraint_missing_fields"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_onboarding_service.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr_onboarding'`.

- [ ] **Step 3: Implement `app/services/hr_onboarding.py`**

Create `backend/app/services/hr_onboarding.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import ExemptionRequest, ExemptionType, PersonalConstraint, Soldier
from app.services.registration import validate_personal_constraint


class OnboardingError(Exception):
    pass


def complete_first_login_onboarding(
    session: Session,
    *,
    soldier: Soldier,
    food_type: str | None,
    food_constraints: str | None,
    last_mitvahim_date: date | None,
    last_alal_date: date | None,
    exemption_requests: list[dict],
    personal_constraints: list[dict],
) -> Soldier:
    for er in exemption_requests:
        exemption_type_id_raw = er.get("exemption_type_id")
        start_date_raw = er.get("start_date")
        end_date_raw = er.get("end_date")
        if not exemption_type_id_raw:
            raise OnboardingError("exemption_missing_fields")
        if end_date_raw and not start_date_raw:
            raise OnboardingError("start_date_required")
        try:
            exemption_type_id = uuid.UUID(str(exemption_type_id_raw))
        except ValueError as exc:
            raise OnboardingError("exemption_missing_fields") from exc
        et = session.get(ExemptionType, exemption_type_id)
        if et is None:
            raise OnboardingError("exemption_type_not_found")
        if et.is_commander_exemption:
            raise OnboardingError("commander_exemption_not_requestable")
        if end_date_raw and start_date_raw and end_date_raw < start_date_raw:
            raise OnboardingError("bad_date_range")

    for pc in personal_constraints:
        try:
            validate_personal_constraint(pc)
        except ValueError as exc:
            raise OnboardingError(str(exc)) from exc

    soldier.food_type = food_type
    soldier.food_constraints = food_constraints
    soldier.last_mitvahim_date = last_mitvahim_date
    soldier.last_alal_date = last_alal_date

    for er in exemption_requests:
        session.add(ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=uuid.UUID(str(er["exemption_type_id"])),
            start_date=er.get("start_date") or None,
            end_date=er.get("end_date") or None,
            reason=er.get("reason"),
            status="pending_commander",
        ))

    for pc in personal_constraints:
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc.get("reason"),
            status="pending_commander",
        ))

    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    session.flush()
    return soldier
```

(Validation runs as a first pass over both lists before any DB writes, so a bad row in either list rejects the whole call with nothing partially applied — matching `register()`'s implicit all-or-nothing behavior within one transaction.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_onboarding_service.py -v` (from `backend/`)
Expected: 5 passed.

- [ ] **Step 5: Write the failing route tests**

Create `backend/tests/integration/test_hr_onboarding_route.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_soldier


def test_first_login_onboarding_sets_fields(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="onbrt-1")

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": "vegetarian", "food_constraints": None,
            "last_mitvahim_date": "2026-01-01", "last_alal_date": None,
            "exemption_requests": [], "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["food_type"] == "vegetarian"
    assert body["hr_onboarding_completed_at"] is not None


def test_first_login_onboarding_requires_password_changed(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="onbrt-2", must_change_password=True)

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": None, "food_constraints": None,
            "last_mitvahim_date": None, "last_alal_date": None,
            "exemption_requests": [], "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 403


def test_first_login_onboarding_rejects_bad_exemption(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="onbrt-3")

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": None, "food_constraints": None,
            "last_mitvahim_date": None, "last_alal_date": None,
            "exemption_requests": [{"exemption_type_id": "not-a-uuid"}],
            "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 400
```

(`create_soldier`'s existing signature already supports `must_change_password` as a kwarg, per `backend/tests/helpers.py`.)

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/integration/test_hr_onboarding_route.py -v` (from `backend/`)
Expected: FAIL — 404s (route doesn't exist yet).

- [ ] **Step 7: Implement the route**

Create `backend/app/routes/hr_onboarding.py`:

```python
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services.hr_onboarding import OnboardingError, complete_first_login_onboarding

router = APIRouter(prefix="/auth", tags=["hr_onboarding"])


class FirstLoginOnboardingRequest(BaseModel):
    food_type: str | None = None
    food_constraints: str | None = None
    last_mitvahim_date: date | None = None
    last_alal_date: date | None = None
    exemption_requests: list[dict] = []
    personal_constraints: list[dict] = []


class FirstLoginOnboardingResponse(BaseModel):
    food_type: str | None
    food_constraints: str | None
    last_mitvahim_date: date | None
    last_alal_date: date | None
    hr_onboarding_completed_at: str | None


@router.post("/first-login-onboarding", response_model=FirstLoginOnboardingResponse)
def first_login_onboarding(
    body: FirstLoginOnboardingRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FirstLoginOnboardingResponse:
    try:
        soldier = complete_first_login_onboarding(
            session, soldier=user,
            food_type=body.food_type, food_constraints=body.food_constraints,
            last_mitvahim_date=body.last_mitvahim_date, last_alal_date=body.last_alal_date,
            exemption_requests=body.exemption_requests, personal_constraints=body.personal_constraints,
        )
    except OnboardingError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return FirstLoginOnboardingResponse(
        food_type=soldier.food_type, food_constraints=soldier.food_constraints,
        last_mitvahim_date=soldier.last_mitvahim_date, last_alal_date=soldier.last_alal_date,
        hr_onboarding_completed_at=soldier.hr_onboarding_completed_at.isoformat() if soldier.hr_onboarding_completed_at else None,
    )
```

In `backend/app/main.py`:
1. Add the import: `from app.routes import hr_onboarding as hr_onboarding_routes`.
2. Add the registration: `app.include_router(hr_onboarding_routes.router, prefix="/api")`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/integration/test_hr_onboarding_route.py -v` (from `backend/`)
Expected: 3 passed.

- [ ] **Step 9: Run the full new-subsystem test suite together**

Run: `pytest tests/unit/test_soldier_activation_code_model.py tests/unit/test_hr_activation_service.py tests/integration/test_hr_activation_route.py tests/integration/test_login.py tests/unit/test_require_hr_onboarding_complete.py tests/unit/test_hr_onboarding_service.py tests/integration/test_hr_onboarding_route.py -v` (from `backend/`)
Expected: all pass, no regressions.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/hr_onboarding.py backend/app/routes/hr_onboarding.py backend/app/main.py backend/tests/unit/test_hr_onboarding_service.py backend/tests/integration/test_hr_onboarding_route.py
git commit -m "feat: add first-login onboarding service and route"
```

---

## Task 7: Coverage check and pytest marker registration

**Files:**
- Modify: `backend/tests/conftest.py` (marker routing, if needed)

**Interfaces:**
- Consumes: nothing new — verifies Tasks 1-6's output meets this plan's coverage bar and fits the existing pytest area-marker system.

- [ ] **Step 1: Check marker routing for the new test files**

Read `backend/tests/conftest.py`'s `_AREA_MARKERS` dict directly (a confirmed explicit stem allow-list from four prior subsystems on this project). Add entries for the new stems: `test_soldier_activation_code_model`, `test_hr_activation_service`, `test_hr_activation_route`, `test_require_hr_onboarding_complete`, `test_hr_onboarding_service`, `test_hr_onboarding_route` — all under `auth` (per its `pyproject.toml` description: "login, JWT, password policy, RBAC, registration/enrollment, security hardening" — this subsystem is squarely activation/login/onboarding, not soldier-profile-data like the HR sync subsystems were). `test_login.py`'s existing stem is presumably already routed (it's a pre-existing file) — confirm, don't assume.

- [ ] **Step 2: Run the new tests via their resolved markers to confirm routing**

Run (from `backend/`): `pytest tests app/services/hr/tests -m auth -v` — confirm the new stems appear among the results (this will be a large run since `auth` likely already covers many existing files; just confirm the new ones are present, not that the whole run is small).

- [ ] **Step 3: Run coverage for the new service modules**

Run (from `backend/`):
```bash
pytest tests/unit/test_hr_activation_service.py tests/unit/test_hr_onboarding_service.py tests/unit/test_require_hr_onboarding_complete.py --cov=app.services.hr_activation --cov=app.services.hr_onboarding --cov-report=term-missing -v
```
Expected: 100% coverage for both service modules. If any lines are missed, add a targeted test in the relevant existing test file for that branch and re-run until 100%, or document precisely what remains uncovered and why.

- [ ] **Step 4: Run the full fast backend suite to confirm no regressions**

Run (from `backend/`): `pytest -q`
Expected: all pass, no new failures introduced. A pre-existing, unrelated flake in `test_active_days_reference_settings.py` (a midnight date-boundary comparison, confirmed unrelated on prior subsystems of this project) is not a regression if it recurs — note it plainly if seen, don't chase it.

- [ ] **Step 5: Commit (if `conftest.py` changed)**

```bash
git add backend/tests/conftest.py
git commit -m "test: route new HR activation code tests to pytest markers"
```

---

## Self-Review Notes

- **Spec coverage:** `soldier_activation_codes` table shaped like `PasswordResetToken`, 8-char human-typeable codes, prior-code invalidation, generation eligibility (linked `SoldierHrProfile` + not-yet-onboarded) and authorization (`dm_scope_covers_target` at/above `hr_activation.min_commander_level`), N-day expiry setting, login-fallback integration (additive, reuses existing lockout/JWT/audit logic unchanged), first-login onboarding mirroring `register()`'s field-collection/validation exactly (exemptions/constraints still `pending_commander`, never auto-granted), `require_hr_onboarding_complete` dependency — all covered across Tasks 1-6.
- **Deliberate scope boundary, stated plainly (not silently dropped):** retrofitting `require_hr_onboarding_complete` onto the ~38 existing routes using `require_password_changed` is explicitly out of this plan — the dependency itself is fully implemented and tested (Task 5), but wiring it broadly is a separate, focused follow-up. This mirrors how earlier subsystems on this project documented "known accepted limitation" notes rather than silently expanding or silently dropping scope.
- **Type consistency:** `generate_activation_code`'s return type (`SoldierActivationCode`) and `consume_activation_code`'s return type (`bool`) match exactly how Task 3's route and Task 4's login patch consume them. `complete_first_login_onboarding`'s keyword-only signature matches exactly how Task 6's route constructs the call from the request body.
- **Reused, not duplicated:** `dm_scope_covers_target`/`scope_root_ids` (Task 2), `validate_personal_constraint` (Task 6) are imported from their existing modules, never reimplemented — matching this project's established convention (e.g. subsystem 4 reusing `_reset_rank_advancement`/`recheck_soldier_assignments` rather than reimplementing rank/eligibility logic).
