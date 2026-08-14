# Academic Officer Track & קבע-Entry Auto-Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split officer rank advancement into two ladders (regular: סגמ→...→רב אלוף; academic: קאב→קאם, with קמא outside both), and add a per-rank admin checkbox that promotes a soldier immediately on entering קבע — computed live, never from the stale `Soldier.is_career` column — with the CP-SAT/manual-check projection accounting for the same early trigger.

**Architecture:** `rank_advancement.py`'s ladder dict grows a third track (`officer_academic`) and drops קמא from both officer ladders — this is purely additive to the existing `(track, rank)`-keyed `RankAdvancementInterval` config table (no schema change needed for the track split itself, since `track` is free text). A new `advance_on_career_entry` boolean column drives a live date computation (`_career_entry_date`, mirroring `derive_is_career`'s exact boundary) consumed by both the daily worker (immediate promotion) and `project_soldier_state` (future-duty projection) — no new stored "was career" state anywhere.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic backend, React/TypeScript frontend.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-14-academic-officer-track-and-career-entry-promotion.md` — read it before starting.
- `eligibility.py`'s `ENLISTED_RANKS`/`OFFICER_RANKS`/`RANK_TRACK_COMPATIBILITY`/`CHOVAH_ONLY_RANKS`/`derive_bahad1_graduate` are **completely unchanged** by this plan — those are rank-validity lists, not advancement ladders. Only `rank_advancement.py`'s ladder definitions change.
- קמא is removed from every advancement ladder — `get_track("קמא")`/`get_next_rank("קמא")` return `None`. It remains a fully valid, assignable rank everywhere else in the app.
- The קבע-entry trigger never reads or compares `Soldier.is_career` (known stale — only refreshed on profile edit). It always recomputes live from `mandatory_end_date`/`discharge_date` for whatever reference date is in play (`today` for the worker, `as_of` for projection).
- Backend tests use pytest markers (`-m soldiers`, `-m algorithm`, etc. per CLAUDE.md). Run only tests relevant to each task; full suite only at the end if asked.
- Frontend: `npm run lint` (zero warnings), `npm run typecheck`, `npm test` must all pass.
- This work happens in the git worktree at `.worktrees/rank-academic-track` on branch `feat/rank-academic-track`, branched from `dev`. Do NOT commit to `dev`/`master` directly.

---

## File Structure

**New files:** none — every change extends an existing module.

**Modified files:**
- `backend/alembic/versions/<new>_add_advance_on_career_entry.py` — migration (down_revision `92afb4359c3b`, current head)
- `backend/app/db/models.py` — `RankAdvancementInterval.advance_on_career_entry` column
- `backend/app/services/rank_advancement.py` — `Track` gains `"officer_academic"`, `_LADDERS` restructured, `upsert_interval`/`set_interval_and_recompute` carry the new field, new `advances_on_career_entry` lookup, new `_career_entry_date` helper
- `backend/app/rank_advancement_worker.py` — new `_promote_on_career_entry` step
- `backend/app/services/rank_eligibility_projection.py` — `project_soldier_state`'s chain-walk accounts for the early trigger; `interval_cache` shape extended
- `backend/app/routes/rank_advancement.py` — `RankIntervalIn` gains `advance_on_career_entry: bool`
- `frontend/src/api/rankAdvancement.ts` — `RankTrack`, `RankLadderEntry`, `RankIntervalUpdate` gain the third track / new field
- `frontend/src/constants/ranks.ts` — `withLadderFields`'s `officerRanks`/`allRanks` reunited with קמא + the academic ladder for picker completeness
- `frontend/src/pages/SystemSettingsPage.tsx` — `RankAdvancementIntervalsSection` renders three track groups + checkbox + tooltip icon

---

### Task 1: Migration — `advance_on_career_entry` column

**Files:**
- Create: `backend/alembic/versions/<rev>_add_advance_on_career_entry.py`
- Modify: `backend/app/db/models.py`

**Interfaces:**
- Produces: `RankAdvancementInterval.advance_on_career_entry: bool` (default `False`)

- [ ] **Step 1: Add the column to the model**

In `backend/app/db/models.py`, in the `RankAdvancementInterval` class (currently `id`, `track`, `rank`, `months_to_next` — around line 1005-1017), add after `months_to_next`:

```python
    advance_on_career_entry: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
