# Dual-Window Calendar Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the single rolling window `W` into two independent caps — `Wt` (T constraint window) and `Wr` (R constraint window) — and replace count-based batching with calendar-window batching to reduce fairness artifacts from sequential density-window coupling.

**Architecture:** Four layers touched in dependency order: (1) pure algorithm types/model/solver, (2) algorithm_bridge service, (3) backend REST routes + system settings, (4) frontend TypeScript API wrapper and form. The split is clean: each layer has no upward imports, so we can commit each layer atomically without breaking anything else.

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, FastAPI + Pydantic v2, SQLAlchemy 2, React + TypeScript, `uv run pytest` for backend tests, `pnpm test` for frontend.

---

## File Map

| File | Change |
|------|--------|
| `backend/app/algorithm/types.py` | Replace `W` with `Wt`/`Wr`; `R` default 8→15; `batch_size`→`batch_window_days`; `relax_r_ceiling` 12→20 |
| `backend/app/algorithm/model.py` | Split single `while ws <= max_d` loop into two separate loops using `Wt` and `Wr` respectively |
| `backend/app/algorithm/solver.py` | Replace `_date_batches` + count threshold with `_calendar_window_batches`; update `_decomposed_solve` and `solve` |
| `backend/app/algorithm/tests/test_solver.py` | Add `test_calendar_window_batching_separates_windows` |
| `backend/tests/unit/test_model.py` | Add `test_dual_window_wr_wider_than_wt`; fix existing tests that pass `W=` |
| `backend/app/services/algorithm_bridge.py` | `load_existing_assignments`: rename `W`→`Wr`; `resolve_solver_settings`: drop W, add Wt/Wr/batch_window_days, update defaults |
| `backend/app/services/tests/test_algorithm_bridge.py` | Update all assertions for Wt/Wr; update system-setting keys |
| `backend/app/routes/algorithm.py` | `SolverSettingsIn`: drop W, add Wt/Wr, R default 15; `AlgorithmDefaultsOut`: drop W, add Wt/Wr; update validation and `get_algorithm_defaults` |
| `backend/app/routes/system_settings.py` | Add `algorithm.window_t`/`algorithm.window_r`/`algorithm.batch_window_days` to `_DENSITY_DEFAULTS`; update R/relax_r_ceiling defaults; update validation |
| `backend/tests/integration/test_algorithm_routes.py` | Update `test_algorithm_defaults_returns_resolved_settings` for Wt/Wr |
| `frontend/src/api/algorithm.ts` | Remove `W`, add `Wt`/`Wr` in `SolverSettings` and `AlgorithmDefaults` |
| `frontend/src/components/AlgorithmRunForm.tsx` | Update `DEFAULT_SETTINGS`; update seed-from-defaults useEffect; update form fields |

---

## Task 1: Core algorithm layer — split W into Wt/Wr, calendar window batching

**Files:**
- Modify: `backend/app/algorithm/types.py`
- Modify: `backend/app/algorithm/model.py`
- Modify: `backend/app/algorithm/solver.py`
- Test (new): `backend/app/algorithm/tests/test_solver.py` (append)
- Test (modify): `backend/tests/unit/test_model.py`

- [ ] **Step 1: Write the failing test for dual-window model constraint**

Append to `backend/tests/unit/test_model.py`:

