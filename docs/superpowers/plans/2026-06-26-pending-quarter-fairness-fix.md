# Pending-Quarter Fairness Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the quarterly effort-fairness metric from treating a soldier's *one* pre-existing duty in an almost-empty quarter as if it were their entire quarterly workload, by having `compute_effort_data` assume the quarter the algorithm is about to plan into will end up fully covered.

**Architecture:** `compute_effort_data()` (`backend/app/services/effort_score.py`) gains an optional `pending_duties` parameter: the same `DutyBlock` list the bridge is about to feed to the solver. Each pending duty's score is apportioned into whichever calendar quarter(s) it falls in — exactly like an already-published duty would be — and added to that quarter's `unit_score` denominator only (never credited to any soldier, since nobody has been assigned it yet). `algorithm_bridge.py`'s `run_algorithm_job` passes its `duties` list through this new parameter. Every other caller (`transparency_rows`, `compute_effort_breakdown`) is unaffected — they describe actual published history, where there is nothing "pending."

**Why this fixes the bug:** The bug (diagnosed against production data) is that `effort_offset` for a soldier is their historical *share* of each quarter's total unit score. When the algorithm runs for a quarter that has only a handful of published duties so far (the normal case — you plan ahead of when duties get published), that tiny published total is the *entire* denominator. A soldier holding even one of those few duties looks like they hold a huge share of "the quarter" — when in reality the quarter is about to receive hundreds more duties for everyone else once this run publishes. The fix doesn't change who currently has what; it changes the yardstick (the denominator) to reflect the quarter's size *once this run's duties land in it, assuming full coverage* — which is the best available estimate of the quarter's true eventual size at decision time. Diluting the denominator this way shrinks that soldier's apparent share back down to what it will actually look like after publishing, so the solver no longer starves them for the rest of the run.

**Tech Stack:** Python, SQLAlchemy, pytest.

---

## File Map

**Modify:**
- `backend/app/services/effort_score.py` — add `_pending_quarter_scores()` helper and `pending_duties` parameter to `compute_effort_data()`
- `backend/app/services/algorithm_bridge.py` — pass `pending_duties=duties` at the `compute_effort_data()` call site in `run_algorithm_job`
- `backend/tests/test_effort_score.py` — new tests for both of the above

---

## Task 1: `compute_effort_data` accounts for pending workload

**Files:**
- Modify: `backend/app/services/effort_score.py`
- Modify: `backend/tests/test_effort_score.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_effort_score.py`:

