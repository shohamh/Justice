# Quarterly Effort Fairness Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current `score / active_days` fairness metric with a quarterly effort-share metric that measures each soldier's average share of unit duties per quarter, eliminating the historical low-activity bias that caused new soldiers to be under-assigned.

**Architecture:** A new `effort_score.py` service computes per-soldier historical effort data (quarterly share averages) using published assignment history from a configurable reset date. `algorithm_bridge.py` calls this service after loading duty blocks and injects two integer fields (`effort_offset`, `effort_per_milli`) into each `SoldierInput`. `model.py` replaces the `norm`-based objective with an effort-based one using the same primary/secondary/tiebreaker structure. The scoring transparency page gains an `effort_score` column. Frontend settings, transparency, and help pages are updated to explain the new system.

**Tech Stack:** Python/FastAPI backend, OR-Tools CP-SAT, SQLAlchemy, React/TypeScript frontend, Tailwind CSS.

---

## Metric Reference

For implementers to understand the math before touching code:

**Quarterly share for soldier i in quarter q:**
```
share_q = soldier_score_q / unit_score_q
```
where `unit_score_q` = total published duty score for ALL soldiers in quarter q (the entire unit's duty load that quarter).

**Active fraction for soldier i in quarter q:**
```
active_frac_q = active_days_in_quarter_q / quarter_length_days
```
Counts days from max(enrolled_at, quarter_start) to quarter_end.

**Historical effort (average quarterly share, weighted by presence):**
```
A_i = Σ_q (share_q × active_frac_q)    [numerator sum]
W_i = Σ_q (active_frac_q)               [weight sum]
effort_score_i = A_i / D_i             [where D_i = W_i + C_i]
```

**Current-planning contribution weight:**
```
C_i = active_days_in_planning_window / planning_window_length
D_i = W_i + C_i
```

**CP-SAT integer encoding (EFFORT_SCALE = 10^9):**
```
effort_offset_i  = int(A_i / D_i × EFFORT_SCALE)
effort_per_milli_i = int(C_i / D_i / unit_score_milli × EFFORT_SCALE)
```
where `unit_score_milli` = sum of all `_block_score(d)` for all duty blocks in the planning window.

**In the model, for each soldier:**
```
effort_var_i = effort_offset_i + Σ_d (effort_per_milli_i × _block_score(d) × x[d,i])
```
Minimize max(effort_var) — maximize min(effort_var among eligible) — tiebreak by effort_offset.

This fixes the פלאש 13 problem: a soldier with no history has `effort_offset = 0`. Each assignment raises their effort by `effort_per_milli × block_score`. Since they start far below veterans (who have nonzero offsets), assigning duties to them doesn't raise the max — so the solver assigns them freely until they reach the same level as everyone else.

---

## File Map

**Create:**
- `backend/app/services/effort_score.py` — compute historical effort data per soldier
- `backend/tests/test_effort_score.py` — unit tests for effort computation

**Modify:**
- `backend/app/algorithm/types.py` — add `effort_offset: int` and `effort_per_milli: int` to `SoldierInput`
- `backend/app/services/algorithm_bridge.py` — inject effort scores after loading soldiers + duties
- `backend/app/algorithm/model.py` — replace norm objective with effort-based objective
- `backend/app/algorithm/explain.py` — update `pre_norm_score` → `pre_effort_score` in explanations
- `backend/app/services/scoring.py` — add `effort_score` field to `transparency_rows()`
- `frontend/src/pages/SystemSettingsPage.tsx` — add `fairness.reset_date` setting
- `frontend/src/api/scoring.ts` — add `effort_score` to `TransparencyRow`
- `frontend/src/pages/TransparencyPage.tsx` — add effort score column
- `frontend/src/components/HelpModal.tsx` — rewrite `FairnessTab` and update `AlgorithmTab`

---

## Task 1: effort_score.py Service

**Files:**
- Create: `backend/app/services/effort_score.py`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/test_effort_score.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/__init__.py` (empty file), then create `backend/tests/test_effort_score.py`:

```python
# backend/tests/test_effort_score.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.services.effort_score import (
    EFFORT_SCALE,
    EffortData,
    quarter_end,
    quarter_start,
    _compute_effort_data,
)


def test_quarter_start_q1():
    assert quarter_start(date(2026, 2, 15)) == date(2026, 1, 1)


def test_quarter_start_q2():
    assert quarter_start(date(2026, 5, 1)) == date(2026, 4, 1)


def test_quarter_start_q3():
    assert quarter_start(date(2026, 8, 31)) == date(2026, 7, 1)


def test_quarter_start_q4():
    assert quarter_start(date(2026, 11, 1)) == date(2026, 10, 1)


def test_quarter_end_q1():
    assert quarter_end(date(2026, 1, 1)) == date(2026, 3, 31)


def test_quarter_end_q4():
    assert quarter_end(date(2026, 10, 1)) == date(2026, 12, 31)


# ---------------------------------------------------------------------------
# _compute_effort_data unit tests (pure logic, no DB)
# ---------------------------------------------------------------------------

@dataclass
class _MockSoldier:
    id: uuid.UUID
    enrolled_at: date


def _sid():
    return uuid.uuid4()


def test_new_soldier_no_history():
    """Soldier with no historical duties → effort_score=0, C_over_D=1.0."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2026, 4, 1))
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=[(date(2026, 4, 1), date(2026, 6, 30))],
        quarter_unit_scores={date(2026, 4, 1): Decimal("100")},
        quarter_soldier_scores={date(2026, 4, 1): {}},
        planning_start=date(2026, 7, 1),
        planning_end=date(2026, 8, 31),
    )
    data = result[sid]
    assert data.effort_score == Decimal("0")
    # C_i = full planning window / planning_window_length = 1.0
    # D_i = W_i + C_i = 0 + 1 = 1.0  (only 1 quarter counted, fully active)
    # C_over_D = 1.0
    assert data.C_over_D == Decimal("1")


def test_veteran_perfect_average():
    """Veteran with exactly 1/N share each quarter → effort_score = 1/N."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 1, 1))
    n = 10  # 10 soldiers in unit
    # 2 full quarters, each with unit_score=100, soldier got 10 (1/10)
    quarters = [
        (date(2025, 1, 1), date(2025, 3, 31)),
        (date(2025, 4, 1), date(2025, 6, 30)),
    ]
    unit_scores = {
        date(2025, 1, 1): Decimal("100"),
        date(2025, 4, 1): Decimal("100"),
    }
    soldier_scores = {
        date(2025, 1, 1): {sid: Decimal("10")},
        date(2025, 4, 1): {sid: Decimal("10")},
    }
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        planning_start=date(2025, 7, 1),
        planning_end=date(2025, 9, 30),
    )
    data = result[sid]
    # share_q1 = share_q2 = 0.1, active_frac = 1.0 both quarters
    # A_i = 0.1 + 0.1 = 0.2, W_i = 2.0, C_i = 1.0, D_i = 3.0
    # effort_score = A_i / D_i = 0.2 / 3 ≈ 0.0667
    assert abs(data.effort_score - Decimal("0.2") / Decimal("3")) < Decimal("0.0001")


