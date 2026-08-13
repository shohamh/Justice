# Rank Advancement & Future-Eligibility Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soldiers automatically advance rank on a configured future date (with notification to the soldier and their commander), and duty-assignment eligibility — both manual validation and the CP-SAT solver — accounts for a soldier's *projected* state (rank, career track, mitvahim/alal recency, driving-license expiry, exemptions, departure) as of each duty's own date, not just today.

**Architecture:** A new `RankAdvancementInterval` config table drives a daily background worker (mirroring the existing `duty_eligibility_worker.py` pattern) that promotes soldiers and auto-chains their next promotion date. A new projection module (`rank_eligibility_projection.py`, mirroring the existing `range_eligibility_projection.py`/`weapon_eligibility.py` "as-of" pattern) computes a soldier's projected rank/career/departure state as of any future date, and feeds `check_soldier_for_assignment` (manual path, via a new `rank_override` parameter on `_is_eligible`) and a new `SoldierInput.future_ineligible_duty_block_ids` field (solver path, mirroring the existing `weapon_ineligible_duty_block_ids` field exactly) that also folds in per-block-date exemption checking — generalizing the fix beyond rank to every eligibility factor that can change value within a single solve's planning window.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic backend, React/TypeScript frontend, pytest with Testcontainers Postgres, OR-Tools CP-SAT solver.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-13-rank-advancement-design.md` — read it before starting; this plan implements it section by section.
- No auto-advancement crosses from the enlisted ladder to the officer ladder — chaining only moves within the soldier's current track's ladder (per spec "Out of scope").
- No new "קבע entry date" field — career-track status stays derived from `mandatory_end_date` via `derive_is_career`, evaluated as-of a future date instead of today.
- Manual-path exemption/personal-constraint checks in `check_soldier_for_assignment` and solver-side personal-constraint checking (`solver.py:305-317`) are already correct against a specific date and must not be touched. Only the CP-SAT solver's exemption-to-duty-type/location mapping (`algorithm_bridge.py` lines ~205-217, evaluated once at solve-start) is in scope — it becomes per-duty-block-date in Task 7.
- Follow existing repo conventions exactly where a precedent exists (daily worker loop shape, `NotificationType` + `_FRONTEND_PATHS` pattern, `weapon_ineligible_duty_block_ids` pattern for solver-side date-sensitive exclusion, `SystemSetting`/`SettingDef` pattern for admin config).
- Test markers: use `-m soldiers` or `-m duty` per `backend/pyproject.toml` (see CLAUDE.md). Run only the tests relevant to each task; do not run the full suite until told to.

---

## File Structure

**New files:**
- `backend/alembic/versions/<rev>_add_rank_advancement.py` — migration
- `backend/app/services/rank_advancement.py` — ladder lookup, interval CRUD, promotion/chaining math, config-change recompute
- `backend/app/services/rank_eligibility_projection.py` — as-of-a-date rank/career/departure projection + `bulk_future_ineligible_duty_blocks` (rank + recency + license + exemptions, per duty-block date)
- `backend/app/rank_advancement_worker.py` — daily promote + warn worker
- `backend/app/routes/rank_advancement.py` — `GET /soldiers/rank-ladder`, `PUT /soldiers/rank-advancement-intervals`
- `backend/app/services/tests/test_rank_advancement.py`
- `backend/app/services/tests/test_rank_eligibility_projection.py`
- `backend/app/tests/test_rank_advancement_worker.py` (mirrors `test_duty_eligibility_worker.py`'s location)
- `backend/app/routes/tests/test_rank_advancement_routes.py`
- `frontend/src/api/rankAdvancement.ts`
- `frontend/src/pages/settings/RankAdvancementSettings.tsx` (or a new section within `SystemSettingsPage.tsx` — decided in Task 12)

**Modified files:**
- `backend/app/db/models.py` — `Soldier.next_rank_date_overridden`, `Soldier.current_rank_since`, `RankAdvancementInterval` model, two new `NotificationType` members
- `backend/app/services/eligibility.py` — `check_soldier_for_assignment` uses assignment date instead of `date.today()`
- `backend/app/services/potential.py` — `_rank_as_of` delegates to the new chained projection instead of its own single-step logic
- `backend/app/algorithm/types.py` — new `SoldierInput.future_ineligible_duty_block_ids` field
- `backend/app/algorithm/solver.py` — two new checks (mirroring the two existing `weapon_ineligible_duty_block_ids` checks)
- `backend/app/algorithm/model.py` — one new check (mirroring the existing `weapon_ineligible_duty_block_ids` check)
- `backend/app/services/algorithm_bridge.py` — populate the new field alongside the existing weapon-eligibility population
- `backend/app/services/notifications.py` — two new notification-sending helpers + `_FRONTEND_PATHS` entries
- `backend/app/services/soldiers.py` — `PROFILE_FIELDS` gains `next_rank_date`; `update_soldier_profile` sets `next_rank_date_overridden`/`current_rank_since`
- `backend/app/main.py` — register the new worker
- `frontend/src/constants/ranks.ts` — fetch ladder from API instead of hardcoding

---

### Task 1: Migration — new columns, new table, new notification types

**Files:**
- Create: `backend/alembic/versions/<rev>_add_rank_advancement.py`
- Modify: `backend/app/db/models.py`

**Interfaces:**
- Produces: `Soldier.next_rank_date_overridden: bool`, `Soldier.current_rank_since: date | None`, `RankAdvancementInterval` ORM model (`id: int`, `track: str`, `rank: str`, `months_to_next: int | None`), `NotificationType.rank_advanced`, `NotificationType.rank_advancement_soon`.

- [ ] **Step 1: Add the two `Soldier` columns and the new table to `models.py`**

In the `Soldier` class in `backend/app/db/models.py`, immediately after the existing `next_rank_date` column (line 57):

```python
    next_rank_date_overridden: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    current_rank_since: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
```

Near the other small lookup/config models in `models.py` (place alongside `PotentialModifier` or similar), add:

```python
class RankAdvancementInterval(Base):
    __tablename__ = "rank_advancement_intervals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[str] = mapped_column(Text, nullable=False)
    months_to_next: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("track", "rank", name="uq_rank_advancement_interval_track_rank"),
    )
```

In the `NotificationType` enum (`models.py:1187-1234`), add two members at the end, following the existing snake_case value convention:

```python
    rank_advanced = "rank_advanced"
    rank_advancement_soon = "rank_advancement_soon"
