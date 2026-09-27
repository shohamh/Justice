# HR Field Mapping & Local-Override Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate a raw `HrUser` into Justice's field vocabulary via pure, fixture-tested mapping functions; add a `soldier_hr_profiles` table to store the raw DTO and sync bookkeeping; and hook the existing dual-approval field-update flow so an admin-approved edit to an HR-owned field marks it locally overridden, so future syncs skip it.

**Architecture:** New `app/services/hr/mapping.py` holds pure vocabulary-translation logic (no DB), producing either fully-mapped fields or a `HeldForReview` result — testable entirely against fixtures, same style as subsystem 1's client. A new `SoldierHrProfile` SQLAlchemy model + migration gives HR sync its own bounded table, separate from the already-wide `Soldier` table. A small, additive change to the *existing* `approve_field_update` in `app/services/soldiers.py` marks a field overridden when an admin approves an edit to it — no new approval workflow.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (`MappedAsDataclass`), Alembic, pytest/pytest-asyncio, existing `testcontainers`-backed Postgres test fixtures for DB-layer tests.

**Spec:** [docs/superpowers/specs/2026-09-23-hr-field-mapping-design.md](../specs/2026-09-23-hr-field-mapping-design.md)

## Global Constraints

- This plan is data model + mapping only — **no** code here creates or updates a `Soldier` row from HR data, loops over HR users, or talks to `HrApiClient`. That orchestration is subsystem 4 (not yet planned).
- Vocabulary translation (`gender`, `rank`, `servicType`) uses explicit dicts only. A value with no entry is held for review — never guessed, never fuzzy-matched.
- `is_officer` is derived as `mapped_rank in OFFICER_RANKS` (existing list from `app.services.eligibility`). `is_career` is derived by calling the *existing*, unmodified `eligibility.derive_is_career(rank, mandatory_end_date, discharge_date)` — never reimplemented.
- New table `soldier_hr_profiles`: `soldier_id` nullable + unique FK to `soldiers.id`, `personal_number` unique (the merge key), `raw_dto` JSONB (required), `sync_status` plain `Text` (not a pg enum, matching the repo's existing status-column convention), `review_reason` nullable `Text`, `overridden_fields` JSONB defaulting to `[]`, `last_synced_at` nullable timestamptz.
- The override hook is an additive change inside the *existing* `approve_field_update` function in `app/services/soldiers.py` — no restructuring of its existing field-application branches.
- `HR_OWNED_FIELDS` (the frozenset of Justice field names HR owns) lives in `app/services/hr/mapping.py` and is imported wherever needed — not duplicated.
- **Known, accepted scope limitation** (not a defect to fix here): `HR_OWNED_FIELDS ∩ SOLDIER_EDITABLE_FIELDS = {"gender", "rank", "phone", "mandatory_end_date", "discharge_date"}`. The override hook can only ever fire for these 5 fields today, because `submit_field_update` already rejects any field not in `SOLDIER_EDITABLE_FIELDS` before an approval is possible. `full_name`, `personal_number`, `email`, `profile_picture_url`, and `enlistment_date` have no existing admin-edit path at all — the hook is a no-op for them, which is correct and forward-compatible if `SOLDIER_EDITABLE_FIELDS` is extended later.
- No FastAPI routes, no frontend changes, no hierarchy logic, no sync-loop orchestration in this plan.
- Docker/testcontainers-Postgres was unavailable in the sandbox this plan was authored in (carried over from subsystem 1). DB-layer tasks (1, 3, 4) should be implemented and self-verified as thoroughly as possible; if Docker is genuinely unavailable when a task is executed, say so plainly in the report rather than claiming unverified success — this is not a regression to chase down.
- Target: 100% test coverage of `mapping.py`, `divergence.py`, and the new `_mark_hr_field_overridden`/`HR_OWNED_FIELDS` additions.
- Current Alembic head at plan-authoring time: `f43bbf6cc6ed`. Confirm this is still current (`python -m alembic heads` from `backend/`) before writing the new migration's `down_revision` — if it has moved, use the actual current head instead.

---

## Task 1: `SoldierHrProfile` model and migration

**Files:**
- Modify: `backend/app/db/models.py` (add `SoldierHrProfile` class)
- Create: `backend/alembic/versions/20260923_soldier_hr_profile.py`
- Test: `backend/tests/unit/test_soldier_hr_profile_model.py`

**Interfaces:**
- Consumes: nothing new (uses existing `Base`, `Soldier`).
- Produces: `SoldierHrProfile` model with columns `id`, `personal_number`, `raw_dto`, `soldier_id`, `sync_status`, `review_reason`, `overridden_fields`, `last_synced_at`, `created_at`, `updated_at` — consumed by Task 3 (`divergence.py`) and Task 4 (override hook).

- [ ] **Step 1: Confirm the current Alembic head**

Run (from `backend/`, venv active): `python -m alembic heads`
Note the output. If it is not `f43bbf6cc6ed`, use the actual head as this migration's `down_revision` in Step 3 instead.

- [ ] **Step 2: Write the failing model test**

Create `backend/tests/unit/test_soldier_hr_profile_model.py`:

```python
from __future__ import annotations

from app.db.models import SoldierHrProfile
from tests.helpers import create_soldier


def test_create_soldier_hr_profile_without_soldier(admin_session):
    profile = SoldierHrProfile(
        personal_number="hrprof-001",
        raw_dto={"personalNumber": "hrprof-001", "fullName": "Held For Review"},
    )
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.id is not None
    assert profile.soldier_id is None
    assert profile.sync_status == "held_for_review"
    assert profile.review_reason is None
    assert profile.overridden_fields == []
    assert profile.last_synced_at is None
    assert profile.created_at is not None


def test_create_soldier_hr_profile_linked_to_soldier(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrprof-002")

    profile = SoldierHrProfile(
        personal_number="hrprof-002",
        raw_dto={"personalNumber": "hrprof-002", "fullName": soldier.full_name},
        soldier_id=soldier.id,
        sync_status="synced",
    )
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.soldier_id == soldier.id
    assert profile.sync_status == "synced"


def test_soldier_hr_profile_personal_number_is_unique(admin_session):
    admin_session.add(SoldierHrProfile(personal_number="hrprof-003", raw_dto={}))
    admin_session.commit()

    admin_session.add(SoldierHrProfile(personal_number="hrprof-003", raw_dto={}))
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()


def test_soldier_hr_profile_overridden_fields_round_trips_list(admin_session):
    profile = SoldierHrProfile(
        personal_number="hrprof-004",
        raw_dto={},
        overridden_fields=["rank", "phone"],
    )
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.overridden_fields == ["rank", "phone"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_soldier_hr_profile_model.py -v` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'SoldierHrProfile' from 'app.db.models'` (or, if Docker/testcontainers is unavailable in your environment, note that in your report and verify by import/collection only: `python -c "from app.db.models import SoldierHrProfile"` should fail the same way).

- [ ] **Step 4: Add the `SoldierHrProfile` model**

In `backend/app/db/models.py`, add this class. Place it near `Soldier`/`AuditLog` (e.g. directly after `AuditLog`, before `SystemSetting`) since it's a Soldier-adjacent table:

```python
class SoldierHrProfile(Base):
    __tablename__ = "soldier_hr_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    personal_number: Mapped[str] = mapped_column(Text, unique=True)
    raw_dto: Mapped[dict[str, Any]] = mapped_column(JSONB)
    soldier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), unique=True, nullable=True, default=None
    )
    sync_status: Mapped[str] = mapped_column(
        Text, server_default=text("'held_for_review'"), default="held_for_review"
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    overridden_fields: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default_factory=list
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

This follows the exact column-ordering rule the file's other `MappedAsDataclass` models use: columns without a default (`personal_number`, `raw_dto`) come before columns with one (`soldier_id` onward); `init=False` columns (`id`, `created_at`, `updated_at`) are exempt from that ordering.

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/20260923_soldier_hr_profile.py` (adjust `down_revision` per Step 1 if the head has moved):

```python
"""Add soldier_hr_profiles table

Revision ID: 20260923_soldier_hr_profile
Revises: f43bbf6cc6ed
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260923_soldier_hr_profile"
down_revision = "f43bbf6cc6ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soldier_hr_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("personal_number", sa.Text(), nullable=False, unique=True),
        sa.Column("raw_dto", postgresql.JSONB(), nullable=False),
        sa.Column(
            "soldier_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, unique=True,
        ),
        sa.Column("sync_status", sa.Text(), server_default="held_for_review", nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("overridden_fields", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("soldier_hr_profiles")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/test_soldier_hr_profile_model.py -v` (from `backend/`)
Expected: 4 passed. If Docker/testcontainers is unavailable in your environment, run `python -m alembic upgrade head` against whatever Postgres you do have access to (or note plainly in your report that this could not be verified end-to-end, same as subsystem 1's Tasks 4-6) — do not claim passing tests you couldn't actually run.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260923_soldier_hr_profile.py backend/tests/unit/test_soldier_hr_profile_model.py
git commit -m "feat: add soldier_hr_profiles table"
```

---

## Task 2: HR field mapping (`mapping.py`)

**Files:**
- Create: `backend/app/services/hr/mapping.py`
- Test: `backend/app/services/hr/tests/test_mapping.py`

**Interfaces:**
- Consumes: `HrUser` from `app.services.hr.schemas` (subsystem 1); `ENLISTED_RANKS`, `OFFICER_RANKS`, `derive_is_career` from `app.services.eligibility` (existing, unmodified).
- Produces: `MappedSoldierFields`, `HeldForReview` dataclasses; `map_hr_user(hr_user: HrUser) -> MappedSoldierFields | HeldForReview`; `HR_OWNED_FIELDS: frozenset[str]` — consumed by Task 4 (override hook) and, later, subsystem 4.

This is a pure module — no DB, no fixtures-as-JSON-files needed (test data is built directly as `HrUser` instances in Python).

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/hr/tests/test_mapping.py`:

```python
from __future__ import annotations

from datetime import date

from app.services.eligibility import OFFICER_RANKS, derive_is_career
from app.services.hr.mapping import HeldForReview, MappedSoldierFields, map_hr_user
from app.services.hr.schemas import HrUser


def _hr_user(**overrides: object) -> HrUser:
    defaults: dict[str, object] = dict(
        full_name="ישראל ישראלי",
        personal_number="1234567",
        mail="israel@example.mil",
        phone="050-1112222",
        image_url="https://hr.example/img/1",
        gender="male",
        rank="טוראי",
        serv_type="chova",
        service_start_date="2024-01-01",
        end_hova_date="2026-01-01",
        service_end_date=None,
    )
    defaults.update(overrides)
    return HrUser(**defaults)


def test_map_hr_user_happy_path_enlisted():
    result = map_hr_user(_hr_user())
    assert isinstance(result, MappedSoldierFields)
    assert result.full_name == "ישראל ישראלי"
    assert result.personal_number == "1234567"
    assert result.email == "israel@example.mil"
    assert result.phone == "050-1112222"
    assert result.profile_picture_url == "https://hr.example/img/1"
    assert result.gender == "male"
    assert result.rank == "טוראי"
    assert result.rank_track == "חובה"
    assert result.is_officer is False
    assert result.enlistment_date == date(2024, 1, 1)
    assert result.mandatory_end_date == date(2026, 1, 1)
    assert result.discharge_date is None


def test_map_hr_user_officer_rank_sets_is_officer_and_kva_track():
    result = map_hr_user(_hr_user(rank=OFFICER_RANKS[0], serv_type="kva"))
    assert isinstance(result, MappedSoldierFields)
    assert result.is_officer is True
    assert result.rank_track == "קבע"


def test_map_hr_user_is_career_matches_derive_is_career_directly():
    hr = _hr_user(rank="רסל", serv_type="kva", end_hova_date="2020-01-01")
    result = map_hr_user(hr)
    assert isinstance(result, MappedSoldierFields)
    expected = derive_is_career("רסל", date(2020, 1, 1), None)
    assert result.is_career == expected
    assert result.is_career is True


def test_map_hr_user_unmappable_gender_held_for_review():
    result = map_hr_user(_hr_user(gender="unspecified"))
    assert isinstance(result, HeldForReview)
    assert result.personal_number == "1234567"
    assert any("gender" in r for r in result.reasons)


def test_map_hr_user_unmappable_rank_held_for_review():
    result = map_hr_user(_hr_user(rank="דרגה לא ידועה"))
    assert isinstance(result, HeldForReview)
    assert any("rank" in r for r in result.reasons)


def test_map_hr_user_unmappable_service_type_held_for_review():
    result = map_hr_user(_hr_user(serv_type="unknown_type"))
    assert isinstance(result, HeldForReview)
    assert any("servicType" in r for r in result.reasons)


def test_map_hr_user_unparseable_date_held_for_review():
    result = map_hr_user(_hr_user(service_start_date="not-a-date"))
    assert isinstance(result, HeldForReview)
    assert any("serviceStartDate" in r for r in result.reasons)


def test_map_hr_user_multiple_failures_all_reported():
    result = map_hr_user(_hr_user(gender="x", rank="y"))
    assert isinstance(result, HeldForReview)
    assert len(result.reasons) == 2


def test_map_hr_user_none_optional_fields_pass_through_as_none():
    result = map_hr_user(
        _hr_user(gender=None, rank=None, serv_type=None, mail=None, phone=None, image_url=None)
    )
    assert isinstance(result, MappedSoldierFields)
    assert result.gender is None
    assert result.rank is None
    assert result.rank_track is None
    assert result.is_officer is False
    assert result.email is None
    assert result.phone is None
    assert result.profile_picture_url is None


def test_map_hr_user_empty_personal_number_held_for_review():
    result = map_hr_user(_hr_user(personal_number=""))
    assert isinstance(result, HeldForReview)
    assert any("personal_number" in r for r in result.reasons)


def test_hr_owned_fields_contains_expected_names():
    from app.services.hr.mapping import HR_OWNED_FIELDS
    assert HR_OWNED_FIELDS == frozenset({
        "full_name", "personal_number", "email", "phone", "gender", "rank",
        "profile_picture_url", "enlistment_date", "mandatory_end_date", "discharge_date",
    })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest app/services/hr/tests/test_mapping.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr.mapping'`.

- [ ] **Step 3: Implement `mapping.py`**

Create `backend/app/services/hr/mapping.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS, derive_is_career
from app.services.hr.schemas import HrUser

GENDER_MAP: dict[str, str] = {
    "male": "male",
    "female": "female",
}

# Keys are HR's raw `rank` string; values are Justice's existing rank
# strings from eligibility.ENLISTED_RANKS / OFFICER_RANKS. Identity-shaped
# today because no real HR fixture data is available to confirm otherwise
# — if HR uses different rank spellings/abbreviations, this map is where
# that translation goes, one confirmed entry at a time.
RANK_MAP: dict[str, str] = {rank: rank for rank in (*ENLISTED_RANKS, *OFFICER_RANKS)}

# HR's `servicType` -> Soldier.rank_track ("חובה" mandatory / "קבע" career).
# TODO: "chova"/"kva" are placeholder keys, unconfirmed against real HR API
# responses — see design doc's "Open questions" section.
SERVICE_TYPE_TO_TRACK_MAP: dict[str, str] = {
    "chova": "חובה",
    "kva": "קבע",
}

HR_OWNED_FIELDS: frozenset[str] = frozenset({
    "full_name", "personal_number", "email", "phone", "gender", "rank",
    "profile_picture_url", "enlistment_date", "mandatory_end_date", "discharge_date",
})


@dataclass(frozen=True)
class MappedSoldierFields:
    full_name: str
    personal_number: str
    email: str | None = None
    phone: str | None = None
    profile_picture_url: str | None = None
    gender: str | None = None
    rank: str | None = None
    rank_track: str | None = None
    is_officer: bool = False
    is_career: bool = False
    enlistment_date: date | None = None
    mandatory_end_date: date | None = None
    discharge_date: date | None = None


@dataclass(frozen=True)
class HeldForReview:
    personal_number: str
    reasons: list[str] = field(default_factory=list)


def _parse_date(value: str | None, field_label: str, reasons: list[str]) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        reasons.append(f"unparseable {field_label}: {value!r}")
        return None


def map_hr_user(hr_user: HrUser) -> MappedSoldierFields | HeldForReview:
    reasons: list[str] = []

    mapped_gender: str | None = None
    if hr_user.gender is not None:
        mapped_gender = GENDER_MAP.get(hr_user.gender)
        if mapped_gender is None:
            reasons.append(f"unmappable gender: {hr_user.gender!r}")

    mapped_rank: str | None = None
    if hr_user.rank is not None:
        mapped_rank = RANK_MAP.get(hr_user.rank)
        if mapped_rank is None:
            reasons.append(f"unmappable rank: {hr_user.rank!r}")

    mapped_track: str | None = None
    if hr_user.serv_type is not None:
        mapped_track = SERVICE_TYPE_TO_TRACK_MAP.get(hr_user.serv_type)
        if mapped_track is None:
            reasons.append(f"unmappable servicType: {hr_user.serv_type!r}")

    enlistment_date = _parse_date(hr_user.service_start_date, "serviceStartDate", reasons)
    mandatory_end_date = _parse_date(hr_user.end_hova_date, "endHovaDate", reasons)
    discharge_date = _parse_date(hr_user.service_end_date, "serviceEndDate", reasons)

    if not hr_user.personal_number:
        reasons.append("missing personal_number")
    if not hr_user.full_name:
        reasons.append("missing full_name")

    if reasons:
        return HeldForReview(personal_number=hr_user.personal_number or "", reasons=reasons)

    is_officer = mapped_rank in OFFICER_RANKS if mapped_rank else False
    is_career = derive_is_career(mapped_rank, mandatory_end_date, discharge_date)

    return MappedSoldierFields(
        full_name=hr_user.full_name,
        personal_number=hr_user.personal_number,
        email=hr_user.mail,
        phone=hr_user.phone,
        profile_picture_url=hr_user.image_url,
        gender=mapped_gender,
        rank=mapped_rank,
        rank_track=mapped_track,
        is_officer=is_officer,
        is_career=is_career,
        enlistment_date=enlistment_date,
        mandatory_end_date=mandatory_end_date,
        discharge_date=discharge_date,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest app/services/hr/tests/test_mapping.py -v` (from `backend/`)
Expected: 11 passed.

- [ ] **Step 5: Run the full HR test suite together**

Run: `pytest app/services/hr/tests/ -v` (from `backend/`)
Expected: all tests, including subsystem 1's existing 39 (or however many currently exist), plus this task's 11, pass with no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hr/mapping.py backend/app/services/hr/tests/test_mapping.py
git commit -m "feat: add HR field mapping (vocabulary translation + held-for-review)"
```

---

## Task 3: Sync divergence audit helper (`divergence.py`)

**Files:**
- Create: `backend/app/services/hr/divergence.py`
- Test: `backend/tests/unit/test_hr_sync_divergence.py`

**Interfaces:**
- Consumes: `write_audit` from `app.audit.writer` (existing); `SoldierHrProfile` from `app.db.models` (Task 1).
- Produces: `record_sync_divergence(session, *, soldier_hr_profile_id, field_name, hr_value, local_value) -> None` — consumed by subsystem 4 (not yet planned; not called anywhere in this plan).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_hr_sync_divergence.py`:

```python
from __future__ import annotations

from sqlalchemy import select

from app.db.models import AuditLog, SoldierHrProfile
from app.services.hr.divergence import record_sync_divergence


def test_record_sync_divergence_writes_audit_entry(admin_session):
    profile = SoldierHrProfile(personal_number="div-001", raw_dto={}, overridden_fields=["rank"])
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    record_sync_divergence(
        admin_session,
        soldier_hr_profile_id=profile.id,
        field_name="rank",
        hr_value="רב טוראי",
        local_value="סמל",
    )
    admin_session.commit()

    entries = admin_session.execute(
        select(AuditLog).where(AuditLog.entity_id == profile.id)
    ).scalars().all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "hr_sync.field_skipped_overridden"
    assert entry.entity_type == "soldier_hr_profile"
    assert entry.actor_id is None
    assert entry.context == {"field_name": "rank", "hr_value": "רב טוראי", "local_value": "סמל"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_hr_sync_divergence.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr.divergence'`.

- [ ] **Step 3: Implement `divergence.py`**

Create `backend/app/services/hr/divergence.py`:

```python
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.writer import write_audit


def record_sync_divergence(
    session: Session,
    *,
    soldier_hr_profile_id: uuid.UUID,
    field_name: str,
    hr_value: Any,
    local_value: Any,
) -> None:
    """Record that a sync run skipped writing `field_name` because it has
    been locally overridden. Called by the person-sync engine (a later
    subsystem) once per skipped field per sync run — not called anywhere
    in this subsystem yet."""
    write_audit(
        session,
        actor_id=None,
        action="hr_sync.field_skipped_overridden",
        entity_type="soldier_hr_profile",
        entity_id=soldier_hr_profile_id,
        context={"field_name": field_name, "hr_value": hr_value, "local_value": local_value},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_hr_sync_divergence.py -v` (from `backend/`)
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/divergence.py backend/tests/unit/test_hr_sync_divergence.py
git commit -m "feat: add HR sync divergence audit helper"
```

---

## Task 4: Override hook in `approve_field_update`

**Files:**
- Modify: `backend/app/services/soldiers.py`
- Test: `backend/tests/unit/test_soldiers_field_updates.py` (existing file, add new tests)

**Interfaces:**
- Consumes: `HR_OWNED_FIELDS` from `app.services.hr.mapping` (Task 2); `SoldierHrProfile` from `app.db.models` (Task 1); existing `write_audit`, `select`, `Session` already imported in `soldiers.py`.
- Produces: `_mark_hr_field_overridden(session, *, soldier_id, field_name, actor_id) -> None`, called from inside the existing `approve_field_update` — no new public interface for other tasks to consume (this plan's last consumer-facing piece; subsystem 4 will read `SoldierHrProfile.overridden_fields` directly, not through this function).

- [ ] **Step 1: Read the current `approve_field_update` function**

Open `backend/app/services/soldiers.py` and locate `approve_field_update` (currently starts around line 612). Read through to its end (currently around line 758) to see the exact current line numbers in your checkout before editing — they may have shifted slightly from what's quoted below if other work has landed on `dev` since this plan was written.

- [ ] **Step 2: Write the failing tests**

Add to the end of `backend/tests/unit/test_soldiers_field_updates.py`:

```python
def test_approving_hr_owned_field_update_marks_it_overridden(admin_session):
    from app.db.models import SoldierHrProfile
    from tests.helpers import create_node, create_soldier

    node = create_node(admin_session, level="branch", name="hr_override_node")
    commander = create_soldier(admin_session, personal_number="hr_override_cmd", role="commander")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number="hr_override_sol", hierarchy_node_id=node.id)
    admin_session.add(SoldierHrProfile(personal_number=soldier.personal_number, raw_dto={}, soldier_id=soldier.id))
    admin_session.commit()

    req = submit_field_update(
        admin_session, soldier_id=soldier.id, field_name="phone", new_value="050-9998888",
        actor_id=soldier.id,
    )
    admin_session.commit()

    approve_field_update(admin_session, update=req, actor_id=commander.id)
    admin_session.commit()

    profile = admin_session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.soldier_id == soldier.id)
    ).scalar_one()
    assert profile.overridden_fields == ["phone"]


def test_approving_hr_owned_field_update_is_idempotent_on_overridden_fields(admin_session):
    from app.db.models import SoldierHrProfile
    from tests.helpers import create_node, create_soldier

    node = create_node(admin_session, level="branch", name="hr_override_idem_node")
    commander = create_soldier(admin_session, personal_number="hr_override_idem_cmd", role="commander")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number="hr_override_idem_sol", hierarchy_node_id=node.id)
    admin_session.add(SoldierHrProfile(personal_number=soldier.personal_number, raw_dto={}, soldier_id=soldier.id))
    admin_session.commit()

    for value in ("050-1112222", "050-3334444"):
        req = submit_field_update(
            admin_session, soldier_id=soldier.id, field_name="phone", new_value=value,
            actor_id=soldier.id,
        )
        admin_session.commit()
        approve_field_update(admin_session, update=req, actor_id=commander.id)
        admin_session.commit()

    profile = admin_session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.soldier_id == soldier.id)
    ).scalar_one()
    assert profile.overridden_fields == ["phone"]


def test_approving_field_update_without_hr_profile_does_not_error(admin_session):
    from tests.helpers import create_node, create_soldier

    node = create_node(admin_session, level="branch", name="no_hr_profile_node")
    commander = create_soldier(admin_session, personal_number="no_hr_profile_cmd", role="commander")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number="no_hr_profile_sol", hierarchy_node_id=node.id)
    admin_session.commit()

    req = submit_field_update(
        admin_session, soldier_id=soldier.id, field_name="phone", new_value="050-1230000",
        actor_id=soldier.id,
    )
    admin_session.commit()

    approve_field_update(admin_session, update=req, actor_id=commander.id)
    admin_session.commit()
    admin_session.refresh(soldier)
    assert soldier.phone == "050-1230000"


def test_approving_non_hr_owned_field_update_does_not_touch_hr_profile(admin_session):
    from app.db.models import SoldierHrProfile
    from tests.helpers import create_node, create_soldier

    node = create_node(admin_session, level="branch", name="non_hr_field_node")
    commander = create_soldier(admin_session, personal_number="non_hr_field_cmd", role="commander")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number="non_hr_field_sol", hierarchy_node_id=node.id)
    admin_session.add(SoldierHrProfile(personal_number=soldier.personal_number, raw_dto={}, soldier_id=soldier.id))
    admin_session.commit()

    req = submit_field_update(
        admin_session, soldier_id=soldier.id, field_name="food_type", new_value="vegetarian",
        actor_id=soldier.id,
    )
    admin_session.commit()

    approve_field_update(admin_session, update=req, actor_id=commander.id)
    admin_session.commit()

    profile = admin_session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.soldier_id == soldier.id)
    ).scalar_one()
    assert profile.overridden_fields == []
```

(This test file already imports `submit_field_update`, `approve_field_update`, and `select` at module scope — check its existing imports at the top of the file and reuse them; add `SoldierHrProfile`/helper imports either at module scope alongside the existing ones or inline in each test as shown, matching whichever style the file's existing tests already use.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_soldiers_field_updates.py -v -k "hr_owned or hr_profile" ` (from `backend/`)
Expected: FAIL — `overridden_fields == []` assertion failures (the field never gets added, since the hook doesn't exist yet), not an import error (all imports already resolve to existing code/Task 1's model).

- [ ] **Step 4: Implement the override hook**

In `backend/app/services/soldiers.py`, add this function near `approve_field_update` (e.g. directly above it):

```python
def _mark_hr_field_overridden(
    session: Session, *, soldier_id: uuid.UUID, field_name: str, actor_id: uuid.UUID,
) -> None:
    from app.db.models import SoldierHrProfile
    from app.services.hr.mapping import HR_OWNED_FIELDS
    if field_name not in HR_OWNED_FIELDS:
        return
    profile = session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.soldier_id == soldier_id)
    ).scalar_one_or_none()
    if profile is None:
        return
    if field_name not in profile.overridden_fields:
        profile.overridden_fields = [*profile.overridden_fields, field_name]
        write_audit(
            session, actor_id=actor_id, action="hr_sync.field_overridden",
            entity_type="soldier_hr_profile", entity_id=profile.id,
            context={"field_name": field_name, "soldier_id": str(soldier_id)},
        )
```

Then, inside `approve_field_update`, call it once the field has actually been applied to `soldier` — insert the call right after the existing `write_audit(session, actor_id=actor_id, action="soldier.field_update.approve", ...)` call (the one inside the non-`unit_join_date` path, near the function's end) and before the `if field in {"last_mitvahim_date", "last_alal_date"}:` block:

```python
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.field_update.approve",
        entity_type="soldier_field_update",
        entity_id=update.id,
        after={"field": field, "value": raw},
    )
    _mark_hr_field_overridden(session, soldier_id=soldier.id, field_name=field, actor_id=actor_id)
    if field in {"last_mitvahim_date", "last_alal_date"}:
        from app.services.duty_eligibility_watch import recheck_soldier_assignments
        recheck_soldier_assignments(session, soldier.id)
    return update
```

Do not add this call inside the `unit_join_date` branch (it returns early before reaching this point, and `unit_join_date` is not in `HR_OWNED_FIELDS` regardless, so no functional change is needed there).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_soldiers_field_updates.py -v` (from `backend/`)
Expected: all tests in the file pass, including the 4 new ones.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/soldiers.py backend/tests/unit/test_soldiers_field_updates.py
git commit -m "feat: mark HR-owned fields overridden when an admin-approved edit lands"
```

---

## Task 5: Coverage check and pytest marker registration

**Files:**
- Modify: `backend/tests/conftest.py` (marker routing, if needed)

**Interfaces:**
- Consumes: nothing new — verifies Tasks 1-4's output meets the plan's coverage bar and fits the existing pytest area-marker system.

- [ ] **Step 1: Check marker routing for the new test file**

`backend/app/services/hr/tests/test_mapping.py` is a new stem under the already-swept `app/services/hr/tests/` tree (subsystem 1's Task 6 already added `test_client`, `test_client_pagination`, `test_errors`, `test_schemas` to `backend/tests/conftest.py`'s `_AREA_MARKERS` dict, routed to `misc`, and already wired `app/services/hr/tests` + `app/tests` into `test-full.ps1`/CI). Add `"test_mapping": "misc"` to that same dict, matching the existing entries' style exactly.

`backend/tests/unit/test_soldier_hr_profile_model.py`, `backend/tests/unit/test_hr_sync_divergence.py` live under `tests/unit/`, already part of the default `testpaths = ["tests"]` sweep — no marker-routing change needed for these two to be *collected*, but check whether `_AREA_MARKERS` assigns them an area marker (their stems are new) and add entries if the dict is used to slice CI runs by area — `test_soldier_hr_profile_model` and `test_hr_sync_divergence` most naturally fit the existing `soldiers` marker (per its description in `pyproject.toml`: "soldier profile, soldier listing, Excel import") rather than `misc`. Add both if the dict doesn't already have a catch-all for them (it doesn't — Task 6 of subsystem 1 confirmed `_AREA_MARKERS` is an explicit allow-list, not a catch-all).

`backend/tests/unit/test_soldiers_field_updates.py` (Task 4's file) already existed before this plan — check whether its stem already has an entry in `_AREA_MARKERS` (it likely does, given it's an established test file) and leave it alone if so.

- [ ] **Step 2: Run the new tests via their resolved markers to confirm routing**

Run (from `backend/`): `pytest tests app/services/hr/tests -m "misc or soldiers" -v`
Expected: includes `test_mapping.py`'s tests (under `misc`) and `test_soldier_hr_profile_model.py`/`test_hr_sync_divergence.py`'s tests (under `soldiers`, or wherever Step 1 routed them) among the results.

- [ ] **Step 3: Run coverage for the new modules**

Run (from `backend/`):
```bash
pytest app/services/hr/tests tests/unit/test_soldier_hr_profile_model.py tests/unit/test_hr_sync_divergence.py tests/unit/test_soldiers_field_updates.py --cov=app.services.hr.mapping --cov=app.services.hr.divergence --cov-report=term-missing -v
```
Expected: 100% coverage for `mapping.py` and `divergence.py`. If any lines are missed, add a targeted test in the relevant existing test file for that branch and re-run until 100%, or document precisely what remains uncovered and why (e.g. a defensive branch genuinely unreachable in practice) if a good-faith effort doesn't close it.

Note: coverage for `_mark_hr_field_overridden` specifically (inside `soldiers.py`, a large existing file) isn't practical to isolate with `--cov` flags the way a whole new module is — instead, manually confirm from Task 4's 4 new tests that every branch of `_mark_hr_field_overridden` is exercised: the early-return for a non-HR-owned field (`test_approving_non_hr_owned_field_update_does_not_touch_hr_profile`), the early-return for no profile (`test_approving_field_update_without_hr_profile_does_not_error`), the append-once path (`test_approving_hr_owned_field_update_marks_it_overridden`), and the idempotent-skip path (`test_approving_hr_owned_field_update_is_idempotent_on_overridden_fields`). All four exist per Task 4 — confirm they pass together in this run.

- [ ] **Step 4: Run the full fast backend suite to confirm no regressions**

Run (from `backend/`): `pytest -q`
Expected: all pass, no new failures introduced. If Docker/testcontainers is unavailable in your environment, note that plainly and run whatever subset you can (at minimum, everything under `app/services/hr/` and any test file directly touched by this plan) — do not claim full-suite verification you couldn't perform.

- [ ] **Step 5: Commit (if `conftest.py` changed)**

```bash
git add backend/tests/conftest.py
git commit -m "test: route new HR field-mapping tests to pytest markers"
```

(Skip this commit if Step 1 concluded no changes were needed to `_AREA_MARKERS` beyond what subsystem 1 already added — unlikely, since `test_mapping`, `test_soldier_hr_profile_model`, and `test_hr_sync_divergence` are all new stems.)

---

## Self-Review Notes

- **Spec coverage:** vocabulary translation via explicit dicts (`GENDER_MAP`/`RANK_MAP`/`SERVICE_TYPE_TO_TRACK_MAP`), `is_officer`/`is_career` derivation reusing existing `eligibility.py` logic, `HeldForReview` with named reasons, `soldier_hr_profiles` table exactly as specced, override hook wired into the existing `approve_field_update` (not a new workflow), `record_sync_divergence` primitive defined but uncalled (correctly deferred to subsystem 4), `HR_OWNED_FIELDS` centralized in `mapping.py` — all covered across Tasks 1-5.
- **Deferred by design (per spec's Non-goals):** Soldier row creation/update, HR API looping, hierarchy placement, routes/UI — correctly excluded.
- **Type consistency:** `MappedSoldierFields`/`HeldForReview` field names in Task 2's dataclass match exactly what Task 2's own tests assert on. `SoldierHrProfile.overridden_fields` (Task 1, `list[str]` via JSONB) matches the list-append logic in Task 4's `_mark_hr_field_overridden`. `record_sync_divergence`'s `soldier_hr_profile_id` parameter name matches `SoldierHrProfile.id`'s type (`uuid.UUID`) from Task 1.
- **Known limitation surfaced, not silently assumed:** the `HR_OWNED_FIELDS ∩ SOLDIER_EDITABLE_FIELDS` gap (Global Constraints) is stated explicitly rather than left for a reviewer to discover — Task 4's tests only exercise the 5 fields that are actually reachable today (`phone`, and implicitly the same code path covers `gender`/`rank`/`mandatory_end_date`/`discharge_date` since they go through the same `_mark_hr_field_overridden` call).