```python
def test_pending_quarter_scores_apportions_by_day():
    """_pending_quarter_scores splits a duty's total score across the calendar
    quarter(s) it touches, using score_per_day x score_days (same convention as
    effective_duty_days), keyed by the duty's quarter_start."""
    from app.services.effort_score import _pending_quarter_scores

    @dataclass
    class _Block:
        start_date: date
        end_date: date
        start_time: str
        end_time: str
        score_per_day: Decimal

    # One 7-day duty fully inside Q3 2026 (Jul 1 - Sep 30), score_per_day=1.00
    # -> total score 7, all attributed to quarter_start=2026-07-01.
    block = _Block(
        start_date=date(2026, 7, 13), end_date=date(2026, 7, 20),
        start_time="00:00", end_time="23:59", score_per_day=Decimal("1.00"),
    )
    buckets = _pending_quarter_scores([block])
    assert buckets == {date(2026, 7, 1): Decimal("7")}


def test_pending_duties_dilute_thin_quarter_share(admin_session):
    """
    Reproduces the production bug: a soldier ('victim') has ONE pre-existing
    7-day duty in a quarter that otherwise has zero published activity. Without
    pending_duties, that duty looks like 100% of the quarter (the only data
    point). With pending_duties representing the other 93 duty-equivalents the
    algorithm is about to plan into the SAME quarter, her share correctly drops
    to 7% -- reflecting what the quarter will actually look like once this run
    publishes, not the artificially thin snapshot from before it ran.
    """
    from app.db.models import DutyLocation, DutyType
    from app.algorithm.types import DutyBlock
    from app.services.assignments import create_assignment
    from tests.helpers import create_soldier

    dt = DutyType(name="שמירה-pending", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    loc = DutyLocation(name="מוצב-pending")
    admin_session.add(loc)
    admin_session.flush()

    enrolled = date(2025, 1, 1)
    victim = create_soldier(admin_session, personal_number="9700010")
    victim.enrolled_at = enrolled
    control = create_soldier(admin_session, personal_number="9700011")
    control.enrolled_at = enrolled
    admin_session.flush()

    # victim's one pre-existing published duty: 7 days @ score 1.00 = 7 total.
    create_assignment(
        admin_session,
        soldier_id=victim.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 13),
        end_date=date(2026, 7, 20),
        actor_id=None,
    )
    admin_session.flush()

    # planning_start chosen so the ENTIRE Q3 2026 quarter is one clipped past
    # quarter (history_end = Sep 30) -> W_i = 1 quarter exactly, so
    # effort_score == that single quarter's share (clean assertion numbers).
    planning_start = date(2026, 10, 1)
    planning_end = date(2026, 10, 1)
    reset_date = date(2026, 7, 1)

    without = compute_effort_data(
        admin_session, soldiers=[victim, control],
        planning_start=planning_start, planning_end=planning_end, reset_date=reset_date,
    )
    assert without[victim.id].effort_score == Decimal("1")  # 7/7 -- the bug
    assert without[control.id].effort_score == Decimal("0")

    # 93 more single-day duty-equivalents about to be planned into the same
    # quarter (Q3 2026), assuming full coverage once the run publishes.
    pending = [
        DutyBlock(
            id=uuid.uuid4(), duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 8, 1) + timedelta(days=i),
            end_date=date(2026, 8, 2) + timedelta(days=i),
            score_per_day=Decimal("1.00"),
        )
        for i in range(93)
    ]

    withp = compute_effort_data(
        admin_session, soldiers=[victim, control],
        planning_start=planning_start, planning_end=planning_end, reset_date=reset_date,
        pending_duties=pending,
    )
    assert withp[victim.id].effort_score == Decimal("7") / Decimal("100")  # 7/100, not 7/7
    assert withp[control.id].effort_score == Decimal("0")  # unaffected -- she had nothing before either
```