```

- [ ] **Step 2: Generate and fill in the migration**

Run (from `backend/`, with the venv active):

```bash
alembic revision -m "add rank advancement"
```

Edit the generated file in `backend/alembic/versions/` to:

```python
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "554960f40583"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "soldiers",
        sa.Column("next_rank_date_overridden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("soldiers", sa.Column("current_rank_since", sa.Date(), nullable=True))
    op.create_table(
        "rank_advancement_intervals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("track", sa.Text(), nullable=False),
        sa.Column("rank", sa.Text(), nullable=False),
        sa.Column("months_to_next", sa.Integer(), nullable=True),
        sa.UniqueConstraint("track", "rank", name="uq_rank_advancement_interval_track_rank"),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'rank_advanced'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'rank_advancement_soon'")


def downgrade() -> None:
    op.drop_table("rank_advancement_intervals")
    op.drop_column("soldiers", "current_rank_since")
    op.drop_column("soldiers", "next_rank_date_overridden")
    # Postgres cannot drop enum values; matches the existing repo convention
    # (see a3f1c9d7e2b4_add_range_covers_duty_info_type.py) of not reversing
    # ALTER TYPE ... ADD VALUE in downgrade.
```

Replace `down_revision` with whatever the actual current head is if it has moved since this plan was written (`alembic heads` to check).

- [ ] **Step 3: Apply and verify**

```bash
alembic upgrade head
```

Expected: no errors. Then confirm columns exist:

```bash
psql "$DATABASE_URL" -c "\d soldiers" | grep -E "next_rank_date_overridden|current_rank_since"
psql "$DATABASE_URL" -c "\d rank_advancement_intervals"
```

(Use whatever local psql/connection approach `dev.ps1`'s Docker Postgres setup provides — adjust the connection string to match your local `.env`.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat: add rank advancement schema (interval table, override tracking, notification types)"
```

---

### Task 2: Rank ladder + interval lookup service

**Files:**
- Create: `backend/app/services/rank_advancement.py`
- Test: `backend/app/services/tests/test_rank_advancement.py`

**Interfaces:**
- Consumes: `Soldier` model, `RankAdvancementInterval` model, `ENLISTED_RANKS`/`OFFICER_RANKS` from `backend/app/services/eligibility.py`.
- Produces (used by later tasks):
  - `get_track(rank: str) -> Literal["enlisted", "officer"] | None`
  - `get_next_rank(rank: str) -> str | None`
  - `get_interval_months(session: Session, *, track: str, rank: str) -> int | None`
  - `compute_next_rank_date(session: Session, *, rank: str, since: date) -> date | None`
  - `upsert_interval(session: Session, *, track: str, rank: str, months_to_next: int | None, actor_id: uuid.UUID | None) -> RankAdvancementInterval`
  - `get_rank_ladder(session: Session) -> dict[str, list[dict]]`

- [ ] **Step 1: Write failing tests for ladder/track lookup**

```python
# backend/app/services/tests/test_rank_advancement.py
from app.services.rank_advancement import get_track, get_next_rank


def test_get_track_enlisted():
    assert get_track("טוראי") == "enlisted"


def test_get_track_officer():
    assert get_track("קמא") == "officer"


def test_get_track_unknown_rank_returns_none():
    assert get_track("not_a_rank") is None


def test_get_next_rank_mid_ladder():
    assert get_next_rank("טוראי") == "רבט"


def test_get_next_rank_top_of_enlisted_ladder_returns_none():
    assert get_next_rank("רנג") is None


def test_get_next_rank_top_of_officer_ladder_returns_none():
    assert get_next_rank("רב אלוף") is None


def test_get_next_rank_never_crosses_enlisted_to_officer():
    # top enlisted rank has no "next" even though the officer ladder starts
    # right after it conceptually -- crossing is never automatic.
    assert get_next_rank("רנג") is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_rank_advancement.py -v
```
Expected: FAIL (`ModuleNotFoundError` / `ImportError`, module doesn't exist yet).

- [ ] **Step 3: Implement ladder/track helpers**

```python
# backend/app/services/rank_advancement.py
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import RankAdvancementInterval, Soldier
from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS

Track = Literal["enlisted", "officer"]

_LADDERS: dict[Track, list[str]] = {"enlisted": ENLISTED_RANKS, "officer": OFFICER_RANKS}


def get_track(rank: str) -> Track | None:
    for track, ladder in _LADDERS.items():
        if rank in ladder:
            return track
    return None


def get_next_rank(rank: str) -> str | None:
    track = get_track(rank)
    if track is None:
        return None
    ladder = _LADDERS[track]
    idx = ladder.index(rank)
    if idx + 1 >= len(ladder):
        return None
    return ladder[idx + 1]
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_rank_advancement.py -v
```
Expected: PASS (4 tests currently defined pass; the module is otherwise incomplete, that's fine for this step).

- [ ] **Step 5: Write failing tests for interval lookup + next-date computation**

Append to the same test file:

```python
from app.services.rank_advancement import get_interval_months, compute_next_rank_date, upsert_interval
from app.db.models import RankAdvancementInterval


def test_get_interval_months_returns_configured_value(app_session):
    app_session.add(RankAdvancementInterval(track="enlisted", rank="טוראי", months_to_next=4))
    app_session.flush()
    assert get_interval_months(app_session, track="enlisted", rank="טוראי") == 4


def test_get_interval_months_returns_none_when_unconfigured(app_session):
    assert get_interval_months(app_session, track="enlisted", rank="טוראי") is None


def test_compute_next_rank_date_adds_months(app_session):
    app_session.add(RankAdvancementInterval(track="enlisted", rank="טוראי", months_to_next=4))
    app_session.flush()
    result = compute_next_rank_date(app_session, rank="טוראי", since=date(2026, 1, 1))
    assert result == date(2026, 5, 1)


def test_compute_next_rank_date_none_when_unconfigured(app_session):
    result = compute_next_rank_date(app_session, rank="טוראי", since=date(2026, 1, 1))
    assert result is None


def test_upsert_interval_creates_row(app_session):
    row = upsert_interval(app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None)
    assert row.months_to_next == 4
    app_session.flush()
    fetched = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "טוראי")
    ).scalar_one()
    assert fetched.months_to_next == 4


def test_upsert_interval_updates_existing_row(app_session):
    upsert_interval(app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None)
    app_session.flush()
    upsert_interval(app_session, track="enlisted", rank="טוראי", months_to_next=6, actor_id=None)
    app_session.flush()
    rows = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "טוראי")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].months_to_next == 6
```

(`app_session` is the existing function-scoped DB-backed fixture from `backend/tests/conftest.py`, same one used by `test_eligibility.py`'s DB-backed cases.)

- [ ] **Step 6: Run to verify failure**

```bash
pytest backend/app/services/tests/test_rank_advancement.py -v
```
Expected: FAIL (`ImportError: cannot import name 'get_interval_months'`, etc.)

- [ ] **Step 7: Implement interval lookup, next-date computation, upsert**

Append to `backend/app/services/rank_advancement.py`:

```python
def get_interval_months(session: Session, *, track: str, rank: str) -> int | None:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    return row.months_to_next if row is not None else None


def compute_next_rank_date(session: Session, *, rank: str, since: date) -> date | None:
    track = get_track(rank)
    if track is None:
        return None
    months = get_interval_months(session, track=track, rank=rank)
    if months is None:
        return None
    return since + relativedelta(months=months)


def upsert_interval(
    session: Session, *, track: str, rank: str, months_to_next: int | None, actor_id: uuid.UUID | None
) -> RankAdvancementInterval:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    before = None if row is None else row.months_to_next
    if row is None:
        row = RankAdvancementInterval(track=track, rank=rank, months_to_next=months_to_next)
        session.add(row)
    else:
        row.months_to_next = months_to_next
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="rank_advancement_interval.upsert",
        entity_type="rank_advancement_interval",
        entity_id=row.id,
        before={"months_to_next": before},
        after={"months_to_next": months_to_next},
    )
    return row
```

Confirm `dateutil` (`python-dateutil`) is already a dependency — check `backend/pyproject.toml`; if absent, add it under `[project.dependencies]` and run `pip install -e ".[dev]"` from `backend/`.

- [ ] **Step 8: Run to verify pass**

```bash
pytest backend/app/services/tests/test_rank_advancement.py -v
```
Expected: PASS, all tests.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/rank_advancement.py backend/app/services/tests/test_rank_advancement.py backend/pyproject.toml
git commit -m "feat: add rank ladder and interval lookup service"
```

---

### Task 3: Config-change recompute + rank ladder read model

**Files:**
- Modify: `backend/app/services/rank_advancement.py`
- Test: `backend/app/services/tests/test_rank_advancement.py`

**Interfaces:**
- Consumes: `upsert_interval` (Task 2), `_LADDERS`/`get_track` (Task 2).
- Produces:
  - `recompute_affected_soldiers(session: Session, *, track: str, rank: str) -> int` (returns count updated)
  - `set_interval_and_recompute(session: Session, *, track: str, rank: str, months_to_next: int | None, actor_id: uuid.UUID | None) -> int`
  - `get_rank_ladder(session: Session) -> dict[str, list[dict]]`

- [ ] **Step 1: Write failing tests**

Append to `test_rank_advancement.py`:

```python
from tests.helpers import create_soldier  # existing DB-soldier-creation test helper
from app.services.rank_advancement import set_interval_and_recompute, get_rank_ladder


def test_set_interval_and_recompute_updates_non_overridden_soldiers(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.current_rank_since = date(2026, 1, 1)
    s.next_rank_date_overridden = False
    app_session.flush()

    count = set_interval_and_recompute(
        app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None
    )

    assert count == 1
    assert s.next_rank_date == date(2026, 5, 1)


def test_set_interval_and_recompute_skips_overridden_soldiers(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.current_rank_since = date(2026, 1, 1)
    s.next_rank_date = date(2099, 1, 1)
    s.next_rank_date_overridden = True
    app_session.flush()

    set_interval_and_recompute(app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None)

    assert s.next_rank_date == date(2099, 1, 1)


def test_set_interval_and_recompute_ignores_other_ranks(app_session):
    s = create_soldier(app_session, rank="רבט")
    s.current_rank_since = date(2026, 1, 1)
    s.next_rank_date = None
    s.next_rank_date_overridden = False
    app_session.flush()

    set_interval_and_recompute(app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None)

    assert s.next_rank_date is None


def test_get_rank_ladder_shape(app_session):
    upsert_interval(app_session, track="enlisted", rank="טוראי", months_to_next=4, actor_id=None)
    ladder = get_rank_ladder(app_session)
    assert ladder["enlisted"][0] == {"rank": "טוראי", "months_to_next": 4}
    assert ladder["enlisted"][-1]["months_to_next"] is None
    assert ladder["officer"][0]["rank"] == "קמא"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_rank_advancement.py -k "recompute or ladder_shape" -v
```
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement**

Append to `backend/app/services/rank_advancement.py`:

```python
def recompute_affected_soldiers(session: Session, *, track: str, rank: str) -> int:
    soldiers = session.execute(
        select(Soldier).where(Soldier.rank == rank, Soldier.next_rank_date_overridden.is_(False))
    ).scalars().all()
    updated = 0
    for s in soldiers:
        since = s.current_rank_since or s.enlistment_date
        if since is None:
            continue
        s.next_rank_date = compute_next_rank_date(session, rank=rank, since=since)
        updated += 1
    return updated


def set_interval_and_recompute(
    session: Session, *, track: str, rank: str, months_to_next: int | None, actor_id: uuid.UUID | None
) -> int:
    upsert_interval(session, track=track, rank=rank, months_to_next=months_to_next, actor_id=actor_id)
    return recompute_affected_soldiers(session, track=track, rank=rank)


def get_rank_ladder(session: Session) -> dict[str, list[dict]]:
    rows = session.execute(select(RankAdvancementInterval)).scalars().all()
    months_by = {(r.track, r.rank): r.months_to_next for r in rows}
    return {
        track: [{"rank": rank, "months_to_next": months_by.get((track, rank))} for rank in ladder]
        for track, ladder in _LADDERS.items()
    }
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_rank_advancement.py -v
```
Expected: PASS, all tests (full file, ~13 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rank_advancement.py backend/app/services/tests/test_rank_advancement.py
git commit -m "feat: recompute non-overridden soldiers when rank interval config changes"
```

---

### Task 4: Rank/career/departure projection ("as of a future date")

**Files:**
- Create: `backend/app/services/rank_eligibility_projection.py`
- Test: `backend/app/services/tests/test_rank_eligibility_projection.py`

**Interfaces:**
- Consumes: `get_track`, `get_next_rank`, `get_interval_months` (Task 2), `derive_is_career` (`eligibility.py`).
- Produces:
  - `@dataclass ProjectedSoldierState: rank: str | None; is_career: bool; departed: bool`
  - `project_soldier_state(session: Session, *, soldier: Soldier, as_of: date) -> ProjectedSoldierState`

- [ ] **Step 1: Write failing tests**

```python
# backend/app/services/tests/test_rank_eligibility_projection.py
from datetime import date

from app.services.rank_advancement import upsert_interval
from app.services.rank_eligibility_projection import project_soldier_state
from tests.helpers import create_soldier


def test_project_no_advancement_before_next_rank_date(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.next_rank_date = date(2026, 6, 1)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 3, 1))
    assert state.rank == "טוראי"


def test_project_single_advancement_reached(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.next_rank_date = date(2026, 3, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, actor_id=None)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 1))
    assert state.rank == "רבט"


def test_project_chained_advancement_across_multiple_steps(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=1, actor_id=None)
    upsert_interval(app_session, track="enlisted", rank="סמל", months_to_next=1, actor_id=None)
    app_session.flush()
    # Jan 1 -> רבט, +1mo (Feb 1) -> סמל, +1mo (Mar 1) -> next -- projecting to Apr 1
    # should have walked two full steps past רבט.
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 4, 1))
    assert state.rank == "סמל"


def test_project_never_crosses_track():
    pass  # covered structurally: get_next_rank never returns a cross-track rank (Task 2)


def test_project_career_track_as_of_future_date(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.mandatory_end_date = date(2026, 6, 1)
    s.discharge_date = None
    app_session.flush()
    before = project_soldier_state(app_session, soldier=s, as_of=date(2026, 1, 1))
    after = project_soldier_state(app_session, soldier=s, as_of=date(2026, 12, 1))
    assert before.is_career is False
    assert after.is_career is True


def test_project_departed_if_left_before_as_of(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.discharge_date = date(2026, 5, 1)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 1))
    assert state.departed is True


def test_project_not_departed_if_as_of_before_discharge(app_session):
    s = create_soldier(app_session, rank="טוראי")
    s.discharge_date = date(2026, 5, 1)
    app_session.flush()
    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 4, 1))
    assert state.departed is False
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_rank_eligibility_projection.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

```python
# backend/app/services/rank_eligibility_projection.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.db.models import Soldier
from app.services.eligibility import derive_is_career
from app.services.rank_advancement import compute_next_rank_date, get_next_rank


@dataclass(frozen=True)
class ProjectedSoldierState:
    rank: str | None
    is_career: bool
    departed: bool


_MAX_CHAIN_STEPS = 24  # safety bound; a soldier cannot realistically advance
                        # more than a couple of ranks within any real duty
                        # planning horizon, this just prevents a runaway loop
                        # on misconfigured (e.g. zero-month) intervals.


def project_soldier_state(session: Session, *, soldier: Soldier, as_of: date) -> ProjectedSoldierState:
    rank = soldier.rank
    next_date = soldier.next_rank_date
    for _ in range(_MAX_CHAIN_STEPS):
        if rank is None or next_date is None or next_date > as_of:
            break
        next_rank = get_next_rank(rank)
        if next_rank is None:
            break
        rank = next_rank
        next_date = compute_next_rank_date(session, rank=rank, since=next_date)

    is_career = derive_is_career(rank, soldier.mandatory_end_date, soldier.discharge_date, today=as_of)

    departed = False
    if soldier.discharge_date is not None and soldier.discharge_date <= as_of:
        departed = True
    if soldier.left_at is not None and soldier.left_at <= as_of:
        departed = True

    return ProjectedSoldierState(rank=rank, is_career=is_career, departed=departed)
```

`derive_is_career` (`eligibility.py:95-111`) already accepts an optional
`today: date | None = None` reference-date parameter (defaulting to
`date.today()` internally) — no signature change needed. Just pass
`today=as_of` as shown above.

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_rank_eligibility_projection.py -v
pytest backend/app/services/tests/test_eligibility.py -v
```
Expected: PASS. The second command guards against having broken any
existing `derive_is_career` caller (there should be none, since this task
doesn't change its signature).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rank_eligibility_projection.py backend/app/services/tests/test_rank_eligibility_projection.py backend/app/services/eligibility.py
git commit -m "feat: add as-of-a-future-date rank/career/departure projection"
```

---

### Task 5: Refactor `potential.py::_rank_as_of` to use the chained projection

**Files:**
- Modify: `backend/app/services/potential.py`
- Test: `backend/app/services/tests/test_potential.py`

**Interfaces:**
- Consumes: `project_soldier_state` (Task 4).

**Context:** `_rank_as_of` (`potential.py:74-87`) currently only applies a single `next_rank_date` rollover, silently under-projecting when a soldier would cross two or more rank steps by `reference_date`. `test_soldier_detail_rank_reflects_next_rank_date_rollover` (`test_potential.py:95`) already exercises the single-step case and must keep passing.

- [ ] **Step 1: Write a failing test for the multi-step case**

Add to `backend/app/services/tests/test_potential.py` near the existing rollover test:

```python
def test_soldier_detail_rank_reflects_chained_rollover(app_session):
    from app.services.rank_advancement import upsert_interval
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=1, actor_id=None)
    app_session.flush()

    # reference_date is 3 months past the first rollover -- should have
    # chained one further step (רבט -> סמל) too, not stopped at רבט.
    result = _rank_as_of(s, date(2026, 4, 1))
    assert result == "סמל"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_potential.py -k chained_rollover -v
```
Expected: FAIL (`AssertionError`, current code returns `"רבט"`).

- [ ] **Step 3: Replace `_rank_as_of`'s body**

In `backend/app/services/potential.py`, replace lines 74-87:

```python
def _rank_as_of(soldier: Soldier, reference_date: date) -> str | None:
    """Resolve the soldier's rank as of reference_date, chaining through any
    configured advancement intervals reached by that date."""
    if soldier.rank is None:
        return None
    from app.services.rank_eligibility_projection import project_soldier_state
    # potential.py has no live Session at this call site today (it's a pure
    # in-memory helper) -- see step 3a for why this needs a session and how
    # callers now supply one.
    return project_soldier_state(session, soldier=soldier, as_of=reference_date).rank
```

- [ ] **Step 3a: Thread a `Session` through `_rank_as_of`'s callers**

`project_soldier_state` needs a `Session` (to look up `RankAdvancementInterval` rows). Check every call site of `_rank_as_of` in `potential.py` (it's called from within functions that already receive a `session: Session` parameter, per the file's existing imports of `Session`/`select`) and pass that same session through: change `_rank_as_of(soldier, reference_date)` calls to `_rank_as_of(session, soldier, reference_date)`, and update `_rank_as_of`'s own signature to `def _rank_as_of(session: Session, soldier: Soldier, reference_date: date) -> str | None:`, using the passed-in `session` instead of the undefined `session` name from the snippet above.

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_potential.py -v
```
Expected: PASS, including the pre-existing single-step test and the new chained test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/potential.py backend/app/services/tests/test_potential.py
git commit -m "fix: chain multiple rank advancement steps in potential calculation"
```

---

### Task 6: Wire projection into `check_soldier_for_assignment`

**Files:**
- Modify: `backend/app/services/eligibility.py`
- Test: `backend/app/services/tests/test_eligibility.py`

**Interfaces:**
- Consumes: `project_soldier_state` (Task 4).

**Context:** Verified against the real file. `check_soldier_for_assignment`
(`eligibility.py:205-298`) hardcodes `today = date.today()` at line 221,
used only at lines 236-240 to call `_is_eligible(soldier, reqs,
mitvahim_months=.., alal_months=.., today=today)` for the duty-type
eligibility check. It does not currently check departure
(`discharge_date`/`left_at`) at all. `_is_eligible` itself already
recomputes mitvahim/alal recency, driving-license expiry, and
service-type/קבע correctly for whatever `today` it's given (see the spec's
"Why rank is the only field that needs projecting") — the only thing
missing is a projected rank and a departure check.

- [ ] **Step 1: Add `rank_override` to `_is_eligible`**

In `backend/app/services/eligibility.py`, change `_is_eligible`'s signature
(line 124) from:

```python
def _is_eligible(soldier: Soldier, reqs: DutyTypeRequirements, *, mitvahim_months: int, alal_months: int, today: date) -> bool:
```

to:

```python
def _is_eligible(
    soldier: Soldier, reqs: DutyTypeRequirements, *, mitvahim_months: int, alal_months: int, today: date,
    rank_override: str | None = None,
) -> bool:
```

And change the `allowed_ranks` check (lines 142-144) from:

```python
    if reqs.allowed_ranks:
        if not soldier.rank or soldier.rank not in reqs.allowed_ranks:
            return False
```

to:

```python
    if reqs.allowed_ranks:
        effective_rank = rank_override if rank_override is not None else soldier.rank
        if not effective_rank or effective_rank not in reqs.allowed_ranks:
            return False
```

Every existing call site (`compute_eligibility_exclusions` at line 199,
`check_soldier_for_assignment` at line 238) omits `rank_override`, so
`soldier.rank` is used exactly as before — no behavior change for them
yet.

- [ ] **Step 2: Write a failing regression test for the new parameter**

Add to `test_eligibility.py`, next to the existing `_is_eligible` tests:

```python
def test_is_eligible_uses_rank_override_when_provided():
    soldier = _soldier(rank="טוראי")  # use this file's existing soldier-builder helper
    reqs = DutyTypeRequirements(allowed_ranks=["רבט"])
    assert _is_eligible(soldier, reqs, mitvahim_months=6, alal_months=3, today=date(2026, 1, 1)) is False
    assert _is_eligible(
        soldier, reqs, mitvahim_months=6, alal_months=3, today=date(2026, 1, 1), rank_override="רבט"
    ) is True
```

- [ ] **Step 3: Run to verify pass**

```bash
pytest backend/app/services/tests/test_eligibility.py -v
```
Expected: PASS, full file (confirms both the new override behavior and that every existing call site is unaffected).

- [ ] **Step 4: Write a failing test for `check_soldier_for_assignment`'s date-projection**

Add to `test_eligibility.py`:

```python
def test_check_soldier_for_assignment_uses_projected_rank_for_future_assignment_date(app_session):
    from app.services.rank_advancement import upsert_interval
    from tests.helpers import create_soldier
    # Construct a soldier who is NOT eligible today (wrong rank for the duty
    # type's allowed_ranks) but WILL be eligible by the assignment's date,
    # once projected forward through a configured advancement.
    ...  # concrete duty-type + soldier + DutyAssignment setup mirroring the
        # existing check_soldier_for_assignment tests in this file; assert
        # the returned (eligible, reason) tuple is (False, ...) when the
        # assignment's start_date is before the projected promotion date and
        # (True, None) when it's on/after.


def test_check_soldier_for_assignment_excludes_departed_soldier(app_session):
    from tests.helpers import create_soldier
    # soldier.discharge_date before the assignment's start_date -> excluded
    ...  # mirror the same setup pattern
```

Write both by copying the existing setup pattern used by the nearest
existing `check_soldier_for_assignment` test in `test_eligibility.py` (duty
type with `allowed_ranks`, soldier + `DutyAssignment` constructed via
`tests.helpers.create_soldier`/whatever local builder this file already
uses) rather than inventing new fixtures.

- [ ] **Step 5: Run to verify failure**

```bash
pytest backend/app/services/tests/test_eligibility.py -k "future_assignment_date or excludes_departed" -v
```
Expected: FAIL.

- [ ] **Step 6: Update `check_soldier_for_assignment`**

At `eligibility.py:221`, replace:

```python
    today = date.today()
```

with:

```python
    from app.services.rank_eligibility_projection import project_soldier_state
    projected = project_soldier_state(session, soldier=soldier, as_of=assignment.start_date)
    if projected.departed:
        return False, "החייל סיים שירות עד תאריך זה"
    today = assignment.start_date
```

Then update the `_is_eligible` call at lines 238-239 to pass the projected
rank:

```python
                if not _is_eligible(soldier, reqs, mitvahim_months=mitvahim_months,
                                    alal_months=alal_months, today=today, rank_override=projected.rank):
```

Leave the exemption/personal-constraint/scheduling-conflict checks (lines
244-296) untouched — they already use `assignment.start_date`/`end_date`
correctly.

- [ ] **Step 7: Run to verify pass**

```bash
pytest backend/app/services/tests/test_eligibility.py -v
```
Expected: PASS, full file (guards against breaking any existing `check_soldier_for_assignment` case).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/eligibility.py backend/app/services/tests/test_eligibility.py
git commit -m "fix: check_soldier_for_assignment projects rank/departure as of the assignment date"
```

---

### Task 7: CP-SAT solver — date-sensitive exclusion for rank, recency, license, and exemptions

**Files:**
- Modify: `backend/app/algorithm/types.py`
- Modify: `backend/app/algorithm/solver.py`
- Modify: `backend/app/algorithm/model.py`
- Modify: `backend/app/services/rank_eligibility_projection.py` (extend — add `bulk_future_ineligible_duty_blocks`)
- Modify: `backend/app/services/algorithm_bridge.py`
- Test: `backend/app/services/tests/test_rank_eligibility_projection.py`
- Test: `backend/app/algorithm/tests/test_solver.py`

**Interfaces:**
- Consumes: `project_soldier_state` (Task 4), `_is_eligible`'s `rank_override` parameter (Task 6), the existing `weapon_ineligible_duty_block_ids` pattern (`types.py:46`, `solver.py:320,1365`, `model.py:337`, `algorithm_bridge.py:1181-1194`) as the exact template to mirror.
- Produces: `SoldierInput.future_ineligible_duty_block_ids: set[uuid.UUID]`, `bulk_future_ineligible_duty_blocks(session, *, soldier_ids, duties) -> dict[uuid.UUID, set[uuid.UUID]]`.

**Context:** Verified against the real files. Today, `compute_eligibility_exclusions` in `algorithm_bridge.py` (line 240-242) is evaluated once at a single `as_of` (`planning_start`) for the whole solve and produces one static `exempted_duty_type_ids` set per soldier (`SoldierInput.exempted_duty_type_ids`, `types.py:40`), applied identically to every duty block regardless of that block's own date. Separately, exemption-to-duty-type mapping (`algorithm_bridge.py` lines ~205-217, `soldier_exempt_dtype_ids`/`soldier_exempt_locids`) is also evaluated once at `as_of`, so exemptions starting or ending within the planning window are invisible to the solver. But `_is_eligible` (`eligibility.py:124-168`) already correctly re-evaluates mitvahim/alal recency, driving-license expiry, and service-type/קבע for whatever `today` it's given — Task 6 already added a `rank_override` parameter to cover the one thing it doesn't recompute (rank). So the fix here is: call `_is_eligible(..., today=block.start_date, rank_override=projected.rank)` once per (soldier, duty-block), plus a separate per-block exemption-date check, and store the combined result as a new block-level exclusion field — mirroring `weapon_ineligible_duty_block_ids` exactly. This does **not** remove `exempted_duty_type_ids`/`compute_eligibility_exclusions` — those stay in place for same-day-snapshot consumers (`diagnose.py`, `explain.py`, the active-days/fairness calculation) that are unrelated to per-duty-date projection.

- [ ] **Step 1: Write failing tests for `bulk_future_ineligible_duty_blocks` — rank**

Append to `test_rank_eligibility_projection.py`:

```python
from app.algorithm.types import DutyBlock
import uuid


def _duty_block(duty_type_id, day, duty_location_id=None):
    return DutyBlock(
        id=uuid.uuid4(), duty_type_id=duty_type_id, duty_location_id=duty_location_id or uuid.uuid4(),
        start_date=day, end_date=day, score_per_day=1,
    )


def test_bulk_future_ineligible_excludes_block_when_projected_rank_fails_requirement(app_session):
    from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks
    from app.db.models import DutyType
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="טוראי")
    dt = DutyType(name="x", requirements={"allowed_ranks": ["רבט"]})
    app_session.add(dt)
    app_session.flush()
    block = _duty_block(dt.id, date(2026, 6, 1))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_includes_block_when_projected_rank_satisfies_requirement(app_session):
    from app.services.rank_advancement import upsert_interval
    from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks
    from app.db.models import DutyType
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=1, actor_id=None)
    dt = DutyType(name="x", requirements={"allowed_ranks": ["רבט"]})
    app_session.add(dt)
    app_session.flush()
    # duty is far enough out that the soldier will have advanced to רבט by then
    block = _duty_block(dt.id, date(2026, 6, 1))

    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id not in result.get(s.id, set())
```

Write the `DutyType.requirements` JSON shape to exactly match `DutyTypeRequirements` (imported in `potential.py:22-26` from `eligibility.py`) — read that model's field names before finalizing this test.

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_rank_eligibility_projection.py -k bulk_future_ineligible -v
```
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `bulk_future_ineligible_duty_blocks` — rank/recency/license/career/departure**

Append to `backend/app/services/rank_eligibility_projection.py`:

```python
import uuid
from typing import Sequence

from sqlalchemy import select

from app.algorithm.types import DutyBlock


def bulk_future_ineligible_duty_blocks(
    session: Session, *, soldier_ids: Sequence[uuid.UUID], duties: Sequence[DutyBlock]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, the set of duty-block ids (among `duties`) they will
    NOT be eligible for as of that block's own start_date -- covering
    projected rank, service-type/career, mitvahim/alal recency,
    driving-license expiry, active exemptions, and departure.

    Mirrors app.services.weapon_eligibility.bulk_ineligible_duty_blocks's
    shape/contract exactly -- see that function's docstring for why this is a
    hard per-block exclusion rather than a single soldier-level set.
    """
    from app.db.models import DutyType, Soldier
    from app.services.eligibility import DutyTypeRequirements, _is_eligible
    from app.services.settings_loader import get_setting_int

    soldiers = session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars().all()
    duty_type_ids = {d.duty_type_id for d in duties}
    duty_types = {
        dt.id: dt for dt in session.execute(
            select(DutyType).where(DutyType.id.in_(duty_type_ids))
        ).scalars().all()
    }
    mitvahim_months = get_setting_int(session, "eligibility.mitvahim_months", 6)
    alal_months = get_setting_int(session, "eligibility.alal_months", 3)

    # Group blocks by distinct start_date so the (soldier, date) projection
    # is only computed once per date, not once per block.
    dates = sorted({d.start_date for d in duties})
    projections: dict[tuple[uuid.UUID, date], ProjectedSoldierState] = {}
    for s in soldiers:
        for d in dates:
            projections[(s.id, d)] = project_soldier_state(session, soldier=s, as_of=d)

    exempt_blocks = _bulk_exempt_duty_blocks(session, soldier_ids=soldier_ids, duties=duties)

    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for s in soldiers:
        excluded: set[uuid.UUID] = set(exempt_blocks.get(s.id, set()))
        for block in duties:
            dt = duty_types.get(block.duty_type_id)
            if dt is None:
                continue
            try:
                reqs = DutyTypeRequirements.model_validate(dt.requirements or {})
            except Exception:
                continue
            projected = projections[(s.id, block.start_date)]
            if projected.departed:
                excluded.add(block.id)
                continue
            if not _is_eligible(
                s, reqs, mitvahim_months=mitvahim_months, alal_months=alal_months,
                today=block.start_date, rank_override=projected.rank,
            ):
                excluded.add(block.id)
        result[s.id] = excluded
    return result
```

Confirm `get_setting_int`'s real import path/signature against `settings_loader.py:59-63` (same function `algorithm_bridge.py` already uses indirectly via its own `_setting_int` wrapper — using `get_setting_int` directly here is simpler and equivalent).

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_rank_eligibility_projection.py -v
```
Expected: PASS for the rank-only cases (the exemption piece, `_bulk_exempt_duty_blocks`, doesn't exist yet — implemented next).

- [ ] **Step 5: Write failing tests for the exemption piece**

Append to `test_rank_eligibility_projection.py`:

```python
def test_bulk_future_ineligible_excludes_block_covered_by_future_exemption(app_session):
    from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks
    from app.db.models import DutyType, ExemptionType, ExemptionDutyTypeMap, SoldierExemption
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="טוראי")
    dt = DutyType(name="x", requirements={})
    et = ExemptionType(name="y", is_global=False)
    app_session.add_all([dt, et])
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    # exemption starts in the future -- not active "today", but covers the block's date
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 5, 1), end_date=date(2026, 7, 1),
    ))
    app_session.flush()

    block = _duty_block(dt.id, date(2026, 6, 1))
    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())


def test_bulk_future_ineligible_includes_block_after_exemption_ends(app_session):
    from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks
    from app.db.models import DutyType, ExemptionType, ExemptionDutyTypeMap, SoldierExemption
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="טוראי")
    dt = DutyType(name="x", requirements={})
    et = ExemptionType(name="y", is_global=False)
    app_session.add_all([dt, et])
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    # exemption is active "today" but ends before the block's date
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
    ))
    app_session.flush()

    block = _duty_block(dt.id, date(2026, 6, 1))
    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id not in result.get(s.id, set())


def test_bulk_future_ineligible_excludes_block_by_global_exemption(app_session):
    from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks
    from app.db.models import DutyType, ExemptionType, SoldierExemption
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="טוראי")
    dt = DutyType(name="x", requirements={})
    et = ExemptionType(name="global", is_global=True)
    app_session.add_all([dt, et])
    app_session.flush()
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id, start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.flush()

    block = _duty_block(dt.id, date(2026, 6, 1))
    result = bulk_future_ineligible_duty_blocks(app_session, soldier_ids=[s.id], duties=[block])

    assert block.id in result.get(s.id, set())
```

Confirm `ExemptionType`/`SoldierExemption`/`ExemptionDutyTypeMap`/`ExemptionDutyLocationMap` field names against `eligibility.py:244-273`'s existing use of them before finalizing these tests.

- [ ] **Step 6: Run to verify failure**

```bash
pytest backend/app/services/tests/test_rank_eligibility_projection.py -k "exempt" -v
```
Expected: FAIL (`ImportError` — `_bulk_exempt_duty_blocks` referenced in Step 3's implementation doesn't exist yet).

- [ ] **Step 7: Implement `_bulk_exempt_duty_blocks`**

Append to `backend/app/services/rank_eligibility_projection.py`, adapting the exemption-resolution logic `check_soldier_for_assignment` already uses at `eligibility.py:244-273` from "one soldier, one assignment" to "many soldiers, many blocks":

```python
def _bulk_exempt_duty_blocks(
    session: Session, *, soldier_ids: Sequence[uuid.UUID], duties: Sequence[DutyBlock]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, duty-block ids covered by an active exemption as of
    that block's own start_date (global, or mapped to the block's duty type
    or location)."""
    from app.db.models import ExemptionDutyLocationMap, ExemptionDutyTypeMap, ExemptionType, SoldierExemption

    exemptions = session.execute(
        select(SoldierExemption).where(SoldierExemption.soldier_id.in_(soldier_ids))
    ).scalars().all()
    if not exemptions:
        return {}

    exemption_type_ids = {e.exemption_type_id for e in exemptions}
    types_by_id = {
        et.id: et for et in session.execute(
            select(ExemptionType).where(ExemptionType.id.in_(exemption_type_ids))
        ).scalars().all()
    }
    dtype_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in session.execute(
        select(ExemptionDutyTypeMap).where(ExemptionDutyTypeMap.exemption_type_id.in_(exemption_type_ids))
    ).scalars().all():
        dtype_map.setdefault(row.exemption_type_id, set()).add(row.duty_type_id)
    loc_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in session.execute(
        select(ExemptionDutyLocationMap).where(ExemptionDutyLocationMap.exemption_type_id.in_(exemption_type_ids))
    ).scalars().all():
        loc_map.setdefault(row.exemption_type_id, set()).add(row.duty_location_id)

    by_soldier: dict[uuid.UUID, list] = {}
    for e in exemptions:
        by_soldier.setdefault(e.soldier_id, []).append(e)

    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for soldier_id, soldier_exemptions in by_soldier.items():
        excluded: set[uuid.UUID] = set()
        for block in duties:
            for e in soldier_exemptions:
                if e.start_date > block.start_date:
                    continue
                if e.end_date is not None and e.end_date < block.start_date:
                    continue
                et = types_by_id.get(e.exemption_type_id)
                if et is not None and et.is_global:
                    excluded.add(block.id)
                    break
                if block.duty_type_id in dtype_map.get(e.exemption_type_id, set()):
                    excluded.add(block.id)
                    break
                if block.duty_location_id in loc_map.get(e.exemption_type_id, set()):
                    excluded.add(block.id)
                    break
        result[soldier_id] = excluded
    return result
```

Confirm `SoldierExemption`'s date-range semantics (`start_date`/`end_date`, `end_date` nullable = open-ended) and `ExemptionType.is_global` against the real model definitions in `models.py` before finalizing — match the same inclusive/exclusive boundary convention `check_soldier_for_assignment` uses (`eligibility.py:248-251` compares against `assignment.end_date`/`assignment.start_date`; here each block is a single day so `start_date <= block.start_date <= end_date` is the natural equivalent).

- [ ] **Step 8: Run to verify pass**

```bash
pytest backend/app/services/tests/test_rank_eligibility_projection.py -v
```
Expected: PASS, full file.

- [ ] **Step 9: Add the `SoldierInput` field**

In `backend/app/algorithm/types.py`, immediately after `weapon_ineligible_duty_block_ids` (line 46):

```python
    # Duty-block ids this soldier will NOT be eligible for as of that
    # block's own start_date -- covers projected rank, service-type/career,
    # mitvahim/alal recency, driving-license expiry, active exemptions, and
    # departure. Populated by algorithm_bridge via
    # bulk_future_ineligible_duty_blocks, mirroring
    # weapon_ineligible_duty_block_ids above. Empty by default for existing
    # callers/tests/fixtures.
    future_ineligible_duty_block_ids: set[uuid.UUID] = field(default_factory=set)
```

- [ ] **Step 10: Add solver/model checks**

In `backend/app/algorithm/solver.py`, at both locations mirroring line 320 (`if settings.enforce_weapon_qualification and d.id in s.weapon_ineligible_duty_block_ids: continue`) — there are two, at lines 320 and 1365 — add immediately after each:

```python
            if d.id in s.future_ineligible_duty_block_ids:
                continue
```

(No settings gate — unlike weapon qualification, none of the factors folded into this field are optional enforcement toggles.)

In `backend/app/algorithm/model.py`, at the equivalent location (line 337), add the same check immediately after.

- [ ] **Step 11: Write a solver-level regression test**

Add to `backend/app/algorithm/tests/test_solver.py`, following the existing style of `weapon_ineligible_duty_block_ids`-based tests in that file (search for one and mirror its shape):

```python
def test_solver_excludes_soldier_from_future_ineligible_block():
    duty = _duty(...)  # use this file's existing duty-construction helper
    soldier = _soldier(..., future_ineligible_duty_block_ids={duty.id})
    result = solve(soldiers=[soldier], duties=[duty], ...)  # match the file's existing solve() call shape
    assert duty.id not in {a.duty_id for a in result.assignments if a.soldier_id == soldier.id}
```

Read an existing `weapon_ineligible_duty_block_ids` test in this file first and copy its exact fixture/call conventions rather than guessing parameter names.

- [ ] **Step 12: Run to verify pass**

```bash
pytest backend/app/algorithm/tests/test_solver.py -v
```
Expected: PASS, full file.

- [ ] **Step 13: Wire into `algorithm_bridge.py`**

In `algorithm_bridge.py`, immediately after the existing weapon-eligibility block (after line 1194's `_phase("weapon_eligibility: done")`):

```python
            _phase("future_eligibility: start")
            from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks
            future_ineligible = bulk_future_ineligible_duty_blocks(
                session, soldier_ids=[s.id for s in soldiers], duties=duties,
            )
            for s in soldiers:
                s.future_ineligible_duty_block_ids = future_ineligible.get(s.id, set())
            _phase("future_eligibility: done")
```

- [ ] **Step 14: Write an `algorithm_bridge` integration test**

Add to `backend/app/services/tests/test_algorithm_bridge.py`, following the existing style of the file's `weapon_ineligible_duty_block_ids`-population tests (search for one) — construct a soldier who fails the projected-rank check for a duty block dated in the future, run the bridge's soldier-loading function, and assert `future_ineligible_duty_block_ids` on the resulting `SoldierInput` contains that block's id. Add a second case using a future-dated exemption instead of rank.

- [ ] **Step 15: Run to verify pass**

```bash
pytest backend/app/services/tests/test_algorithm_bridge.py -v
```
Expected: PASS.

- [ ] **Step 16: Run the full algorithm test suite as a regression guard**

```bash
pytest -m algorithm -v
```
Expected: PASS. (Do not run `--slow` here — save that for pre-release per CLAUDE.md.)

- [ ] **Step 17: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/algorithm/solver.py backend/app/algorithm/model.py backend/app/services/rank_eligibility_projection.py backend/app/services/algorithm_bridge.py backend/app/algorithm/tests/test_solver.py backend/app/services/tests/test_algorithm_bridge.py backend/app/services/tests/test_rank_eligibility_projection.py
git commit -m "feat: exclude soldiers ineligible-by-projected-date (rank, recency, license, exemptions) from CP-SAT candidate pool per duty block"
```

---

### Task 8: Notification helpers

**Files:**
- Modify: `backend/app/services/notifications.py`
- Test: `backend/app/services/tests/test_notifications.py`

**Interfaces:**
- Consumes: `NotificationType.rank_advanced`, `NotificationType.rank_advancement_soon` (Task 1), `create_notification` (`notifications.py:282-341`).
- Produces: `notify_rank_advanced(session, *, soldier_id, new_rank, actor_id=None) -> None`, `notify_rank_advancement_soon(session, *, soldier_id, new_rank, effective_date, actor_id=None) -> None`.

- [ ] **Step 1: Write failing tests**

```python
# add to backend/app/services/tests/test_notifications.py
from app.services.notifications import notify_rank_advanced, notify_rank_advancement_soon
from app.db.models import Notification, NotificationType
from tests.helpers import create_soldier


def test_notify_rank_advanced_creates_notification_for_soldier(app_session):
    s = create_soldier(app_session, rank="רבט")
    notify_rank_advanced(app_session, soldier_id=s.id, new_rank="רבט")
    app_session.flush()
    notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == s.id, Notification.type == NotificationType.rank_advanced
        )
    ).scalar_one()
    assert "רבט" in notif.title
```

Write a second test asserting the commander also receives a notification, following the same commander-fixture pattern used by an existing dual-audience test in this file (e.g. near `notify_enrollment_received`'s tests) — read that test first and mirror its commander/hierarchy setup exactly.

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_notifications.py -k rank_advanced -v
```
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement**

Append to `backend/app/services/notifications.py`, following `create_notification`'s existing call shape (it already auto-cascades to commanders per line 317-324, so no separate commander call is needed):

```python
def notify_rank_advanced(
    session: Session, *, soldier_id: uuid.UUID, new_rank: str, actor_id: uuid.UUID | None = None
) -> None:
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.rank_advanced,
        title=f"קודמת לדרגת {new_rank}",
        actor_id=actor_id,
    )


def notify_rank_advancement_soon(
    session: Session, *, soldier_id: uuid.UUID, new_rank: str, effective_date: date, actor_id: uuid.UUID | None = None
) -> None:
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.rank_advancement_soon,
        title=f"קידום צפוי לדרגת {new_rank} בתאריך {effective_date.strftime('%d.%m.%Y')}",
        actor_id=actor_id,
    )
```

Add both to `_FRONTEND_PATHS` (`notifications.py:39-68`), pointing at the soldier profile route (match whatever existing entry points at a soldier's own profile, e.g. reuse the same path used for other soldier-profile-centric notification types in that dict).

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_notifications.py -v
```
Expected: PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/notifications.py backend/app/services/tests/test_notifications.py
git commit -m "feat: add rank-advancement notification helpers"
```

---

### Task 9: Daily promotion worker

**Files:**
- Create: `backend/app/rank_advancement_worker.py`
- Modify: `backend/app/main.py`
- Test: `backend/app/tests/test_rank_advancement_worker.py`

**Interfaces:**
- Consumes: `get_next_rank`, `compute_next_rank_date` (Task 2), `notify_rank_advanced`, `notify_rank_advancement_soon` (Task 8), `get_setting_int` (`settings_loader.py:59-63`).
- Produces: `run_rank_advancement_worker() -> None` (async, registered in `main.py`), `_promote_due_soldiers() -> None`, `_warn_upcoming_soldiers() -> None` (sync, run via `asyncio.to_thread`).

- [ ] **Step 1: Write failing tests (mirroring `test_duty_eligibility_worker.py`'s mock-based style)**

```python
# backend/app/tests/test_rank_advancement_worker.py
from unittest.mock import patch
import asyncio

from app.rank_advancement_worker import run_rank_advancement_worker


def test_worker_calls_promote_and_warn_each_cycle():
    with patch("app.rank_advancement_worker._promote_due_soldiers") as mock_promote, \
         patch("app.rank_advancement_worker._warn_upcoming_soldiers") as mock_warn, \
         patch("app.rank_advancement_worker.asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        try:
            asyncio.run(run_rank_advancement_worker())
        except asyncio.CancelledError:
            pass
    mock_promote.assert_called_once()
    mock_warn.assert_called_once()
```

Write the actual promotion-logic tests as DB-backed tests using `app_session`, following the fixture pattern established in Task 2/3/4's tests:

```python
def test_promote_due_soldiers_advances_rank_and_chains_next_date(app_session):
    from datetime import date
    from app.rank_advancement_worker import _promote_soldier
    from app.services.rank_advancement import upsert_interval
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, actor_id=None)
    app_session.flush()

    _promote_soldier(app_session, s, today=date(2026, 1, 1))

    assert s.rank == "רבט"
    assert s.next_rank_date == date(2026, 9, 1)
    assert s.next_rank_date_overridden is False
    assert s.current_rank_since == date(2026, 1, 1)


def test_promote_due_soldiers_stops_at_top_of_ladder(app_session):
    from datetime import date
    from app.rank_advancement_worker import _promote_soldier
    from tests.helpers import create_soldier

    s = create_soldier(app_session, rank="רנג")  # top of enlisted ladder
    s.next_rank_date = date(2026, 1, 1)
    app_session.flush()

    _promote_soldier(app_session, s, today=date(2026, 1, 1))

    assert s.rank == "רנג"
    assert s.next_rank_date is None


def test_promote_due_soldiers_skips_discharged_soldiers(app_session):
    from datetime import date
    from tests.helpers import create_soldier
    from app.rank_advancement_worker import _promote_due_soldiers

    s = create_soldier(app_session, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)
    s.discharge_date = date(2025, 12, 1)
    app_session.flush()

    _promote_due_soldiers(session_factory=lambda: app_session, today=date(2026, 1, 1))

    assert s.rank == "טוראי"  # unchanged
```

Adjust `_promote_due_soldiers`'s test call above once its real signature is settled in Step 3 — the mock-based worker-loop test in this step doesn't depend on that signature, only the DB-backed tests do; if `_promote_due_soldiers` ends up managing its own `session_scope()` internally (matching `duty_eligibility_worker.py`'s `_recheck_all_published_weapon_assignments` pattern) rather than taking a session/factory parameter, restructure these DB-backed tests to call `_promote_soldier` directly per-soldier (as the first test already does) and cover `_promote_due_soldiers`' query/filtering behavior with a lighter integration test instead.

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/tests/test_rank_advancement_worker.py -v
```
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the worker**

```python
# backend/app/rank_advancement_worker.py
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.db.session import session_scope
from app.db.models import Soldier
from app.services.notifications import notify_rank_advanced, notify_rank_advancement_soon
from app.services.rank_advancement import compute_next_rank_date, get_next_rank
from app.services.settings_loader import get_setting_int

logger = logging.getLogger(__name__)

_POLL_SECONDS = 86400


def _promote_soldier(session, soldier: Soldier, *, today: date) -> None:
    next_rank = get_next_rank(soldier.rank) if soldier.rank else None
    if next_rank is None:
        soldier.next_rank_date = None
        return
    old_rank = soldier.rank
    soldier.rank = next_rank
    soldier.current_rank_since = today
    soldier.next_rank_date_overridden = False
    soldier.next_rank_date = compute_next_rank_date(session, rank=next_rank, since=today)
    notify_rank_advanced(session, soldier_id=soldier.id, new_rank=next_rank)


def _promote_due_soldiers() -> None:
    today = date.today()
    with session_scope() as session:
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.next_rank_date.is_not(None),
                Soldier.next_rank_date <= today,
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
            )
        ).scalars().all()
        for s in soldiers:
            _promote_soldier(session, s, today=today)


def _warn_upcoming_soldiers() -> None:
    today = date.today()
    with session_scope() as session:
        warning_days = get_setting_int(session, "rank_advancement.warning_days", 7)
        target = today + timedelta(days=warning_days)
        soldiers = session.execute(
            select(Soldier).where(Soldier.next_rank_date == target)
        ).scalars().all()
        for s in soldiers:
            next_rank = get_next_rank(s.rank) if s.rank else None
            if next_rank is None:
                continue
            notify_rank_advancement_soon(
                session, soldier_id=s.id, new_rank=next_rank, effective_date=target
            )


async def run_rank_advancement_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_promote_due_soldiers)
            await asyncio.to_thread(_warn_upcoming_soldiers)
        except Exception:
            logger.warning("rank advancement worker: unhandled error", exc_info=True)
```

Confirm `session_scope`'s real import path (`app.db.session` is a placeholder — check `duty_eligibility_worker.py`'s actual import line and match it exactly) and `get_setting_int`'s real signature (`settings_loader.py:59-63`) before finalizing. Register the new setting key `rank_advancement.warning_days` — no schema change needed since `SystemSetting` is a generic key/value table (Task 12 adds the frontend field for it).

- [ ] **Step 4: Register in `main.py`**

Mirror the exact registration pattern for `run_duty_eligibility_worker` (`main.py:128-140`): import `run_rank_advancement_worker` at the top alongside the other worker imports, `asyncio.create_task(run_rank_advancement_worker())` in the lifespan startup block, and add the resulting task to both shutdown-cancel tuples alongside the other workers' tasks.

- [ ] **Step 5: Run to verify pass**

```bash
pytest backend/app/tests/test_rank_advancement_worker.py -v
```
Expected: PASS, full file.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rank_advancement_worker.py backend/app/main.py backend/app/tests/test_rank_advancement_worker.py
git commit -m "feat: add daily rank advancement worker (promote + warn)"
```

---

### Task 10: Manual override tracking on soldier profile edit

**Files:**
- Modify: `backend/app/services/soldiers.py`
- Test: `backend/tests` — find and extend the existing `update_soldier_profile` test file (search for it; likely `backend/app/services/tests/test_soldiers.py`)

**Interfaces:**
- Consumes: `compute_next_rank_date` (Task 2).
- Produces: updated `update_soldier_profile` behavior — no new public interface, but changes what it writes to `next_rank_date`/`next_rank_date_overridden`/`current_rank_since`.

- [ ] **Step 1: Write failing tests**

Add to the existing `update_soldier_profile` test file:

```python
def test_update_soldier_profile_manual_next_rank_date_sets_overridden(app_session):
    from tests.helpers import create_soldier
    from app.services.soldiers import update_soldier_profile

    s = create_soldier(app_session, rank="טוראי")
    update_soldier_profile(
        app_session, soldier=s, fields={"next_rank_date": date(2030, 1, 1)}, actor_id=None
    )
    assert s.next_rank_date == date(2030, 1, 1)
    assert s.next_rank_date_overridden is True


def test_update_soldier_profile_rank_change_without_explicit_date_auto_computes(app_session):
    from tests.helpers import create_soldier
    from app.services.rank_advancement import upsert_interval
    from app.services.soldiers import update_soldier_profile

    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, actor_id=None)
    s = create_soldier(app_session, rank="טוראי")
    update_soldier_profile(
        app_session, soldier=s, fields={"rank": "רבט"}, actor_id=None
    )
    assert s.current_rank_since == date.today()
    assert s.next_rank_date == date.today() + relativedelta(months=8)
    assert s.next_rank_date_overridden is False
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_soldiers.py -k "next_rank_date" -v
```
Expected: FAIL (`next_rank_date` not yet in `PROFILE_FIELDS`, so the field is silently ignored and both assertions fail).

- [ ] **Step 3: Implement**

In `backend/app/services/soldiers.py`, add `"next_rank_date"` to `PROFILE_FIELDS` (line 273-278). Then in `update_soldier_profile` (line 287-320), after the existing `for k, v in fields.items(): if k in PROFILE_FIELDS: setattr(soldier, k, v)` loop, add:

```python
    if "next_rank_date" in fields:
        soldier.next_rank_date_overridden = True
    elif "rank" in fields:
        from app.services.rank_advancement import compute_next_rank_date
        soldier.current_rank_since = date.today()
        soldier.next_rank_date = compute_next_rank_date(session, rank=soldier.rank, since=date.today())
        soldier.next_rank_date_overridden = False
```

Place this before the existing `is_career`/`validate_rank_track_compatibility` block (line 299) so `soldier.rank` is already updated by the time it runs.

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_soldiers.py -v
```
Expected: PASS, full file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/soldiers.py backend/app/services/tests/test_soldiers.py
git commit -m "feat: track manual next_rank_date overrides and auto-compute on rank changes"
```

---

### Task 11: Routes — rank ladder read + interval config write

**Files:**
- Create: `backend/app/routes/rank_advancement.py`
- Test: `backend/app/routes/tests/test_rank_advancement_routes.py`
- Modify: `backend/app/main.py` (register router — find the existing router-registration block and add this one alongside it)

**Interfaces:**
- Consumes: `get_rank_ladder`, `set_interval_and_recompute` (Tasks 2-3).
- Produces: `GET /soldiers/rank-ladder` (any authenticated user), `PUT /soldiers/rank-advancement-intervals` (admin only).

- [ ] **Step 1: Write failing route tests**

Before writing these, read one existing admin-only route file (e.g. wherever `SystemSettingsPage.tsx`'s backend endpoint lives, or any other admin-gated route) to copy its exact auth-dependency pattern (likely a `require_role("admin")` or similar FastAPI dependency).

```python
# backend/app/routes/tests/test_rank_advancement_routes.py
def test_get_rank_ladder_returns_both_tracks(client, auth_headers):
    resp = client.get("/soldiers/rank-ladder", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enlisted"][0]["rank"] == "טוראי"
    assert body["officer"][0]["rank"] == "קמא"


def test_put_rank_advancement_intervals_requires_admin(client, auth_headers):
    resp = client.put(
        "/soldiers/rank-advancement-intervals",
        json=[{"track": "enlisted", "rank": "טוראי", "months_to_next": 4}],
        headers=auth_headers,  # non-admin fixture
    )
    assert resp.status_code == 403


def test_put_rank_advancement_intervals_updates_config(client, admin_auth_headers):
    resp = client.put(
        "/soldiers/rank-advancement-intervals",
        json=[{"track": "enlisted", "rank": "טוראי", "months_to_next": 4}],
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    ladder_resp = client.get("/soldiers/rank-ladder", headers=admin_auth_headers)
    entry = next(r for r in ladder_resp.json()["enlisted"] if r["rank"] == "טוראי")
    assert entry["months_to_next"] == 4
```

Use whatever the file's real fixture names are for an authenticated client and an admin-authenticated client (search `conftest.py` for `auth_headers`/similar) rather than the placeholder names above.

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/routes/tests/test_rank_advancement_routes.py -v
```
Expected: FAIL (404, route doesn't exist).

- [ ] **Step 3: Implement**

```python
# backend/app/routes/rank_advancement.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_session  # confirm real import path against an existing route file
from app.auth.dependencies import require_role, get_current_soldier  # confirm real names
from app.services.rank_advancement import get_rank_ladder, set_interval_and_recompute

router = APIRouter(prefix="/soldiers", tags=["rank-advancement"])


class RankIntervalIn(BaseModel):
    track: str
    rank: str
    months_to_next: int | None


@router.get("/rank-ladder")
def read_rank_ladder(
    session: Session = Depends(get_session), _soldier=Depends(get_current_soldier)
) -> dict:
    return get_rank_ladder(session)


@router.put("/rank-advancement-intervals")
def update_rank_advancement_intervals(
    intervals: list[RankIntervalIn],
    session: Session = Depends(get_session),
    admin=Depends(require_role("admin")),
) -> dict:
    for item in intervals:
        set_interval_and_recompute(
            session, track=item.track, rank=item.rank, months_to_next=item.months_to_next,
            actor_id=admin.id,
        )
    session.commit()
    return get_rank_ladder(session)
```

Replace the placeholder import paths/dependency names with the real ones found by reading an existing route file in `backend/app/routes/` before finalizing.

- [ ] **Step 4: Register the router in `main.py`**

Find the block in `main.py` that does `app.include_router(...)` for other route modules and add `app.include_router(rank_advancement.router)` alongside them, with the matching import at the top.

- [ ] **Step 5: Run to verify pass**

```bash
pytest backend/app/routes/tests/test_rank_advancement_routes.py -v
```
Expected: PASS, full file.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/rank_advancement.py backend/app/routes/tests/test_rank_advancement_routes.py backend/app/main.py
git commit -m "feat: add rank ladder read and interval config write endpoints"
```

---

### Task 12: Frontend — rank ladder from API + admin settings screen

**Files:**
- Create: `frontend/src/api/rankAdvancement.ts`
- Modify: `frontend/src/constants/ranks.ts`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: co-located `.test.ts`/`.test.tsx` files matching this repo's existing frontend test conventions (search for an existing test file next to `SystemSettingsPage.tsx` or `ranks.ts` if one exists, to match its exact testing library/setup)

- [ ] **Step 1: Add the typed API wrapper**

```typescript
// frontend/src/api/rankAdvancement.ts
import { apiFetch } from "./client"; // confirm the real shared fetch wrapper name/path from an existing api/*.ts file

export interface RankLadderEntry {
  rank: string;
  months_to_next: number | null;
}

export interface RankLadder {
  enlisted: RankLadderEntry[];
  officer: RankLadderEntry[];
}

export async function getRankLadder(): Promise<RankLadder> {
  return apiFetch("/soldiers/rank-ladder");
}

export async function updateRankAdvancementIntervals(
  intervals: { track: "enlisted" | "officer"; rank: string; months_to_next: number | null }[]
): Promise<RankLadder> {
  return apiFetch("/soldiers/rank-advancement-intervals", { method: "PUT", body: JSON.stringify(intervals) });
}
```

Match `apiFetch`'s real name/signature from an existing file in `frontend/src/api/` (e.g. `ineligibleSoldiers.ts`, mentioned in the spec) before finalizing.

- [ ] **Step 2: Replace hardcoded ladder in `ranks.ts`**

Read the full current `frontend/src/constants/ranks.ts` first. Replace the hardcoded `ENLISTED_RANKS`/`OFFICER_RANKS` arrays with a fetch-and-cache: export a hook (e.g. `useRankLadder()`, following whatever data-fetching convention the rest of the frontend uses — likely `@tanstack/react-query`'s `useQuery`, confirm by checking an existing hook in `frontend/src/api/` or `frontend/src/hooks/`) that calls `getRankLadder()` and derives the flat rank-order arrays from its result. Keep `RANK_TRACK_COMPATIBILITY`, the `is_career`-equivalent helper, and `derive_bahad1_graduate`-equivalent helper as they are (out of scope per the spec) — only the ladder-order arrays move to the API.

Every existing consumer of the hardcoded `ENLISTED_RANKS`/`OFFICER_RANKS` constants in the frontend needs to switch to the new hook — grep the frontend for both names and update each call site.

- [ ] **Step 3: Add the admin settings section**

In `frontend/src/pages/SystemSettingsPage.tsx`, following the file's existing `SettingDef`/`SETTING_GROUPS` pattern (`SystemSettingsPage.tsx:13-20` for the interface, `:22+` for the groups), add a new group for `rank_advancement.warning_days` as a plain integer `SettingDef` (fits the existing generic settings mechanism, no new component needed).

The per-rank interval table (`months_to_next` per rank/track) does NOT fit the flat `SettingDef` shape (it's a list of rows, not a single value) — add a dedicated small table UI within the same settings page (new section, not a new route): one row per rank (from `getRankLadder()`), an editable `months_to_next` number input per row, and a "Save" button that calls `updateRankAdvancementIntervals()` with all rows. Follow the page's existing `draft`/`isDirty`/`useMutation` state pattern (`SystemSettingsPage.tsx:402-418, 462-469`) for this table's own local state, separate from the generic `SETTING_GROUPS` draft since it's a different shape.

- [ ] **Step 4: Manual verification in the browser**

Start the dev stack (`.\dev.ps1`), open `http://localhost:5173`, log in as an admin, navigate to the system settings page, confirm:
- The rank interval table loads with all ranks from both tracks, empty `months_to_next` for unconfigured ones.
- Editing a value and saving persists (reload the page, value is retained).
- The warning-days setting appears in the existing settings group and saves correctly.
- Elsewhere in the app, any UI showing a soldier's rank (profile page, soldier list, edit modal) still renders correctly — the ladder now comes from the API instead of a hardcoded constant, so this is a regression check, not new functionality.

- [ ] **Step 5: Run frontend checks**

```bash
npm run lint
npm run typecheck
npm test
```
(run from `frontend/`) Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/rankAdvancement.ts frontend/src/constants/ranks.ts frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: rank ladder from API, admin UI for advancement intervals and warning days"
```

---

## Self-Review Notes

- **Spec coverage:** rank ladder as structured config + API (Task 12), interval config admin-editable + recompute-on-change (Tasks 3, 11, 12), daily promotion + auto-chain + notifications (Tasks 8-9), advance-warning notification (Task 9), future-eligibility projection wired into both the manual check (Task 6) and the CP-SAT solver (Task 7), override tracking (Task 10), no track-crossing (enforced structurally in `get_next_rank`, Task 2), no new קבע-entry field (confirmed — `derive_is_career` already accepts a `today` reference-date param, Task 4), and the broadened per-duty-block-date CP-SAT fix covering rank + mitvahim/alal recency + driving-license expiry + exemptions (Task 7, added after the initial plan when the algorithm exploration surfaced that `_is_eligible` already handles the recency/license factors correctly given the right `today` — only rank and exemptions needed new machinery).
- Task 4, Task 6, and Task 7 were revised after verifying `eligibility.py`'s real contents directly (rather than from a summarized exploration report): `derive_is_career` already takes a `today` parameter (no signature change needed, Task 4 Step 3a removed), `_is_eligible` reads `soldier.rank`/`soldier.is_officer` directly rather than taking rank/career as parameters (Task 6 adds a `rank_override` parameter instead of the originally-assumed override-object approach), and `check_soldier_for_assignment` has no existing departure check (Task 6 adds one).
- Several route/import paths (`session_scope`, `get_session`, `require_role`, `apiFetch`, the frontend data-fetching hook convention) are marked "confirm against an existing file" rather than guessed outright, since this plan was written without opening every one of those files — the implementer must resolve them from the named existing files before writing code, not invent new ones.