```python
def test_dual_window_wr_wider_than_wt():
    """When Wr > Wt, a soldier can take a reserve duty in the Wr window even when
    the same window would exceed T under Wt — because reserve duties only count
    against R (Wr window), not T (Wt window)."""
    s = _soldier(0.0)
    # Soldier already has 7 non-reserve existing duties on days 1-7 (fills T=8 almost)
    # and 1 reserve existing duty on day 8 (fills R-side).
    # New duty: reserve on day 15 (within Wr=28 from day 1, outside Wt=14 from day 1)
    from app.algorithm.types import ExistingAssignment
    existing = [
        ExistingAssignment(
            soldier_id=s.id,
            duty_type_id=uuid.uuid4(),
            start_date=date(2027, 1, d),
            end_date=date(2027, 1, d),
            is_reserve=False,
        )
        for d in range(1, 8)  # 7 non-reserve days
    ]
    # Reserve duty on day 20 — within Wr=28 window, outside Wt=14 window
    reserve_d = _duty(date(2027, 1, 20), score=0.2)
    reserve_d = DutyBlock(
        id=reserve_d.id,
        duty_type_id=reserve_d.duty_type_id,
        duty_location_id=reserve_d.duty_location_id,
        start_date=reserve_d.start_date,
        end_date=reserve_d.end_date,
        score_per_day=reserve_d.score_per_day,
        is_reserve=True,
    )
    # With Wt=14, Wr=28, T=8, R=8: the reserve duty on day 20 is inside the R window
    # [day1, day28] (8 existing_all_fixed days = 7 non-reserve + 0 reserve existing).
    # existing_all_fixed = 7 (days 1-7), so 7 + 1 (reserve) = 8 <= R=8 — FEASIBLE.
    assigned = _solve([s], [reserve_d], existing=existing, T=8, Wt=14, R=8, Wr=28)
    assert reserve_d.id in assigned.values() or reserve_d.id in assigned
```

- [ ] **Step 2: Run test to verify it fails (W parameter missing)**

```
cd backend && uv run pytest tests/unit/test_model.py::test_dual_window_wr_wider_than_wt -v
```

Expected: `TypeError` — `SolverSettings.__init__() got an unexpected keyword argument 'Wt'`

- [ ] **Step 3: Update `backend/app/algorithm/types.py`**

Replace the entire `SolverSettings` dataclass:

```python
@dataclass
class SolverSettings:
    """CP-SAT solver configuration.

    T: non-reserve duty-day cap per Wt rolling window
    Wt: rolling window length (days) for the T (non-reserve) cap
    R: total duty-day cap per Wr rolling window (incl. reserve); invariant T <= R
    Wr: rolling window length (days) for the R (all-duties) cap
    alpha: score-preference weight (higher = stronger preference for low-score soldiers)
    """
    T: int = 8
    Wt: int = 14
    R: int = 15
    Wr: int = 28
    alpha: Decimal = Decimal("1.0")
    time_limit_seconds: int = 30
    seed: int | None = None
    reserve_hierarchy_weight: Decimal = Decimal("0.5")
    # Fairness L1 in count-space: effort × effort_resolution, rounded to integers.
    effort_resolution: int = 10_000
    # Infeasibility relaxation ceilings: R relaxes first up to relax_r_ceiling,
    # then T relaxes up to relax_t_ceiling. Invariant: relax_t_ceiling <= relax_r_ceiling.
    relax_r_ceiling: int = 20
    relax_t_ceiling: int = 10
    # Decomposition + chronological calendar-window batching.
    batching_enabled: bool = True
    batch_window_days: int = 28
    batch_time_limit_seconds: int = 10
```

- [ ] **Step 4: Update `backend/app/algorithm/model.py`**

Replace the lines:
```python
    W = settings.W
    T = settings.T
    R = settings.R
```
with:
```python
    Wt = settings.Wt
    Wr = settings.Wr
    T = settings.T
    R = settings.R
```

Then replace the single window loop (from `ws = min_d` through `ws += timedelta(days=1)`) with two separate loops:

