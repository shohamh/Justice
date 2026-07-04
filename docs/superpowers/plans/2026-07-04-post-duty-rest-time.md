# Post-Duty Rest Time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a minimum rest period (default 12h, configurable globally and per duty type) between a soldier's duties, both in the CP-SAT auto-scheduler and in manual assignment creation — and, when a soldier is dismissed early and never returns to a duty, count that rest from the dismissal moment instead of the duty's scheduled end.

**Architecture:** A new pure `backend/app/algorithm/rest.py` module provides DB-free rest-window math reused by both the CP-SAT model and the DB-facing `backend/app/services/rest.py` (which resolves rest-hours settings and computes a duty assignment's dismissal-aware "effective end"). The CP-SAT solver (`backend/app/algorithm/model.py`) gets a new hard constraint using pre-resolved `rest_hours`/effective-end fields carried on `DutyBlock`/`ExistingAssignment` (populated by `algorithm_bridge.py`, keeping the pure algorithm package DB-free). The manual assignment path (`backend/app/services/assignments.py`) gets an analogous rest check. The existing gimelim (reserve dismissal) flow is fixed to compute its rest window from the actual dismissal date instead of the assignment's nominal `end_date`, and its existing `gimalim.default_rest_days` setting becomes an *additional* buffer stacked on top of the new base rest.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, OR-Tools CP-SAT, pytest; React/TypeScript frontend (no new libraries).

## Global Constraints

- Default base rest: 12 hours. System setting key `duty.default_rest_hours` (fallback default `12`), read via `get_setting_int`.
- Per-duty-type override: `DutyType.requirements["rest_hours"]` (int, hours). Falls back to the global default when absent.
- `DutyDismissal.dismissed_to` can never equal or exceed `assignment.end_date` (enforced today by `dismiss_primary`, `backend/app/services/reserves.py:69`). Since `end_date` is exclusive, "the soldier never returns" is `dismissed_to >= last_duty_day(assignment)`, i.e. `dismissed_to >= assignment.end_date - timedelta(days=1)` for multi-day assignments (see `last_duty_day` in Task 2).
- When a dismissal is permanent (per above), the effective end for rest purposes is `dismissed_from` combined with the assignment's own `start_time` (conservative: assume dismissal happened at shift-start that day).
- `gimalim.default_rest_days` (existing setting, default `7`) keeps its key and default value but becomes "extra days stacked on top of base rest_hours for gimelim dismissals," not a standalone rule.
- No new DB migrations: `DutyDismissal`, `DutyType.requirements` (JSONB), and `SystemSetting` (JSONB key/value) already support everything this feature needs.
- The CP-SAT rest constraint is **hard** (never violated by the solver), matching the existing no-overlap constraint's enforcement style.
- Rest applies to every duty-to-duty transition, not just dismissals — the dismissal case only changes *which moment* counts as "the end."

---

### Task 1: Shared `get_setting_int` helper

**Files:**
- Modify: `backend/app/services/settings_loader.py`
- Test: `backend/tests/unit/test_settings_loader.py`

**Interfaces:**
- Produces: `get_setting_int(session: Session, key: str, default: int) -> int` — reads an int-valued system setting, falling back to `default` if the key is missing. Used by Task 4 (services/rest.py) and Task 7 (gimelim.py).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_settings_loader.py`:

```python
from app.services.settings_loader import SettingNotFound, get_setting, get_setting_int, set_setting


def test_get_setting_int_returns_value(admin_session):
    assert get_setting_int(admin_session, "auth.session_minutes", 999) == 15


def test_get_setting_int_falls_back_to_default(admin_session):
    assert get_setting_int(admin_session, "does.not.exist", 42) == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_settings_loader.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_setting_int'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/settings_loader.py`, add after `get_setting`:

```python
def get_setting_int(session: Session, key: str, default: int) -> int:
    try:
        return int(get_setting(session, key))
    except SettingNotFound:
        return default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_settings_loader.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/settings_loader.py backend/tests/unit/test_settings_loader.py
git commit -m "feat: add shared get_setting_int helper"
```

---

### Task 2: Pure rest-window math (`algorithm/rest.py`)

**Files:**
- Create: `backend/app/algorithm/rest.py`
- Test: `backend/tests/unit/test_algorithm_rest.py`

**Interfaces:**
- Consumes: `combine_date_time(d: date, hhmm: str) -> datetime` from `backend/app/algorithm/duration.py:7` (already exists).
- Produces: `last_duty_day(start_date: date, end_date: date) -> date` and `rest_violated(prior_end_dt: datetime, next_start_date: date, next_start_time: str, rest_hours: int) -> bool`. Used by Task 3 (model.py) and Task 4 (services/rest.py).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_algorithm_rest.py`:

```python
from __future__ import annotations

from datetime import date, datetime

from app.algorithm.rest import last_duty_day, rest_violated


def test_last_duty_day_multi_day_exclusive_end():
    # A duty spanning [2026-06-01, 2026-06-04) touches 06-01, 06-02, 06-03.
    assert last_duty_day(date(2026, 6, 1), date(2026, 6, 4)) == date(2026, 6, 3)


def test_last_duty_day_single_day_sentinel():
    # start_date == end_date is used as a single-day sentinel by some callers.
    assert last_duty_day(date(2026, 6, 1), date(2026, 6, 1)) == date(2026, 6, 1)


def test_rest_satisfied_8am_to_5pm_then_8am_next_day():
    """Explicit scenario from the design spec: a duty ending at 17:00, followed
    by another starting at 08:00 the next day, is a 15h gap — satisfies a 12h
    rest requirement with no extra blocked days."""
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 2), "08:00", rest_hours=12) is False