Change the existing `from datetime import date` import at the top of `backend/tests/test_effort_score.py` to `from datetime import date, timedelta` (it's used in the test below). `uuid`, `dataclass`, and `DutyBlock` are already imported in that file — no other import changes needed.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_effort_score.py::test_pending_quarter_scores_apportions_by_day tests/test_effort_score.py::test_pending_duties_dilute_thin_quarter_share -v
```
Expected: both FAIL — `test_pending_quarter_scores_apportions_by_day` with `ImportError: cannot import name '_pending_quarter_scores'`; `test_pending_duties_dilute_thin_quarter_share` with `TypeError: compute_effort_data() got an unexpected keyword argument 'pending_duties'`.

- [ ] **Step 3: Add `_pending_quarter_scores` and wire it into `compute_effort_data`**

In `backend/app/services/effort_score.py`, update the imports at the top:

```python
from collections.abc import Sequence
from app.algorithm.duration import calendar_days_touched, score_days
```

Add this function after `_find_quarter_key` (around line 80, before `_compute_effort_data`):

```python
def _pending_quarter_scores(pending_duties: Sequence[Any]) -> dict[date, Decimal]:
    """Apportion each pending (not-yet-published) duty's total score across the
    calendar quarter(s) it falls in, using the same per-day weighting
    `effective_duty_days` uses for published assignments (score_days /
    days_touched per calendar day touched). Keyed by the UNCLIPPED calendar
    quarter_start -- these duties haven't happened yet, so there is no history
    boundary to clip against.

    Used by `compute_effort_data`'s `pending_duties` parameter to inflate a
    quarter's unit_score by the workload the algorithm is about to assign this
    run, assuming it ends up fully covered.
    """
    buckets: dict[date, Decimal] = {}
    for d in pending_duties:
        touched = calendar_days_touched(d.start_date, d.end_date)
        if touched <= 0:
            continue
        day_weight = Decimal(score_days(d.start_date, d.end_date, d.start_time, d.end_time)) / Decimal(touched)
        per_day_score = Decimal(d.score_per_day) * day_weight
        day = d.start_date
        while day < d.end_date:
            qs = quarter_start(day)
            buckets[qs] = buckets.get(qs, Decimal("0")) + per_day_score
            day += timedelta(days=1)
    return buckets
```

Now update `compute_effort_data`'s signature and body. Replace:

```python
def compute_effort_data(
    session: Session,
    *,
    soldiers: list[Any],    # objects with .id (UUID) and .enrolled_at (date)
    planning_start: date,
    planning_end: date,
    reset_date: date,
) -> dict[uuid.UUID, EffortData]:
    """
    Compute EffortData for all soldiers using published assignment history plus
    any manual score adjustments (ScoreAdjustment records).

    Uses effective_duty_days() from scoring.py (same source-of-truth as score calculations).
    Loads history from reset_date up to (but not including) planning_start, PLUS any
    published assignments after planning_end (future duties beyond the planning window).

    Returns dict[soldier_id, EffortData] with effort_per_milli=0;
    the caller (bridge) sets effort_per_milli after knowing unit_score_milli.
    """
    from sqlalchemy import select
    from app.db.models import DutyType, ScoreAdjustment

    history_end = planning_start - timedelta(days=1)

    # Build list of past quarters (reset_date → planning_start-1), clipping first quarter
    # start to reset_date so active_frac is only counted from when we have actual duty data.
    past_quarters: list[tuple[date, date]] = []
    if history_end >= reset_date:
        q_s = quarter_start(reset_date)
        while q_s < planning_start:
            q_e = quarter_end(q_s)
            actual_start = max(q_s, reset_date)
            actual_end = min(q_e, history_end)
            past_quarters.append((actual_start, actual_end))
            next_month = q_e + timedelta(days=1)
            q_s = next_month

    # Fetch ALL published duties from reset_date onwards (covers past and future)
    days_data = effective_duty_days(session, date_from=reset_date, date_to=date(2099, 12, 31))

    # Build future quarters from dates after planning_end
    future_quarters = _build_future_quarters(days_data, planning_end)

    all_quarters = past_quarters + future_quarters

    if not all_quarters:
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=[],
            quarter_unit_scores={},
            quarter_soldier_scores={},
        )

    # Fetch duty type scores
    dt_scores: dict[uuid.UUID, Decimal] = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    # Map calendar-quarter-start → clipped quarter-start used in all_quarters.
    # O(Q) instead of O(Q × 90 days) — the per-day loop was building ~720 entries
    # only to do a dict lookup that quarter_start() computes directly.
    cal_qs_to_clipped: dict[date, date] = {
        quarter_start(q_start_d): q_start_d for q_start_d, _ in all_quarters
    }

    # Aggregate duty scores per quarter
    q_unit_scores: dict[date, Decimal] = {}
    q_soldier_scores: dict[date, dict[uuid.UUID, Decimal]] = {}
    for day, soldier_id, duty_type_id, mult in days_data:
        # Skip the planning window — solver controls those
        if planning_start <= day <= planning_end:
            continue
        qs = cal_qs_to_clipped.get(quarter_start(day))
        if qs is None:
            continue
        score = dt_scores.get(duty_type_id, Decimal("0")) * mult
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + score
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[soldier_id] = q_s_map.get(soldier_id, Decimal("0")) + score

    # Include manual score adjustments in effort calculation
    adj_rows = session.execute(select(ScoreAdjustment)).scalars().all()
    for adj in adj_rows:
        qs = _find_quarter_key(all_quarters, adj.created_at.date())
        if qs is None:
            continue
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + adj.delta
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[adj.soldier_id] = q_s_map.get(adj.soldier_id, Decimal("0")) + adj.delta

    return _compute_effort_data(
        soldiers=soldiers,
        quarters=all_quarters,
        quarter_unit_scores=q_unit_scores,
        quarter_soldier_scores=q_soldier_scores,
    )