```python
        # ── T cap: non-reserve duty-days per Wt-day rolling window ───────────
        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=Wt - 1)
            existing_real_fixed = (
                bisect.bisect_right(sorted_existing_real, we)
                - bisect.bisect_left(sorted_existing_real, ws)
            )
            right = bisect.bisect_right(starts_sorted, we)
            vars_real: list[IntVar] = []
            for i in range(right):
                if ends_sorted[i] < ws:
                    continue
                di = si_duties_sorted[i]
                if not duty_list[di].is_reserve:
                    vars_real.append(x[(di, si)])
            if vars_real or existing_real_fixed:
                model.Add(existing_real_fixed + sum(vars_real) <= T)
            ws += timedelta(days=1)

        # ── R cap: all duty-days (reserve + real) per Wr-day rolling window ──
        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=Wr - 1)
            existing_all_fixed = (
                bisect.bisect_right(sorted_existing_all, we)
                - bisect.bisect_left(sorted_existing_all, ws)
            )
            right = bisect.bisect_right(starts_sorted, we)
            vars_all: list[IntVar] = []
            for i in range(right):
                if ends_sorted[i] < ws:
                    continue
                di = si_duties_sorted[i]
                vars_all.append(x[(di, si)])
            if vars_all or existing_all_fixed:
                model.Add(existing_all_fixed + sum(vars_all) <= R)
            ws += timedelta(days=1)
```

- [ ] **Step 5: Write the failing test for calendar window batching**

Append to `backend/app/algorithm/tests/test_solver.py`:

```python
def test_calendar_window_batches_groups_by_start_date():
    """Calendar window batching must group duties whose start_date falls within
    [window_start, window_start + batch_window_days), advancing the window start
    to each new duty's date when that duty would exceed the window."""
    from app.algorithm.solver import _calendar_window_batches
    from app.algorithm.types import DutyBlock
    import uuid
    from datetime import date
    from decimal import Decimal

    def _blk(d: date) -> DutyBlock:
        return DutyBlock(
            id=uuid.uuid4(),
            duty_type_id=uuid.uuid4(),
            duty_location_id=uuid.uuid4(),
            start_date=d,
            end_date=d,
            score_per_day=Decimal("1.0"),
        )

    # 3 duties in first window (Jan 1-28), 2 duties in second window (Feb 1-28)
    duties = [
        _blk(date(2027, 1, 1)),
        _blk(date(2027, 1, 15)),
        _blk(date(2027, 1, 28)),
        _blk(date(2027, 2, 1)),
        _blk(date(2027, 2, 20)),
    ]
    idxs = list(range(5))
    batches = _calendar_window_batches(idxs, duties, batch_window_days=28)
    assert len(batches) == 2
    assert batches[0] == [0, 1, 2]
    assert batches[1] == [3, 4]
```

- [ ] **Step 6: Run test to verify it fails**

```
cd backend && uv run pytest app/algorithm/tests/test_solver.py::test_calendar_window_batches_groups_by_start_date -v
```

Expected: `ImportError` — `cannot import name '_calendar_window_batches'`

- [ ] **Step 7: Update `backend/app/algorithm/solver.py`**

Replace the `_date_batches` function with `_calendar_window_batches`:

```python
def _calendar_window_batches(
    duty_idxs_sorted: list[int], duties: Sequence[DutyBlock], batch_window_days: int
) -> list[list[int]]:
    """Group duties into non-overlapping calendar windows of batch_window_days.

    Window N covers [window_start, window_start + batch_window_days). When the
    next duty's start_date falls outside the current window, a new window opens
    anchored at that duty's start_date. This keeps duties that couple via the
    Wr density window in the same batch, reducing infeasibility-relaxation artifacts.
    """
    if not duty_idxs_sorted:
        return []
    batches: list[list[int]] = []
    window_start = duties[duty_idxs_sorted[0]].start_date
    cur: list[int] = []
    for di in duty_idxs_sorted:
        d = duties[di]
        if (d.start_date - window_start).days >= batch_window_days:
            if cur:
                batches.append(cur)
            window_start = d.start_date
            cur = []
        cur.append(di)
    if cur:
        batches.append(cur)
    return batches
```

Then in `_decomposed_solve`, replace:
```python
        for batch in _date_batches(duty_idxs, duties, settings.batch_size):
```
with:
```python
        for batch in _calendar_window_batches(duty_idxs, duties, settings.batch_window_days):
```