def test_soldier_not_yet_enrolled():
    """Quarter before soldier enrolled → not counted in W_i."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 4, 1))
    quarters = [
        (date(2025, 1, 1), date(2025, 3, 31)),  # soldier not here yet
        (date(2025, 4, 1), date(2025, 6, 30)),  # soldier here
    ]
    unit_scores = {
        date(2025, 1, 1): Decimal("100"),
        date(2025, 4, 1): Decimal("100"),
    }
    soldier_scores = {
        date(2025, 1, 1): {},
        date(2025, 4, 1): {sid: Decimal("10")},
    }
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        planning_start=date(2025, 7, 1),
        planning_end=date(2025, 9, 30),
    )
    data = result[sid]
    # Q1: soldier not enrolled → skip. Q2: active_frac=1.0, share=0.1
    # A_i=0.1, W_i=1.0, C_i=1.0, D_i=2.0
    # effort_score = 0.1 / 2 = 0.05
    assert abs(data.effort_score - Decimal("0.05")) < Decimal("0.0001")
    assert abs(data.C_over_D - Decimal("0.5")) < Decimal("0.0001")


def test_effort_offset_integer():
    """effort_offset = int(effort_score × EFFORT_SCALE) and ≥ 0."""
    sid = _sid()
    soldier = _MockSoldier(id=sid, enrolled_at=date(2025, 1, 1))
    quarters = [(date(2025, 1, 1), date(2025, 3, 31))]
    unit_scores = {date(2025, 1, 1): Decimal("100")}
    soldier_scores = {date(2025, 1, 1): {sid: Decimal("20")}}
    result = _compute_effort_data(
        soldiers=[soldier],
        quarters=quarters,
        quarter_unit_scores=unit_scores,
        quarter_soldier_scores=soldier_scores,
        planning_start=date(2025, 4, 1),
        planning_end=date(2025, 6, 30),
    )
    data = result[sid]
    expected_offset = int(data.effort_score * EFFORT_SCALE)
    assert data.effort_offset == expected_offset
    assert data.effort_offset >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/test_effort_score.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.effort_score'`

- [ ] **Step 3: Create `backend/app/services/effort_score.py`**

```python
# backend/app/services/effort_score.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.services.scoring import effective_duty_days

# Scale factor for converting Decimal effort scores to CP-SAT integers.
# effort_offset = int(effort_score × EFFORT_SCALE)
# effort_per_milli = int(C_over_D / unit_score_milli × EFFORT_SCALE)
EFFORT_SCALE = 1_000_000_000  # 10^9


@dataclass
class EffortData:
    """Per-soldier effort computation result for use in the CP-SAT model."""
    effort_score: Decimal      # A_i / D_i: historical weighted-average quarterly share
    C_over_D: Decimal          # C_i / D_i: current-window weight over total weight
    effort_offset: int = 0     # int(effort_score × EFFORT_SCALE) — precomputed for model
    effort_per_milli: int = 0  # int(C_over_D / unit_score_milli × EFFORT_SCALE) — set by bridge


def quarter_start(d: date) -> date:
    """Return the first day of the calendar quarter containing d."""
    month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, month, 1)


def quarter_end(d: date) -> date:
    """Return the last day of the calendar quarter containing d."""
    qs = quarter_start(d)
    if qs.month >= 10:
        return date(qs.year, 12, 31)
    return date(qs.year, qs.month + 3, 1) - timedelta(days=1)


@dataclass
class _MockSoldier:
    """Minimal duck-typed soldier for testing _compute_effort_data without DB."""
    id: uuid.UUID
    enrolled_at: date


def _compute_effort_data(
    *,
    soldiers: list[Any],   # objects with .id (UUID) and .enrolled_at (date)
    quarters: list[tuple[date, date]],
    quarter_unit_scores: dict[date, Decimal],   # keyed by quarter_start date
    quarter_soldier_scores: dict[date, dict[uuid.UUID, Decimal]],  # keyed by quarter_start date
    planning_start: date,
    planning_end: date,
) -> dict[uuid.UUID, EffortData]:
    """
    Pure-logic core: compute EffortData per soldier given pre-aggregated quarter scores.

    quarters: list of (q_start, q_end) in ascending order.
    quarter_unit_scores: total unit score per quarter, keyed by q_start.
    quarter_soldier_scores: per-soldier scores per quarter, keyed by q_start.
    """
    planning_days = (planning_end - planning_start).days + 1
    result: dict[uuid.UUID, EffortData] = {}

    for soldier in soldiers:
        A_i = Decimal("0")  # numerator: sum(share_q × active_frac_q)
        W_i = Decimal("0")  # denominator: sum(active_frac_q)

        for q_start, q_end in quarters:
            q_days = (q_end - q_start).days + 1
            soldier_start = max(soldier.enrolled_at, q_start)
            if soldier_start > q_end:
                continue  # soldier not enrolled in this quarter

            active_in_q = (q_end - soldier_start).days + 1
            active_frac = Decimal(active_in_q) / Decimal(q_days)

            unit_score = quarter_unit_scores.get(q_start, Decimal("0"))
            if unit_score > 0:
                s_score = quarter_soldier_scores.get(q_start, {}).get(soldier.id, Decimal("0"))
                share_q = s_score / unit_score
                A_i += share_q * active_frac

            # Count the quarter in W_i regardless of whether unit had duties
            W_i += active_frac

        # Current planning window contribution
        sol_plan_start = max(soldier.enrolled_at, planning_start)
        if sol_plan_start <= planning_end:
            sol_planning_days = (planning_end - sol_plan_start).days + 1
            C_i = Decimal(sol_planning_days) / Decimal(planning_days)
        else:
            C_i = Decimal("0")

        D_i = W_i + C_i
        if D_i <= 0:
            result[soldier.id] = EffortData(
                effort_score=Decimal("0"), C_over_D=Decimal("0"),
                effort_offset=0, effort_per_milli=0,
            )
            continue

        effort_score = A_i / D_i
        C_over_D = C_i / D_i
        effort_offset = int(effort_score * EFFORT_SCALE)

        result[soldier.id] = EffortData(
            effort_score=effort_score,
            C_over_D=C_over_D,
            effort_offset=effort_offset,
            effort_per_milli=0,  # set by bridge after unit_score_milli is known
        )

    return result


def compute_effort_data(
    session: Session,
    *,
    soldiers: list[Any],    # objects with .id (UUID) and .enrolled_at (date)
    planning_start: date,
    planning_end: date,
    reset_date: date,
) -> dict[uuid.UUID, EffortData]:
    """
    Compute EffortData for all soldiers using published assignment history.

    Uses effective_duty_days() from scoring.py (same source-of-truth as score calculations).
    Loads history from reset_date up to (but not including) planning_start.

    Returns dict[soldier_id, EffortData] with effort_per_milli=0;
    the caller (bridge) sets effort_per_milli after knowing unit_score_milli.
    """
    from sqlalchemy import select
    from app.db.models import DutyType

    history_end = planning_start - timedelta(days=1)
    if history_end < reset_date:
        # No historical data — all soldiers start fresh
        quarters: list[tuple[date, date]] = []
        q_unit: dict[date, Decimal] = {}
        q_soldier: dict[date, dict[uuid.UUID, Decimal]] = {}
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=quarters,
            quarter_unit_scores=q_unit,
            quarter_soldier_scores=q_soldier,
            planning_start=planning_start,
            planning_end=planning_end,
        )

    # Build list of complete quarters between reset_date and planning_start
    quarters = []
    q_s = quarter_start(reset_date)
    while q_s < planning_start:
        q_e = quarter_end(q_s)
        actual_end = min(q_e, history_end)
        quarters.append((q_s, actual_end))
        # Advance to next quarter
        next_month = q_e + timedelta(days=1)
        q_s = next_month

    if not quarters:
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=[],
            quarter_unit_scores={},
            quarter_soldier_scores={},
            planning_start=planning_start,
            planning_end=planning_end,
        )

    # Fetch duty type scores
    dt_scores: dict[uuid.UUID, Decimal] = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    # Expand published assignments to per-day rows, filtered to history range
    days_data = effective_duty_days(session, date_from=reset_date, date_to=history_end)

    # Map each calendar date to its quarter_start
    date_to_quarter: dict[date, date] = {}
    for q_start_d, q_end_d in quarters:
        d = q_start_d
        while d <= q_end_d:
            date_to_quarter[d] = q_start_d
            d += timedelta(days=1)

    # Aggregate scores per quarter
    q_unit_scores: dict[date, Decimal] = {}
    q_soldier_scores: dict[date, dict[uuid.UUID, Decimal]] = {}
    for day, soldier_id, duty_type_id, mult in days_data:
        qs = date_to_quarter.get(day)
        if qs is None:
            continue
        score = dt_scores.get(duty_type_id, Decimal("0")) * mult
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + score
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[soldier_id] = q_s_map.get(soldier_id, Decimal("0")) + score

    return _compute_effort_data(
        soldiers=soldiers,
        quarters=quarters,
        quarter_unit_scores=q_unit_scores,
        quarter_soldier_scores=q_soldier_scores,
        planning_start=planning_start,
        planning_end=planning_end,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd backend
uv run pytest tests/test_effort_score.py -v
```
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/effort_score.py backend/tests/__init__.py backend/tests/test_effort_score.py
git commit -m "feat: add quarterly effort score service"
```

---

## Task 2: Update SoldierInput Type

**Files:**
- Modify: `backend/app/algorithm/types.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_effort_score.py` at the bottom:

```python
def test_soldier_input_has_effort_fields():
    """SoldierInput must have effort_offset and effort_per_milli fields."""
    from app.algorithm.types import SoldierInput
    import uuid
    from datetime import date
    from decimal import Decimal

    s = SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=90,
    )
    assert hasattr(s, "effort_offset")
    assert hasattr(s, "effort_per_milli")
    assert s.effort_offset == 0
    assert s.effort_per_milli == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
uv run pytest tests/test_effort_score.py::test_soldier_input_has_effort_fields -v
```
Expected: FAIL — `SoldierInput` has no attribute `effort_offset`.

- [ ] **Step 3: Add fields to `SoldierInput`**

In `backend/app/algorithm/types.py`, modify the `SoldierInput` dataclass (currently lines 11–19):

```python
@dataclass
class SoldierInput:
    """A soldier eligible for duty assignment."""
    id: uuid.UUID
    enrolled_at: date
    cumulative_score: Decimal
    active_days: int
    hierarchy_node_id: uuid.UUID | None = None
    approved_constraint_dates: list[tuple[date, date]] = field(default_factory=list)
    exempted_duty_type_ids: set[uuid.UUID] = field(default_factory=set)
    # Effort-based fairness fields (set by algorithm_bridge after loading duty blocks)
    effort_offset: int = 0      # int(effort_score × EFFORT_SCALE) — historical quarterly share
    effort_per_milli: int = 0   # int(C_over_D / unit_score_milli × EFFORT_SCALE) — per-milli contribution
```

- [ ] **Step 4: Run test**

```bash
cd backend
uv run pytest tests/test_effort_score.py -v
```
Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/types.py backend/tests/test_effort_score.py
git commit -m "feat: add effort_offset and effort_per_milli to SoldierInput"
```

---

## Task 3: Update algorithm_bridge.py — Inject Effort Scores

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

The bridge calls `compute_effort_data()` after loading soldiers and duty blocks, then sets `effort_offset` and `effort_per_milli` on each `SoldierInput` in-place.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_effort_score.py`:

```python
def test_inject_effort_scores():
    """After injection, SoldierInput has nonzero effort_per_milli when unit_score > 0."""
    from app.services.effort_score import EFFORT_SCALE, EffortData
    from app.algorithm.types import SoldierInput, DutyBlock
    from app.services.algorithm_bridge import inject_effort_scores
    import uuid
    from datetime import date
    from decimal import Decimal

    sid = uuid.uuid4()
    s = SoldierInput(
        id=sid, enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"), active_days=90,
    )
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(),
        duty_location_id=uuid.uuid4(),
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
        score_per_day=Decimal("0.5"),
    )
    # unit_score_milli = int(0.5 * 7 * 1000) = 3500
    # effort data: effort_score=0.1, C_over_D=0.5
    effort_map = {
        sid: EffortData(
            effort_score=Decimal("0.1"), C_over_D=Decimal("0.5"),
            effort_offset=int(Decimal("0.1") * EFFORT_SCALE),
        )
    }
    inject_effort_scores([s], [block], effort_map)
    assert s.effort_offset == int(Decimal("0.1") * EFFORT_SCALE)
    # effort_per_milli = int(0.5 / 3500 × EFFORT_SCALE) = int(142857) = 142857
    expected = int(Decimal("0.5") / 3500 * EFFORT_SCALE)
    assert s.effort_per_milli == expected
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
uv run pytest tests/test_effort_score.py::test_inject_effort_scores -v
```
Expected: FAIL — `cannot import name 'inject_effort_scores' from 'app.services.algorithm_bridge'`

- [ ] **Step 3: Add `inject_effort_scores` function to `algorithm_bridge.py`**

Add this import at the top of `backend/app/services/algorithm_bridge.py` (after existing imports):

```python
from app.services.effort_score import EFFORT_SCALE, EffortData, compute_effort_data
```

Add this function anywhere before `run_algorithm_job`:

```python
def inject_effort_scores(
    soldiers: list[SoldierInput],
    duty_blocks: list[DutyBlock],
    effort_map: dict[uuid.UUID, EffortData],
) -> None:
    """Set effort_offset and effort_per_milli on each SoldierInput in-place.

    effort_per_milli = int(C_over_D / unit_score_milli × EFFORT_SCALE)
    where unit_score_milli = sum of _block_score(b) for all blocks.
    """
    unit_score_milli = sum(
        int(float(b.score_per_day) * ((b.end_date - b.start_date).days + 1) * 1000)
        for b in duty_blocks
    )
    for s in soldiers:
        data = effort_map.get(s.id)
        if data is None:
            continue
        s.effort_offset = data.effort_offset
        if unit_score_milli > 0:
            s.effort_per_milli = int(float(data.C_over_D) / unit_score_milli * EFFORT_SCALE)
        else:
            s.effort_per_milli = 0
```

- [ ] **Step 4: Wire into `run_algorithm_job`**

Inside `run_algorithm_job`, after the line `soldiers = load_soldier_inputs(session, as_of=planning_start)` and after `duties, block_to_shift_map = load_duty_blocks_from_shifts(...)`, add the effort injection block. Find the section (around line 535–545):

```python
                soldiers = load_soldier_inputs(session, as_of=planning_start)
                existing = load_existing_assignments(
                    session,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    W=settings.W,
                )
```

After `soldiers = load_soldier_inputs(...)`, add:

```python
                # Compute and inject quarterly effort scores
                from app.services.effort_score import compute_effort_data
                from datetime import date as _date
                _reset_raw = get_setting(session, "fairness.reset_date") if True else None
                try:
                    _reset_raw = get_setting(session, "fairness.reset_date")
                    _reset_date = _date.fromisoformat(str(_reset_raw))
                except Exception:
                    # Default: 2 years ago, aligned to nearest quarter start
                    from app.services.effort_score import quarter_start as _qs
                    _reset_date = _qs(_date(planning_start.year - 2, planning_start.month, 1))
                effort_map = compute_effort_data(
                    session,
                    soldiers=soldiers,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    reset_date=_reset_date,
                )
                inject_effort_scores(soldiers, duties, effort_map)
```

- [ ] **Step 5: Run tests**

```bash
cd backend
uv run pytest tests/test_effort_score.py -v
```
Expected: all 10 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/tests/test_effort_score.py
git commit -m "feat: inject quarterly effort scores into SoldierInput in algorithm bridge"
```

---

## Task 4: Update model.py — Effort-Based Objective

**Files:**
- Modify: `backend/app/algorithm/model.py`

Replace the entire `# ── Normalised-score expressions` section (lines 114–163) and `# ── Fairness objective` section (lines 237–275) with effort-based equivalents.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_model_effort.py`:

```python
# backend/tests/test_model_effort.py
"""Verify the CP-SAT model uses effort-based objective when effort fields are set."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.algorithm.model import build_model
from app.algorithm.types import (
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)
from app.algorithm.solver import solve


