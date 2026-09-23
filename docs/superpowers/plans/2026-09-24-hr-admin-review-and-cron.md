# HR Admin Review UI + Cron Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built HR hierarchy/person sync engines onto an automatic schedule, resolve the rank-advancement-worker/HR-sync ownership conflict, and give admins a review UI for what sync already flags (held-for-review records, field-override divergences, vanished profiles) plus new rank-conflict visibility.

**Architecture:** Backend: a new asyncio poll-loop worker (matching the codebase's existing 7-worker pattern) calls the existing `run_hierarchy_sync`/`run_person_sync`; `rank_advancement_worker` stops touching HR-linked soldiers and person-sync gains conflict detection + notification when HR's rank value disagrees with the worker's last independent decision or isn't a simple one-step advance; a new admin-only route module exposes 5 read views plus 2 actions (dismiss held-for-review, clear a field override) plus a manual "run sync now" trigger. Frontend: one new tab in the existing `AdminSettingsPage` tab-bar, following the `AuditLogContent`-style content-component pattern.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic/pytest (backend), React/TypeScript/TanStack Query/`DataTable` (frontend).

**Spec:** docs/superpowers/specs/2026-09-23-hr-admin-review-and-cron-design.md

## Global Constraints

- Cron uses the existing in-process asyncio poll-loop pattern (`while True: sleep; work`) — no APScheduler, no external scheduler. Reference: `backend/app/rank_advancement_worker.py`.
- The worker is skipped as a no-op (not an error) when `settings.hr_sync_enabled` is `False` (property on `Settings`, `app/settings.py:62-64`, checks `hr_api_base_url`/`hr_api_key` both set).
- `mandatory_end_date`/`discharge_date` are already fully HR-authoritative today (unchanged by this plan) — only `rank` has a competing local writer (`rank_advancement_worker`), so conflict detection is scoped to `rank` only.
- HR stays authoritative for `rank` in all cases — a detected conflict is logged/notified, never blocked or reverted.
- Held-for-review dismissal is "sticky until HR's underlying reasons change," not a one-time acknowledgement — re-dismissal is required only when the *reasons list* actually differs from what was last dismissed.
- Vanished soldiers and rank conflicts are read-only in the admin UI (no action endpoints) — explicit v1 scope boundary from the spec.
- All new admin routes use `require_roles("admin")` (`app/auth/deps.py:61-69`), matching `admin_list_audit_logs`'s pattern in `app/routes/audit_logs.py:317-328`.
- New Postgres enum value additions use `op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '...'")` and are never reversed in `downgrade()` (Postgres cannot drop enum values) — matches `20260925_hr_person_sync.py`'s existing convention.
- Never add a new i18n key to `frontend/src/i18n/he.json` (or its English counterpart) without first grepping for the exact key string — this project has been bitten by silent duplicate-key masking before.

---

### Task 1: Data model + migration

**Files:**
- Modify: `backend/app/db/models.py` — `Soldier` class (add `rank_last_set_by` after `current_rank_since`, line 63), `SoldierHrProfile` class (add `review_dismissed_at`/`review_dismissed_reasons` after `review_reason`, around line 131), `NotificationType` enum (add `hr_rank_conflict` after `hr_sync_anomaly_aborted`, line 1647), new `HrRankConflict` class (add after `HrPersonSyncError`, around line 216).
- Create: `backend/alembic/versions/20260927_hr_admin_review.py`
- Test: `backend/tests/unit/test_hr_rank_conflict_model.py`

**Interfaces:**
- Produces: `Soldier.rank_last_set_by: str | None` (values: `"hr_sync"` | `"worker"` | `"manual"` | `None`); `SoldierHrProfile.review_dismissed_at: datetime | None`, `SoldierHrProfile.review_dismissed_reasons: list[str] | None`; `HrRankConflict` model (`id`, `soldier_id`, `old_rank`, `new_rank`, `triggered_by_worker_decision: bool`, `non_sequential_jump: bool`, `hr_person_sync_id: uuid.UUID | None`, `created_at`); `NotificationType.hr_rank_conflict`.

- [ ] **Step 1: Add the model fields**

In `backend/app/db/models.py`, in the `Soldier` class, right after the `current_rank_since` field (line 63):

```python
    current_rank_since: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    # Who last wrote `rank`: "hr_sync" | "worker" | "manual" | None (unknown
    # provenance, e.g. pre-existing rows). Used by person_sync's conflict
    # detection (app/services/hr/person_sync.py) to tell "HR is confirming
    # what the worker already decided" apart from "HR is silently overriding
    # the worker's own decision".
    rank_last_set_by: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
```

In the `SoldierHrProfile` class, right after `review_reason` (line 131):

```python
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Snapshot of `review_reason`'s reasons list at the moment an admin last
    # dismissed this held-for-review record, plus when. `_mark_held`
    # (app/services/hr/person_sync.py) clears both whenever the new run's
    # reasons differ from this snapshot, so the admin review UI's
    # held-for-review list only re-surfaces a record when HR's underlying
    # data actually changed, not on every sync run.
    review_dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    review_dismissed_reasons: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
```

In the `NotificationType` enum, right after `hr_sync_anomaly_aborted = "hr_sync_anomaly_aborted"` (line 1647):

```python
    hr_sync_anomaly_aborted = "hr_sync_anomaly_aborted"
    hr_rank_conflict = "hr_rank_conflict"
```

New class, added after `HrPersonSyncError` (after line 216, before `class SystemSetting`):

```python
class HrRankConflict(Base):
    __tablename__ = "hr_rank_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    old_rank: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    new_rank: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    triggered_by_worker_decision: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    non_sequential_jump: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    hr_person_sync_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hr_person_syncs.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/20260927_hr_admin_review.py`:

```python
"""Add rank_last_set_by, review dismissal fields, hr_rank_conflicts table, hr_rank_conflict notification type

Revision ID: 20260927_hr_admin_review
Revises: 20260926_hr_activation_codes
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260927_hr_admin_review"
down_revision = "20260926_hr_activation_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soldiers", sa.Column("rank_last_set_by", sa.Text(), nullable=True))
    op.add_column(
        "soldier_hr_profiles",
        sa.Column("review_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "soldier_hr_profiles",
        sa.Column("review_dismissed_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "hr_rank_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "soldier_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("old_rank", sa.Text(), nullable=True),
        sa.Column("new_rank", sa.Text(), nullable=True),
        sa.Column("triggered_by_worker_decision", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("non_sequential_jump", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "hr_person_sync_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_person_syncs.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'hr_rank_conflict'")


def downgrade() -> None:
    op.drop_table("hr_rank_conflicts")
    op.drop_column("soldier_hr_profiles", "review_dismissed_reasons")
    op.drop_column("soldier_hr_profiles", "review_dismissed_at")
    op.drop_column("soldiers", "rank_last_set_by")
    # Postgres cannot drop enum values; matches existing repo convention
    # (20260925_hr_person_sync.py) of not reversing ALTER TYPE ... ADD VALUE.
```

- [ ] **Step 3: Apply the migration**

Run: `alembic upgrade head` (from `backend/`, with `DATABASE_URL`/`DB_ADMIN_URL` pointed at the local Postgres container — see CLAUDE.md's one-liners).
Expected: migration applies cleanly, `alembic heads` now shows `20260927_hr_admin_review`.

- [ ] **Step 4: Write the failing test**

Create `backend/tests/unit/test_hr_rank_conflict_model.py`:

```python
from __future__ import annotations

import uuid

from app.db.models import HrRankConflict, Soldier, SoldierHrProfile
from tests.helpers import create_soldier


def test_hr_rank_conflict_round_trips(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrc-1")
    conflict = HrRankConflict(
        soldier_id=soldier.id, old_rank="טוראי", new_rank="סמל",
        triggered_by_worker_decision=True, non_sequential_jump=False,
    )
    admin_session.add(conflict)
    admin_session.commit()
    admin_session.refresh(conflict)

    assert conflict.id is not None
    assert conflict.soldier_id == soldier.id
    assert conflict.old_rank == "טוראי"
    assert conflict.new_rank == "סמל"
    assert conflict.triggered_by_worker_decision is True
    assert conflict.non_sequential_jump is False
    assert conflict.hr_person_sync_id is None
    assert conflict.created_at is not None


def test_soldier_rank_last_set_by_defaults_to_none(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrc-2")
    assert soldier.rank_last_set_by is None
    soldier.rank_last_set_by = "worker"
    admin_session.commit()
    admin_session.refresh(soldier)
    assert soldier.rank_last_set_by == "worker"


def test_soldier_hr_profile_dismissal_fields_default_to_none(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrc-3")
    profile = SoldierHrProfile(personal_number="hrc-3", raw_dto={}, soldier_id=soldier.id)
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.review_dismissed_at is None
    assert profile.review_dismissed_reasons is None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/unit/test_hr_rank_conflict_model.py -v` (from `backend/`, with `DATABASE_URL`/`DB_ADMIN_URL` set to the local Postgres container).
Expected: FAIL — `ImportError: cannot import name 'HrRankConflict'` (before Step 1) or a DB error about the missing columns/table (if Step 1's model edit is done but Step 2/3's migration isn't applied yet). Do Steps 1-3 first, then this test should already pass — this is TDD-in-spirit for a schema task (schema tasks are verified by the round-trip test passing after the migration, not by a separate red/green on the model edit itself).

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/test_hr_rank_conflict_model.py -v`
Expected: `3 passed`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260927_hr_admin_review.py backend/tests/unit/test_hr_rank_conflict_model.py
git commit -m "feat: add rank provenance tracking, review dismissal fields, hr_rank_conflicts table"
```

---

### Task 2: Rank worker stops acting on HR-linked soldiers, tracks provenance

**Files:**
- Modify: `backend/app/rank_advancement_worker.py` (add HR-linked exclusion to `_promote_on_career_entry`, `_promote_due_soldiers`, `_warn_upcoming_soldiers`)
- Modify: `backend/app/services/soldiers.py` — `_promote_soldier`'s caller sets provenance; `update_soldier_profile`'s rank-edit path sets provenance
- Test: `backend/tests/unit/test_rank_advancement_worker.py`, `backend/tests/unit/test_soldiers_service.py` (or the existing test file covering `update_soldier_profile` — search for it if the exact name differs; if none is found, add assertions to `test_rank_advancement_worker.py` for the `_promote_soldier` provenance write and create a new minimal test file `backend/tests/unit/test_update_soldier_profile_rank_provenance.py` for the manual-edit path)

**Interfaces:**
- Consumes: `Soldier.rank_last_set_by` (Task 1).
- Produces: `_promote_soldier` now sets `soldier.rank_last_set_by = "worker"` whenever it writes `soldier.rank`; `update_soldier_profile`'s rank-edit path sets `soldier.rank_last_set_by = "manual"` whenever it writes `soldier.rank` directly. Both are consumed by Task 3's conflict-detection condition 1.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_rank_advancement_worker.py`:

```python
from app.db.models import SoldierHrProfile


def test_promote_soldier_sets_rank_last_set_by_worker(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000009")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, advance_on_career_entry=False, actor_id=None)
    app_session.flush()

    _promote_soldier(app_session, s, today=date(2026, 1, 1))

    assert s.rank_last_set_by == "worker"


def test_promote_due_soldiers_skips_hr_linked_soldiers(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000010")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, advance_on_career_entry=False, actor_id=None)
    app_session.add(SoldierHrProfile(personal_number="1000010", raw_dto={}, soldier_id=s.id, sync_status="synced"))
    app_session.commit()

    _promote_due_soldiers()

    app_session.refresh(s)
    assert s.rank == "טוראי"
    assert s.rank_last_set_by is None


def test_promote_due_soldiers_still_promotes_non_hr_linked_soldiers(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000011")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, advance_on_career_entry=False, actor_id=None)
    app_session.commit()

    _promote_due_soldiers()

    app_session.refresh(s)
    assert s.rank == "רבט"
    assert s.rank_last_set_by == "worker"
```

(`app_session` and `create_soldier`/`upsert_interval` imports already exist at the top of this file per the current version — no new imports needed beyond `SoldierHrProfile`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_rank_advancement_worker.py -v -k "rank_last_set_by or skips_hr_linked"`
Expected: FAIL — `AttributeError` on `rank_last_set_by` being unset (if Task 1 isn't done) is not expected here (Task 1 precedes this task), so the real expected failure is: `test_promote_soldier_sets_rank_last_set_by_worker` fails because `_promote_soldier` never sets it (assertion `None == "worker"` fails); `test_promote_due_soldiers_skips_hr_linked_soldiers` fails because the worker still promotes the HR-linked soldier (`s.rank == "רבט"` instead of the asserted `"טוראי"`).

- [ ] **Step 3: Implement**

In `backend/app/rank_advancement_worker.py`, add the import and the exclusion subquery, then use it in all three query functions:

```python
from app.db.models import RankAdvancementInterval, Soldier, SoldierHrProfile
```

(replaces the existing `from app.db.models import RankAdvancementInterval, Soldier` import line)

```python
def _not_hr_linked() -> Any:
    from sqlalchemy import select as _select
    return Soldier.id.not_in(
        _select(SoldierHrProfile.soldier_id).where(SoldierHrProfile.soldier_id.is_not(None))
    )
```

Add `from typing import Any` to the top imports. Place `_not_hr_linked` right after the module-level `_POLL_SECONDS = 86400` line.

In `_promote_soldier`, add the provenance write right before the `notify_rank_advanced` call:

```python
def _promote_soldier(session, soldier: Soldier, *, today: date) -> None:
    track = resolve_track(soldier.rank, soldier.rank_track)
    soldier.rank_track = track
    next_rank = get_next_rank(soldier.rank, track=track) if soldier.rank else None
    if next_rank is None:
        soldier.next_rank_date = None
        return
    soldier.rank = next_rank
    soldier.rank_last_set_by = "worker"
    soldier.current_rank_since = today
    soldier.next_rank_date_overridden = False
    soldier.next_rank_date = compute_next_rank_date(
        session, rank=next_rank, since=today, track=track
    )
    notify_rank_advanced(session, soldier_id=soldier.id, new_rank=next_rank)
```

In `_promote_on_career_entry`, add `_not_hr_linked()` to the `soldiers` query's `where(...)`:

```python
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.rank.in_(flagged_ranks),
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
                _not_hr_linked(),
            )
        ).scalars().all()
```

In `_promote_due_soldiers`, same addition:

```python
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.next_rank_date.is_not(None),
                Soldier.next_rank_date <= today,
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
                _not_hr_linked(),
            )
        ).scalars().all()
```

In `_warn_upcoming_soldiers`, same addition:

```python
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.next_rank_date == target,
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
                _not_hr_linked(),
            )
        ).scalars().all()
```

Now find `update_soldier_profile` in `backend/app/services/soldiers.py` (starts at line 345). Read the function in full first — it calls `_reset_rank_advancement` when `rank` is one of the edited `fields` (this is the existing "admin/DM edits rank directly" path). Add the provenance write at the same point `rank` is applied from `fields` (read the function to find the exact line where `setattr(soldier, "rank", ...)` or equivalent happens — it's inside a loop over `fields.items()` or an explicit `if "rank" in fields:` block; add `soldier.rank_last_set_by = "manual"` immediately after `soldier.rank` is set there, inside the same conditional so it only fires when `rank` was actually part of this edit).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_rank_advancement_worker.py -v`
Expected: all pass, including the 3 new tests and every pre-existing test in this file (the exclusion filter must not affect non-HR-linked soldiers' behavior — `test_promote_due_soldiers_advances_rank_and_chains_next_date` and the other pre-existing tests use `create_soldier` with no `SoldierHrProfile`, so they stay unaffected).

For the `update_soldier_profile` manual-edit provenance write: write a focused test (in whichever file already covers `update_soldier_profile`'s rank-edit path — find it via `grep -rl "update_soldier_profile" backend/tests/`; if one exists, add a test there following its existing fixture conventions asserting `soldier.rank_last_set_by == "manual"` after editing `fields={"rank": "<next rank>"}`; if no such file exists, create `backend/tests/unit/test_update_soldier_profile_rank_provenance.py` with one test doing the same, using `create_soldier` + a direct call to `update_soldier_profile`).

Run whichever test file you used and confirm the new assertion passes.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rank_advancement_worker.py backend/app/services/soldiers.py backend/tests/unit/test_rank_advancement_worker.py
git commit -m "feat: rank_advancement_worker skips HR-linked soldiers, tracks rank provenance"
```

(If a separate test file was created for the `update_soldier_profile` provenance test, add it to this commit too.)

---

### Task 3: Person sync — rank conflict detection, logging, notification

**Files:**
- Modify: `backend/app/services/hr/person_sync.py` — `_apply_existing_person`
- Test: `backend/tests/unit/test_hr_person_sync.py`

**Interfaces:**
- Consumes: `Soldier.rank_last_set_by` (Task 1, Task 2), `HrRankConflict` model (Task 1), `NotificationType.hr_rank_conflict` (Task 1), `get_next_rank`/`resolve_track` (`app.services.rank_advancement`, pre-existing), `create_notification`/`notify_commanders_of_request` (`app.services.notifications`, pre-existing).
- Produces: nothing new consumed by later tasks — this is a terminal behavior change in the existing sync path.

- [ ] **Step 1: Write the failing tests**

Read `backend/app/services/hr/person_sync.py` in full first, and re-read `_apply_existing_person` (lines 129-162) and the `_hr_user`/`_mapped`/`_linked_profile` test helpers already in `backend/tests/unit/test_hr_person_sync.py` (lines 1-97, 165-171) before writing these — reuse them exactly, don't redefine.

Append to `backend/tests/unit/test_hr_person_sync.py`:

```python
from app.db.models import HrRankConflict, Notification, NotificationType


def test_apply_existing_person_no_conflict_on_ordinary_sequential_advance(admin_session):
    from app.services.rank_advancement import upsert_interval

    soldier = create_soldier(admin_session, personal_number="ps-rc-1")
    soldier.rank = "טוראי"
    soldier.rank_last_set_by = "hr_sync"
    profile = _linked_profile(admin_session, soldier)
    upsert_interval(admin_session, track="enlisted", rank="רבט", months_to_next=8, advance_on_career_entry=False, actor_id=None)
    admin_session.commit()

    user = _hr_user(personal_number="ps-rc-1")
    mapped = _mapped(personal_number="ps-rc-1", rank="רבט")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()
    admin_session.refresh(soldier)

    assert soldier.rank == "רבט"
    assert soldier.rank_last_set_by == "hr_sync"
    assert admin_session.query(HrRankConflict).filter_by(soldier_id=soldier.id).count() == 0


def test_apply_existing_person_flags_conflict_when_worker_set_rank_first(admin_session):
    soldier = create_soldier(admin_session, personal_number="ps-rc-2")
    soldier.rank = "טוראי"
    soldier.rank_last_set_by = "worker"
    profile = _linked_profile(admin_session, soldier)
    admin_session.commit()

    user = _hr_user(personal_number="ps-rc-2")
    mapped = _mapped(personal_number="ps-rc-2", rank="סמל")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()
    admin_session.refresh(soldier)

    assert soldier.rank == "סמל"
    assert soldier.rank_last_set_by == "hr_sync"
    conflicts = admin_session.query(HrRankConflict).filter_by(soldier_id=soldier.id).all()
    assert len(conflicts) == 1
    assert conflicts[0].old_rank == "טוראי"
    assert conflicts[0].new_rank == "סמל"
    assert conflicts[0].triggered_by_worker_decision is True

    soldier_notif = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, type=NotificationType.hr_rank_conflict
    ).one_or_none()
    assert soldier_notif is not None


def test_apply_existing_person_flags_conflict_on_non_sequential_jump(admin_session):
    from app.services.rank_advancement import upsert_interval

    soldier = create_soldier(admin_session, personal_number="ps-rc-3")
    soldier.rank = "טוראי"
    soldier.rank_last_set_by = "hr_sync"
    profile = _linked_profile(admin_session, soldier)
    upsert_interval(admin_session, track="enlisted", rank="רבט", months_to_next=8, advance_on_career_entry=False, actor_id=None)
    admin_session.commit()

    user = _hr_user(personal_number="ps-rc-3")
    mapped = _mapped(personal_number="ps-rc-3", rank="סמל")  # not the next rank in sequence (רבט is)

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    conflicts = admin_session.query(HrRankConflict).filter_by(soldier_id=soldier.id).all()
    assert len(conflicts) == 1
    assert conflicts[0].non_sequential_jump is True
    assert conflicts[0].triggered_by_worker_decision is False


def test_apply_existing_person_no_conflict_when_rank_unchanged(admin_session):
    soldier = create_soldier(admin_session, personal_number="ps-rc-4")
    soldier.rank = "טוראי"
    soldier.rank_last_set_by = "worker"
    profile = _linked_profile(admin_session, soldier)
    admin_session.commit()

    user = _hr_user(personal_number="ps-rc-4")
    mapped = _mapped(personal_number="ps-rc-4", rank="טוראי")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    assert admin_session.query(HrRankConflict).filter_by(soldier_id=soldier.id).count() == 0
```

Note: `רבט` is the correct next rank after `טוראי` on the `"enlisted"` track per the existing `upsert_interval` fixture usage already established in `test_rank_advancement_worker.py` — reuse that same rank pair for the "sequential" tests. `סמל` is used only as a rank that is *not* `get_next_rank("טוראי", track="enlisted")` for the non-sequential test — if `get_next_rank` returns something else in this codebase's actual rank ladder for the enlisted track, adjust the non-sequential test's chosen rank so it's genuinely not the next-in-sequence rank (check `app/services/rank_advancement.py`'s ladder definitions if in doubt).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_person_sync.py -v -k "conflict"`
Expected: FAIL — no `HrRankConflict` rows are ever created (conflict detection doesn't exist yet), so the "flags conflict" tests fail on `len(conflicts) == 1` (actual 0), and the "no conflict" tests should already trivially pass (nothing creates conflicts yet) — that's fine, they're regression guards for after Step 3 lands.

- [ ] **Step 3: Implement**

In `backend/app/services/hr/person_sync.py`, add imports:

```python
from app.db.models import (
    HrHierarchyNodeMap,
    HrPersonSync,
    HrPersonSyncError,
    HrRankConflict,
    NotificationType,
    Soldier,
    SoldierHrProfile,
)
from app.services.notifications import create_notification, notify_commanders_of_request
from app.services.rank_advancement import get_next_rank, resolve_track
```

(this replaces the existing `from app.db.models import (...)` and `from app.services.notifications import create_notification` import lines — merge in the new names, don't duplicate the import statement.)

Modify `_apply_existing_person` to detect and record a rank conflict at the point `rank` is about to change. The loop over `HR_OWNED_FIELDS` currently does:

```python
    for field_name in HR_OWNED_FIELDS:
        if field_name == "personal_number":
            continue
        new_value = getattr(mapped, field_name)
        if field_name in profile.overridden_fields:
            old_value = getattr(soldier, field_name)
            if old_value != new_value:
                record_sync_divergence(
                    session, soldier_hr_profile_id=profile.id, field_name=field_name,
                    hr_value=new_value, local_value=old_value,
                )
            continue
        old_value = getattr(soldier, field_name)
        if field_name in _DEPENDENT_LOGIC_TRIGGER_FIELDS and old_value != new_value:
            changed_dependent_field = True
        setattr(soldier, field_name, new_value)
```

Replace the final three lines (from `old_value = getattr(soldier, field_name)` to `setattr(soldier, field_name, new_value)`) with:

```python
        old_value = getattr(soldier, field_name)
        if field_name in _DEPENDENT_LOGIC_TRIGGER_FIELDS and old_value != new_value:
            changed_dependent_field = True
        if field_name == "rank" and old_value != new_value and old_value is not None:
            _flag_rank_conflict_if_needed(session, soldier=soldier, old_rank=old_value, new_rank=new_value)
        setattr(soldier, field_name, new_value)
        if field_name == "rank" and old_value != new_value:
            soldier.rank_last_set_by = "hr_sync"
```

Add the new helper function right before `_apply_existing_person`:

```python
def _flag_rank_conflict_if_needed(
    session: Session, *, soldier: Soldier, old_rank: str, new_rank: str,
) -> None:
    """Record a conflict and notify the soldier + their commander(s) when
    HR's incoming rank either overrides a decision the worker made on its
    own, or isn't a simple one-step advance from where the soldier was.
    HR's value is applied regardless (HR stays authoritative) -- this is a
    visibility/audit action, not a block."""
    triggered_by_worker_decision = soldier.rank_last_set_by == "worker"
    track = resolve_track(old_rank, soldier.rank_track)
    expected_next = get_next_rank(old_rank, track=track) if old_rank else None
    non_sequential_jump = new_rank != expected_next

    if not (triggered_by_worker_decision or non_sequential_jump):
        return

    session.add(HrRankConflict(
        soldier_id=soldier.id, old_rank=old_rank, new_rank=new_rank,
        triggered_by_worker_decision=triggered_by_worker_decision,
        non_sequential_jump=non_sequential_jump,
    ))
    title = "דרגתך עודכנה בעקבות סנכרון מול מערכת משאבי אנוש"
    body = f"הדרגה עודכנה מ-{old_rank} ל-{new_rank} בעקבות נתוני משאבי אנוש, שאינם תואמים את ההתקדמות הצפויה."
    create_notification(
        session, soldier_id=soldier.id, type=NotificationType.hr_rank_conflict,
        title=title, body=body, reference_type="soldier", reference_id=soldier.id,
    )
    notify_commanders_of_request(
        session, soldier_id=soldier.id, type=NotificationType.hr_rank_conflict,
        title=title, body=body, reference_type="soldier", reference_id=soldier.id,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_person_sync.py -v`
Expected: all pass, including every pre-existing test in this file (the divergence/override path is untouched; only the non-overridden `rank`-write branch changed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/person_sync.py backend/tests/unit/test_hr_person_sync.py
git commit -m "feat: detect and notify HR-vs-worker rank conflicts during person sync"
```

---

### Task 4: Held-for-review dismissal persistence

**Files:**
- Modify: `backend/app/services/hr/person_sync.py` — `_mark_held`
- Test: `backend/tests/unit/test_hr_person_sync.py`

**Interfaces:**
- Consumes: `SoldierHrProfile.review_dismissed_at`/`review_dismissed_reasons` (Task 1).
- Produces: the invariant Task 7's held-for-review list query relies on — a dismissed profile whose `reasons` haven't changed since dismissal keeps `review_dismissed_at` set; any change to `reasons` clears both fields.

- [ ] **Step 1: Write the failing tests**

Read the current `_mark_held` (around line 117-123) first. Append to `backend/tests/unit/test_hr_person_sync.py`:

```python
from datetime import datetime, timezone


def test_mark_held_clears_dismissal_when_reasons_change(admin_session):
    profile = SoldierHrProfile(
        personal_number="ps-dismiss-1", raw_dto={}, sync_status="held_for_review",
        review_reason="bad date",
        review_dismissed_at=datetime.now(tz=timezone.utc),
        review_dismissed_reasons=["bad date"],
    )
    admin_session.add(profile)
    admin_session.commit()

    user = _hr_user(personal_number="ps-dismiss-1")
    held = HeldForReview(personal_number="ps-dismiss-1", reasons=["different reason now"])
    _mark_held(admin_session, user, held)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.review_dismissed_at is None
    assert profile.review_dismissed_reasons is None


def test_mark_held_keeps_dismissal_when_reasons_unchanged(admin_session):
    dismissed_at = datetime.now(tz=timezone.utc)
    profile = SoldierHrProfile(
        personal_number="ps-dismiss-2", raw_dto={}, sync_status="held_for_review",
        review_reason="bad date",
        review_dismissed_at=dismissed_at,
        review_dismissed_reasons=["bad date"],
    )
    admin_session.add(profile)
    admin_session.commit()

    user = _hr_user(personal_number="ps-dismiss-2")
    held = HeldForReview(personal_number="ps-dismiss-2", reasons=["bad date"])
    _mark_held(admin_session, user, held)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.review_dismissed_at is not None
    assert profile.review_dismissed_reasons == ["bad date"]
```

(`HeldForReview` is already imported at the top of this test file per its existing content — confirm before adding a duplicate import.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_person_sync.py -v -k dismiss`
Expected: FAIL — `test_mark_held_clears_dismissal_when_reasons_change` fails because nothing currently clears the dismissal fields (`review_dismissed_at` stays set).

- [ ] **Step 3: Implement**

In `backend/app/services/hr/person_sync.py`, modify `_mark_held`:

```python
def _mark_held(session: Session, user: HrUser, held: HeldForReview) -> SoldierHrProfile:
    profile = _find_or_create_soldier_hr_profile(session, held.personal_number)
    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "held_for_review"
    profile.review_reason = "; ".join(held.reasons)
    profile.last_synced_at = datetime.now(tz=timezone.utc)
    if profile.review_dismissed_reasons != held.reasons:
        profile.review_dismissed_at = None
        profile.review_dismissed_reasons = None
    return profile
```

(only the new `if profile.review_dismissed_reasons != held.reasons:` block is added — everything else in the function is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_person_sync.py -v`
Expected: all pass, including every pre-existing test (`_mark_held`'s existing behavior for a never-dismissed profile is unchanged: `review_dismissed_reasons` starts `None`, `None != held.reasons` is `True` for any non-empty `reasons`, so the fields get set to `None` again — a no-op for a profile that was never dismissed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/person_sync.py backend/tests/unit/test_hr_person_sync.py
git commit -m "feat: held-for-review dismissal persists until HR's underlying reasons change"
```

---

### Task 5: Cron worker

**Files:**
- Create: `backend/app/hr_sync_worker.py`
- Modify: `backend/app/main.py` (import + lifespan wiring)
- Test: `backend/tests/unit/test_hr_sync_worker.py`

**Interfaces:**
- Consumes: `run_hierarchy_sync(session, client) -> HrHierarchySync` (`app.services.hr.hierarchy_sync`, pre-existing), `run_person_sync(session, client) -> HrPersonSync` (`app.services.hr.person_sync`, pre-existing), `HrApiClient` (`app.services.hr.client`, pre-existing), `settings.hr_sync_enabled` / `settings.hr_api_base_url` / `settings.hr_api_key` / `settings.hr_api_ca_bundle_path` / `settings.hr_api_page_size` (`app.settings`, pre-existing), `get_setting_int`/`SettingNotFound` (`app.services.settings_loader`, pre-existing), `session_scope` (`app.db.session`, pre-existing).
- Produces: `run_hr_sync_worker() -> None` (the poll loop, wired into `main.py`'s lifespan), `_run_hr_sync_cycle(session) -> None` (one cycle's logic, used directly by Task 7's "run sync now" action so the manual trigger doesn't have to duplicate the client-construction/hierarchy-then-person-order logic).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_hr_sync_worker.py`:

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.hr_sync_worker import _run_hr_sync_cycle, run_hr_sync_worker


def test_worker_calls_sync_cycle_each_wake(app_session) -> None:
    with patch("app.hr_sync_worker._run_hr_sync_cycle_in_own_session") as mock_cycle, \
         patch("app.hr_sync_worker.asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        try:
            asyncio.run(run_hr_sync_worker())
        except asyncio.CancelledError:
            pass
    mock_cycle.assert_called_once()


def test_run_hr_sync_cycle_skips_when_hr_not_configured(app_session) -> None:
    with patch("app.hr_sync_worker.get_settings") as mock_settings:
        mock_settings.return_value.hr_sync_enabled = False
        with patch("app.hr_sync_worker.run_hierarchy_sync") as mock_hierarchy, \
             patch("app.hr_sync_worker.run_person_sync") as mock_person:
            asyncio.run(_run_hr_sync_cycle(app_session))
    mock_hierarchy.assert_not_called()
    mock_person.assert_not_called()


def test_run_hr_sync_cycle_runs_hierarchy_then_person_sync(app_session) -> None:
    with patch("app.hr_sync_worker.get_settings") as mock_settings:
        mock_settings.return_value.hr_sync_enabled = True
        mock_settings.return_value.hr_api_base_url = "https://hr.example"
        mock_settings.return_value.hr_api_key = "key"
        mock_settings.return_value.hr_api_ca_bundle_path = ""
        mock_settings.return_value.hr_api_page_size = 200
        with patch("app.hr_sync_worker.HrApiClient") as mock_client_cls, \
             patch("app.hr_sync_worker.run_hierarchy_sync", new_callable=AsyncMock) as mock_hierarchy, \
             patch("app.hr_sync_worker.run_person_sync", new_callable=AsyncMock) as mock_person:
            call_order = []
            mock_hierarchy.side_effect = lambda *a, **k: call_order.append("hierarchy")
            mock_person.side_effect = lambda *a, **k: call_order.append("person")
            asyncio.run(_run_hr_sync_cycle(app_session))
    mock_client_cls.assert_called_once_with(
        "https://hr.example", "key", ca_bundle_path="", page_size=200,
    )
    mock_hierarchy.assert_called_once()
    mock_person.assert_called_once()
    assert call_order == ["hierarchy", "person"]


def test_run_hr_sync_cycle_logs_and_swallows_exceptions(app_session) -> None:
    with patch("app.hr_sync_worker.get_settings") as mock_settings:
        mock_settings.return_value.hr_sync_enabled = True
        mock_settings.return_value.hr_api_base_url = "https://hr.example"
        mock_settings.return_value.hr_api_key = "key"
        mock_settings.return_value.hr_api_ca_bundle_path = ""
        mock_settings.return_value.hr_api_page_size = 200
        with patch("app.hr_sync_worker.HrApiClient"), \
             patch("app.hr_sync_worker.run_hierarchy_sync", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            # Must not raise -- the cycle catches and logs.
            asyncio.run(_run_hr_sync_cycle(app_session))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_sync_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.hr_sync_worker'`.

- [ ] **Step 3: Implement**

Create `backend/app/hr_sync_worker.py`:

```python
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.services.hr.client import HrApiClient
from app.services.hr.hierarchy_sync import run_hierarchy_sync
from app.services.hr.person_sync import run_person_sync
from app.services.settings_loader import SettingNotFound, get_setting_int
from app.settings import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_POLL_HOURS = 6


async def _run_hr_sync_cycle(session: Session) -> None:
    settings = get_settings()
    if not settings.hr_sync_enabled:
        return
    client = HrApiClient(
        settings.hr_api_base_url, settings.hr_api_key,
        ca_bundle_path=settings.hr_api_ca_bundle_path,
        page_size=settings.hr_api_page_size,
    )
    try:
        await run_hierarchy_sync(session, client)
        await run_person_sync(session, client)
    except Exception:
        logger.warning("hr sync worker: unhandled error", exc_info=True)


def _run_hr_sync_cycle_in_own_session() -> None:
    with session_scope() as session:
        try:
            poll_hours = get_setting_int(session, "hr_sync.poll_hours", _DEFAULT_POLL_HOURS)
        except SettingNotFound:
            poll_hours = _DEFAULT_POLL_HOURS
        asyncio.run(_run_hr_sync_cycle(session))
        session.commit()
        return poll_hours


async def run_hr_sync_worker() -> None:
    while True:
        poll_hours = await asyncio.to_thread(_run_hr_sync_cycle_in_own_session)
        await asyncio.sleep((poll_hours or _DEFAULT_POLL_HOURS) * 3600)
```

Wait — re-derive this: `get_setting_int` already has its own internal `try/except SettingNotFound: return default` (confirmed in `app/services/settings_loader.py:68-72`), so the outer `try/except SettingNotFound` in `_run_hr_sync_cycle_in_own_session` above is dead code (redundant) — remove it. Corrected version of that function:

```python
def _run_hr_sync_cycle_in_own_session() -> int:
    with session_scope() as session:
        poll_hours = get_setting_int(session, "hr_sync.poll_hours", _DEFAULT_POLL_HOURS)
        asyncio.run(_run_hr_sync_cycle(session))
        session.commit()
        return poll_hours
```

(This still matches `test_run_hr_sync_cycle_skips_when_hr_not_configured`/`..._runs_hierarchy_then_person_sync`/`..._logs_and_swallows_exceptions`, which all patch and call `_run_hr_sync_cycle` directly with an `app_session` fixture, not through `_run_hr_sync_cycle_in_own_session` — those three tests don't touch `session_scope` at all. Only `test_worker_calls_sync_cycle_each_wake` patches `_run_hr_sync_cycle_in_own_session` itself, as a black box.)

Also note `_run_hr_sync_cycle_in_own_session` runs `asyncio.run(...)` inside a function that itself gets called via `asyncio.to_thread` from the async `run_hr_sync_worker` loop — this is deliberate: `session_scope()` is presumably a synchronous context manager (matching every other worker's `with session_scope() as session:` pattern, e.g. `rank_advancement_worker.py`), so the whole cycle (session open → close) has to happen off the event loop thread, same as `await asyncio.to_thread(_promote_due_soldiers)` does in `rank_advancement_worker.run_rank_advancement_worker`. Before finalizing this file, read `app/db/session.py`'s `session_scope` to confirm it's synchronous (not an async context manager) — if it is (expected, matching the rank worker's usage), the structure above is correct as written.

- [ ] **Step 4: Wire into main.py**

In `backend/app/main.py`, add the import alongside the other worker imports (near `from app.rank_advancement_worker import run_rank_advancement_worker`):

```python
from app.hr_sync_worker import run_hr_sync_worker
```

In the `lifespan` function, add the task creation alongside the others:

```python
    hr_sync_task = asyncio.create_task(run_hr_sync_worker())
```

(add this line right after `rank_advancement_task = asyncio.create_task(run_rank_advancement_worker())`)

And add `hr_sync_task` into both tuples in the shutdown loop:

```python
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task, duty_eligibility_task, rank_advancement_task, hr_sync_task, qualification_expiry_task, score_projection_revalidation_task):
        task.cancel()
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task, duty_eligibility_task, rank_advancement_task, hr_sync_task, qualification_expiry_task, score_projection_revalidation_task):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_sync_worker.py -v`
Expected: all 4 pass.

Also run the full backend suite's app.main import smoke test if one exists (`grep -rl "from app.main import app" backend/tests` and run whatever test file that turns up), to confirm `main.py`'s new import doesn't break app startup — at minimum, `pytest -q` on the full suite at the end of this task should surface any import-time breakage.

- [ ] **Step 6: Commit**

```bash
git add backend/app/hr_sync_worker.py backend/app/main.py backend/tests/unit/test_hr_sync_worker.py
git commit -m "feat: wire hierarchy/person HR sync onto an automatic poll-loop worker"
```

---

### Task 6: Admin review service (dismiss + clear-override actions)

**Files:**
- Create: `backend/app/services/hr/review.py`
- Test: `backend/app/services/hr/tests/test_review.py`

**Interfaces:**
- Consumes: `SoldierHrProfile` (fields from Task 1 + pre-existing `sync_status`/`review_reason`/`overridden_fields`), `write_audit` (`app.audit.writer`, pre-existing, used the same way `record_sync_divergence` uses it).
- Produces: `dismiss_held_for_review(session, *, profile_id: uuid.UUID) -> SoldierHrProfile` (raises `ReviewActionError` on a bad id or wrong `sync_status`), `clear_field_override(session, *, profile_id: uuid.UUID, field_name: str) -> SoldierHrProfile` (raises `ReviewActionError` on a bad id, unknown `field_name`, or a `field_name` not currently in `overridden_fields`), `ReviewActionError` (exception class, string messages, same shape as `hr_activation.ActivationCodeError`/`hr_onboarding.OnboardingError`). Task 7's routes catch `ReviewActionError` and map it to HTTP status codes.

- [ ] **Step 1: Write the failing tests**

Read `backend/app/services/hr/mapping.py`'s `HR_OWNED_FIELDS` frozenset (line 29-32) first — `clear_field_override` validates `field_name` against it.

Create `backend/app/services/hr/tests/test_review.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import SoldierHrProfile
from app.services.hr.review import ReviewActionError, clear_field_override, dismiss_held_for_review
from tests.helpers import create_soldier


def _held_profile(session, *, personal_number: str, reasons: list[str] = None) -> SoldierHrProfile:
    reasons = reasons or ["bad date"]
    profile = SoldierHrProfile(
        personal_number=personal_number, raw_dto={}, sync_status="held_for_review",
        review_reason="; ".join(reasons),
    )
    session.add(profile)
    session.commit()
    return profile


def test_dismiss_held_for_review_sets_dismissal_fields(admin_session):
    profile = _held_profile(admin_session, personal_number="rev-1", reasons=["bad date", "unmapped rank"])

    result = dismiss_held_for_review(admin_session, profile_id=profile.id)
    admin_session.commit()
    admin_session.refresh(profile)

    assert result.id == profile.id
    assert profile.review_dismissed_at is not None
    assert profile.review_dismissed_reasons == ["bad date", "unmapped rank"]


def test_dismiss_held_for_review_raises_on_unknown_profile(admin_session):
    with pytest.raises(ReviewActionError, match="profile_not_found"):
        dismiss_held_for_review(admin_session, profile_id=uuid.uuid4())


def test_dismiss_held_for_review_raises_when_not_held(admin_session):
    profile = SoldierHrProfile(personal_number="rev-2", raw_dto={}, sync_status="synced")
    admin_session.add(profile)
    admin_session.commit()

    with pytest.raises(ReviewActionError, match="not_held_for_review"):
        dismiss_held_for_review(admin_session, profile_id=profile.id)


def test_clear_field_override_removes_field_and_writes_audit(admin_session):
    soldier = create_soldier(admin_session, personal_number="rev-3")
    profile = SoldierHrProfile(
        personal_number="rev-3", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone", "email"],
    )
    admin_session.add(profile)
    admin_session.commit()

    result = clear_field_override(admin_session, profile_id=profile.id, field_name="phone")
    admin_session.commit()
    admin_session.refresh(profile)

    assert result.overridden_fields == ["email"]
    assert profile.overridden_fields == ["email"]


def test_clear_field_override_raises_on_unknown_field_name(admin_session):
    soldier = create_soldier(admin_session, personal_number="rev-4")
    profile = SoldierHrProfile(
        personal_number="rev-4", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone"],
    )
    admin_session.add(profile)
    admin_session.commit()

    with pytest.raises(ReviewActionError, match="unknown_field"):
        clear_field_override(admin_session, profile_id=profile.id, field_name="not_a_real_field")


def test_clear_field_override_raises_when_field_not_overridden(admin_session):
    soldier = create_soldier(admin_session, personal_number="rev-5")
    profile = SoldierHrProfile(
        personal_number="rev-5", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["email"],
    )
    admin_session.add(profile)
    admin_session.commit()

    with pytest.raises(ReviewActionError, match="field_not_overridden"):
        clear_field_override(admin_session, profile_id=profile.id, field_name="phone")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest app/services/hr/tests/test_review.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr.review'`.

- [ ] **Step 3: Implement**

Create `backend/app/services/hr/review.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import SoldierHrProfile
from app.services.hr.mapping import HR_OWNED_FIELDS


class ReviewActionError(Exception):
    pass


def dismiss_held_for_review(session: Session, *, profile_id: uuid.UUID) -> SoldierHrProfile:
    profile = session.get(SoldierHrProfile, profile_id)
    if profile is None:
        raise ReviewActionError("profile_not_found")
    if profile.sync_status != "held_for_review":
        raise ReviewActionError("not_held_for_review")

    reasons = profile.review_reason.split("; ") if profile.review_reason else []
    profile.review_dismissed_at = datetime.now(tz=timezone.utc)
    profile.review_dismissed_reasons = reasons
    return profile


def clear_field_override(
    session: Session, *, profile_id: uuid.UUID, field_name: str,
) -> SoldierHrProfile:
    profile = session.get(SoldierHrProfile, profile_id)
    if profile is None:
        raise ReviewActionError("profile_not_found")
    if field_name not in HR_OWNED_FIELDS:
        raise ReviewActionError("unknown_field")
    if field_name not in profile.overridden_fields:
        raise ReviewActionError("field_not_overridden")

    before = list(profile.overridden_fields)
    profile.overridden_fields = [f for f in profile.overridden_fields if f != field_name]
    write_audit(
        session, actor_id=None, action="hr_sync.override_cleared",
        entity_type="soldier_hr_profile", entity_id=profile.id,
        context={"field_name": field_name, "before": before, "after": profile.overridden_fields},
    )
    return profile
```

`write_audit`'s `actor_id=None` here matches `record_sync_divergence`'s own convention in `app/services/hr/divergence.py` — Task 7's route is responsible for passing the actual admin's id; revisit this if Task 7 needs `actor_id` threaded through (check that task's exact route signature — if `require_roles("admin")` gives the route the acting `Soldier`, thread `actor_id=user.id` through `clear_field_override`'s signature as an added `actor_id: uuid.UUID | None` parameter instead of hardcoding `None` here, matching how `generate_activation_code` threads `actor` through from subsystem 5. Prefer that over the hardcoded `None` — update the signature and the two tests that call `clear_field_override` to pass `actor_id=None` explicitly if you make this change, so the tests still assert real behavior rather than relying on a default.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest app/services/hr/tests/test_review.py -v` (from `backend/`)
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/review.py backend/app/services/hr/tests/test_review.py
git commit -m "feat: admin review service — dismiss held-for-review, clear field overrides"
```

---

### Task 7: Admin review routes

**Files:**
- Create: `backend/app/routes/hr_review.py`
- Modify: `backend/app/main.py` (import + `include_router`)
- Test: `backend/tests/integration/test_hr_review_routes.py`

**Interfaces:**
- Consumes: `dismiss_held_for_review`/`clear_field_override`/`ReviewActionError` (Task 6), `_run_hr_sync_cycle`/`session` pattern (Task 5, for the manual trigger — actually re-derive: the manual trigger needs an `HrApiClient` and to call `run_hierarchy_sync`/`run_person_sync` directly with the route's own request-scoped `session`, not `_run_hr_sync_cycle`'s own `session_scope()`-opened session — so this route imports `run_hierarchy_sync`/`run_person_sync`/`HrApiClient` directly from their own modules and constructs the client itself, following the same construction shown in Task 5's `_run_hr_sync_cycle`, rather than calling `_run_hr_sync_cycle` itself), `require_roles` (`app.auth.deps`, pre-existing), `HrHierarchySync`/`HrPersonSync`/`HrPersonSyncError`/`HrRankConflict`/`SoldierHrProfile`/`AuditLog`/`Soldier` models (pre-existing + Task 1).
- Produces: 5 GET routes + 2 POST action routes + 1 POST manual-trigger route, all under `/admin/hr-sync/*`, all `require_roles("admin")`.

- [ ] **Step 1: Write the failing tests**

Read `backend/app/routes/audit_logs.py`'s `admin_list_audit_logs` (lines 317-397) once more before writing this route file — it's the closest precedent for pagination/facet shape, admin auth, and response models.

Create `backend/tests/integration/test_hr_review_routes.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import HrRankConflict, SoldierHrProfile
from tests.helpers import create_soldier


def _admin_headers(client, admin_session):
    admin = create_soldier(admin_session, personal_number="hrr-admin", role="admin")
    from app.auth.jwt_tokens import issue_access_token
    token = issue_access_token(soldier_id=admin.id, role=admin.role, token_version=admin.token_version)
    return {"Authorization": f"Bearer {token}"}


def test_non_admin_gets_403(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="hrr-1")
    from app.auth.jwt_tokens import issue_access_token
    token = issue_access_token(soldier_id=soldier.id, role=soldier.role, token_version=soldier.token_version)
    r = client.get("/api/admin/hr-sync/held-for-review", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_held_for_review_excludes_dismissed_unchanged_records(client, admin_session):
    headers = _admin_headers(client, admin_session)
    admin_session.add_all([
        SoldierHrProfile(
            personal_number="hrr-2", raw_dto={}, sync_status="held_for_review",
            review_reason="bad date",
        ),
        SoldierHrProfile(
            personal_number="hrr-3", raw_dto={}, sync_status="held_for_review",
            review_reason="bad date",
            review_dismissed_at=datetime.now(tz=timezone.utc),
            review_dismissed_reasons=["bad date"],
        ),
    ])
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/held-for-review", headers=headers)
    assert r.status_code == 200
    personal_numbers = {item["personal_number"] for item in r.json()["items"]}
    assert "hrr-2" in personal_numbers
    assert "hrr-3" not in personal_numbers


def test_dismiss_held_for_review_action(client, admin_session):
    headers = _admin_headers(client, admin_session)
    profile = SoldierHrProfile(
        personal_number="hrr-4", raw_dto={}, sync_status="held_for_review", review_reason="bad date",
    )
    admin_session.add(profile)
    admin_session.commit()

    r = client.post(f"/api/admin/hr-sync/held-for-review/{profile.id}/dismiss", headers=headers)
    assert r.status_code == 200
    admin_session.refresh(profile)
    assert profile.review_dismissed_at is not None


def test_divergences_lists_field_skipped_overridden_audit_rows(client, admin_session):
    headers = _admin_headers(client, admin_session)
    soldier = create_soldier(admin_session, personal_number="hrr-5")
    profile = SoldierHrProfile(
        personal_number="hrr-5", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone"],
    )
    admin_session.add(profile)
    admin_session.commit()

    from app.services.hr.divergence import record_sync_divergence
    record_sync_divergence(
        admin_session, soldier_hr_profile_id=profile.id, field_name="phone",
        hr_value="050-1112222", local_value="050-9998888",
    )
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/divergences", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["field_name"] == "phone"


def test_clear_override_action(client, admin_session):
    headers = _admin_headers(client, admin_session)
    soldier = create_soldier(admin_session, personal_number="hrr-6")
    profile = SoldierHrProfile(
        personal_number="hrr-6", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone"],
    )
    admin_session.add(profile)
    admin_session.commit()

    r = client.post(
        f"/api/admin/hr-sync/divergences/{profile.id}/clear-override",
        headers=headers, json={"field_name": "phone"},
    )
    assert r.status_code == 200
    admin_session.refresh(profile)
    assert profile.overridden_fields == []


def test_vanished_lists_vanished_profiles(client, admin_session):
    headers = _admin_headers(client, admin_session)
    admin_session.add(SoldierHrProfile(personal_number="hrr-7", raw_dto={}, sync_status="vanished"))
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/vanished", headers=headers)
    assert r.status_code == 200
    assert any(item["personal_number"] == "hrr-7" for item in r.json()["items"])


def test_rank_conflicts_lists_conflicts(client, admin_session):
    headers = _admin_headers(client, admin_session)
    soldier = create_soldier(admin_session, personal_number="hrr-8")
    admin_session.add(HrRankConflict(
        soldier_id=soldier.id, old_rank="טוראי", new_rank="סמל",
        triggered_by_worker_decision=True, non_sequential_jump=False,
    ))
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/rank-conflicts", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["old_rank"] == "טוראי"


def test_sync_runs_lists_recent_runs(client, admin_session):
    headers = _admin_headers(client, admin_session)
    from app.db.models import HrPersonSync
    run = HrPersonSync(status="completed", total_fetched=10, created_count=2, updated_count=8)
    admin_session.add(run)
    admin_session.commit()

    r = client.get("/api/admin/hr-sync/runs", headers=headers)
    assert r.status_code == 200
    assert any(item["id"] == str(run.id) for item in r.json()["person_syncs"])


def test_run_now_triggers_sync(client, admin_session, monkeypatch):
    headers = _admin_headers(client, admin_session)
    from unittest.mock import AsyncMock
    import app.routes.hr_review as hr_review_module
    monkeypatch.setattr(hr_review_module, "run_hierarchy_sync", AsyncMock())
    monkeypatch.setattr(hr_review_module, "run_person_sync", AsyncMock())

    from app.settings import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("HR_API_BASE_URL", "https://hr.example")
    monkeypatch.setenv("HR_API_KEY", "key")

    r = client.post("/api/admin/hr-sync/run-now", headers=headers)
    assert r.status_code == 200
    hr_review_module.run_hierarchy_sync.assert_called_once()
    hr_review_module.run_person_sync.assert_called_once()
    get_settings.cache_clear()
```

`client`/`admin_session` fixtures already exist project-wide (used throughout `backend/tests/integration/`) — confirm their exact names by checking any neighboring integration test file (e.g. `test_hr_activation_route.py`) rather than assuming; adjust the test bodies above if this project's actual fixture names differ. `issue_access_token`'s exact signature — confirm it against its real definition in `app/auth/jwt_tokens.py` before using it (the calls above assume `issue_access_token(soldier_id, role, token_version)` as keyword args; if the real signature differs, use its actual parameter names — check how `test_login.py`'s existing tests construct tokens if this constructor form is wrong).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_hr_review_routes.py -v`
Expected: FAIL — `404` on every route (module doesn't exist / isn't registered yet).

- [ ] **Step 3: Implement**

Create `backend/app/routes/hr_review.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import (
    AuditLog,
    HrHierarchySync,
    HrPersonSync,
    HrPersonSyncError,
    HrRankConflict,
    Soldier,
    SoldierHrProfile,
)
from app.db.session import get_session
from app.services.hr.client import HrApiClient
from app.services.hr.hierarchy_sync import run_hierarchy_sync
from app.services.hr.person_sync import run_person_sync
from app.services.hr.review import ReviewActionError, clear_field_override, dismiss_held_for_review
from app.settings import get_settings

router = APIRouter(prefix="/admin/hr-sync", tags=["hr-review"])


class HeldForReviewItemOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    review_reason: str | None
    last_synced_at: datetime | None


class HeldForReviewPageOut(BaseModel):
    items: list[HeldForReviewItemOut]


@router.get("/held-for-review", response_model=HeldForReviewPageOut)
def list_held_for_review(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HeldForReviewPageOut:
    rows = session.execute(
        select(SoldierHrProfile).where(
            SoldierHrProfile.sync_status == "held_for_review",
            SoldierHrProfile.review_dismissed_at.is_(None),
        ).order_by(SoldierHrProfile.last_synced_at.desc())
    ).scalars().all()
    return HeldForReviewPageOut(items=[
        HeldForReviewItemOut(
            id=r.id, personal_number=r.personal_number,
            review_reason=r.review_reason, last_synced_at=r.last_synced_at,
        ) for r in rows
    ])


@router.post("/held-for-review/{profile_id}/dismiss", response_model=HeldForReviewItemOut)
def dismiss_held_for_review_route(
    profile_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HeldForReviewItemOut:
    try:
        profile = dismiss_held_for_review(session, profile_id=profile_id)
    except ReviewActionError as exc:
        session.rollback()
        code = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if code == "profile_not_found" else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=status_code, detail=code) from exc
    session.commit()
    return HeldForReviewItemOut(
        id=profile.id, personal_number=profile.personal_number,
        review_reason=profile.review_reason, last_synced_at=profile.last_synced_at,
    )


class DivergenceItemOut(BaseModel):
    id: uuid.UUID
    soldier_hr_profile_id: uuid.UUID
    field_name: str
    hr_value: object
    local_value: object
    created_at: datetime


class DivergencePageOut(BaseModel):
    items: list[DivergenceItemOut]


@router.get("/divergences", response_model=DivergencePageOut)
def list_divergences(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> DivergencePageOut:
    rows = session.execute(
        select(AuditLog)
        .where(AuditLog.action == "hr_sync.field_skipped_overridden")
        .order_by(AuditLog.created_at.desc())
    ).scalars().all()
    return DivergencePageOut(items=[
        DivergenceItemOut(
            id=r.id, soldier_hr_profile_id=r.entity_id,
            field_name=(r.context or {}).get("field_name", ""),
            hr_value=(r.context or {}).get("hr_value"),
            local_value=(r.context or {}).get("local_value"),
            created_at=r.created_at,
        ) for r in rows
    ])


class ClearOverrideIn(BaseModel):
    field_name: str


@router.post("/divergences/{profile_id}/clear-override", response_model=HeldForReviewItemOut)
def clear_override_route(
    profile_id: uuid.UUID,
    body: ClearOverrideIn,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HeldForReviewItemOut:
    try:
        profile = clear_field_override(session, profile_id=profile_id, field_name=body.field_name)
    except ReviewActionError as exc:
        session.rollback()
        code = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if code == "profile_not_found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=code) from exc
    session.commit()
    return HeldForReviewItemOut(
        id=profile.id, personal_number=profile.personal_number,
        review_reason=profile.review_reason, last_synced_at=profile.last_synced_at,
    )


class VanishedItemOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    last_synced_at: datetime | None


class VanishedPageOut(BaseModel):
    items: list[VanishedItemOut]


@router.get("/vanished", response_model=VanishedPageOut)
def list_vanished(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> VanishedPageOut:
    rows = session.execute(
        select(SoldierHrProfile)
        .where(SoldierHrProfile.sync_status == "vanished")
        .order_by(SoldierHrProfile.last_synced_at.desc())
    ).scalars().all()
    return VanishedPageOut(items=[
        VanishedItemOut(id=r.id, personal_number=r.personal_number, last_synced_at=r.last_synced_at)
        for r in rows
    ])


class RankConflictItemOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    old_rank: str | None
    new_rank: str | None
    triggered_by_worker_decision: bool
    non_sequential_jump: bool
    created_at: datetime


class RankConflictPageOut(BaseModel):
    items: list[RankConflictItemOut]


@router.get("/rank-conflicts", response_model=RankConflictPageOut)
def list_rank_conflicts(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> RankConflictPageOut:
    rows = session.execute(
        select(HrRankConflict).order_by(HrRankConflict.created_at.desc())
    ).scalars().all()
    return RankConflictPageOut(items=[
        RankConflictItemOut(
            id=r.id, soldier_id=r.soldier_id, old_rank=r.old_rank, new_rank=r.new_rank,
            triggered_by_worker_decision=r.triggered_by_worker_decision,
            non_sequential_jump=r.non_sequential_jump, created_at=r.created_at,
        ) for r in rows
    ])


class SyncErrorOut(BaseModel):
    personal_number: str
    error_message: str


class PersonSyncRunOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    total_fetched: int
    created_count: int
    updated_count: int
    held_count: int
    vanished_count: int
    error_count: int
    error_message: str | None
    errors: list[SyncErrorOut]


class HierarchySyncRunOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    created_count: int
    matched_count: int
    held_count: int
    error_message: str | None


class SyncRunsOut(BaseModel):
    person_syncs: list[PersonSyncRunOut]
    hierarchy_syncs: list[HierarchySyncRunOut]


@router.get("/runs", response_model=SyncRunsOut)
def list_sync_runs(
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> SyncRunsOut:
    person_runs = session.execute(
        select(HrPersonSync).order_by(HrPersonSync.started_at.desc()).limit(limit)
    ).scalars().all()
    hierarchy_runs = session.execute(
        select(HrHierarchySync).order_by(HrHierarchySync.started_at.desc()).limit(limit)
    ).scalars().all()

    person_out = []
    for run in person_runs:
        errors = session.execute(
            select(HrPersonSyncError).where(HrPersonSyncError.hr_person_sync_id == run.id)
        ).scalars().all()
        person_out.append(PersonSyncRunOut(
            id=run.id, status=run.status, started_at=run.started_at, completed_at=run.completed_at,
            total_fetched=run.total_fetched, created_count=run.created_count,
            updated_count=run.updated_count, held_count=run.held_count,
            vanished_count=run.vanished_count, error_count=run.error_count,
            error_message=run.error_message,
            errors=[SyncErrorOut(personal_number=e.personal_number, error_message=e.error_message) for e in errors],
        ))

    hierarchy_out = [
        HierarchySyncRunOut(
            id=run.id, status=run.status, started_at=run.started_at, completed_at=run.completed_at,
            created_count=run.created_count, matched_count=run.matched_count,
            held_count=run.held_count, error_message=run.error_message,
        ) for run in hierarchy_runs
    ]

    return SyncRunsOut(person_syncs=person_out, hierarchy_syncs=hierarchy_out)


class RunNowOut(BaseModel):
    hierarchy_sync_id: uuid.UUID | None
    person_sync_id: uuid.UUID | None


@router.post("/run-now", response_model=RunNowOut)
async def run_sync_now(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> RunNowOut:
    settings = get_settings()
    if not settings.hr_sync_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="hr_sync_not_configured")
    client = HrApiClient(
        settings.hr_api_base_url, settings.hr_api_key,
        ca_bundle_path=settings.hr_api_ca_bundle_path, page_size=settings.hr_api_page_size,
    )
    hierarchy_run = await run_hierarchy_sync(session, client)
    person_run = await run_person_sync(session, client)
    return RunNowOut(hierarchy_sync_id=hierarchy_run.id, person_sync_id=person_run.id)
```

Register in `backend/app/main.py`: add `from app.routes import hr_review as hr_review_routes` alongside the other `from app.routes import X as X_routes` lines (alphabetically, near `hr_onboarding`/`hr_activation`), and `app.include_router(hr_review_routes.router, prefix="/api")` alongside the other `include_router` calls (near `hr_onboarding_routes`/`hr_activation_routes`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_hr_review_routes.py -v`
Expected: all pass. If `client`/`admin_session`/`issue_access_token` usage in the test file needed adjusting to match this project's real fixtures/signatures (per the Step 1 note), make sure those adjustments are reflected here before considering this done.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/hr_review.py backend/app/main.py backend/tests/integration/test_hr_review_routes.py
git commit -m "feat: admin HR sync review routes — held-for-review, divergences, vanished, rank conflicts, run history, manual trigger"
```

---

### Task 8: Frontend API wrapper

**Files:**
- Create: `frontend/src/api/hrReview.ts`
- Test: `frontend/src/api/hrReview.test.ts`

**Interfaces:**
- Consumes: `api` (`./client`, pre-existing axios instance), `requiredObjectResponse`/`optionalArrayResponse` (`./responseGuards`, pre-existing — same pattern as `adminAuditLogs.ts`).
- Produces: `listHeldForReview()`, `dismissHeldForReview(profileId)`, `listDivergences()`, `clearFieldOverride(profileId, fieldName)`, `listVanished()`, `listRankConflicts()`, `listSyncRuns()`, `runSyncNow()` — typed functions matching Task 7's response shapes exactly (field names, nesting).

- [ ] **Step 1: Write the failing test**

Read `frontend/src/api/adminAuditLogs.ts` in full again (already shown above) and `frontend/src/api/responseGuards.ts` before writing this, to match the exact `requiredObjectResponse`/`optionalArrayResponse` call shapes.

Create `frontend/src/api/hrReview.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "./client";
import {
  listHeldForReview,
  listDivergences,
  listVanished,
  listRankConflicts,
  listSyncRuns,
  dismissHeldForReview,
  clearFieldOverride,
  runSyncNow,
} from "./hrReview";

vi.mock("./client", () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));

describe("hrReview api", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
  });

  it("listHeldForReview parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [{ id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null }] },
    });
    const result = await listHeldForReview();
    expect(api.get).toHaveBeenCalledWith("/admin/hr-sync/held-for-review");
    expect(result.items).toHaveLength(1);
    expect(result.items[0].personal_number).toBe("123");
  });

  it("dismissHeldForReview posts to the right path", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null },
    });
    await dismissHeldForReview("1");
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/held-for-review/1/dismiss");
  });

  it("listDivergences parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [{
          id: "1", soldier_hr_profile_id: "2", field_name: "phone",
          hr_value: "050-1", local_value: "050-2", created_at: "2026-01-01T00:00:00Z",
        }],
      },
    });
    const result = await listDivergences();
    expect(result.items[0].field_name).toBe("phone");
  });

  it("clearFieldOverride posts field_name in the body", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "1", personal_number: "123", review_reason: null, last_synced_at: null },
    });
    await clearFieldOverride("1", "phone");
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/divergences/1/clear-override", { field_name: "phone" });
  });

  it("listVanished parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: [{ id: "1", personal_number: "123", last_synced_at: null }] },
    });
    const result = await listVanished();
    expect(result.items).toHaveLength(1);
  });

  it("listRankConflicts parses items", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [{
          id: "1", soldier_id: "2", old_rank: "טוראי", new_rank: "סמל",
          triggered_by_worker_decision: true, non_sequential_jump: false,
          created_at: "2026-01-01T00:00:00Z",
        }],
      },
    });
    const result = await listRankConflicts();
    expect(result.items[0].old_rank).toBe("טוראי");
  });

  it("listSyncRuns parses both run lists", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { person_syncs: [], hierarchy_syncs: [] },
    });
    const result = await listSyncRuns();
    expect(result.person_syncs).toEqual([]);
    expect(result.hierarchy_syncs).toEqual([]);
  });

  it("runSyncNow posts with no body", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { hierarchy_sync_id: "1", person_sync_id: "2" },
    });
    const result = await runSyncNow();
    expect(api.post).toHaveBeenCalledWith("/admin/hr-sync/run-now");
    expect(result.person_sync_id).toBe("2");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- hrReview.test.ts` (from `frontend/`)
Expected: FAIL — `Cannot find module './hrReview'`.

- [ ] **Step 3: Implement**

Create `frontend/src/api/hrReview.ts`:

```typescript
import { api } from "./client";
import { requiredObjectResponse, optionalArrayResponse } from "./responseGuards";

export interface HeldForReviewItemDTO {
  id: string;
  personal_number: string;
  review_reason: string | null;
  last_synced_at: string | null;
}

export async function listHeldForReview(): Promise<{ items: HeldForReviewItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/held-for-review");
  const data = requiredObjectResponse(r.data, "Invalid held-for-review response");
  return { items: optionalArrayResponse<HeldForReviewItemDTO>(data.items) };
}

export async function dismissHeldForReview(profileId: string): Promise<HeldForReviewItemDTO> {
  const r = await api.post<unknown>(`/admin/hr-sync/held-for-review/${profileId}/dismiss`);
  return requiredObjectResponse(r.data, "Invalid dismiss response") as unknown as HeldForReviewItemDTO;
}

export interface DivergenceItemDTO {
  id: string;
  soldier_hr_profile_id: string;
  field_name: string;
  hr_value: unknown;
  local_value: unknown;
  created_at: string;
}

export async function listDivergences(): Promise<{ items: DivergenceItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/divergences");
  const data = requiredObjectResponse(r.data, "Invalid divergences response");
  return { items: optionalArrayResponse<DivergenceItemDTO>(data.items) };
}

export async function clearFieldOverride(
  profileId: string, fieldName: string
): Promise<HeldForReviewItemDTO> {
  const r = await api.post<unknown>(
    `/admin/hr-sync/divergences/${profileId}/clear-override`, { field_name: fieldName }
  );
  return requiredObjectResponse(r.data, "Invalid clear-override response") as unknown as HeldForReviewItemDTO;
}

export interface VanishedItemDTO {
  id: string;
  personal_number: string;
  last_synced_at: string | null;
}

export async function listVanished(): Promise<{ items: VanishedItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/vanished");
  const data = requiredObjectResponse(r.data, "Invalid vanished response");
  return { items: optionalArrayResponse<VanishedItemDTO>(data.items) };
}

export interface RankConflictItemDTO {
  id: string;
  soldier_id: string;
  old_rank: string | null;
  new_rank: string | null;
  triggered_by_worker_decision: boolean;
  non_sequential_jump: boolean;
  created_at: string;
}

export async function listRankConflicts(): Promise<{ items: RankConflictItemDTO[] }> {
  const r = await api.get<unknown>("/admin/hr-sync/rank-conflicts");
  const data = requiredObjectResponse(r.data, "Invalid rank-conflicts response");
  return { items: optionalArrayResponse<RankConflictItemDTO>(data.items) };
}

export interface SyncErrorDTO {
  personal_number: string;
  error_message: string;
}

export interface PersonSyncRunDTO {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  total_fetched: number;
  created_count: number;
  updated_count: number;
  held_count: number;
  vanished_count: number;
  error_count: number;
  error_message: string | null;
  errors: SyncErrorDTO[];
}

export interface HierarchySyncRunDTO {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  created_count: number;
  matched_count: number;
  held_count: number;
  error_message: string | null;
}

export async function listSyncRuns(): Promise<{
  person_syncs: PersonSyncRunDTO[];
  hierarchy_syncs: HierarchySyncRunDTO[];
}> {
  const r = await api.get<unknown>("/admin/hr-sync/runs");
  const data = requiredObjectResponse(r.data, "Invalid sync-runs response");
  return {
    person_syncs: optionalArrayResponse<PersonSyncRunDTO>(data.person_syncs),
    hierarchy_syncs: optionalArrayResponse<HierarchySyncRunDTO>(data.hierarchy_syncs),
  };
}

export interface RunNowResultDTO {
  hierarchy_sync_id: string | null;
  person_sync_id: string | null;
}

export async function runSyncNow(): Promise<RunNowResultDTO> {
  const r = await api.post<unknown>("/admin/hr-sync/run-now");
  return requiredObjectResponse(r.data, "Invalid run-now response") as unknown as RunNowResultDTO;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- hrReview.test.ts` (from `frontend/`)
Expected: all 8 pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/hrReview.ts frontend/src/api/hrReview.test.ts
git commit -m "feat: typed API wrapper for the admin HR sync review endpoints"
```

---

### Task 9: Frontend admin review UI

**Files:**
- Create: `frontend/src/pages/admin/HrSyncReviewContent.tsx`
- Create: `frontend/src/pages/admin/HrSyncReviewContent.test.tsx`
- Modify: `frontend/src/pages/admin/AdminSettingsPage.tsx` (new tab)
- Modify: `frontend/src/pages/admin/AdminSettingsPage.test.tsx` (if it asserts the tab count/labels — read it first; add a case for the new tab if the file's existing structure expects one per tab)
- Modify: `frontend/src/i18n/he.json` and its English counterpart (`frontend/src/i18n/en.json` — confirm the exact filename first: `ls frontend/src/i18n/`)

**Interfaces:**
- Consumes: everything from Task 8's `hrReview.ts`.
- Produces: nothing consumed by a later task (last task before test-coverage closing).

- [ ] **Step 1: Check the exact locale filenames and existing key patterns**

Run: `ls frontend/src/i18n/` to confirm both locale filenames. Run: `grep -n "admin_audit_log\|audit_log\." frontend/src/i18n/he.json` and the English equivalent to see the exact nesting convention used for `AuditLogContent`'s keys (`admin.audit_log.*`, `nav.admin_audit_log`) — mirror this exactly for `admin.hr_sync.*` / `nav.admin_hr_sync`. **Before adding any new key, grep for it first** (e.g. `grep -n '"admin_hr_sync"' frontend/src/i18n/he.json`) to confirm it doesn't already exist under a different value — this project has a standing issue with silently-duplicated i18n keys.

- [ ] **Step 2: Write the failing test**

Read `frontend/src/pages/admin/AuditLogContent.tsx` (already shown above) once more as the structural precedent, and read `frontend/src/components/DataTable.tsx`'s `ColDef` type in full before writing.

Create `frontend/src/pages/admin/HrSyncReviewContent.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import HrSyncReviewContent from "./HrSyncReviewContent";
import * as hrReviewApi from "../../api/hrReview";

vi.mock("../../api/hrReview");

function renderWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <HrSyncReviewContent />
    </QueryClientProvider>
  );
}

describe("HrSyncReviewContent", () => {
  beforeEach(() => {
    vi.mocked(hrReviewApi.listHeldForReview).mockResolvedValue({
      items: [{ id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null }],
    });
    vi.mocked(hrReviewApi.listDivergences).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listVanished).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listRankConflicts).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listSyncRuns).mockResolvedValue({ person_syncs: [], hierarchy_syncs: [] });
    vi.mocked(hrReviewApi.dismissHeldForReview).mockResolvedValue({
      id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null,
    });
  });

  it("shows the held-for-review section with the fetched item", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("123")).toBeInTheDocument());
  });

  it("dismisses a held-for-review item on button click", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("123")).toBeInTheDocument());
    const button = screen.getByTestId("hr-sync-dismiss-1");
    fireEvent.click(button);
    await waitFor(() => expect(hrReviewApi.dismissHeldForReview).toHaveBeenCalledWith("1"));
  });
});
```

(This test's exact matcher choices — `getByTestId`, `getByText` — must match whatever `data-testid`s/rendered text your Step 3 implementation actually uses; treat this as the behavior to build toward, and adjust selectors together with the component if a more precise/stable selector is warranted, same as any other TDD task.)

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- HrSyncReviewContent.test.tsx` (from `frontend/`)
Expected: FAIL — `Cannot find module './HrSyncReviewContent'`.

- [ ] **Step 4: Implement**

Create `frontend/src/pages/admin/HrSyncReviewContent.tsx`. Follow `AuditLogContent.tsx`'s structural conventions (a `DataTable` per section, `useQuery`/`useMutation` from `@tanstack/react-query`, `useTranslation`, Tailwind classes matching the existing admin pages, RTL-aware). Build five sub-sections stacked vertically (held-for-review, divergences, vanished, rank conflicts, sync run history), each its own `DataTable`, plus a "run sync now" button at the top. Structure:

```typescript
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  listHeldForReview, dismissHeldForReview,
  listDivergences, clearFieldOverride,
  listVanished, listRankConflicts, listSyncRuns, runSyncNow,
} from "../../api/hrReview";
import { DataTable, ColDef } from "../../components/DataTable";
import type {
  HeldForReviewItemDTO, DivergenceItemDTO, VanishedItemDTO,
  RankConflictItemDTO, PersonSyncRunDTO,
} from "../../api/hrReview";

export default function HrSyncReviewContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const heldQuery = useQuery({ queryKey: ["hr-sync-held"], queryFn: listHeldForReview });
  const divergencesQuery = useQuery({ queryKey: ["hr-sync-divergences"], queryFn: listDivergences });
  const vanishedQuery = useQuery({ queryKey: ["hr-sync-vanished"], queryFn: listVanished });
  const conflictsQuery = useQuery({ queryKey: ["hr-sync-conflicts"], queryFn: listRankConflicts });
  const runsQuery = useQuery({ queryKey: ["hr-sync-runs"], queryFn: listSyncRuns });

  const dismissMutation = useMutation({
    mutationFn: (profileId: string) => dismissHeldForReview(profileId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["hr-sync-held"] }),
  });
  const clearOverrideMutation = useMutation({
    mutationFn: ({ profileId, fieldName }: { profileId: string; fieldName: string }) =>
      clearFieldOverride(profileId, fieldName),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["hr-sync-divergences"] }),
  });
  const runNowMutation = useMutation({
    mutationFn: runSyncNow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-held"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-divergences"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-vanished"] });
      void queryClient.invalidateQueries({ queryKey: ["hr-sync-conflicts"] });
    },
  });

  const heldColumns: ColDef<HeldForReviewItemDTO>[] = [
    { id: "personal_number", header: t("admin.hr_sync.personal_number"), cell: (r) => r.personal_number },
    { id: "review_reason", header: t("admin.hr_sync.reason"), cell: (r) => r.review_reason ?? "—" },
    {
      id: "actions", header: "", cell: (r) => (
        <button
          type="button"
          data-testid={`hr-sync-dismiss-${r.id}`}
          className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600"
          onClick={() => dismissMutation.mutate(r.id)}
        >
          {t("admin.hr_sync.dismiss")}
        </button>
      ),
    },
  ];

  const divergenceColumns: ColDef<DivergenceItemDTO>[] = [
    { id: "field_name", header: t("admin.hr_sync.field"), cell: (r) => r.field_name },
    { id: "hr_value", header: t("admin.hr_sync.hr_value"), cell: (r) => String(r.hr_value ?? "—") },
    { id: "local_value", header: t("admin.hr_sync.local_value"), cell: (r) => String(r.local_value ?? "—") },
    {
      id: "actions", header: "", cell: (r) => (
        <button
          type="button"
          data-testid={`hr-sync-clear-override-${r.id}`}
          className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600"
          onClick={() => clearOverrideMutation.mutate({ profileId: r.soldier_hr_profile_id, fieldName: r.field_name })}
        >
          {t("admin.hr_sync.clear_override")}
        </button>
      ),
    },
  ];

  const vanishedColumns: ColDef<VanishedItemDTO>[] = [
    { id: "personal_number", header: t("admin.hr_sync.personal_number"), cell: (r) => r.personal_number },
  ];

  const conflictColumns: ColDef<RankConflictItemDTO>[] = [
    { id: "old_rank", header: t("admin.hr_sync.old_rank"), cell: (r) => r.old_rank ?? "—" },
    { id: "new_rank", header: t("admin.hr_sync.new_rank"), cell: (r) => r.new_rank ?? "—" },
    {
      id: "why", header: t("admin.hr_sync.why"),
      cell: (r) => (r.triggered_by_worker_decision ? t("admin.hr_sync.why_worker") : t("admin.hr_sync.why_jump")),
    },
  ];

  const runColumns: ColDef<PersonSyncRunDTO>[] = [
    { id: "status", header: t("admin.hr_sync.status"), cell: (r) => r.status },
    { id: "total_fetched", header: t("admin.hr_sync.total_fetched"), cell: (r) => r.total_fetched },
    { id: "created_count", header: t("admin.hr_sync.created_count"), cell: (r) => r.created_count },
    { id: "updated_count", header: t("admin.hr_sync.updated_count"), cell: (r) => r.updated_count },
    { id: "held_count", header: t("admin.hr_sync.held_count"), cell: (r) => r.held_count },
  ];

  return (
    <div className="space-y-6" data-testid="hr-sync-review-content">
      <div className="flex justify-end">
        <button
          type="button"
          data-testid="hr-sync-run-now"
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white disabled:opacity-50"
          disabled={runNowMutation.isPending}
          onClick={() => runNowMutation.mutate()}
        >
          {t("admin.hr_sync.run_now")}
        </button>
      </div>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.held_for_review")}</h3>
        <DataTable
          columns={heldColumns}
          data={heldQuery.data?.items ?? []}
          testId="hr-sync-held-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.divergences")}</h3>
        <DataTable
          columns={divergenceColumns}
          data={divergencesQuery.data?.items ?? []}
          testId="hr-sync-divergences-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.vanished")}</h3>
        <DataTable
          columns={vanishedColumns}
          data={vanishedQuery.data?.items ?? []}
          testId="hr-sync-vanished-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.rank_conflicts")}</h3>
        <DataTable
          columns={conflictColumns}
          data={conflictsQuery.data?.items ?? []}
          testId="hr-sync-conflicts-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2">{t("admin.hr_sync.run_history")}</h3>
        <DataTable
          columns={runColumns}
          data={runsQuery.data?.person_syncs ?? []}
          testId="hr-sync-runs-table"
          emptyMessage={t("admin.hr_sync.empty")}
        />
      </section>
    </div>
  );
}
```

Add the i18n keys under a new `admin.hr_sync` block in both `frontend/src/i18n/he.json` and its English counterpart, plus `nav.admin_hr_sync`, matching whatever nesting style `admin.audit_log.*` already uses in those files (read the surrounding JSON structure before inserting — match indentation/ordering conventions, and confirm via `grep` first that none of these keys already exist).

Modify `frontend/src/pages/admin/AdminSettingsPage.tsx`:

```typescript
import { HrSyncReviewContent } from "./HrSyncReviewContent";
```

Wait — `HrSyncReviewContent.tsx` above uses `export default`, matching `AuditLogContent.tsx`'s own `export default function AuditLogContent()` — so the import must be a default import, not a named one:

```typescript
import HrSyncReviewContent from "./HrSyncReviewContent";
```

Update `ADMIN_SETTINGS_TAB_ORDER`, the `raw >= 0 && raw <= 5` bound, the `tabs` array, the `badges` array, and the `activeTab === N` blocks:

```typescript
export const ADMIN_SETTINGS_TAB_ORDER = ["settings", "invite-codes", "changelog", "bug-reports", "errors", "audit-log", "hr-sync"] as const;
```

```typescript
  const activeTab = raw >= 0 && raw <= 6 ? raw : 0;
```

```typescript
  const tabs = [
    t("nav.admin_settings"),
    t("nav.admin_invite_codes"),
    t("nav.admin_changelog"),
    t("nav.admin_bug_reports"),
    t("nav.admin_errors", { defaultValue: "שגיאות" }),
    t("nav.admin_audit_log"),
    t("nav.admin_hr_sync"),
  ];
```

```typescript
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} badges={[null, null, null, bugUnread.data ?? null, errorUnread.data ?? null, null, null]} />
      {activeTab === 0 && <SystemSettingsContent />}
      {activeTab === 1 && <AdminInviteCodesContent />}
      {activeTab === 2 && <ChangelogContent />}
      {activeTab === 3 && <BugReportsContent />}
      {activeTab === 4 && <ErrorsContent />}
      {activeTab === 5 && <AuditLogContent />}
      {activeTab === 6 && <HrSyncReviewContent />}
```

Read `frontend/src/pages/admin/AdminSettingsPage.test.tsx` before finishing this step — if it has an assertion like "renders N tabs" or enumerates `ADMIN_SETTINGS_TAB_ORDER`'s length, update it to account for the 7th tab; if it has per-tab render tests following a repeated pattern (one test per existing tab), add one more following that exact pattern for `activeTab === 6`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- HrSyncReviewContent.test.tsx AdminSettingsPage.test.tsx` (from `frontend/`)
Expected: all pass.

Run: `npm run typecheck` (from `frontend/`)
Expected: no errors.

Run: `npm run lint` (from `frontend/`)
Expected: zero warnings (this project enforces `--max-warnings 0`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/admin/HrSyncReviewContent.tsx frontend/src/pages/admin/HrSyncReviewContent.test.tsx frontend/src/pages/admin/AdminSettingsPage.tsx frontend/src/pages/admin/AdminSettingsPage.test.tsx frontend/src/i18n/he.json frontend/src/i18n/en.json
git commit -m "feat: admin HR sync review UI tab"
```

(adjust the `en.json` filename in the `git add` line if Step 1 found a different actual filename.)

---

### Task 10: Coverage check and pytest marker registration

**Files:**
- Modify: `backend/tests/conftest.py` (`_AREA_MARKERS`)
- Modify (possibly): test files touched in Tasks 1-7, only if coverage gaps are found

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed elsewhere — this is the plan's closing task, matching the pattern used at the end of the activation-codes plan (subsystem 5's Task 7).

- [ ] **Step 1: Read `_AREA_MARKERS` and confirm routing for every new test stem**

Read `backend/tests/conftest.py`'s `_AREA_MARKERS` dict in full. Confirm whether these stems already have entries (they won't): `test_hr_rank_conflict_model`, `test_hr_sync_worker`, `test_hr_review_routes`, `test_review` (under `app/services/hr/tests/`, may use a different registration mechanism than `_AREA_MARKERS` if that directory's tests aren't stem-routed the same way as `backend/tests/` — check how the existing `app/services/hr/tests/test_mapping.py`/`test_hierarchy_sync_topo.py` are routed, e.g. via a marker on the whole `app/services/hr/tests` package or `pyproject.toml`'s test path config, and follow that same mechanism rather than assuming `_AREA_MARKERS` applies).

`test_hr_person_sync` and `test_rank_advancement_worker` already have entries (confirm their existing mapped areas — likely `"soldiers"` and an area covering rank advancement respectively — Tasks 2-4 add tests to these existing files, not new files, so no new marker entries are needed for them).

- [ ] **Step 2: Add missing marker entries**

For any of `test_hr_rank_conflict_model`, `test_hr_sync_worker`, `test_hr_review_routes` not already present, add each to whichever `_AREA_MARKERS` area block best matches (likely `"hierarchy"` for anything sync-run/HR-hierarchy-adjacent, matching `test_hr_hierarchy_sync`'s existing area — or a new/existing area for admin-facing review routes; use your judgment based on the dict's existing organization, matching the reasoning style of `test_hr_activation_service`/`test_hr_onboarding_service`'s placement in subsystem 5's equivalent task).

- [ ] **Step 3: Run the full fast backend suite with coverage**

Run (from `backend/`, with `DATABASE_URL`/`DB_ADMIN_URL` pointed at the local Postgres container):

```bash
pytest tests app/services/hr/tests --cov=app.services.hr.review --cov=app.services.hr.person_sync --cov=app.hr_sync_worker --cov=app.rank_advancement_worker --cov=app.routes.hr_review --cov-report=term-missing -q
```

Expected: real pasted output showing each module's coverage percentage and missing line numbers.

- [ ] **Step 4: Close any coverage gaps with targeted tests**

For any module below 100% on a reachable branch (not an unreachable defensive branch), add targeted tests the same way subsystem 5's Task 7 did — append-only, no restructuring of existing tests, one test per missing branch, in the same file the branch's other tests already live in.

- [ ] **Step 5: Run the full fast backend suite**

Run: `pytest -q --junitxml=/tmp/hr_admin_review_full.xml` (or wherever this environment's scratch path is) from `backend/`.
Expected: 0 failures, 0 errors. Paste the real `<testsuite ...>` summary line from the XML (the plain stdout summary line has been unreliable in this environment before — use the XML as the source of truth, per this project's established practice).

- [ ] **Step 6: Run the frontend suite**

Run: `npm test -- --run` and `npm run typecheck` and `npm run lint` (all from `frontend/`).
Expected: all green, zero lint warnings.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: route new HR admin review tests to pytest markers, close coverage gaps"
```

(add any additional test files touched in Step 4 to this commit too.)

---

## Self-Review Notes

- **Spec coverage:** Section A (cron) → Task 5. Section B (rank conflict reconciliation) → Tasks 2-3. Section C.1/C.2 (held-for-review, divergences + actions) → Tasks 6-7, 9. Section C.3 (dismissal persistence) → Task 4. Section C.4/C.5 (vanished, rank conflicts, read-only) → Tasks 7, 9. Section C.6 (sync run history + manual trigger) → Tasks 7, 9. Section D (data model) → Task 1. All spec sections have a task.
- **Placeholder scan:** no TBD/TODO; every step has real code. The two spots where a step corrects itself mid-task (Task 5's `_run_hr_sync_cycle_in_own_session`, Task 6's `actor_id` threading note) are deliberate — they show the implementer the reasoning behind the final form rather than asserting it silently, which is preferable to a plan that hides a wrong first draft.
- **Type consistency:** `HrRankConflict`, `ReviewActionError`, `dismiss_held_for_review`, `clear_field_override` signatures match exactly between the task that defines them (1, 6) and the tasks that consume them (3, 7). Route response field names (`personal_number`, `review_reason`, `field_name`, `hr_value`/`local_value`, `old_rank`/`new_rank`, `triggered_by_worker_decision`/`non_sequential_jump`) match 1:1 between Task 7's Pydantic models and Task 8's TypeScript interfaces.