And in `solve`, replace:
```python
    if settings.batching_enabled and len(duties) > settings.batch_size:
```
with:
```python
    if settings.batching_enabled:
```

- [ ] **Step 8: Fix existing `test_model.py` tests that pass `W=`**

In `_solve` helper, `SolverSettings(**settings_kwargs)` is called. Search for any call passing `W=`:

```
cd backend && grep -n "W=" tests/unit/test_model.py
```

If any test passes `W=14` or similar, replace with `Wt=14, Wr=28` (or the test-appropriate values). Also fix any test that asserts on `settings.W`.

- [ ] **Step 9: Run full algorithm test suite**

```
cd backend && uv run pytest app/algorithm/tests/ tests/unit/test_model.py -v
```

Expected: All tests pass.

- [ ] **Step 10: Commit**

```
git add backend/app/algorithm/types.py backend/app/algorithm/model.py backend/app/algorithm/solver.py backend/tests/unit/test_model.py backend/app/algorithm/tests/
git commit -m "feat: split W into Wt/Wr, replace count batching with calendar windows"
```

---

## Task 2: Services layer — update algorithm_bridge.py

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`
- Modify: `backend/app/services/tests/test_algorithm_bridge.py`

- [ ] **Step 1: Update the existing bridge tests to assert new parameter names**

In `backend/app/services/tests/test_algorithm_bridge.py`, the three existing tests need:

```python
def test_resolve_solver_settings_uses_system_defaults(admin_session):
    set_setting(admin_session, "algorithm.max_duties_per_window", 6, actor_id=None)
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    set_setting(admin_session, "algorithm.window_t", 21, actor_id=None)
    set_setting(admin_session, "algorithm.window_r", 35, actor_id=None)
    set_setting(admin_session, "algorithm.relax_t_ceiling", 8, actor_id=None)
    set_setting(admin_session, "algorithm.relax_r_ceiling", 15, actor_id=None)
    admin_session.flush()

    s = resolve_solver_settings(admin_session, {})
    assert s.T == 6
    assert s.R == 10
    assert s.Wt == 21
    assert s.Wr == 35
    assert s.relax_t_ceiling == 8
    assert s.relax_r_ceiling == 15


def test_resolve_solver_settings_per_run_overrides_win(admin_session):
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    admin_session.flush()
    s = resolve_solver_settings(admin_session, {"T": 5, "R": 9, "Wt": 14, "Wr": 28})
    assert s.T == 5
    assert s.R == 9
    assert s.Wt == 14
    assert s.Wr == 28


def test_resolve_solver_settings_falls_back_to_hardcoded_defaults(admin_session):
    s = resolve_solver_settings(admin_session, {})
    assert s.T == 8
    assert s.R == 15
    assert s.Wt == 14
    assert s.Wr == 28
    assert s.relax_t_ceiling == 10
    assert s.relax_r_ceiling == 20
```

- [ ] **Step 2: Run the tests to verify they fail**

```
cd backend && uv run pytest app/services/tests/test_algorithm_bridge.py -v
```

Expected: `AssertionError` on `s.Wt` (AttributeError or wrong value) and `s.R == 8` ≠ 15.

- [ ] **Step 3: Update `load_existing_assignments` in `algorithm_bridge.py`**

Change the function signature from `W: int` to `Wr: int`:

```python
def load_existing_assignments(
    session: Session,
    *,
    planning_start: date,
    planning_end: date,
    Wr: int,
) -> list[ExistingAssignment]:
    """Load published assignments within Wr days of the planning window for density checks."""
    boundary_start = planning_start - timedelta(days=Wr)
    boundary_end = planning_end + timedelta(days=Wr)
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
    return [
        ExistingAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
            is_reserve=a.is_reserve,
        )
        for a in rows
    ]