```

- [ ] **Step 2: Generate and fill in the migration**

```bash
cd backend && .venv/Scripts/python.exe -m alembic revision -m "add advance_on_career_entry to rank_advancement_intervals"
```

Edit the generated file:

```python
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "<generated>"
down_revision: Union[str, Sequence[str], None] = "92afb4359c3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rank_advancement_intervals",
        sa.Column("advance_on_career_entry", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("rank_advancement_intervals", "advance_on_career_entry")
```

Confirm `92afb4359c3b` is still the actual head before finalizing (`alembic heads`) — if another migration landed on `dev` since this plan was written, use that instead.

- [ ] **Step 3: Apply and verify**

```bash
cd backend && .venv/Scripts/python.exe -m alembic upgrade head
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat: add advance_on_career_entry column to rank_advancement_intervals"
```

---

### Task 2: Ladder restructuring — three tracks, קמא excluded

**Files:**
- Modify: `backend/app/services/rank_advancement.py`
- Modify: `backend/app/routes/rank_advancement.py`
- Test: `backend/app/services/tests/test_rank_advancement.py`
- Test: `backend/app/routes/tests/test_rank_advancement_routes.py`

**Interfaces:**
- Consumes: Task 1's `advance_on_career_entry` column.
- Produces:
  - `Track = Literal["enlisted", "officer", "officer_academic"]`
  - `get_track(rank: str) -> Track | None` (קמא → `None`)
  - `get_next_rank(rank: str) -> str | None` (קאב → קאם under `officer_academic`; קאם → `None`; regular officer ladder skips קאב/קאם entirely)
  - `upsert_interval(session, *, track, rank, months_to_next, advance_on_career_entry, actor_id) -> RankAdvancementInterval` (new required kwarg)
  - `set_interval_and_recompute(session, *, track, rank, months_to_next, advance_on_career_entry, actor_id) -> int` (new required kwarg)
  - `advances_on_career_entry(session, *, track, rank) -> bool` (new function)
  - `get_rank_ladder(session) -> dict[str, list[dict]]` (each entry dict now also has `"advance_on_career_entry": bool`; three top-level keys: `enlisted`, `officer`, `officer_academic`)

- [ ] **Step 1: Write failing tests for the restructured ladder**

Add to `backend/app/services/tests/test_rank_advancement.py`:

```python
def test_get_track_kama_is_none():
    assert get_track("קמא") is None


def test_get_next_rank_kama_is_none():
    assert get_next_rank("קמא") is None


def test_get_track_kab_is_officer_academic():
    assert get_track("קאב") == "officer_academic"


def test_get_track_kam_is_officer_academic():
    assert get_track("קאם") == "officer_academic"


def test_get_next_rank_kab_goes_to_kam():
    assert get_next_rank("קאב") == "קאם"


def test_get_next_rank_kam_is_top_of_academic_ladder():
    assert get_next_rank("קאם") is None


def test_regular_officer_ladder_skips_kab_and_kam():
    # סגן -> סרן directly, not via קאב/קאם
    assert get_next_rank("סגן") == "סרן"
    assert get_next_rank("סרן") == "רסן"


def test_get_track_sgan_is_officer_not_academic():
    assert get_track("סגן") == "officer"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && .venv/Scripts/activate && pytest app/services/tests/test_rank_advancement.py -k "kama or kab or kam or regular_officer_ladder or sgan" -v
```

Expected: FAIL (`קמא`/`קאב` resolve to `"officer"` under the current single ladder, or assertions about the old chain order fail).

- [ ] **Step 3: Restructure the ladders**

In `backend/app/services/rank_advancement.py`, replace lines 13-17:

```python
from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS

Track = Literal["enlisted", "officer"]

_LADDERS: dict[Track, list[str]] = {"enlisted": ENLISTED_RANKS, "officer": OFFICER_RANKS}
```

with:

```python
from app.services.eligibility import ENLISTED_RANKS

# eligibility.py's ENLISTED_RANKS/OFFICER_RANKS are rank-VALIDITY lists (used
# for gender/service-type checks, בה"ד 1 inference, RANK_TRACK_COMPATIBILITY)
# and are deliberately left untouched -- a soldier can still hold, and be
# validated as holding, any of those ranks. These ladders below are only the
# ADVANCEMENT chain, which is a different (and narrower) concept: קמא sits
# outside every automated ladder (promoting off it is a manual action), and
# קאב/קאם belong exclusively to the academic officer track now, not the
# regular one -- the same rank name chains to a different "next rank"
# depending on which track the officer is actually on.
ENLISTED_LADDER = ENLISTED_RANKS
OFFICER_LADDER = ["סגמ", "סגן", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף"]
OFFICER_ACADEMIC_LADDER = ["קאב", "קאם"]

Track = Literal["enlisted", "officer", "officer_academic"]

_LADDERS: dict[Track, list[str]] = {
    "enlisted": ENLISTED_LADDER,
    "officer": OFFICER_LADDER,
    "officer_academic": OFFICER_ACADEMIC_LADDER,
}
```

`get_track`/`get_next_rank` (lines 20-35) need no change — they already iterate `_LADDERS` generically.

- [ ] **Step 4: Run to verify pass**

```bash
pytest app/services/tests/test_rank_advancement.py -v
```

Expected: PASS, full file.

- [ ] **Step 5: Write failing tests for `advance_on_career_entry` plumbing**

Add to the same test file:

```python
def test_upsert_interval_persists_advance_on_career_entry(app_session):
    row = upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    assert row.advance_on_career_entry is True
    app_session.flush()
    fetched = app_session.execute(
        select(RankAdvancementInterval).where(RankAdvancementInterval.rank == "קאב")
    ).scalar_one()
    assert fetched.advance_on_career_entry is True


def test_advances_on_career_entry_true(app_session):
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    assert advances_on_career_entry(app_session, track="officer_academic", rank="קאב") is True


def test_advances_on_career_entry_false_when_unconfigured(app_session):
    assert advances_on_career_entry(app_session, track="officer_academic", rank="קאב") is False


def test_get_rank_ladder_has_three_tracks_and_flag(app_session):
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    ladder = get_rank_ladder(app_session)
    assert set(ladder.keys()) == {"enlisted", "officer", "officer_academic"}
    kab_entry = next(e for e in ladder["officer_academic"] if e["rank"] == "קאב")
    assert kab_entry == {"rank": "קאב", "months_to_next": None, "advance_on_career_entry": True}
    assert "קמא" not in [e["rank"] for e in ladder["officer"]]
```

- [ ] **Step 6: Run to verify failure**

```bash
pytest app/services/tests/test_rank_advancement.py -k "advance_on_career_entry or three_tracks" -v
```

Expected: FAIL (`upsert_interval` doesn't accept the kwarg yet; `advances_on_career_entry` doesn't exist).

- [ ] **Step 7: Implement**

In `backend/app/services/rank_advancement.py`, update `upsert_interval` (lines 57-81):

```python
def upsert_interval(
    session: Session, *, track: str, rank: str, months_to_next: int | None,
    advance_on_career_entry: bool, actor_id: uuid.UUID | None,
) -> RankAdvancementInterval:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    before = None if row is None else {
        "months_to_next": row.months_to_next, "advance_on_career_entry": row.advance_on_career_entry,
    }
    if row is None:
        row = RankAdvancementInterval(
            track=track, rank=rank, months_to_next=months_to_next,
            advance_on_career_entry=advance_on_career_entry,
        )
        session.add(row)
    else:
        row.months_to_next = months_to_next
        row.advance_on_career_entry = advance_on_career_entry
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="rank_advancement_interval.upsert",
        entity_type="rank_advancement_interval",
        entity_id=row.id,
        before=before,
        after={"months_to_next": months_to_next, "advance_on_career_entry": advance_on_career_entry},
    )
    return row
```

Update `set_interval_and_recompute` (lines 98-102) to accept and forward the new kwarg:

```python
def set_interval_and_recompute(
    session: Session, *, track: str, rank: str, months_to_next: int | None,
    advance_on_career_entry: bool, actor_id: uuid.UUID | None,
) -> int:
    upsert_interval(
        session, track=track, rank=rank, months_to_next=months_to_next,
        advance_on_career_entry=advance_on_career_entry, actor_id=actor_id,
    )
    return recompute_affected_soldiers(session, track=track, rank=rank)
```

Add a new function, near `get_interval_months`:

```python
def advances_on_career_entry(session: Session, *, track: str, rank: str) -> bool:
    row = session.execute(
        select(RankAdvancementInterval).where(
            RankAdvancementInterval.track == track, RankAdvancementInterval.rank == rank
        )
    ).scalar_one_or_none()
    return row.advance_on_career_entry if row is not None else False
```

Update `get_rank_ladder` (lines 105-111) to include the flag per entry:

```python
def get_rank_ladder(session: Session) -> dict[str, list[dict]]:
    rows = session.execute(select(RankAdvancementInterval)).scalars().all()
    by_key = {(r.track, r.rank): r for r in rows}
    return {
        track: [
            {
                "rank": rank,
                "months_to_next": (row := by_key.get((track, rank))) and row.months_to_next,
                "advance_on_career_entry": bool(row and row.advance_on_career_entry),
            }
            for rank in ladder
        ]
        for track, ladder in _LADDERS.items()
    }
```

(Note: `row and row.months_to_next` evaluates to `None`/falsy `row` correctly since `row` is either `None` or a real row object — double-check this reads cleanly in review; a more explicit `by_key.get(...)` + `if row is not None else None` ternary is equally acceptable if clearer.)

- [ ] **Step 8: Run to verify pass**

```bash
pytest app/services/tests/test_rank_advancement.py -v
```

Expected: PASS, full file.

- [ ] **Step 9: Update the route's `RankIntervalIn` and its call site**

In `backend/app/routes/rank_advancement.py`, add the field to `RankIntervalIn` (line 22-38):

```python
class RankIntervalIn(BaseModel):
    track: Track
    rank: str
    months_to_next: Annotated[int, Field(ge=1)] | None
    advance_on_career_entry: bool = False

    @model_validator(mode="after")
    def _validate_rank_in_track(self) -> "RankIntervalIn":
        if get_track(self.rank) != self.track:
            raise ValueError(f"rank {self.rank!r} is not part of the {self.track!r} ladder")
        return self
```

`Track` already includes `"officer_academic"` after Step 3, so this endpoint's validation automatically accepts it — no other change needed here. Update the `set_interval_and_recompute` call (line 55-62) to forward the new field:

```python
    for item in intervals:
        set_interval_and_recompute(
            session,
            track=item.track,
            rank=item.rank,
            months_to_next=item.months_to_next,
            advance_on_career_entry=item.advance_on_career_entry,
            actor_id=admin.id,
        )
```

- [ ] **Step 10: Write a route-level test**

Add to `backend/app/routes/tests/test_rank_advancement_routes.py`, following the existing tests' style (read one first for the exact client/fixture pattern):

```python
def test_put_rank_advancement_intervals_persists_academic_track_and_flag(client, admin_auth_headers):
    resp = client.put(
        "/api/soldiers/rank-advancement-intervals",
        json=[{"track": "officer_academic", "rank": "קאב", "months_to_next": None, "advance_on_career_entry": True}],
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    entry = next(e for e in resp.json()["officer_academic"] if e["rank"] == "קאב")
    assert entry["advance_on_career_entry"] is True


def test_put_rank_advancement_intervals_rejects_kab_under_officer_track(client, admin_auth_headers):
    # קאב no longer belongs to the regular officer ladder
    resp = client.put(
        "/api/soldiers/rank-advancement-intervals",
        json=[{"track": "officer", "rank": "קאב", "months_to_next": 6, "advance_on_career_entry": False}],
        headers=admin_auth_headers,
    )
    assert resp.status_code == 422
```

Use whatever the file's real fixture names are (`client`/`admin_auth_headers` are placeholders — check the existing tests in this file for the real ones).

- [ ] **Step 11: Run to verify pass**

```bash
pytest app/routes/tests/test_rank_advancement_routes.py -v
```

Expected: PASS, full file.

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/rank_advancement.py backend/app/routes/rank_advancement.py backend/app/services/tests/test_rank_advancement.py backend/app/routes/tests/test_rank_advancement_routes.py
git commit -m "feat: split officer advancement into regular/academic ladders, exclude קמא"
```

---

### Task 3: קבע-entry detection + daily worker integration

**Files:**
- Modify: `backend/app/services/rank_advancement.py` (or a new small helper location — see Step 1)
- Modify: `backend/app/rank_advancement_worker.py`
- Test: `backend/tests/unit/test_rank_advancement_worker.py`

**Interfaces:**
- Consumes: `advances_on_career_entry` (Task 2), `_promote_soldier` (existing, `rank_advancement_worker.py:20-29`).
- Produces: `_career_entry_date(mandatory_end_date, discharge_date) -> date | None` (in `rank_advancement.py`, importable by both the worker and the projection module in Task 4), new worker step `_promote_on_career_entry()`.

- [ ] **Step 1: Write failing tests for `_career_entry_date`**

Add to `backend/app/services/tests/test_rank_advancement.py`:

```python
def test_career_entry_date_day_after_mandatory_end():
    assert _career_entry_date(date(2026, 6, 1), None) == date(2026, 6, 2)


def test_career_entry_date_none_when_no_mandatory_end_date():
    assert _career_entry_date(None, None) is None


def test_career_entry_date_none_when_discharged_before_mandatory_end():
    assert _career_entry_date(date(2026, 6, 1), date(2026, 5, 1)) is None


def test_career_entry_date_present_when_discharge_after_mandatory_end():
    assert _career_entry_date(date(2026, 6, 1), date(2026, 12, 1)) == date(2026, 6, 2)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_rank_advancement.py -k career_entry_date -v
```

Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement `_career_entry_date`**

Append to `backend/app/services/rank_advancement.py` (add `from datetime import timedelta` to the existing `from datetime import date` import):

```python
def _career_entry_date(mandatory_end_date: date | None, discharge_date: date | None) -> date | None:
    """The first calendar day this soldier is career (קבע), or None if they
    never reach it -- mirrors derive_is_career's exact True/False boundary
    (eligibility.py) as a single date instead of a per-call boolean, so it
    can be compared against other candidate advancement dates."""
    if mandatory_end_date is None:
        return None
    if discharge_date is not None and discharge_date <= mandatory_end_date:
        return None
    return mandatory_end_date + timedelta(days=1)
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest app/services/tests/test_rank_advancement.py -v
```

Expected: PASS, full file.

- [ ] **Step 5: Write failing tests for the worker's career-entry promotion step**

Add to `backend/tests/unit/test_rank_advancement_worker.py`, following the existing tests' pattern for direct-session DB-backed tests (read a couple of existing `_promote_due_soldiers`/`_promote_soldier` tests first to match construction style):

```python
def test_promote_on_career_entry_promotes_when_mandatory_end_was_yesterday(app_session):
    from datetime import date
    from app.rank_advancement_worker import _promote_on_career_entry
    from app.services.rank_advancement import upsert_interval
    from tests.helpers import create_soldier

    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    s = create_soldier(app_session, personal_number="p1")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)  # career starts 6/2
    s.discharge_date = None
    s.next_rank_date = date(2099, 1, 1)  # far future -- proves this ISN'T what triggered it
    app_session.flush()

    _promote_on_career_entry(session_scope_override=lambda: app_session, today=date(2026, 6, 2))

    assert s.rank == "קאם"


def test_promote_on_career_entry_does_not_fire_before_mandatory_end(app_session):
    from datetime import date
    from app.rank_advancement_worker import _promote_on_career_entry
    from app.services.rank_advancement import upsert_interval
    from tests.helpers import create_soldier

    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    s = create_soldier(app_session, personal_number="p2")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 12, 1)  # career starts later
    app_session.flush()

    _promote_on_career_entry(session_scope_override=lambda: app_session, today=date(2026, 6, 2))

    assert s.rank == "קאב"


def test_promote_on_career_entry_excludes_discharged_soldier(app_session):
    from datetime import date
    from app.rank_advancement_worker import _promote_on_career_entry
    from app.services.rank_advancement import upsert_interval
    from tests.helpers import create_soldier

    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    s = create_soldier(app_session, personal_number="p3")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)
    s.discharge_date = date(2026, 6, 1)  # discharged at the same time -- never reaches קבע
    app_session.flush()

    _promote_on_career_entry(session_scope_override=lambda: app_session, today=date(2026, 6, 2))

    assert s.rank == "קאב"


def test_promote_on_career_entry_ignores_soldiers_whose_rank_is_not_flagged(app_session):
    from datetime import date
    from app.rank_advancement_worker import _promote_on_career_entry
    from tests.helpers import create_soldier

    s = create_soldier(app_session, personal_number="p4")
    s.rank = "קאב"  # no interval row configured -> advance_on_career_entry defaults False
    s.mandatory_end_date = date(2026, 6, 1)
    app_session.flush()

    _promote_on_career_entry(session_scope_override=lambda: app_session, today=date(2026, 6, 2))

    assert s.rank == "קאב"


def test_promote_on_career_entry_persists_after_session_close(app_session, app_engine):
    # Mirrors the existing session.commit() regression test for
    # _promote_due_soldiers/_warn_upcoming_soldiers -- proves this new step
    # also commits, not just mutates the in-memory session.
    from datetime import date
    from sqlalchemy.orm import sessionmaker
    from app.rank_advancement_worker import _promote_on_career_entry
    from app.services.rank_advancement import upsert_interval
    from tests.helpers import create_soldier

    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    s = create_soldier(app_session, personal_number="p5")
    s.rank = "קאב"
    s.mandatory_end_date = date(2026, 6, 1)
    app_session.flush()
    app_session.commit()
    soldier_id = s.id

    _promote_on_career_entry(today=date(2026, 6, 2))  # real session_scope(), no override

    FreshSession = sessionmaker(bind=app_engine)
    with FreshSession() as fresh:
        from app.db.models import Soldier
        reloaded = fresh.get(Soldier, soldier_id)
        assert reloaded.rank == "קאם"
```

The `session_scope_override` parameter above is a suggested minimal seam for testing without patching module-level state — confirm against how `_promote_due_soldiers`/`_warn_upcoming_soldiers` are actually tested in this file (they use `session_scope` patched via `unittest.mock.patch`, per the existing pattern) and use whichever mechanism matches the file's established convention instead of inventing a new one, adjusting the test calls above accordingly. The important behavioral content of each test (which soldier ends up promoted or not) must be preserved.

- [ ] **Step 6: Run to verify failure**

```bash
pytest tests/unit/test_rank_advancement_worker.py -k career_entry -v
```

Expected: FAIL (`ImportError` — `_promote_on_career_entry` doesn't exist).

- [ ] **Step 7: Implement the worker step**

In `backend/app/rank_advancement_worker.py`, add the import and new function:

```python
from app.services.rank_advancement import (
    compute_next_rank_date, get_next_rank, advances_on_career_entry, _career_entry_date,
)
from app.db.models import RankAdvancementInterval
from sqlalchemy import select as sa_select  # or reuse the existing `select` import if already present
```

(Reconcile with the existing `from sqlalchemy import select` import already in this file — don't duplicate it.)

```python
def _promote_on_career_entry() -> None:
    today = date.today()
    with session_scope() as session:
        flagged = session.execute(
            select(RankAdvancementInterval.track, RankAdvancementInterval.rank).where(
                RankAdvancementInterval.advance_on_career_entry.is_(True)
            )
        ).all()
        if not flagged:
            return
        flagged_ranks = {rank for _track, rank in flagged}
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.rank.in_(flagged_ranks),
                Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
                Soldier.left_at.is_(None) | (Soldier.left_at > today),
            )
        ).scalars().all()
        for s in soldiers:
            entry_date = _career_entry_date(s.mandatory_end_date, s.discharge_date)
            if entry_date is not None and entry_date <= today:
                _promote_soldier(session, s, today=today)
        session.commit()
```

Register it in `run_rank_advancement_worker` (run before the date-due promotion, per the plan's ordering note — promoting first means a soldier's new rank/next_rank_date is already in place before the regular due-date query runs its own fresh pass):

```python
async def run_rank_advancement_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_promote_on_career_entry)
            await asyncio.to_thread(_promote_due_soldiers)
            await asyncio.to_thread(_warn_upcoming_soldiers)
        except Exception:
            logger.warning("rank advancement worker: unhandled error", exc_info=True)
```

Adjust the test-seam parameter (`session_scope_override`) from Step 5 to match whatever you actually implement — if you follow this codebase's existing `unittest.mock.patch("app.rank_advancement_worker.session_scope", ...)` convention instead, remove that parameter from `_promote_on_career_entry`'s signature and update the Step 5 tests to patch `session_scope` the same way the file's other tests already do.

- [ ] **Step 8: Run to verify pass**

```bash
pytest tests/unit/test_rank_advancement_worker.py -v
```

Expected: PASS, full file.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/rank_advancement.py backend/app/rank_advancement_worker.py backend/tests/unit/test_rank_advancement_worker.py backend/app/services/tests/test_rank_advancement.py
git commit -m "feat: promote a soldier immediately on entering קבע when configured, computed live"
```

---

### Task 4: Future-eligibility projection accounts for the early trigger

**Files:**
- Modify: `backend/app/services/rank_eligibility_projection.py`
- Test: `backend/app/services/tests/test_rank_eligibility_projection.py`

**Interfaces:**
- Consumes: `advances_on_career_entry`, `_career_entry_date` (Task 2/3).
- Produces: `project_soldier_state`'s chain-walk now accounts for the early trigger (no new public signature — `interval_cache`'s internal shape changes, which is why the extension happens inside `_load_interval_cache`/`_next_rank_date` rather than at the public API).

**Context:** Read the current `project_soldier_state`/`_next_rank_date`/`_load_interval_cache` in full first (`rank_eligibility_projection.py:31-92`) — this task changes the chain-walk loop body and the interval cache's value shape.

- [ ] **Step 1: Write failing tests**

Add to `backend/app/services/tests/test_rank_eligibility_projection.py`:

```python
def test_project_soldier_state_advances_early_via_career_entry(app_session):
    from app.services.rank_advancement import upsert_interval

    s = create_soldier(app_session, rank="קאב")  # use this file's existing soldier-builder helper
    s.mandatory_end_date = date(2026, 6, 1)  # career starts 6/2
    s.next_rank_date = date(2099, 1, 1)  # scheduled date is far in the future
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    app_session.flush()

    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 2))

    assert state.rank == "קאם"


def test_project_soldier_state_uses_scheduled_date_when_earlier_than_career_entry(app_session):
    from app.services.rank_advancement import upsert_interval

    s = create_soldier(app_session, rank="קאב")
    s.mandatory_end_date = date(2026, 12, 1)  # career starts much later
    s.next_rank_date = date(2026, 3, 1)  # scheduled promotion comes first
    upsert_interval(
        app_session, track="officer_academic", rank="קאב", months_to_next=None,
        advance_on_career_entry=True, actor_id=None,
    )
    app_session.flush()

    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 4, 1))

    assert state.rank == "קאם"  # advanced via the scheduled date, well before career-entry