def test_rest_violated_same_day_start():
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 1), "18:00", rest_hours=12) is True


def test_rest_violated_next_day_too_early():
    """5pm to 6am next day is only a 13h gap... but 5pm to 5:30am is 12.5h — still
    fine. Push it under 12h: 5pm to 4am next day is 11h — violated."""
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 2), "04:00", rest_hours=12) is True


def test_rest_hours_zero_never_violated():
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 1), "17:01", rest_hours=0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_algorithm_rest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.algorithm.rest'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/algorithm/rest.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.algorithm.duration import combine_date_time


def last_duty_day(start_date: date, end_date: date) -> date:
    """The last calendar day actually touched by a duty. `end_date` is
    exclusive for multi-day duties (see duration.calendar_days_touched); for
    single-day sentinel duties where start_date == end_date (used by some
    test/call sites), the day itself is the last day."""
    return end_date - timedelta(days=1) if end_date > start_date else end_date


def rest_violated(
    prior_end_dt: datetime,
    next_start_date: date,
    next_start_time: str,
    rest_hours: int,
) -> bool:
    """True if starting a duty at (next_start_date, next_start_time) does not
    leave `rest_hours` of rest after `prior_end_dt`. rest_hours <= 0 means no
    rest requirement (never violated)."""
    if rest_hours <= 0:
        return False
    next_start_dt = combine_date_time(next_start_date, next_start_time)
    return next_start_dt < prior_end_dt + timedelta(hours=rest_hours)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_algorithm_rest.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/rest.py backend/tests/unit/test_algorithm_rest.py
git commit -m "feat: add pure rest-window math for duty scheduling"
```

---

### Task 3: CP-SAT hard rest constraint

**Files:**
- Modify: `backend/app/algorithm/types.py:47-73` (`DutyBlock`, `ExistingAssignment`)
- Modify: `backend/app/algorithm/model.py:388-403` (insert new constraint block after existing no-overlap constraint)
- Test: `backend/tests/unit/test_model.py`

**Interfaces:**
- Consumes: `last_duty_day`, `rest_violated` from Task 2 (`app.algorithm.rest`); `combine_date_time` from `app.algorithm.duration`.
- Produces: `DutyBlock.rest_hours: int = 0` (rest required after this duty); `ExistingAssignment.rest_hours: int = 0`, `ExistingAssignment.rest_effective_end_date: date | None = None`, `ExistingAssignment.rest_effective_end_time: str = "23:59"`. All default to values that impose no constraint, so every existing caller/test of `build_model` is unaffected unless it opts in. Used by Task 5 (`algorithm_bridge.py`).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_model.py` (reuses the `_soldier`, `_duty`, `_solve` helpers already in the file):