```

- [ ] **Step 4: Update `resolve_solver_settings` in `algorithm_bridge.py`**

Replace the return statement in `resolve_solver_settings`:

```python
    return SolverSettings(
        T=int(settings_json.get("T", _setting_int("algorithm.max_duties_per_window", 8))),
        Wt=int(settings_json.get("Wt", _setting_int("algorithm.window_t", 14))),
        R=int(settings_json.get("R", _setting_int("algorithm.max_total_duties_per_window", 15))),
        Wr=int(settings_json.get("Wr", _setting_int("algorithm.window_r", 28))),
        alpha=Decimal(str(settings_json.get("alpha", 1.0))),
        time_limit_seconds=int(settings_json.get("time_limit_seconds", 30)),
        reserve_hierarchy_weight=_setting_decimal("fairness.reserve_hierarchy_weight", "0.5"),
        effort_resolution=_setting_int("fairness.effort_resolution", 10_000),
        batching_enabled=_setting_bool("algorithm.batching_enabled", True),
        batch_window_days=_setting_int("algorithm.batch_window_days", 28),
        batch_time_limit_seconds=_setting_int("algorithm.batch_time_limit_seconds", 10),
        relax_t_ceiling=int(settings_json.get("relax_t_ceiling", _setting_int("algorithm.relax_t_ceiling", 10))),
        relax_r_ceiling=int(settings_json.get("relax_r_ceiling", _setting_int("algorithm.relax_r_ceiling", 20))),
    )
```

- [ ] **Step 5: Update `run_algorithm_job` call to `load_existing_assignments`**

Find this line in `run_algorithm_job`:
```python
                existing = load_existing_assignments(
                    session,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    W=settings.W,
                )
```

Replace with:
```python
                existing = load_existing_assignments(
                    session,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    Wr=settings.Wr,
                )
```

- [ ] **Step 6: Run bridge tests**

```
cd backend && uv run pytest app/services/tests/test_algorithm_bridge.py -v
```

Expected: All 3 tests pass.

- [ ] **Step 7: Run full test suite to catch any other W references**

```
cd backend && uv run pytest -q 2>&1 | head -60
```

Fix any remaining `settings.W` or `settings.batch_size` references in test files.

- [ ] **Step 8: Commit**

```
git add backend/app/services/algorithm_bridge.py backend/app/services/tests/test_algorithm_bridge.py
git commit -m "feat: update algorithm_bridge for Wt/Wr split and batch_window_days"
```

---

## Task 3: Backend routes — update schemas and system settings

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Modify: `backend/app/routes/system_settings.py`
- Modify: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Update the integration test for GET /defaults**

In `backend/tests/integration/test_algorithm_routes.py`, find `test_algorithm_defaults_returns_resolved_settings` and replace it:

```python
def test_algorithm_defaults_returns_resolved_settings(client, admin_session):
    from app.services.settings_loader import set_setting
    dm, _node = _setup_dm(admin_session, "route_alg_def")
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    admin_session.commit()

    resp = client.get("/api/algorithm/defaults", headers=auth_headers(dm))
    assert resp.status_code == 200
    body = resp.json()
    assert body["T"] == 8
    assert body["R"] == 10
    assert body["Wt"] == 14
    assert body["Wr"] == 28
```

Also find `test_create_job_rejects_T_greater_than_R` which passes `"W": 14` in the settings dict. Replace `"W": 14` with `"Wt": 14, "Wr": 28`.

- [ ] **Step 2: Run the test to verify it fails**

```
cd backend && uv run pytest tests/integration/test_algorithm_routes.py::test_algorithm_defaults_returns_resolved_settings -v
```

Expected: `AssertionError` — body has `"W"` key, no `"Wt"` key.

- [ ] **Step 3: Update `SolverSettingsIn` and `AlgorithmDefaultsOut` in `algorithm.py`**

Replace:
```python
class SolverSettingsIn(BaseModel):
    K: int = 8
    T: int = 8
    R: int = 8
    W: int = 14
    alpha: float = 1.0
    time_limit_seconds: int = 30