def test_project_soldier_state_no_early_trigger_when_flag_unset(app_session):
    s = create_soldier(app_session, rank="קאב")
    s.mandatory_end_date = date(2026, 6, 1)
    s.next_rank_date = date(2099, 1, 1)
    app_session.flush()
    # no upsert_interval call -- advance_on_career_entry defaults False

    state = project_soldier_state(app_session, soldier=s, as_of=date(2026, 6, 2))

    assert state.rank == "קאב"  # unchanged -- no trigger configured, scheduled date not reached
```

Also add a test proving the `interval_cache`-driven path (used by `bulk_future_ineligible_duty_blocks`) produces the same result as the uncached path for the career-entry scenario — mirror the existing `test_cached_matches_uncached`-style test already in this file (Task 7 of the original plan added one for `months_to_next` caching; extend it or add a sibling for `advance_on_career_entry`).

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_rank_eligibility_projection.py -k career_entry -v
```

Expected: FAIL (assertions about early advancement don't hold against the current chain-walk).

- [ ] **Step 3: Extend `_load_interval_cache`'s value shape and `project_soldier_state`'s loop**

In `backend/app/services/rank_eligibility_projection.py`, change the cache's value type from `int | None` (bare `months_to_next`) to a small tuple/dataclass carrying both fields, everywhere it's threaded through. Update the type alias used across the file:

```python
IntervalCacheEntry = tuple[int | None, bool]  # (months_to_next, advance_on_career_entry)
```

Update `_load_interval_cache`:

```python
def _load_interval_cache(session: Session) -> dict[tuple[str, str], IntervalCacheEntry]:
    """The whole RankAdvancementInterval table (at most ~30 rows) as a dict."""
    rows = session.execute(select(RankAdvancementInterval)).scalars().all()
    return {(r.track, r.rank): (r.months_to_next, r.advance_on_career_entry) for r in rows}
```

Update `_next_rank_date` to unpack the tuple instead of using the bare int:

```python
def _next_rank_date(
    session: Session, *, rank: str, since: date, interval_cache: dict[tuple[str, str], IntervalCacheEntry] | None,
) -> date | None:
    """compute_next_rank_date, but served from `interval_cache` when provided."""
    if interval_cache is None:
        return compute_next_rank_date(session, rank=rank, since=since)
    track = get_track(rank)
    if track is None:
        return None
    entry = interval_cache.get((track, rank))
    if entry is None:
        return None
    months, _advance_on_career_entry = entry
    if months is None:
        return None
    return since + relativedelta(months=months)
```

Add a small helper mirroring `advances_on_career_entry` but cache-aware:

```python
def _advances_on_career_entry(
    session: Session, *, rank: str, interval_cache: dict[tuple[str, str], IntervalCacheEntry] | None,
) -> bool:
    track = get_track(rank)
    if track is None:
        return False
    if interval_cache is not None:
        entry = interval_cache.get((track, rank))
        return entry[1] if entry is not None else False
    return advances_on_career_entry(session, track=track, rank=rank)
```

Add the import: `from app.services.rank_advancement import (compute_next_rank_date, get_next_rank, get_track, advances_on_career_entry, _career_entry_date)`.

Update the chain-walk in `project_soldier_state` (lines 48-57):

```python
    rank = soldier.rank
    next_date = soldier.next_rank_date
    for _ in range(_MAX_CHAIN_STEPS):
        if rank is None:
            break
        next_rank = get_next_rank(rank)
        if next_rank is None:
            break
        effective_date = next_date
        if _advances_on_career_entry(session, rank=rank, interval_cache=interval_cache):
            entry_date = _career_entry_date(soldier.mandatory_end_date, soldier.discharge_date)
            if entry_date is not None and (effective_date is None or entry_date < effective_date):
                effective_date = entry_date
        if effective_date is None or effective_date > as_of:
            break
        rank = next_rank
        next_date = _next_rank_date(session, rank=rank, since=effective_date, interval_cache=interval_cache)
```

Note the loop's shape changed slightly: the old version checked `next_date is None or next_date > as_of` as its very first break condition; the new version must compute `effective_date` (which may come from the career-entry path even when `next_date` is `None`) BEFORE that check. Read the diff carefully against the original to confirm no soldier with `next_rank_date = None` but a career-entry-flagged current rank is incorrectly skipped.

Update `bulk_future_ineligible_duty_blocks`'s docstring/comment where it says the interval cache holds `months_to_next` values (around line 238-241) to reflect the new tuple shape — a one-line wording fix, not a behavior change there.

- [ ] **Step 4: Run to verify pass**

```bash
pytest app/services/tests/test_rank_eligibility_projection.py -v
```

Expected: PASS, full file — this is the highest-risk change in the plan (core chain-walk loop used by both the solver and the manual-check path), so also run:

```bash
pytest -m algorithm -q
```

Expected: PASS, no regressions in solver-side tests that exercise `bulk_future_ineligible_duty_blocks`/`project_soldier_state` indirectly.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rank_eligibility_projection.py backend/app/services/tests/test_rank_eligibility_projection.py
git commit -m "feat: project_soldier_state accounts for קבע-entry early promotion trigger"
```

---

### Task 5: Frontend — types, three-track picker completeness

**Files:**
- Modify: `frontend/src/api/rankAdvancement.ts`
- Modify: `frontend/src/constants/ranks.ts`
- Test: `frontend/src/constants/ranks.test.ts`
- Test: `frontend/src/api/rankAdvancement.test.ts`

**Interfaces:**
- Produces: `RankTrack = "enlisted" | "officer" | "officer_academic"`, `RankLadderEntry.advance_on_career_entry: boolean`, `RankIntervalUpdate.advance_on_career_entry: boolean`, `useRankLadder()`/`usePublicRankLadder()`'s `officerRanks`/`allRanks` include קמא and the academic ladder.

**Context:** After Task 2, the backend's `GET /soldiers/rank-ladder` response no longer includes קמא anywhere, and קאב/קאם move to a new `officer_academic` key. `ranks.ts`'s private (unexported) `OFFICER_RANKS` array — used for `isOfficerRank`/`RANK_TRACK_COMPATIBILITY`/`deriveBahad1Graduate`/`deriveIsCareer` — is a separate, deliberately-unchanged rank-*validity* list (mirrors `eligibility.py`'s untouched `OFFICER_RANKS`) and still includes all 12 officer ranks including קמא/קאב/קאם. Do not touch it. The issue is narrower: `withLadderFields`'s derived `officerRanks`/`allRanks` (used to populate rank-picker dropdowns in `RegisterPage`/`EnrollmentApprovalModal`) is built purely from the fetched ladder response, so once קמא/קאב/קאם leave the `officer` group, those pickers would silently lose three valid, assignable rank options.

- [ ] **Step 1: Write failing tests**

Add to `frontend/src/api/rankAdvancement.test.ts` (following the existing tests' mocking pattern):

```typescript
test("getRankLadder response includes officer_academic and advance_on_career_entry", async () => {
  // mock the api client's GET to return a three-track shape with the new field,
  // matching this file's existing mocking convention
  const ladder = await getRankLadder();
  expect(ladder.officer_academic).toBeDefined();
});
```

Add to `frontend/src/constants/ranks.test.ts`:

```typescript
test("useRankLadder's officerRanks includes קמא even though it's absent from the ladder response", () => {
  // mock the query to resolve with officer=[סגמ,...], officer_academic=[קאב,קאם], no קמא anywhere
  // assert officerRanks/allRanks from the hook's return value include "קמא"
});

test("useRankLadder's officerRanks includes both officer and officer_academic ranks", () => {
  // same mock shape -- assert officerRanks includes both "סגמ" (regular) and "קאב" (academic)
});
```

Write the actual mocking mechanics to match this file's existing test setup exactly (check how the current tests mock `useQuery`/the API call) rather than inventing a new pattern.

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && npm test -- --run rankAdvancement ranks
```

Expected: FAIL.

- [ ] **Step 3: Update the types**

In `frontend/src/api/rankAdvancement.ts`:

```typescript
export type RankTrack = "enlisted" | "officer" | "officer_academic";

export interface RankLadderEntry {
  rank: string;
  months_to_next: number | null;
  advance_on_career_entry: boolean;
}

export interface RankLadder {
  enlisted: RankLadderEntry[];
  officer: RankLadderEntry[];
  officer_academic: RankLadderEntry[];
}

export interface RankIntervalUpdate {
  track: RankTrack;
  rank: string;
  months_to_next: number | null;
  advance_on_career_entry: boolean;
}
```

- [ ] **Step 4: Fix picker completeness in `ranks.ts`**

In `frontend/src/constants/ranks.ts`, add a small explicit constant near the top (after the existing `OFFICER_RANKS` block) noting why it exists:

```typescript
// קמא sits outside every advancement ladder (see rank_advancement.py) --
// promoting off it is a manual action, not automated -- so it never appears
// in the /rank-ladder response. It's still a fully valid, assignable rank,
// so pickers built from the ladder response need it added back explicitly.
const UNLADDERED_OFFICER_RANKS = ["קמא"];
```

Update `withLadderFields` (currently lines 101-111) to reunite קמא and the academic ladder into the picker lists:

```typescript
function withLadderFields<T extends { data?: RankLadder }>(query: T) {
  const enlistedRanks = query.data?.enlisted.map((e) => e.rank) ?? [];
  const officerRanks = query.data
    ? [
        ...UNLADDERED_OFFICER_RANKS,
        ...query.data.officer.map((e) => e.rank),
        ...query.data.officer_academic.map((e) => e.rank),
      ]
    : [];
  return {
    ...query,
    ladder: query.data,
    enlistedRanks,
    officerRanks,
    allRanks: [...enlistedRanks, ...officerRanks],
  };
}
```

- [ ] **Step 5: Run to verify pass**

```bash
npm test -- --run rankAdvancement ranks
npm run typecheck
```

Expected: PASS. Typecheck will also surface every other place `RankLadder`/`RankLadderEntry`/`RankIntervalUpdate` is used with a now-incomplete shape (Task 6 fixes `SystemSettingsPage.tsx`) — expect typecheck errors there until Task 6 lands; that's fine, it's the next task.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/rankAdvancement.ts frontend/src/constants/ranks.ts frontend/src/api/rankAdvancement.test.ts frontend/src/constants/ranks.test.ts
git commit -m "feat: add officer_academic track and advance_on_career_entry to frontend types"
```

---

### Task 6: Frontend — admin UI (three groups, checkbox, tooltip)

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `frontend/src/pages/SystemSettingsPage.test.tsx`

**Interfaces:**
- Consumes: Task 5's three-track `RankLadder`/`RankIntervalUpdate` shape.

**Context:** Read `RankAdvancementIntervalsSection` in full first (`SystemSettingsPage.tsx:616-745`) — every place it hardcodes `["enlisted", "officer"] as const` needs the third value, `draftKey` needs to also carry the checkbox's draft state, and a new checkbox + tooltip-icon column is added per row.

- [ ] **Step 1: Write failing tests**

Add to `frontend/src/pages/SystemSettingsPage.test.tsx`, following the existing `RankAdvancementIntervalsSection` tests' setup (mock `getRankLadder` to resolve with a three-track payload including `officer_academic`):

```typescript
test("renders a group for the academic officer track", async () => {
  // mock getRankLadder to include officer_academic: [{rank: "קאב", months_to_next: null, advance_on_career_entry: false}, ...]
  // render SystemSettingsPage, wait for the ladder to load
  // assert a "קאב" row is visible
});

test("toggling the career-entry checkbox and saving includes it in the PUT payload", async () => {
  // mock getRankLadder as above; mock updateRankAdvancementIntervals to capture its argument
  // render, find the קאב row's checkbox, click it, click save
  // assert the captured payload includes {track: "officer_academic", rank: "קאב", advance_on_career_entry: true, ...}
});

test("career-entry tooltip icon is present with explanatory text", async () => {
  // render; assert an element with the explanatory title/text is present near the checkbox column header
});
```

Write the actual RTL query mechanics matching this test file's existing conventions (how it renders the page, mocks React Query, finds elements) rather than inventing new patterns.

- [ ] **Step 2: Run to verify failure**

```bash
npm test -- --run SystemSettingsPage
```

Expected: FAIL.

- [ ] **Step 3: Implement**

In `frontend/src/pages/SystemSettingsPage.tsx`, import the `HelpCircle` icon (already used elsewhere in this codebase, e.g. `SwapsPage.tsx` — same import source) alongside the existing imports for this section.

Update `TRACK_LABELS` (line 622):

```typescript
const TRACK_LABELS: Record<RankTrack, string> = {
  enlisted: "חיילים",
  officer: "קצינים",
  officer_academic: "קצינים אקדמאים",
};
const TRACKS = ["enlisted", "officer", "officer_academic"] as const;
```

Replace every literal `["enlisted", "officer"] as const` in this section (lines 638, 661, 676, 713) with `TRACKS`.

Change the draft state shape to also carry the checkbox — simplest: keep `draft` keyed by `draftKey(track, rank)` but store a small object instead of a bare number:

```typescript
interface DraftEntry {
  months_to_next: number | "";
  advance_on_career_entry: boolean;
}

const [draft, setDraft] = useState<Record<string, DraftEntry>>({});
```

Update the `useEffect` that seeds `draft` from `ladderQuery.data` (lines 635-644):

```typescript
  useEffect(() => {
    if (!ladderQuery.data) return;
    const next: Record<string, DraftEntry> = {};
    for (const track of TRACKS) {
      for (const entry of ladderQuery.data[track]) {
        next[draftKey(track, entry.rank)] = {
          months_to_next: entry.months_to_next ?? "",
          advance_on_career_entry: entry.advance_on_career_entry,
        };
      }
    }
    setDraft(next);
  }, [ladderQuery.data]);
```

Update `setValue` to take a field discriminator (or split into two setters — `setMonthsValue`/`setCareerEntryValue` — implementer's call, whichever reads cleaner in this file's existing style):

```typescript
  function setMonthsValue(track: RankTrack, rank: string, raw: string) {
    setDraft(prev => ({
      ...prev,
      [draftKey(track, rank)]: {
        ...prev[draftKey(track, rank)],
        months_to_next: raw === "" ? "" : Number(raw),
      },
    }));
    setSaved(false);
  }

  function setCareerEntryValue(track: RankTrack, rank: string, checked: boolean) {
    setDraft(prev => ({
      ...prev,
      [draftKey(track, rank)]: {
        ...prev[draftKey(track, rank)],
        advance_on_career_entry: checked,
      },
    }));
    setSaved(false);
  }
```

Update `handleSave` (lines 659-672):

```typescript
  function handleSave() {
    if (!ladderQuery.data) return;
    const intervals: RankIntervalUpdate[] = TRACKS.flatMap(track =>
      ladderQuery.data![track].map(entry => {
        const d = draft[draftKey(track, entry.rank)];
        return {
          track,
          rank: entry.rank,
          months_to_next: !d || d.months_to_next === "" ? null : Number(d.months_to_next),
          advance_on_career_entry: d?.advance_on_career_entry ?? false,
        };
      }),
    );
    saveMutation.mutate(intervals);
  }
```

Update the `serverDraft`/`isDirty` comparison block (lines 674-682) to build the same `DraftEntry` shape for comparison.

Add the checkbox + tooltip column to the table header and each row (lines 716-741):

```typescript
              <tr className="text-gray-500 dark:text-gray-400 text-xs">
                <th className="text-right py-1 font-normal">דרגה</th>
                <th className="text-right py-1 font-normal">חודשים לדרגה הבאה</th>
                <th className="text-right py-1 font-normal">
                  <span className="inline-flex items-center gap-1">
                    קידום עם כניסה לקבע
                    <HelpCircle
                      size={14}
                      title="אם מסומן, החייל יקודם אוטומטית לדרגה הבאה ברגע שהוא נכנס לשירות קבע, גם אם התאריך המתוכנן לקידום לדרגה זו עדיין לא הגיע."
                      className="text-gray-400"
                    />
                  </span>
                </th>
              </tr>
```

```typescript
              {(ladderQuery.data?.[track] ?? []).map(entry => (
                <tr key={entry.rank} className="border-t dark:border-gray-700">
                  <td className="py-1 text-gray-800 dark:text-gray-100">{entry.rank}</td>
                  <td className="py-1">
                    <input
                      type="number"
                      min="1"
                      value={String(draft[draftKey(track, entry.rank)]?.months_to_next ?? "")}
                      onChange={e => setMonthsValue(track, entry.rank, e.target.value)}
                      className="w-28 border rounded px-2 py-1 text-sm text-right dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      dir="ltr"
                    />
                  </td>
                  <td className="py-1">
                    <input
                      type="checkbox"
                      checked={draft[draftKey(track, entry.rank)]?.advance_on_career_entry ?? false}
                      onChange={e => setCareerEntryValue(track, entry.rank, e.target.checked)}
                    />
                  </td>
                </tr>
              ))}
```

(Note `min="1"` here, not `min="0"` — matches the backend's `Field(ge=1)` validation, closing the pre-existing minor gap noted in the shipped feature's final review where the input still advertised `0` as valid despite the backend rejecting it.)

- [ ] **Step 4: Run to verify pass**

```bash
npm test -- --run SystemSettingsPage
npm run typecheck
npm run lint
```

Expected: PASS, zero lint warnings.

- [ ] **Step 5: Manual verification note**

If a dev server can be safely started against this worktree without port-conflicting another running instance (check before starting — see the shipped feature's Task 12 for the same caution), verify visually: three track sections render, the tooltip icon shows the Hebrew explanation on hover, saving with the checkbox toggled round-trips correctly. If not safely startable, say so explicitly rather than claiming a live check — the RTL test coverage from Steps 1-4 is the fallback evidence, same precedent as the shipped feature's Task 12.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx frontend/src/pages/SystemSettingsPage.test.tsx
git commit -m "feat: admin UI for academic officer track and career-entry auto-promotion checkbox"
```

---

## Self-Review Notes

- **Spec coverage:** ladder restructuring with קמא excluded (Task 2), `advance_on_career_entry` config field (Task 1-2), live קבע-entry detection with no stored-state dependency (Task 3), worker integration (Task 3), projection integration (Task 4), frontend types + picker completeness (Task 5), admin UI with tooltip (Task 6).
- Picker completeness (`UNLADDERED_OFFICER_RANKS`, Task 5) is a consequence the spec didn't spell out explicitly but is a direct requirement of removing קמא/קאב/קאם from the ladder response while `RegisterPage`/`EnrollmentApprovalModal` still need to offer all 12 officer ranks as selectable — flagged clearly in Task 5's Context section so the implementer understands why, not just what.
- `IntervalCacheEntry`'s shape change (Task 4) is the plan's highest-risk edit — it touches the exact chain-walk loop shared by the CP-SAT solver and the manual-assignment check. The step explicitly calls out the loop's restructured break condition and asks the implementer to diff carefully against the original.
- Every task's tests use `tests.helpers.create_soldier`'s real signature (`personal_number` required, `rank` set as a plain attribute afterward) and existing fixture/mocking conventions per file, matching the pattern established throughout the already-shipped rank-advancement work on this branch's ancestor commits — implementers should still verify against the live files, since exact fixture names are noted as "confirm against the real file" rather than guessed outright in a few places (route test fixtures in Task 2, RTL mocking mechanics in Tasks 5-6).