```python
def test_rest_allows_next_day_start_with_enough_gap():
    """Matches the design spec's explicit scenario: a duty ending 17:00,
    followed by another starting 08:00 the next day (15h gap), must NOT be
    blocked by a 12h rest requirement — both go to the same soldier."""
    solo = _soldier(0.0)
    d1 = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2),
        start_time="08:00", end_time="17:00",
        score_per_day=Decimal("1.0"), rest_hours=12,
    )
    d2 = DutyBlock(
        id=uuid.uuid4(), duty_type_id=d1.duty_type_id, duty_location_id=uuid.uuid4(),
        start_date=date(2026, 9, 2), end_date=date(2026, 9, 3),
        start_time="08:00", end_time="17:00",
        score_per_day=Decimal("1.0"), rest_hours=12,
    )
    assigned = _solve([solo], [d1, d2], T=7, Wt=14, Wr=28, alpha=Decimal("0"))
    assert assigned[d1.id] == solo.id
    assert assigned[d2.id] == solo.id


def test_rest_blocks_insufficient_gap_between_candidates():
    """Two candidate duties with only an 11h gap cannot both go to the same
    soldier when rest_hours=12 — but with 2 soldiers, they're split."""
    s1, s2 = _soldier(0.0), _soldier(0.0)
    d1 = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2),
        start_time="08:00", end_time="17:00",
        score_per_day=Decimal("1.0"), rest_hours=12,
    )
    d2 = DutyBlock(
        id=uuid.uuid4(), duty_type_id=d1.duty_type_id, duty_location_id=uuid.uuid4(),
        start_date=date(2026, 9, 2), end_date=date(2026, 9, 3),
        start_time="04:00", end_time="12:00",
        score_per_day=Decimal("1.0"), rest_hours=12,
    )
    assigned = _solve([s1, s2], [d1, d2], T=7, Wt=14, Wr=28, alpha=Decimal("0"))
    assert assigned[d1.id] != assigned[d2.id]


def test_rest_blocks_candidate_against_existing_assignment():
    """An existing (published) assignment ending at 17:00 blocks a candidate
    starting at 04:00 the next day (11h gap) for that same soldier."""
    solo = _soldier(0.0)
    existing = [
        ExistingAssignment(
            soldier_id=solo.id,
            duty_type_id=uuid.uuid4(),
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            rest_hours=12,
            rest_effective_end_date=date(2026, 9, 1),
            rest_effective_end_time="17:00",
        )
    ]
    candidate = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date(2026, 9, 2), end_date=date(2026, 9, 3),
        start_time="04:00", end_time="12:00",
        score_per_day=Decimal("1.0"),
    )
    settings = SolverSettings(T=7, Wt=14, Wr=28, alpha=Decimal("0"))
    model, x = build_model([solo], [candidate], existing, settings)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    assert solver.StatusName(status) in ("OPTIMAL", "FEASIBLE")
    assert (0, 0) in x, "candidate should be eligible (just blocked by rest, not excluded upstream)"
    assert solver.Value(x[(0, 0)]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_model.py -k rest -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'rest_hours'` (dataclasses don't have the field yet).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/algorithm/types.py`, extend `DutyBlock` (around line 47-63) by adding one field at the end:

```python
@dataclass
class DutyBlock:
    """A duty block (shift) to be assigned to a soldier."""
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    score_per_day: Decimal
    is_reserve: bool = False
    eligible_node_ids: list[uuid.UUID] | None = None
    start_time: str = "00:00"
    end_time: str = "23:59"
    node_quotas: dict[uuid.UUID, int] | None = None
    # Hours of rest required after this duty ends before the same soldier can
    # start another. 0 = no rest requirement (default, safe for existing callers).
    rest_hours: int = 0
```

Extend `ExistingAssignment` (around line 66-73):

```python
@dataclass
class ExistingAssignment:
    """An already-published assignment for min_gap continuity."""
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date
    is_reserve: bool = False
    # Rest-window fields (all default to "no constraint" for existing callers).
    # rest_effective_end_date/time already account for an early dismissal —
    # see backend/app/services/rest.py:effective_assignment_end.
    rest_hours: int = 0
    rest_effective_end_date: date | None = None
    rest_effective_end_time: str = "23:59"
```

In `backend/app/algorithm/model.py`, add to the imports (near the existing `app.algorithm.types` import):

```python
from app.algorithm.rest import last_duty_day, rest_violated
```

Insert this new block immediately after the existing "Hard constraint 2: No overlap" loop (after line 403, before the "Count-space effort" section comment):

```python
    # Hard constraint 2b: Rest time — a soldier needs each duty's `rest_hours`
    # of rest between that duty's effective end and the start of their next
    # duty (existing or newly assigned in this same run).
    for si, s in enumerate(soldier_list):
        si_duties = soldier_duties.get(si, [])
        if not si_duties:
            continue

        # Existing (published) assignments block candidates outright — they
        # are fixed, not decision variables.
        for ea in existing:
            if ea.soldier_id != s.id or ea.rest_effective_end_date is None:
                continue
            prior_end_dt = combine_date_time(ea.rest_effective_end_date, ea.rest_effective_end_time)
            for di in si_duties:
                d = duty_list[di]
                if rest_violated(prior_end_dt, d.start_date, d.start_time, ea.rest_hours):
                    model.Add(x[(di, si)] == 0)

        # Candidate-vs-candidate: at most one of a pair too close together can
        # be chosen for this soldier. Bounded lookahead (based on rest_hours)
        # keeps this from becoming an O(n^2) scan over unrelated duties.
        sorted_duties = sorted(si_duties, key=lambda di: duty_list[di].start_date)
        for a_pos, di_a in enumerate(sorted_duties):
            d_a = duty_list[di_a]
            if d_a.rest_hours <= 0:
                continue
            end_day_a = last_duty_day(d_a.start_date, d_a.end_date)
            prior_end_dt = combine_date_time(end_day_a, d_a.end_time)
            lookahead_days = -(-d_a.rest_hours // 24) + 1  # ceil(rest_hours/24) + 1 buffer day
            for di_b in sorted_duties[a_pos + 1:]:
                d_b = duty_list[di_b]
                if d_b.start_date > end_day_a + timedelta(days=lookahead_days):
                    break
                if rest_violated(prior_end_dt, d_b.start_date, d_b.start_time, d_a.rest_hours):
                    model.Add(x[(di_a, si)] + x[(di_b, si)] <= 1)
```

Also add the `combine_date_time` import in `model.py`:

```python
from app.algorithm.duration import combine_date_time, score_days
```

(replacing the existing `from app.algorithm.duration import score_days` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_model.py -v`
Expected: PASS (all tests, including the 3 new ones and every pre-existing test in the file — the new fields default to no-constraint).

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/algorithm/model.py backend/tests/unit/test_model.py
git commit -m "feat: enforce minimum rest between duties in CP-SAT solver"
```

---

### Task 4: DB-facing rest resolution (`services/rest.py`)

**Files:**
- Create: `backend/app/services/rest.py`
- Test: `backend/tests/unit/test_rest_service.py`

**Interfaces:**
- Consumes: `get_setting_int` (Task 1), `last_duty_day` (Task 2), `combine_date_time` (`app.algorithm.duration`), `DutyAssignment`/`DutyDismissal`/`DutyType` models.
- Produces: `resolve_rest_hours(duty_type: DutyType, default_rest_hours: int) -> int`; `effective_assignment_end(session: Session, assignment: DutyAssignment) -> datetime`; `earliest_eligible_date(effective_end_dt: datetime, rest_hours: int, extra_days: int = 0) -> date`. Used by Task 5 (`algorithm_bridge.py`) and Task 7 (`gimelim.py`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_rest_service.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyType
from app.services.rest import (
    earliest_eligible_date,
    effective_assignment_end,
    resolve_rest_hours,
)
from tests.helpers import create_soldier


def _make_assignment(session, *, start, end, start_time="08:00", end_time="17:00"):
    dt = DutyType(name=f"dt-{start.isoformat()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc-{start.isoformat()}")
    session.add_all([dt, loc])
    session.flush()
    s = create_soldier(session, personal_number=f"81{start.day:05d}")
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start, end_date=end, start_time=start_time, end_time=end_time,
        status="published",
    )
    session.add(a)
    session.flush()
    return a, dt


def test_resolve_rest_hours_uses_type_override():
    dt = DutyType(name="dt-override", score_per_day=Decimal("1.00"), requirements={"rest_hours": 8})
    assert resolve_rest_hours(dt, default_rest_hours=12) == 8


def test_resolve_rest_hours_falls_back_to_default():
    dt = DutyType(name="dt-no-override", score_per_day=Decimal("1.00"))
    assert resolve_rest_hours(dt, default_rest_hours=12) == 12


def test_effective_end_normal_assignment(admin_session):
    a, _ = _make_assignment(admin_session, start=date(2026, 6, 1), end=date(2026, 6, 4))
    admin_session.flush()
    end_dt = effective_assignment_end(admin_session, a)
    # last_duty_day(06-01, 06-04) == 06-03, at end_time 17:00
    assert end_dt.isoformat() == "2026-06-03T17:00:00"


def test_effective_end_uses_dismissal_when_soldier_never_returns(admin_session):
    a, _ = _make_assignment(admin_session, start=date(2026, 6, 1), end=date(2026, 6, 5))
    admin_session.flush()
    # Dismissed from 06-03 through 06-04 (the last duty day) — never returns.
    dismissal = DutyDismissal(
        duty_assignment_id=a.id, dismissed_from=date(2026, 6, 3), dismissed_to=date(2026, 6, 4),
    )
    admin_session.add(dismissal)
    admin_session.flush()
    end_dt = effective_assignment_end(admin_session, a)
    # dismissed_from (06-03) combined with the assignment's start_time (08:00)
    assert end_dt.isoformat() == "2026-06-03T08:00:00"


def test_effective_end_ignores_temporary_dismissal_with_return(admin_session):
    a, _ = _make_assignment(admin_session, start=date(2026, 6, 1), end=date(2026, 6, 10))
    admin_session.flush()
    # Dismissed 06-03..06-05, but the assignment runs through 06-09 (last day) —
    # the soldier returns, so this must NOT shorten the effective end.
    dismissal = DutyDismissal(
        duty_assignment_id=a.id, dismissed_from=date(2026, 6, 3), dismissed_to=date(2026, 6, 5),
    )
    admin_session.add(dismissal)
    admin_session.flush()
    end_dt = effective_assignment_end(admin_session, a)
    assert end_dt.isoformat() == "2026-06-09T17:00:00"


def test_earliest_eligible_date_rounds_up_partial_day():
    from datetime import datetime
    effective_end = datetime(2026, 6, 1, 17, 0)
    # +12h = 2026-06-02 05:00 — not midnight, rounds up to 06-03.
    assert earliest_eligible_date(effective_end, rest_hours=12) == date(2026, 6, 3)


def test_earliest_eligible_date_exact_midnight_no_roundup():
    from datetime import datetime
    effective_end = datetime(2026, 6, 1, 12, 0)
    # +12h = 2026-06-02 00:00 exactly — no roundup needed.
    assert earliest_eligible_date(effective_end, rest_hours=12) == date(2026, 6, 2)


def test_earliest_eligible_date_stacks_extra_days():
    from datetime import datetime
    effective_end = datetime(2026, 6, 1, 12, 0)
    assert earliest_eligible_date(effective_end, rest_hours=12, extra_days=7) == date(2026, 6, 9)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_rest_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.rest'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/rest.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.duration import combine_date_time
from app.algorithm.rest import last_duty_day
from app.db.models import DutyAssignment, DutyDismissal, DutyType


def resolve_rest_hours(duty_type: DutyType, default_rest_hours: int) -> int:
    """Per-duty-type rest hours override (requirements.rest_hours), or the
    global default."""
    override = (duty_type.requirements or {}).get("rest_hours")
    return int(override) if override is not None else default_rest_hours


def effective_assignment_end(session: Session, assignment: DutyAssignment) -> datetime:
    """The real end of an assignment for rest purposes: the scheduled end, or
    the dismissal moment if the soldier was dismissed through the last duty
    day and never returned to finish the assignment."""
    last_day = last_duty_day(assignment.start_date, assignment.end_date)
    dismissals = session.execute(
        select(DutyDismissal).where(DutyDismissal.duty_assignment_id == assignment.id)
    ).scalars().all()
    permanent = [d for d in dismissals if d.dismissed_to >= last_day]
    if permanent:
        earliest = min(permanent, key=lambda d: d.dismissed_from)
        return combine_date_time(earliest.dismissed_from, assignment.start_time)
    return combine_date_time(last_day, assignment.end_time)


def earliest_eligible_date(effective_end_dt: datetime, rest_hours: int, extra_days: int = 0) -> date:
    """Earliest calendar date on/after which a new duty may start, given
    rest_hours (and any extra_days stacked on top, e.g. gimelim's extra
    rest). Rounds up when the rest window ends mid-day, since callers work
    in whole calendar days."""
    earliest_dt = effective_end_dt + timedelta(hours=rest_hours, days=extra_days)
    if earliest_dt.time() == datetime.min.time():
        return earliest_dt.date()
    return earliest_dt.date() + timedelta(days=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_rest_service.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rest.py backend/tests/unit/test_rest_service.py
git commit -m "feat: add DB-facing rest-hours resolution and effective-end calculation"
```

---

### Task 5: Wire `algorithm_bridge.py` to populate rest fields

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:310-413` (`load_duty_blocks_from_shifts`)
- Modify: `backend/app/services/algorithm_bridge.py:488-518` (`load_existing_assignments`)
- Test: `backend/tests/unit/test_algorithm_bridge_rest.py`

**Interfaces:**
- Consumes: `resolve_rest_hours`, `effective_assignment_end` (Task 4); `get_setting_int` (Task 1); `DutyBlock.rest_hours`, `ExistingAssignment.rest_hours/rest_effective_end_date/rest_effective_end_time` (Task 3).
- Produces: both loader functions now populate the rest fields on every `DutyBlock`/`ExistingAssignment` they construct.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_algorithm_bridge_rest.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import (
    DutyAssignment, DutyDismissal, DutyLocation, DutyShift, DutyType, SystemSetting,
)
from app.services.algorithm_bridge import load_duty_blocks_from_shifts, load_existing_assignments
from tests.helpers import create_soldier


def test_load_duty_blocks_uses_type_override(admin_session):
    dt = DutyType(name="dt-rest-a", score_per_day=Decimal("1.00"), requirements={"rest_hours": 8})
    loc = DutyLocation(name="loc-rest-a")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].rest_hours == 8


def test_load_duty_blocks_uses_global_default(admin_session):
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    dt = DutyType(name="dt-rest-b", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="loc-rest-b")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert blocks[0].rest_hours == 12


def test_load_existing_assignments_populates_effective_end(admin_session):
    dt = DutyType(name="dt-rest-c", score_per_day=Decimal("1.00"), requirements={"rest_hours": 10})
    loc = DutyLocation(name="loc-rest-c")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    s = create_soldier(admin_session, personal_number="8109001")
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 4),
        start_time="08:00", end_time="17:00", status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    existing = load_existing_assignments(
        admin_session, planning_start=date(2026, 9, 1), planning_end=date(2026, 9, 10), W=14,
    )
    assert len(existing) == 1
    ea = existing[0]
    assert ea.rest_hours == 10
    assert ea.rest_effective_end_date == date(2026, 9, 3)
    assert ea.rest_effective_end_time == "17:00"


def test_load_existing_assignments_uses_dismissal_effective_end(admin_session):
    dt = DutyType(name="dt-rest-d", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="loc-rest-d")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    s = create_soldier(admin_session, personal_number="8109002")
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 5),
        start_time="08:00", end_time="17:00", status="published",
    )
    admin_session.add(a)
    admin_session.flush()
    admin_session.add(DutyDismissal(
        duty_assignment_id=a.id, dismissed_from=date(2026, 9, 3), dismissed_to=date(2026, 9, 4),
    ))
    admin_session.flush()

    existing = load_existing_assignments(
        admin_session, planning_start=date(2026, 9, 1), planning_end=date(2026, 9, 10), W=14,
    )
    ea = existing[0]
    assert ea.rest_effective_end_date == date(2026, 9, 3)
    assert ea.rest_effective_end_time == "08:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_algorithm_bridge_rest.py -v`