class AlgorithmDefaultsOut(BaseModel):
    T: int
    R: int
    W: int
```

With:
```python
class SolverSettingsIn(BaseModel):
    K: int = 8
    T: int = 8
    Wt: int = 14
    R: int = 15
    Wr: int = 28
    alpha: float = 1.0
    time_limit_seconds: int = 30


class AlgorithmDefaultsOut(BaseModel):
    T: int
    Wt: int
    R: int
    Wr: int
```

- [ ] **Step 4: Update the `get_algorithm_defaults` endpoint and job validation in `algorithm.py`**

Replace:
```python
    return AlgorithmDefaultsOut(T=s.T, R=s.R, W=s.W)
```
with:
```python
    return AlgorithmDefaultsOut(T=s.T, Wt=s.Wt, R=s.R, Wr=s.Wr)
```

The `T > R` validation at the top of `create_job` uses `body.settings.T` and `body.settings.R` which still exist — no change needed there.

- [ ] **Step 5: Update `_DENSITY_DEFAULTS` and validation in `system_settings.py`**

Replace:
```python
_DENSITY_DEFAULTS = {
    "algorithm.max_duties_per_window": 8,
    "algorithm.max_total_duties_per_window": 8,
    "algorithm.relax_t_ceiling": 10,
    "algorithm.relax_r_ceiling": 12,
}
```
with:
```python
_DENSITY_DEFAULTS = {
    "algorithm.max_duties_per_window": 8,
    "algorithm.max_total_duties_per_window": 15,
    "algorithm.window_t": 14,
    "algorithm.window_r": 28,
    "algorithm.batch_window_days": 28,
    "algorithm.relax_t_ceiling": 10,
    "algorithm.relax_r_ceiling": 20,
}
```

Replace the validation block in `update_settings`:
```python
    def _density(key: str) -> int:
        return int(merged.get(key, _DENSITY_DEFAULTS[key]))

    t = _density("algorithm.max_duties_per_window")
    r = _density("algorithm.max_total_duties_per_window")
    t_ceil = _density("algorithm.relax_t_ceiling")
    r_ceil = _density("algorithm.relax_r_ceiling")

    if t > r:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="t_exceeds_r")
    if t_ceil > r_ceil or t > t_ceil or r > r_ceil:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="relax_ceiling_invalid")
```
(No change needed — the validation only uses T/R/ceilings which are still present. Just confirm it compiles cleanly after `_DENSITY_DEFAULTS` is updated.)

- [ ] **Step 6: Run integration tests**

```
cd backend && uv run pytest tests/integration/test_algorithm_routes.py -v
```

Expected: All tests pass including the updated defaults test.

- [ ] **Step 7: Run full backend test suite**

```
cd backend && uv run pytest -q
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```
git add backend/app/routes/algorithm.py backend/app/routes/system_settings.py backend/tests/integration/test_algorithm_routes.py
git commit -m "feat: update algorithm routes and system settings for Wt/Wr split"
```

---

## Task 4: Frontend — update TypeScript API wrapper and run form

**Files:**
- Modify: `frontend/src/api/algorithm.ts`
- Modify: `frontend/src/components/AlgorithmRunForm.tsx`

- [ ] **Step 1: Update `frontend/src/api/algorithm.ts`**

Find the `SolverSettings` and `AlgorithmDefaults` interfaces. Replace:
```typescript
export interface SolverSettings {
  K: number;
  T: number;
  R: number;
  W: number;
  alpha: number;
  beta: number;
  time_limit_seconds: number;
}

export interface AlgorithmDefaults {
  T: number;
  R: number;
  W: number;
}
```
with:
```typescript
export interface SolverSettings {
  K: number;
  T: number;
  Wt: number;
  R: number;
  Wr: number;
  alpha: number;
  beta: number;
  time_limit_seconds: number;
}

export interface AlgorithmDefaults {
  T: number;
  Wt: number;
  R: number;
  Wr: number;
}
```