```

with:

```python
def compute_effort_data(
    session: Session,
    *,
    soldiers: list[Any],    # objects with .id (UUID) and .enrolled_at (date)
    planning_start: date,
    planning_end: date,
    reset_date: date,
    pending_duties: Sequence[Any] = (),  # DutyBlock-like: about to be planned, not yet published
) -> dict[uuid.UUID, EffortData]:
    """
    Compute EffortData for all soldiers using published assignment history plus
    any manual score adjustments (ScoreAdjustment records).

    Uses effective_duty_days() from scoring.py (same source-of-truth as score calculations).
    Loads history from reset_date up to (but not including) planning_start, PLUS any
    published assignments after planning_end (future duties beyond the planning window).

    `pending_duties` are duties the algorithm is ABOUT TO assign this run (not yet
    published). Each one's score is added to whichever quarter(s) it falls in, as if
    that quarter will end up fully covered -- WITHOUT crediting it to any soldier
    (nobody has been assigned it yet). This stops a quarter that currently has only
    a handful of published duties from looking like a soldier's huge personal share
    of it, when the algorithm is about to multiply that quarter's true total many
    times over. Leave empty for callers with nothing pending (e.g. the transparency
    page), where actual published history is the only honest signal.

    Returns dict[soldier_id, EffortData] with effort_per_milli=0;
    the caller (bridge) sets effort_per_milli after knowing unit_score_milli.
    """
    from sqlalchemy import select
    from app.db.models import DutyType, ScoreAdjustment

    history_end = planning_start - timedelta(days=1)

    # Build list of past quarters (reset_date → planning_start-1), clipping first quarter
    # start to reset_date so active_frac is only counted from when we have actual duty data.
    past_quarters: list[tuple[date, date]] = []
    if history_end >= reset_date:
        q_s = quarter_start(reset_date)
        while q_s < planning_start:
            q_e = quarter_end(q_s)
            actual_start = max(q_s, reset_date)
            actual_end = min(q_e, history_end)
            past_quarters.append((actual_start, actual_end))
            next_month = q_e + timedelta(days=1)
            q_s = next_month

    # Fetch ALL published duties from reset_date onwards (covers past and future)
    days_data = effective_duty_days(session, date_from=reset_date, date_to=date(2099, 12, 31))

    # Build future quarters from dates after planning_end
    future_quarters = _build_future_quarters(days_data, planning_end)

    all_quarters = past_quarters + future_quarters

    # Merge the about-to-be-assigned workload into whichever quarter(s) it falls
    # in (creating a new unclipped quarter tuple if none is tracked yet -- e.g. a
    # fresh future quarter with no published history at all). Computed before the
    # "anything to do" check below since pending-only duties can be the only
    # reason a quarter exists.
    cal_to_tracked: dict[date, date] = {quarter_start(q_s): q_s for q_s, _ in all_quarters}
    pending_unit_scores: dict[date, Decimal] = {}
    if pending_duties:
        for cal_qs, amount in _pending_quarter_scores(pending_duties).items():
            tracked_qs = cal_to_tracked.get(cal_qs)
            if tracked_qs is None:
                tracked_qs = cal_qs
                all_quarters.append((cal_qs, quarter_end(cal_qs)))
                cal_to_tracked[cal_qs] = cal_qs
            pending_unit_scores[tracked_qs] = pending_unit_scores.get(tracked_qs, Decimal("0")) + amount

    if not all_quarters:
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=[],
            quarter_unit_scores={},
            quarter_soldier_scores={},
        )

    # Fetch duty type scores
    dt_scores: dict[uuid.UUID, Decimal] = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    # Map calendar-quarter-start → clipped quarter-start used in all_quarters.
    # O(Q) instead of O(Q × 90 days) — the per-day loop was building ~720 entries
    # only to do a dict lookup that quarter_start() computes directly.
    cal_qs_to_clipped: dict[date, date] = {
        quarter_start(q_start_d): q_start_d for q_start_d, _ in all_quarters
    }

    # Aggregate duty scores per quarter, seeded with the pending-workload baseline.
    q_unit_scores: dict[date, Decimal] = dict(pending_unit_scores)
    q_soldier_scores: dict[date, dict[uuid.UUID, Decimal]] = {}
    for day, soldier_id, duty_type_id, mult in days_data:
        # Skip the planning window — solver controls those
        if planning_start <= day <= planning_end:
            continue
        qs = cal_qs_to_clipped.get(quarter_start(day))
        if qs is None:
            continue
        score = dt_scores.get(duty_type_id, Decimal("0")) * mult
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + score
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[soldier_id] = q_s_map.get(soldier_id, Decimal("0")) + score

    # Include manual score adjustments in effort calculation
    adj_rows = session.execute(select(ScoreAdjustment)).scalars().all()
    for adj in adj_rows:
        qs = _find_quarter_key(all_quarters, adj.created_at.date())
        if qs is None:
            continue
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + adj.delta
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[adj.soldier_id] = q_s_map.get(adj.soldier_id, Decimal("0")) + adj.delta

    return _compute_effort_data(
        soldiers=soldiers,
        quarters=all_quarters,
        quarter_unit_scores=q_unit_scores,
        quarter_soldier_scores=q_soldier_scores,
    )