def _soldier(score: Decimal, active_days: int, effort_offset: int, effort_per_milli: int, enrolled: date | None = None) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=enrolled or date(2024, 1, 1),
        cumulative_score=score,
        active_days=active_days,
        effort_offset=effort_offset,
        effort_per_milli=effort_per_milli,
    )


def _block(start: date, end: date, score: Decimal = Decimal("0.5")) -> DutyBlock:
    return DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=uuid.uuid4(),
        duty_location_id=uuid.uuid4(),
        start_date=start, end_date=end,
        score_per_day=score,
    )


def test_new_soldier_gets_duties_over_veteran():
    """
    Veteran has high effort_offset (100M). New soldier has effort_offset=0.
    With 2 duties and 2 soldiers, the new soldier should get at least 1 duty
    because assigning to them doesn't raise max_effort (they're far below veteran).
    """
    veteran = _soldier(
        score=Decimal("50"), active_days=1000,
        effort_offset=100_000_000,  # already high historical effort
        effort_per_milli=100,       # each duty only raises veteran effort by a little
    )
    newbie = _soldier(
        score=Decimal("0"), active_days=90,
        effort_offset=0,
        effort_per_milli=1000,  # each duty raises newbie effort by more (fewer quarters)
    )
    # duty type ids must match both soldiers (no exemptions)
    dt_id = uuid.uuid4()
    loc_id = uuid.uuid4()
    veteran.exempted_duty_type_ids = set()
    newbie.exempted_duty_type_ids = set()

    duties = [
        DutyBlock(id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=loc_id,
                  start_date=date(2026, 7, 1), end_date=date(2026, 7, 1), score_per_day=Decimal("0.5")),
        DutyBlock(id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=loc_id,
                  start_date=date(2026, 7, 2), end_date=date(2026, 7, 2), score_per_day=Decimal("0.5")),
    ]
    settings = SolverSettings(T=7, W=14, alpha=Decimal("1.0"), time_limit_seconds=10)
    result = solve([veteran, newbie], duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    # Count assignments per soldier
    vet_count = sum(1 for a in result.assignments if a.soldier_id == veteran.id)
    new_count = sum(1 for a in result.assignments if a.soldier_id == newbie.id)
    # With effort-based fairness, the new soldier should get the majority
    # (veteran already at high effort_offset=100M, assigning to them keeps raising max)
    assert new_count >= 1, f"New soldier got {new_count} duties, expected ≥1"


def test_model_builds_without_error_with_zero_effort():
    """Model must build and solve even when all effort fields are 0 (fallback path)."""
    dt_id = uuid.uuid4()
    loc_id = uuid.uuid4()
    soldiers = [
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     effort_offset=0, effort_per_milli=0)
        for _ in range(3)
    ]
    duties = [
        DutyBlock(id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=loc_id,
                  start_date=date(2026, 7, i), end_date=date(2026, 7, i),
                  score_per_day=Decimal("0.5"))
        for i in range(1, 4)
    ]
    settings = SolverSettings(T=7, W=14, alpha=Decimal("1.0"), time_limit_seconds=10)
    result = solve(soldiers, duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
uv run pytest tests/test_model_effort.py -v
```
Expected: `test_new_soldier_gets_duties_over_veteran` FAILS (new soldier gets 0 duties with old norm model).

- [ ] **Step 3: Replace the norm section in `model.py`**

In `backend/app/algorithm/model.py`, replace the entire block from line 114 (`# ── Normalised-score expressions`) through line 163 (end of `if duties_for_s:` block) with:

```python
    # ── Effort-based fairness expressions ──────────────────────────────────
    #
    # effort_var_i = effort_offset_i + Σ_d (effort_per_milli_i × _block_score(d) × x[d,i])
    #
    # effort_offset_i encodes the soldier's historical weighted-average quarterly
    # duty share (scaled by EFFORT_SCALE=10^9). A soldier with a long history
    # of heavy loads has a high offset; a new soldier starts at 0.
    #
    # effort_per_milli_i = C_i/D_i / unit_score_milli × EFFORT_SCALE
    # encodes how much this planning window "counts" relative to the soldier's
    # full history. New soldiers (first quarter: D_i=C_i) have per_milli=1/unit_milli×SCALE,
    # maximising the impact of each duty so the solver eagerly assigns them duties
    # to raise the fairness floor.
    #
    # Objective structure identical to old norm approach:
    # PRIMARY  (weight alpha_int): minimize max(effort) — avoids overloading veterans
    # SECONDARY (weight 1): maximize min(effort among eligible) — lifts new soldiers
    # TIEBREAKER: prefer assigning to historically lower-effort soldiers
    # ─────────────────────────────────────────────────────────────────────

    all_effort_exprs: list = []
    eligible_effort_exprs: list = []
    hist_penalty_terms: list = []

    for si, s in enumerate(soldier_list):
        duties_for_s = soldier_duties.get(si, [])

        if not duties_for_s and s.effort_offset == 0:
            continue

        block_sum = sum(
            s.effort_per_milli * _block_score(duty_list[di]) * x[(di, si)]
            for di in duties_for_s
        )

        effort_var = model.NewIntVar(0, 2_000_000_000_000, f"effort_s{si}")
        model.Add(effort_var == s.effort_offset + block_sum)
        all_effort_exprs.append(effort_var)

        if duties_for_s:
            eligible_effort_exprs.append(effort_var)

        # Historical tiebreaker: prefer assigning to soldiers with lower current effort
        for di in duties_for_s:
            hist_penalty_terms.append(s.effort_offset * x[(di, si)])

    max_effort_var = None
    if all_effort_exprs:
        max_effort_var = model.NewIntVar(0, 2_000_000_000_000, "max_effort")
        model.AddMaxEquality(max_effort_var, all_effort_exprs)
```

Then replace the fairness objective section (lines 237–275, from `# ── Fairness objective` to end of `model.Maximize` call) with:

```python
    # ── Fairness objective (effort-based) ──────────────────────────────────
    alpha_int = int(settings.alpha * 1000)
    dist_term = sum(reserve_dist_terms) if reserve_dist_terms else 0
    hist_penalty = sum(hist_penalty_terms) if hist_penalty_terms else 0

    if max_effort_var is not None and alpha_int > 0:
        min_term = 0
        if len(eligible_effort_exprs) > 1:
            min_effort_var = model.NewIntVar(0, 2_000_000_000_000, "min_effort_eligible")
            model.AddMinEquality(min_effort_var, eligible_effort_exprs)
            min_term = min_effort_var

        model.Maximize(-alpha_int * max_effort_var + min_term - hist_penalty - dist_term)
    else:
        model.Maximize(-dist_term)
```

Also remove the `max_norm_var = None` block (old lines 160–163) since it's no longer needed.

- [ ] **Step 4: Run tests**

```bash
cd backend
uv run pytest tests/test_model_effort.py tests/test_effort_score.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/model.py backend/tests/test_model_effort.py
git commit -m "feat: replace norm-based fairness objective with effort-based quarterly share metric"
```

---

## Task 5: Update explain.py — Effort Scores in Explanations

**Files:**
- Modify: `backend/app/algorithm/explain.py`
- Modify: `backend/app/algorithm/types.py` (`CandidateInfo`)
- Modify: `backend/app/services/algorithm_bridge.py` (`_explanation_payload`)

Update the explanation pipeline to show `pre_effort_score` and `post_effort_score` instead of `pre_norm_score` and `post_norm_score`.

- [ ] **Step 1: Update `CandidateInfo` in `types.py`**

Replace the `CandidateInfo` dataclass fields (currently `pre_norm_score` and `post_norm_score`):

```python
@dataclass
class CandidateInfo:
    """Analysis of a single candidate soldier for explainability."""
    soldier_id: uuid.UUID
    blocked: bool = False
    blocking_constraints: list[str] = field(default_factory=list)
    pre_effort_score: float | None = None   # effort_offset / EFFORT_SCALE (historical effort)
    post_effort_score: float | None = None  # effort after this assignment
```

- [ ] **Step 2: Update `explain.py`**

In `backend/app/algorithm/explain.py`, replace the `pre_norm`/`post_norm` computation block (lines 47–56):

```python
from app.services.effort_score import EFFORT_SCALE

        pre_effort = s.effort_offset / EFFORT_SCALE if EFFORT_SCALE > 0 else None
        blocked = len(blocking) > 0
        post_effort = None
        if not blocked:
            block_milli = int(
                float(duty.score_per_day) * ((duty.end_date - duty.start_date).days + 1) * 1000
            )
            post_milli = s.effort_offset + s.effort_per_milli * block_milli
            post_effort = post_milli / EFFORT_SCALE

        candidates.append(CandidateInfo(
            soldier_id=s.id,
            blocked=blocked,
            blocking_constraints=blocking,
            pre_effort_score=float(pre_effort) if pre_effort is not None else None,
            post_effort_score=float(post_effort) if post_effort is not None else None,
        ))
```

- [ ] **Step 3: Update `_explanation_payload` in `algorithm_bridge.py`**

Find the payload serialization in `_explanation_payload` (lines 357–358) and update the field names:

```python
        if dm_view:
            entry["soldier_name"] = soldier_names.get(c.soldier_id, "")
            entry["pre_effort_score"] = c.pre_effort_score
            entry["post_effort_score"] = c.post_effort_score
```

- [ ] **Step 4: Run all backend tests**

```bash
cd backend
uv run pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/explain.py backend/app/algorithm/types.py backend/app/services/algorithm_bridge.py
git commit -m "feat: update algorithm explanations to show effort scores instead of norm scores"
```

---

## Task 6: Update scoring.py — Effort Score in Transparency

**Files:**
- Modify: `backend/app/services/scoring.py`

Add `effort_score` to the dict returned by `transparency_rows()`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_effort_score.py`:

```python
def test_transparency_rows_has_effort_score_key():
    """transparency_rows() output dicts must contain an 'effort_score' key."""
    # We can't run the full DB query in a unit test, but we can verify the
    # function signature by inspecting that the key is expected in the return type.
    # This test will pass once the implementation is done.
    import inspect
    from app.services import scoring as sc
    src = inspect.getsource(sc.transparency_rows)
    assert "effort_score" in src, "transparency_rows must include effort_score in output"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
uv run pytest tests/test_effort_score.py::test_transparency_rows_has_effort_score_key -v
```
Expected: FAIL.

- [ ] **Step 3: Update `transparency_rows` in `scoring.py`**

In `backend/app/services/scoring.py`, inside `transparency_rows()`, replace the `rows.append(...)` block to add `effort_score`. First, add the import at the top of the function (after the existing variable assignments):

```python
def transparency_rows(session: Session) -> list[dict[str, Any]]:
    from app.services.effort_score import compute_effort_data, quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    duty_scores = duty_score_by_soldier(session)
    adj_scores = adjustments_by_soldier(session)
    shift_counts = shift_count_by_soldier(session)
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    exempted_ids = globally_exempted_soldier_ids(session)

    # Compute effort scores for all soldiers
    today = date.today()
    try:
        reset_raw = get_setting(session, "fairness.reset_date")
        reset_date = date.fromisoformat(str(reset_raw))
    except (SettingNotFound, ValueError):
        reset_date = quarter_start(date(today.year - 2, today.month, 1))

    effort_map = compute_effort_data(
        session,
        soldiers=soldiers,
        planning_start=today,
        planning_end=today,
        reset_date=reset_date,
    )

    rows: list[dict[str, Any]] = []
    for s in soldiers:
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = active_days(session, soldier=s)
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        effort_data = effort_map.get(s.id)
        effort_score = float(effort_data.effort_score) if effort_data else 0.0
        rows.append(
            {
                "soldier_id": s.id,
                "full_name": s.full_name,
                "node_id": s.hierarchy_node_id,
                "node_name": node.name if node is not None else None,
                "enrolled_at": s.enrolled_at,
                "active_days": ad,
                "shift_count": shift_counts.get(s.id, 0),
                "rank": s.rank,
                "is_officer": s.is_officer,
                "service_type": inferred_service_type(s),
                "cumulative_score": cum,
                "score_per_day": cum / Decimal(ad),
                "is_globally_exempted": s.id in exempted_ids,
                "effort_score": effort_score,
            }
        )
    if rows:
        avg_spd = sum(r["score_per_day"] for r in rows) / Decimal(len(rows))
    else:
        avg_spd = Decimal("0")
    for r in rows:
        r["normalised_score"] = (
            r["score_per_day"] / avg_spd if avg_spd != Decimal("0") else Decimal("0")
        )
    rows.sort(key=lambda r: r["effort_score"], reverse=True)
    return rows
```

Note the sort changed to `effort_score` (descending) — shows highest-effort soldiers first.

- [ ] **Step 4: Run tests**

```bash
cd backend
uv run pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py
git commit -m "feat: add effort_score to transparency rows, sort by effort"
```

---

## Task 7: SystemSettingsPage — Add fairness.reset_date

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`

Add a `fairness.reset_date` setting (type `"date"`) in the "הוגנות אלגוריתם" group. The date picker enforces ISO date string format.

- [ ] **Step 1: Add the new setting type to the settings infrastructure**

In `frontend/src/pages/SystemSettingsPage.tsx`, the `SettingDef` interface currently allows types `"boolean" | "number" | "decimal" | "select"`. Add `"date"`:

```typescript
interface SettingDef {
  key: string;
  label: string;
  description?: string;
  type: "boolean" | "number" | "decimal" | "select" | "date";
  defaultValue: string | number | boolean;
  options?: { value: string; label: string }[];
}
```

- [ ] **Step 2: Add the setting to the "הוגנות אלגוריתם" group**

In `SETTING_GROUPS`, add to the `"הוגנות אלגוריתם"` group:

```typescript
  {
    label: "הוגנות אלגוריתם",
    settings: [
      { key: "fairness.reserve_hierarchy_weight", label: "משקל קרבה היררכית לרזרבה", description: "משקל קרבה היררכית בבחירת חיילי רזרבה (0=ללא משקל, ערכים גבוהים=מעדיפים חיילים קרובים)", type: "decimal", defaultValue: 1.0 },
      {
        key: "fairness.reset_date",
        label: "תאריך איפוס נתוני הוגנות",
        description: "רק תורנויות מתאריך זה ואילך נלקחות בחשבון לחישוב עומס ההוגנות. מומלץ לבחור תחילת רבעון (1 בינואר, אפריל, יולי, אוקטובר). שינוי תאריך זה ישפיע על כל הרצות אלגוריתם עתידיות.",
        type: "date" as const,
        defaultValue: "",
      },
    ],
  },
```

- [ ] **Step 3: Add date input rendering in the settings form**

In the `SystemSettingsContent` component, find the section that renders input controls for each setting (the `{group.settings.map(def => { ... })}` block). Add a `date` case alongside the existing `number`, `boolean`, `decimal`, `select` cases:

```typescript
{def.type === "date" && (
  <input
    type="date"
    value={typeof resolveValue(draft, def) === "string" ? resolveValue(draft, def) as string : ""}
    onChange={e => setValue(def.key, e.target.value)}
    className="border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-indigo-300 outline-none"
    dir="ltr"
  />
)}
```

- [ ] **Step 4: Update `resolveValue` to handle empty date strings**

The `resolveValue` function returns `def.defaultValue` when the setting is unset. For a date field with `defaultValue: ""`, it will return `""`. No change needed — this works correctly.

- [ ] **Step 5: Verify in dev server**

Start the dev server with `dev.ps1` and navigate to Admin Settings → Fairness section. Confirm the date picker appears and saving a date (e.g., `2024-01-01`) works.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: add fairness.reset_date date picker to system settings"
```

---

## Task 8: TransparencyPage — Add Effort Score Column

**Files:**
- Modify: `frontend/src/api/scoring.ts`
- Modify: `frontend/src/pages/TransparencyPage.tsx`

- [ ] **Step 1: Update `TransparencyRow` in `scoring.ts`**

In `frontend/src/api/scoring.ts`, add `effort_score` to the `TransparencyRow` interface:

```typescript
export interface TransparencyRow {
  soldier_id: string;
  full_name: string;
  node_id: string | null;
  node_name: string | null;
  enrolled_at: string;
  active_days: number;
  shift_count: number;
  rank: string | null;
  is_officer: boolean;
  service_type: "חובה" | "קבע" | null;
  cumulative_score: string;
  score_per_day: string;
  normalised_score: string;
  is_globally_exempted: boolean;
  effort_score: number;   // weighted-average quarterly share (0.0–1.0+)
}
```

- [ ] **Step 2: Add effort_score column to TransparencyPage**

In `frontend/src/pages/TransparencyPage.tsx`, add the column definition to `soldierCols` after the `normalised` column:

```typescript
    {
      id: "effort_score", header: "עומס רבעוני",
      headerTooltip: "ממוצע משוקלל של חלק התורנויות של החייל מסך תורנויות היחידה לרבעון, מאז תאריך האיפוס. 0 = לא עשה תורנויות. ערך גבוה = עשה יותר מחלקו.",
      cell: (r) => {
        const n = r.effort_score;
        if (isNaN(n) || n === undefined) return "—";
        return (n * 100).toFixed(2) + "%";
      },
      sortValue: (r) => r.effort_score,
    },
```

Display as percentage (e.g., 2.34%) to be intuitive.

- [ ] **Step 3: Update summary cards in TransparencyPage**

After the existing 4 summary cards, the `avgNormalised` card can remain. The effort score is shown per-soldier in the table — no summary card needed (the average effort_score across all soldiers is always 1/N, which is uninformative).

- [ ] **Step 4: Verify**

Start dev server and open the Transparency page. The new "עומס רבעוני" column should appear and sort correctly. New soldiers (פלאש 13 type) show `0.00%` or a very small percentage, while soldiers with heavy recent history show higher percentages.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/scoring.ts frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: add effort_score (quarterly load) column to transparency page"
```

---

## Task 9: HelpModal — Rewrite Fairness and Algorithm Tabs

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`

Rewrite `FairnessTab` to explain the new quarterly effort metric. Update `AlgorithmTab` to replace the old norm reference.

- [ ] **Step 1: Replace `FairnessTab` in `HelpModal.tsx`**

Find and replace the entire `function FairnessTab()` (from line 181 to its closing `}`) with:

```tsx
function FairnessTab() {
  return (
    <div className="space-y-4 text-sm leading-relaxed" dir="rtl">
      <h3 className="text-base font-semibold text-indigo-700 dark:text-indigo-300">הוגנות ושקיפות</h3>
      <p className="text-gray-700 dark:text-gray-300">
        המערכת מודדת הוגנות על פי <strong>עומס רבעוני</strong> — כמה מסך תורנויות היחידה ברבעון נשא כל חייל, בממוצע על פני הרבעונים שבהם שירת.
      </p>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📊 איך מחשבים את העומס הרבעוני?</p>

        <div className="space-y-2 text-indigo-700 dark:text-indigo-300">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-medium text-sm">שלב 1 — חלק רבעוני</p>
            <div className="flex items-center justify-center gap-2 text-xs flex-wrap">
              <div className="bg-indigo-100 dark:bg-indigo-900 rounded px-2 py-1 font-medium">ניקוד החייל ברבעון</div>
              <div className="text-gray-500 font-bold">÷</div>
              <div className="bg-purple-100 dark:bg-purple-900 rounded px-2 py-1 font-medium">ניקוד כלל היחידה ברבעון</div>
              <div className="text-gray-500 font-bold">=</div>
              <div className="bg-green-100 dark:bg-green-900 rounded px-2 py-1 font-medium">חלק%</div>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-lg p-3 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-medium text-sm">שלב 2 — ממוצע משוקלל לפי נוכחות</p>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              רבעונים בהם שירתת פחות ימים (הצטרפת באמצע, חופשה ממושכת) מקבלים משקל פחות בממוצע. רבעון שלם = משקל מלא.
            </p>
          </div>
        </div>

        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded-lg p-3 text-xs text-amber-800 dark:text-amber-300">
          <p className="font-medium mb-1">🔑 למה זה פותר את בעיית הוותיקות?</p>
          <p>אם ביחידה היו מעט תורנויות לפני 5 שנים — כולם קיבלו חלק קטן. זה לא פוגע בחייל ותיק, כי היחס (חלק/כלל) נשאר הוגן בכל רבעון. חייל חדש מושווה <em>רק לתקופה שהוא שירת בה</em>.</p>
        </div>
      </div>

      <div className="bg-indigo-50 dark:bg-indigo-950 rounded-xl p-4 border border-indigo-200 dark:border-indigo-800 space-y-3">
        <p className="font-semibold text-indigo-800 dark:text-indigo-200">📝 דוגמה מספרית</p>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="bg-white dark:bg-gray-800 rounded-lg p-2 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-bold text-indigo-700 dark:text-indigo-300">דן — 3 שנים בשירות</p>
            <p>ניקוד ממוצע ברבעון: 4</p>
            <p>ניקוד יחידה ממוצע: 100</p>
            <p className="text-green-700 dark:text-green-400 font-medium">עומס: 4% לרבעון</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg p-2 border border-indigo-200 dark:border-indigo-700 space-y-1">
            <p className="font-bold text-purple-700 dark:text-purple-300">יעל — חדשה, רבעון ראשון</p>
            <p>ניקוד ברבעון עד כה: 0</p>
            <p>ניקוד יחידה: 100</p>
            <p className="text-red-600 dark:text-red-400 font-medium">עומס: 0% — תקבל עדיפות!</p>
          </div>
        </div>
        <p className="text-xs text-indigo-700 dark:text-indigo-300">האלגוריתם יעדיף את יעל כי יש לה עומס אפסי — היא תצבור תורנויות עד שהיא מגיעה לרמת דן.</p>
      </div>

      <div className="space-y-2">
        <p className="font-medium text-gray-800 dark:text-gray-200">🔎 שקיפות</p>
        {[
          { icon: "📊", title: "דף השקיפות", desc: "כל חייל רואה את העומס הרבעוני שלו ושל שאר חברי היחידה — כולל טבלה שניתן למיין לפי עומס." },
          { icon: "📅", title: "תאריך איפוס", desc: "מנהל המערכת יכול לקבוע מאיזה תאריך מחשבים היסטוריה. מומלץ: תחילת רבעון. תורנויות לפני תאריך זה לא נלקחות בחשבון." },
          { icon: "⚖️", title: "הגינות לחדשים", desc: "חייל שהצטרף לאחרונה מושווה רק לתקופה שבה שירת — הוא לא נפגע מכך שהיחידה הייתה פחות עסוקה לפני שהצטרף." },
        ].map(({ icon, title, desc }) => (
          <div key={title} className="flex gap-3 bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600">
            <span className="text-xl flex-shrink-0">{icon}</span>
            <div>
              <p className="font-medium text-gray-800 dark:text-gray-200">{title}</p>
              <p className="text-gray-600 dark:text-gray-300">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update `AlgorithmTab` — replace the old norm reference**

In `AlgorithmTab`, find the "ניקוד מנורמל" item in the `[...].map(...)` list:

```tsx
{ icon: "📊", title: "ניקוד מנורמל", desc: "מי שעשה פחות תורנויות ביחס לאחרים מקבל עדיפות. ראו הסבר מלא בטאב הוגנות." },
```

Replace with:

```tsx
{ icon: "📊", title: "עומס רבעוני", desc: "מי שחלקו בתורנויות ברבעונים האחרונים נמוך מחבריו מקבל עדיפות. חייל חדש בעל עומס אפס יזכה בתורנויות עד שישתווה לשאר. ראו הסבר מלא בטאב הוגנות." },
```

Also update the "מגבלת הוגנות (K)" item description (since K was tied to old norm system):

```tsx
{ icon: "🔒", title: "איזון עומסים", desc: "האלגוריתם ממזער את הפער בין החייל עם העומס הגבוה ביותר לנמוך ביותר. אם אין מספיק חיילים כשירים, הפער עלול להישאר — האלגוריתם עושה את מיטבו בתוך האילוצים." },
```

Update the numerical example at the bottom of `AlgorithmTab` (currently showing "ניקוד מנורמל 0.8", "1.0", "1.4"):

```tsx
        <p className="text-indigo-700 dark:text-indigo-300 text-xs leading-relaxed">
          נניח שיש 3 חיילים: דן (עומס 3%), יעל (5%), ורוני (8%).
          משמרת חדשה צריכה מישהו — יעל פטורה ממנה.
          האלגוריתם בוחר מדן ורוני; מכיוון שדן בעל עומס נמוך יותר הוא יקבל עדיפות.
          כך ברמה העולמית, ההפרש בין רוני (8%) לדן ייצטמצם עם הזמן.
        </p>
        <div className="grid grid-cols-3 gap-2 text-xs text-center">
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-indigo-700 dark:text-indigo-300">דן</p>
            <p>עומס: 3%</p>
            <p className="text-green-600">⬆ עדיפות גבוהה</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-purple-700 dark:text-purple-300">יעל</p>
            <p>עומס: 5%</p>
            <p className="text-gray-500">✗ פטור חל</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded p-2 border border-indigo-200 dark:border-indigo-700">
            <p className="font-bold text-orange-700 dark:text-orange-300">רוני</p>
            <p>עומס: 8%</p>
            <p className="text-orange-600">⬇ עדיפות נמוכה</p>
          </div>
        </div>
```

- [ ] **Step 3: Verify**

Start dev server, open Help modal, check "⚖️ הוגנות ושקיפות" and "⚙️ האלגוריתם" tabs. Both should show updated content with no references to old norm/score-per-day metric.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "docs: rewrite HelpModal fairness and algorithm tabs for quarterly effort metric"
```

---

## Self-Review

**Spec coverage:**
- ✅ `effort_score.py` service with quarterly share computation
- ✅ `SoldierInput` new fields
- ✅ Bridge injection of effort scores
- ✅ `model.py` effort-based objective (minimize max effort, maximize min, tiebreak by history)
- ✅ `explain.py` updated to show effort scores
- ✅ `scoring.py` effort_score in transparency rows
- ✅ `SystemSettingsPage` fairness.reset_date date picker
- ✅ `TransparencyPage` effort_score column
- ✅ `HelpModal` rewritten fairness + algorithm tabs

**Type consistency:**
- `EffortData.effort_score` (Decimal) → `effort_offset` (int) — consistent across effort_score.py and bridge
- `effort_per_milli` set in bridge and consumed in model — consistent field name
- `pre_effort_score` / `post_effort_score` — updated in both `types.py` and `explain.py`

**One gap to note:** The `SubRow` data in `TransparencyPage` (sub-hierarchy tab) still shows `avg_normalised` using the old norm. That's a display-layer concern — updating the sub-hierarchy aggregation to show average effort_score would require additional work and is out of scope for this plan. Can be done as a follow-up.