- [ ] **Step 2: Update `frontend/src/components/AlgorithmRunForm.tsx`**

Replace `DEFAULT_SETTINGS`:
```typescript
const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};
```

Update the defaults useEffect to seed `Wt` and `Wr` (not `W`):
```typescript
  useEffect(() => {
    void getAlgorithmDefaults()
      .then(d => setSettings(s => ({ ...s, T: d.T, Wt: d.Wt, R: d.R, Wr: d.Wr })))
      .catch(() => { /* keep hardcoded defaults if unavailable */ });
  }, []);
```

Update the form field list — replace `"W"` with `"Wt"` and `"Wr"` in the settings grid:
```typescript
          {(["K", "T", "Wt", "R", "Wr", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
```

- [ ] **Step 3: Run TypeScript type check**

```
cd frontend && pnpm tsc --noEmit
```

Expected: Zero errors.

- [ ] **Step 4: Run frontend tests**

```
cd frontend && pnpm test
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```
git add frontend/src/api/algorithm.ts frontend/src/components/AlgorithmRunForm.tsx
git commit -m "feat: update frontend for Wt/Wr split in algorithm settings"
```

---

## Self-Review

**Spec coverage:**
- ✅ W split into Wt (for T) and Wr (for R) — Tasks 1, 2, 3, 4
- ✅ T=8, Wt=14, R=15, Wr=28 as new defaults — Task 1 (types.py), Task 2 (bridge), Task 3 (routes)
- ✅ relax_r_ceiling updated to 20 — Task 1 (types.py), Task 2 (bridge), Task 3 (system_settings)
- ✅ batch_size replaced by batch_window_days=28 (calendar windows) — Task 1 (types.py + solver.py)
- ✅ All params configurable in system settings — Task 3 (system_settings.py: `algorithm.window_t`, `algorithm.window_r`, `algorithm.batch_window_days`)
- ✅ All params configurable per-run — Task 2 (bridge: `settings_json.get("Wt", ...)`) + Task 3 (routes: `SolverSettingsIn` with Wt/Wr fields)
- ✅ Frontend form shows Wt/Wr — Task 4

**Type consistency check:**
- `SolverSettings.Wt` used in `model.py` (Wt loop) and `resolve_solver_settings` (return value key "Wt") — consistent
- `SolverSettings.Wr` used in `model.py` (Wr loop), `load_existing_assignments(Wr=settings.Wr)` — consistent
- `SolverSettings.batch_window_days` used in `_calendar_window_batches` call and `_decomposed_solve` — consistent
- `SolverSettingsIn.Wt/Wr` fed into `job.settings_json`, then `resolve_solver_settings(settings_json.get("Wt", ...))` — consistent
- `AlgorithmDefaultsOut.Wt/Wr` returned from `AlgorithmDefaults.Wt/Wr` in frontend — consistent

**Potential gap**: The `_infeasibility_relaxation_chain` in `solver.py` relaxes `current.R` in hops of 2. With `R=15` and `relax_r_ceiling=20`, this allows 3 hops (R→17, R→19, R→20). The invariant `T <= R` still holds (T=8 ≤ R=15). No code change needed, just verify the relaxation still works at the new defaults (it does — same logic).

**Potential gap**: The `test_create_job_rejects_T_greater_than_R` test in `test_algorithm_routes.py` passes `"W": 14` in the settings dict — this is an extra unknown key that Pydantic will ignore by default (or raise if strict). Verify Pydantic v2 model ignores extra fields (it does by default) — `"W": 14` will be silently dropped. Alternatively, update the test to pass `"Wt": 14, "Wr": 28` instead. Task 3 Step 1 covers this.