```

- [ ] **Step 4: Run the new tests**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_effort_score.py -v
```
Expected: all tests PASS, including the two new ones and all pre-existing ones (`test_future_duties_increase_effort_offset`, `test_planning_window_duties_excluded_from_offset`, `test_future_quarters_appear_in_breakdown`, etc. — `pending_duties` defaults to `()` so their behavior is byte-identical to before).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/effort_score.py backend/tests/test_effort_score.py
git commit -m "fix(fairness): inflate thin-quarter denominator by pending workload before computing effort share"
```

---

## Task 2: Wire pending duties into the algorithm run

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`
- Modify: `backend/tests/test_effort_score.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_effort_score.py`:

```python
def test_run_algorithm_job_passes_pending_duties_to_compute_effort_data():
    """run_algorithm_job must pass its own `duties` list as `pending_duties` to
    compute_effort_data, so the algorithm's fairness input accounts for the
    workload it is about to assign (see test_pending_duties_dilute_thin_quarter_share
    for why this matters). Source-inspection style matches
    test_transparency_rows_has_effort_score_key in this same file."""
    import inspect
    from app.services import algorithm_bridge as ab

    src = inspect.getsource(ab.run_algorithm_job)
    assert "pending_duties=duties" in src, (
        "run_algorithm_job's compute_effort_data(...) call must pass pending_duties=duties"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_effort_score.py::test_run_algorithm_job_passes_pending_duties_to_compute_effort_data -v
```
Expected: FAIL — assertion error, string not found.

- [ ] **Step 3: Wire it in**

In `backend/app/services/algorithm_bridge.py`, find the `compute_effort_data` call inside `run_algorithm_job` (currently around line 1084):

```python
                effort_map = compute_effort_data(
                    session,
                    soldiers=soldiers,
                    planning_start=effort_horizon,
                    planning_end=effort_horizon,
                    reset_date=_reset_date,
                )
```

Replace with:

```python
                effort_map = compute_effort_data(
                    session,
                    soldiers=soldiers,
                    planning_start=effort_horizon,
                    planning_end=effort_horizon,
                    reset_date=_reset_date,
                    pending_duties=duties,
                )
```

- [ ] **Step 4: Run the test**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_effort_score.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/tests/test_effort_score.py
git commit -m "fix(fairness): feed the run's own duty workload into the effort-share denominator"
```

---

## Task 3: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
```
Expected: all tests PASS (no regressions in `app/algorithm/tests/`, `tests/integration/`, etc.). `pending_duties` defaults to `()` everywhere it isn't explicitly passed, so no other test's behavior should change.

- [ ] **Step 2: Manually verify against the original production scenario (optional but recommended)**

The job that exposed this bug is `8f9e631f-4cd8-4604-a2ed-ab882b03da34` in the dev DB (soldiers ספקטרה 5/6/7/8/9/10/11/15 each had one pre-existing manual duty and got starved). Re-running the algorithm for the same window after this fix should no longer single out exactly those soldiers — spot-check via the Transparency page or a fresh job run that ספקטרה 7 (and siblings) receive a comparable number of new duties to soldiers with no pre-existing history.

- [ ] **Step 3: Commit (if Step 2 surfaced any follow-up fixes; otherwise nothing to commit)**