Expected: FAIL — `AssertionError: assert 0 == 8` (blocks/assignments don't carry rest_hours yet, defaults to 0).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/algorithm_bridge.py`, add imports:

```python
from app.db.models import DutyDismissal  # add to the existing app.db.models import block
from app.services.rest import effective_assignment_end, resolve_rest_hours
from app.services.settings_loader import get_setting_int
```

In `load_duty_blocks_from_shifts` (around line 320-327), after `score_map` is built, resolve the global default once and build a per-type rest_hours map:

```python
    type_ids = {s.duty_type_id for s in shifts}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    score_map = {dt.id: dt.score_per_day for dt in types_q}
    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
    rest_hours_map = {dt.id: resolve_rest_hours(dt, default_rest_hours) for dt in types_q}
```

Then pass `rest_hours=rest_hours_map.get(shift.duty_type_id, default_rest_hours)` to both `DutyBlock(...)` constructions in the function (the primary block around line 380-392 and the reserve block around line 399-410).

In `load_existing_assignments` (lines 488-518), replace the function body:

```python
def load_existing_assignments(
    session: Session,
    *,
    planning_start: date,
    planning_end: date,
    W: int,
) -> list[ExistingAssignment]:
    """Load published assignments within W days of the planning window for spacing checks."""
    boundary_start = planning_start - timedelta(days=W)
    boundary_end = planning_end + timedelta(days=W)
    rows = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.start_date <= boundary_end,
                DutyAssignment.end_date >= boundary_start,
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    type_ids = {a.duty_type_id for a in rows}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
    rest_hours_map = {dt.id: resolve_rest_hours(dt, default_rest_hours) for dt in types_q}

    result: list[ExistingAssignment] = []
    for a in rows:
        end_dt = effective_assignment_end(session, a)
        result.append(
            ExistingAssignment(
                soldier_id=a.soldier_id,
                duty_type_id=a.duty_type_id,
                start_date=a.start_date,
                end_date=a.end_date,
                is_reserve=a.is_reserve,
                rest_hours=rest_hours_map.get(a.duty_type_id, default_rest_hours),
                rest_effective_end_date=end_dt.date(),
                rest_effective_end_time=end_dt.strftime("%H:%M"),
            )
        )
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_algorithm_bridge_rest.py -v`
Expected: PASS (4 tests)

Then run the full algorithm/bridge test suite to check for regressions:

Run: `cd backend && pytest -m algorithm -q`
Expected: PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/tests/unit/test_algorithm_bridge_rest.py
git commit -m "feat: populate rest-hours and effective-end on algorithm inputs"
```

---

### Task 6: Manual assignment path rest validation

**Files:**
- Modify: `backend/app/services/assignments.py` (add `_has_insufficient_rest`, call it from `create_assignment`)
- Modify: `backend/app/routes/assignments.py:20` (`_CONFLICT` set)
- Test: `backend/tests/unit/test_assignments_service.py`
- Test: `backend/tests/integration/test_assignments_api.py`

**Interfaces:**
- Consumes: `resolve_rest_hours`, `effective_assignment_end` (Task 4), `get_setting_int` (Task 1), `rest_violated` (Task 2), `combine_date_time` (`app.algorithm.duration`).
- Produces: `create_assignment` now raises `AssignmentError("insufficient_rest")` when the new assignment would violate rest against an adjacent assignment for the same soldier; this error is mapped to HTTP 409 like `"overlap"`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_assignments_service.py`:

```python
def test_create_rejects_insufficient_rest_after_prior_duty(admin_session):
    s = create_soldier(admin_session, personal_number="8100010")
    dt = _dt(admin_session, "שמירה-rest1")
    loc = _loc(admin_session, "מוצב-rest1")
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None,
    )
    admin_session.flush()
    # Prior assignment ends 23:59 on 06-01 (default end_time). New one starts
    # 00:00 on 06-02 (default start_time) — 1 minute gap, violates any rest > 0.
    from app.db.models import SystemSetting
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(
            admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 6, 2), end_date=date(2026, 6, 3), notes=None, actor_id=None,
        )
    assert str(exc.value) == "insufficient_rest"


def test_create_allows_sufficient_rest_gap(admin_session):
    s = create_soldier(admin_session, personal_number="8100011")
    dt = _dt(admin_session, "שמירה-rest2")
    loc = _loc(admin_session, "מוצב-rest2")
    create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 5), end_date=date(2026, 6, 8), notes=None, actor_id=None,
    )
    admin_session.flush()
    from app.db.models import SystemSetting
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()
    # Prior ends 23:59 on 06-07; new one starts 00:00 on 06-10 — plenty of gap.
    a = create_assignment(
        admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 12), notes=None, actor_id=None,
    )
    assert a.start_date == date(2026, 6, 10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_assignments_service.py -k rest -v`
Expected: FAIL — `Failed: DID NOT RAISE <class 'AssignmentError'>` for the first test.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/assignments.py`, add imports:

```python
from app.algorithm.duration import combine_date_time
from app.algorithm.rest import last_duty_day, rest_violated
from app.services.rest import effective_assignment_end, resolve_rest_hours
from app.services.settings_loader import get_setting_int
```

Add a new helper after `_has_overlap` (around line 46):

```python
def _has_insufficient_rest(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    duty_type_id: uuid.UUID,
    start_date: date,
    end_date: date,
    start_time: str,
    end_time: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    q = select(DutyAssignment).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status != "cancelled",
    )
    if exclude_id is not None:
        q = q.where(DutyAssignment.id != exclude_id)
    others = session.execute(q).scalars().all()
    if not others:
        return False

    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
    this_type = session.get(DutyType, duty_type_id)
    this_rest_hours = resolve_rest_hours(this_type, default_rest_hours) if this_type else default_rest_hours
    this_last_day = last_duty_day(start_date, end_date)
    this_end_dt = combine_date_time(this_last_day, end_time)
    this_start_dt = combine_date_time(start_date, start_time)

    for other in others:
        if other.start_date >= end_date:
            # other starts after this one ends: this one's rest_hours must be
            # satisfied before other's start.
            if rest_violated(this_end_dt, other.start_date, other.start_time, this_rest_hours):
                return True
        elif other.end_date <= start_date:
            # other ends before this one starts: other's rest_hours must be
            # satisfied before this one's start.
            other_type = session.get(DutyType, other.duty_type_id)
            other_rest_hours = (
                resolve_rest_hours(other_type, default_rest_hours) if other_type else default_rest_hours
            )
            other_end_dt = effective_assignment_end(session, other)
            if rest_violated(other_end_dt, start_date, start_time, other_rest_hours):
                return True
    return False
```

In `create_assignment` (around line 82-104), move the existing shift-time lookup (currently at line 100-104, right before `DutyAssignment(...)` is constructed) up to run before the overlap check, then reuse the same `start_time`/`end_time` locals for both the new rest check and the assignment construction — no duplicate lookup:

```python
    if end_date <= start_date:
        raise AssignmentError("bad_date_range")
    if session.get(Soldier, soldier_id) is None:
        raise AssignmentError("soldier_not_found")
    if session.get(DutyType, duty_type_id) is None:
        raise AssignmentError("duty_type_not_found")
    if session.get(DutyLocation, duty_location_id) is None:
        raise AssignmentError("location_not_found")
    start_time, end_time = "00:00", "23:59"
    if duty_shift_id is not None:
        shift = session.get(DutyShift, duty_shift_id)
        if shift is not None:
            start_time, end_time = shift.start_time, shift.end_time
    if _has_overlap(session, soldier_id=soldier_id, start_date=start_date, end_date=end_date):
        raise AssignmentError("overlap")
    if _has_insufficient_rest(
        session,
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
    ):
        raise AssignmentError("insufficient_rest")
    if _has_blocking_exemption(
        session,
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        start_date=start_date,
        end_date=end_date,
    ):
        raise AssignmentError("exempted")
```

Then delete the now-duplicate `start_time, end_time = "00:00", "23:59"` / shift-lookup block that used to sit right before `DutyAssignment(...)` (original lines 100-104) — the assignment construction below now reuses the `start_time`/`end_time` computed above.

In `backend/app/routes/assignments.py:20`, update the conflict set:

```python
_CONFLICT = {"overlap", "exempted", "insufficient_rest"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_assignments_service.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Add an integration test**

Add to `backend/tests/integration/test_assignments_api.py` (find the existing overlap-returns-409 test in this file first and mirror its setup):

```python
def test_insufficient_rest_returns_409(client: TestClient, admin_session: Session):
    from app.db.models import SystemSetting

    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number="5400010", role="admin")
    target = create_soldier(admin_session, personal_number="5400011", role="soldier")
    dt, loc = _dt_loc(admin_session, "api-rest1")
    body = {
        "soldier_id": str(target.id),
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
    }
    assert (
        client.post("/api/assignments", headers=auth_headers(admin), json=body).status_code == 201
    )
    # Prior assignment ends 23:59 on 10-01 (default end_time); this one starts
    # 00:00 on 10-02 (default start_time) — 1 minute gap, violates 12h rest.
    r = client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={**body, "start_date": "2026-10-02", "end_date": "2026-10-03"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "insufficient_rest"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_assignments_api.py -k rest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/assignments.py backend/app/routes/assignments.py backend/tests/unit/test_assignments_service.py backend/tests/integration/test_assignments_api.py
git commit -m "feat: validate minimum rest when manually creating assignments"
```

---

### Task 7: Gimelim rest fix — dismissal-aware, stacked extra days

**Files:**
- Modify: `backend/app/services/gimelim.py:93-97` (remove private `_get_setting_int`, use shared one)
- Modify: `backend/app/services/gimelim.py:286-362` (`preview_gimelim` — fix `earliest_date` calculation)
- Test: `backend/tests/unit/test_gimelim_service.py`

**Interfaces:**
- Consumes: `get_setting_int` (Task 1), `resolve_rest_hours`, `earliest_eligible_date` (Task 4), `combine_date_time` (`app.algorithm.duration`).
- Produces: `preview_gimelim`'s `rest_days` parameter now means "extra days stacked on top of base rest_hours," and `earliest_date` is computed from the actual `from_date` (dismissal moment) instead of `primary_a.end_date`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_gimelim_service.py` (reuses `_make_soldier`, `_make_shift_with_primary_and_reserve`, `_seed_base` helpers already in the file). This test reads `earliest_date` off the preview's internal token payload (`_PREVIEW_STORE`) — Step 3 adds that key to the payload alongside the existing `"rest_days"` entry:

```python
def test_preview_earliest_date_counts_from_dismissal_not_scheduled_end(admin_session):
    dt, loc = _seed_base(admin_session)
    a = _make_soldier(admin_session, "8200001", "חייל א")
    b = _make_soldier(admin_session, "8200002", "חייל ב")
    # Shift runs 2026-07-01..2026-07-11 (10 days) — A is dismissed on day 3
    # (2026-07-03), far earlier than the scheduled end (2026-07-10).
    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc, date(2026, 7, 1), date(2026, 7, 11), a, b,
    )
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=7,
        reason="פציעה",
        actor_id=a.id,
        from_date=date(2026, 7, 3),
    )
    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[preview.preview_token]
    # effective_end = 2026-07-03 08:00 (assignment's default start_time) +
    # 12h base rest = 2026-07-03 20:00, + 7 extra days = 2026-07-10 20:00,
    # which is mid-day so it rounds up to 2026-07-11.
    assert payload["rest_days"] == 7
    assert payload["earliest_date"] == "2026-07-11"


def test_preview_earliest_date_without_dismissal_still_uses_scheduled_end(admin_session):
    """Sanity check: with no early dismissal (from_date == scheduled start of
    the rest window), the calculation still lines up with the assignment's
    own end when from_date is set to end_date - 1 (the normal 'dismiss on the
    last day' case used by commit_gimelim)."""
    dt, loc = _seed_base(admin_session)
    a = _make_soldier(admin_session, "8200003", "חייל ג")
    b = _make_soldier(admin_session, "8200004", "חייל ד")
    shift, primary, reserve = _make_shift_with_primary_and_reserve(
        admin_session, dt, loc, date(2026, 8, 1), date(2026, 8, 5), a, b,
    )
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    admin_session.flush()

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=0,
        reason="פציעה",
        actor_id=a.id,
        from_date=date(2026, 8, 4),  # end_date - 1, the last scheduled day
    )
    from app.services.gimelim import _PREVIEW_STORE
    _, payload = _PREVIEW_STORE[preview.preview_token]
    # effective_end = 2026-08-04 08:00 (default start_time) + 12h = 08-04 20:00
    # -> rounds up to 08-05.
    assert payload["earliest_date"] == "2026-08-05"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/unit/test_gimelim_service.py -k earliest_date -v`
Expected: FAIL with `KeyError: 'earliest_date'` (the preview payload doesn't carry this key yet, and `earliest_date` is still computed the old way).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/gimelim.py`, replace the imports:

```python
from app.services.settings_loader import SettingNotFound, get_setting
```

with:

```python
from app.algorithm.duration import combine_date_time
from app.services.rest import earliest_eligible_date, resolve_rest_hours
from app.services.settings_loader import SettingNotFound, get_setting, get_setting_int
```

Remove the private `_get_setting_int` (lines 93-97; `_get_setting_str` at line 100 stays — it's a different helper, still needed). `_get_setting_int` has FOUR call sites in this file — lines 180, 181, 341, and 342 — update all four to call the shared `get_setting_int` instead (they already pass `session, key, default` positionally, so this is a drop-in rename; search the whole file for `_get_setting_int(` to make sure none are missed).

Replace lines 341-343:

```python
    T = _get_setting_int(session, "algorithm.T", 7)
    W = _get_setting_int(session, "algorithm.W", 14)
    earliest_date = primary_a.end_date + timedelta(days=rest_days)
```

with:

```python
    T = get_setting_int(session, "algorithm.T", 7)
    W = get_setting_int(session, "algorithm.W", 14)
    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
    base_rest_hours = resolve_rest_hours(duty_type, default_rest_hours)
    effective_end_dt = combine_date_time(from_date, primary_a.start_time)
    earliest_date = earliest_eligible_date(effective_end_dt, base_rest_hours, extra_days=rest_days)
```

Add `"earliest_date": earliest_date.isoformat(),` to the `payload` dict (around line 388-406), next to the existing `"rest_days": rest_days,` entry.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/unit/test_gimelim_service.py -v`
Expected: PASS (all tests, including the new one — check that no pre-existing test asserted the old flat-`end_date + rest_days` value; if one does, update its expected date to match the new dismissal-aware calculation using the same formula).

- [ ] **Step 5: Run the full gimelim + duty_history + assignments suites**

Run: `cd backend && pytest -m "duty or misc" -q`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gimelim.py backend/tests/unit/test_gimelim_service.py
git commit -m "fix: compute gimelim rest window from dismissal date, not scheduled end"
```

---

### Task 8: Frontend — duty type override and system settings

**Files:**
- Modify: `frontend/src/api/dutyConfig.ts` (add `rest_hours` to the `requirements` type)
- Modify: `frontend/src/components/DutyTypeFormModal.tsx` (add an input for the override)
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` (add `duty.default_rest_hours`; relabel `gimalim.default_rest_days`)

**Interfaces:**
- Consumes: existing `updateDutyTypeRequirements`/`createDutyType`/`updateDutyType` API functions (unchanged signatures — `requirements` is already a passthrough `dict`).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Add the field to the `DutyType` requirements type**

In `frontend/src/api/dutyConfig.ts`, add `rest_hours?: number;` to the `requirements` object type (around line 11-20):

```typescript
  requirements?: {
    allowed_genders?: string[];
    requires_mitvahim?: boolean;
    requires_alal?: boolean;
    allowed_ranks?: string[];
    allowed_service_types?: string[];
    officers_allowed?: boolean;
    enlisted_allowed?: boolean;
    requires_bahad1?: boolean;
    rest_hours?: number;
  };
```

- [ ] **Step 2: Add the input to `DutyTypeFormModal.tsx`**

Add local state near the other `reqs`-adjacent state (around line 30):

```typescript
  const [restHours, setRestHours] = useState<string>(
    initial?.requirements?.rest_hours != null ? String(initial.requirements.rest_hours) : ""
  );
```

In `handleSubmit` (around line 61-83), merge `restHours` into `reqs` before saving:

```typescript
    setSaving(true);
    try {
      const mergedReqs = {
        ...reqs,
        ...(restHours.trim() ? { rest_hours: parseInt(restHours, 10) } : {}),
      };
      const payload = {
        name,
        score_per_day: score,
        reserve_ratio: reserveRatio,
        reserve_minimum: parseInt(reserveMin) || 0,
        contact_name: contactName || null,
        contact_phone: contactPhone || null,
        start_time: startTime || null,
        end_time: endTime || null,
        instructions: instructions || null,
        is_external: isExternal === "true",
        eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
      };
      let dt: DutyType;
      if (initial) {
        dt = await updateDutyType(initial.id, { ...payload, requirements: mergedReqs });
      } else {
        dt = await createDutyType(payload);
        if (Object.keys(mergedReqs).length > 0) {
          dt = await updateDutyTypeRequirements(dt.id, mergedReqs);
        }
      }
      onSaved(dt);
```

Add the input field near the reserve ratio/minimum inputs (around line 117-124):

```tsx
              <div className="w-24">
                <label htmlFor="duty-type-rest-hours" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">שעות מנוחה</label>
                <input id="duty-type-rest-hours" type="number" min="0" step="1" placeholder="ברירת מחדל" value={restHours} onChange={e => setRestHours(e.target.value)} className={inputCls} />
              </div>
```

- [ ] **Step 3: Add the global setting to `SystemSettingsPage.tsx`**

In the `gimalim.default_rest_days` entry (around line 158-164), update the description to reflect stacking:

```typescript
      {
        key: "gimalim.default_rest_days",
        label: "ימי מנוחה נוספים לגימלים",
        description: "מספר ימים נוספים, מעל שעות המנוחה הבסיסיות, לפני שיבוץ חוזר לחייל ששוחרר בגימלים (ניתן לשינוי בכל פעולת גימלים)",
        type: "number" as const,
        defaultValue: 7,
      },
```

Add a new entry right before it in the same group:

```typescript
      {
        key: "duty.default_rest_hours",
        label: "שעות מנוחה בסיסיות בין תורנויות",
        description: "מספר שעות המנוחה המינימלי הנדרש לחייל בין סיום תורנות אחת לתחילת הבאה. ניתן לשנות פר-סוג תורנות.",
        type: "number" as const,
        defaultValue: 12,
      },
```

- [ ] **Step 4: Manually verify in the browser**

Run: `.\dev.ps1` (or ensure it's already running)
Navigate to the duty types admin page, open a duty type's edit modal, confirm the "שעות מנוחה" field appears and saves (check via the network tab that `requirements.rest_hours` is sent in the PATCH body). Then navigate to system settings and confirm "שעות מנוחה בסיסיות בין תורנויות" appears and its value can be edited and saved.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/dutyConfig.ts frontend/src/components/DutyTypeFormModal.tsx frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: expose rest-hours settings in duty type and system settings UI"
```

---

## Post-implementation checklist

- [ ] Run the full fast suite: `cd backend && pytest -q`
- [ ] Run the algorithm-marked tests explicitly: `cd backend && pytest -m algorithm -q`
- [ ] Run `npm run lint` and `npm run typecheck` in `frontend/`
- [ ] Update `frontend/CHANGELOG.md` per the project's daily-changelog convention before merging
