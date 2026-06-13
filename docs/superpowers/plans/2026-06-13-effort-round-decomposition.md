# Effort-Round Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace calendar-window batching with a two-phase effort-round decomposition that never strands duties on a time boundary, is fair by construction, and stays tractable — plus reasons on partial jobs.

**Architecture:** Per eligibility component: Phase 1 solves disjoint 50-soldier groups (lowest-effort first) at hard **base** caps with **soft coverage**, carrying assignments forward; Phase 2 brings the full pool back against the small residual with graduated relaxation; Phase 3 relaxes beyond the ceiling as a flagged last resort. No per-soldier caps — the phase is the cap regime.

**Tech Stack:** Python, OR-Tools CP-SAT, SQLAlchemy, pytest. Run from `backend/`. Tests: `uv run pytest app/algorithm/ -q` (and `app/services/` for the bridge task). On Windows, prefix Hebrew-printing runs with `PYTHONUTF8=1`.

Spec: [docs/superpowers/specs/2026-06-13-effort-round-decomposition-design.md](../specs/2026-06-13-effort-round-decomposition-design.md)

---

### Task 1: Settings — `decomposition` + `round_soldier_count`

**Files:**
- Modify: `backend/app/algorithm/types.py` (SolverSettings)
- Modify: `backend/app/services/algorithm_bridge.py` (`resolve_solver_settings`)
- Test: `backend/app/algorithm/tests/test_solver.py`, `backend/app/services/tests/test_algorithm_bridge.py`

- [ ] **Step 1: Write the failing test** — add to `test_solver.py`:

```python
def test_settings_have_decomposition_fields() -> None:
    s = SolverSettings()
    assert s.decomposition == "effort_rounds"
    assert s.round_soldier_count == 50
    assert SolverSettings(decomposition="calendar").decomposition == "calendar"
```

- [ ] **Step 2: Run it, expect FAIL** — `uv run pytest app/algorithm/tests/test_solver.py::test_settings_have_decomposition_fields -v` → `TypeError`/`AttributeError`.

- [ ] **Step 3: Add the fields** in `SolverSettings` (after `batch_time_limit_seconds`):

```python
    # Decomposition strategy: "effort_rounds" (default) | "calendar" | "none".
    decomposition: str = "effort_rounds"
    # Disjoint Phase-1 group size for effort-round decomposition.
    round_soldier_count: int = 50
```

- [ ] **Step 4: Wire system-setting fallbacks** in `resolve_solver_settings` (mirror the existing `settings_json.get(..., _setting_*)` lines):

```python
        decomposition=str(settings_json.get("decomposition", _setting_str("algorithm.decomposition", "effort_rounds"))),
        round_soldier_count=int(settings_json.get("round_soldier_count", _setting_int("algorithm.round_soldier_count", 50))),
```

Add a `_setting_str(key, default)` local helper next to `_setting_int` (returns `str(get_setting(...))` or default).

- [ ] **Step 5: Bridge test** — add to `test_algorithm_bridge.py`:

```python
def test_resolve_solver_settings_decomposition_default(admin_session):
    s = resolve_solver_settings(admin_session, {})
    assert s.decomposition == "effort_rounds"
    assert s.round_soldier_count == 50

def test_resolve_solver_settings_decomposition_override(admin_session):
    s = resolve_solver_settings(admin_session, {"decomposition": "calendar", "round_soldier_count": 30})
    assert s.decomposition == "calendar"
    assert s.round_soldier_count == 30
```

- [ ] **Step 6: Run + commit**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_settings_have_decomposition_fields app/services/tests/test_algorithm_bridge.py -q` → PASS.
```bash
git add app/algorithm/types.py app/services/algorithm_bridge.py app/algorithm/tests/test_solver.py app/services/tests/test_algorithm_bridge.py
git commit -m "feat: add decomposition + round_soldier_count solver settings"
```

---

### Task 2: Soft coverage (max-coverage lexicographic solve)

**Files:**
- Modify: `backend/app/algorithm/model.py` (`build_model`)
- Modify: `backend/app/algorithm/solver.py` (new `_solve_soft_coverage`)
- Test: `backend/app/algorithm/tests/test_solver.py`

**Why lexicographic, not weighted:** the existing objective already uses `l1_w=1e11`; adding a coverage tier above it risks int64 overflow. Instead solve in two stages on the same model: (1) maximise duties covered, (2) fix that count and run the existing fairness objective.

- [ ] **Step 1: Write the failing test** — a single soldier, two same-day duties (can take at most one). Hard mode → INFEASIBLE; soft mode → covers exactly 1, no exception.

```python
def test_soft_coverage_covers_max_without_infeasible() -> None:
    s_id = uuid4(); dt = uuid4()
    soldiers = [SoldierInput(id=s_id, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100)]
    day = date(2026, 6, 1)
    duties = [_single_day_duty(day, dt, is_reserve=False), _single_day_duty(day, dt, is_reserve=False)]
    # Hard coverage: 1 soldier cannot cover 2 same-day duties -> INFEASIBLE.
    from app.algorithm.solver import _solve_soft_coverage
    hard = build_model(soldiers=soldiers, duties=duties, existing=[], settings=SolverSettings())
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = 5
    assert solver.Solve(hard[0]) == cp_model.INFEASIBLE
    # Soft coverage: covers exactly one, status OK.
    res = _solve_soft_coverage(soldiers, duties, [], SolverSettings(time_limit_seconds=5), reserve_dist=None)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert len(res.assignments) == 1
```

- [ ] **Step 2: Run it, expect FAIL** — `ImportError: _solve_soft_coverage`.

- [ ] **Step 3: Add `coverage` param to `build_model`** ([model.py:100-103](../../../backend/app/algorithm/model.py)):

```python
def build_model(..., coverage: str = "hard") -> tuple[CpModel, dict[tuple[int, int], IntVar]]:
    ...
    # Hard constraint 1: Coverage
    for di in range(len(duty_list)):
        vars_for_d = [x[(di, si)] for (dii, si) in eligible if dii == di]
        if coverage == "soft":
            if vars_for_d:
                model.Add(sum(vars_for_d) <= 1)
        else:
            model.Add(sum(vars_for_d) == 1)
```

(Leave the objective section unchanged; the soft-coverage maximisation is driven from the solver, Step 4.)

- [ ] **Step 4: Add `_solve_soft_coverage` in solver.py** — two-stage lexicographic on one model:

```python
def _solve_soft_coverage(soldiers, duties, existing, settings, reserve_dist, cancel_event=None) -> SolverResult:
    """Maximise duties covered (stage 1), then optimise fairness with the covered
    count fixed (stage 2). Coverage is soft (<=1), so leftover duties are simply
    not selected and can be deferred by the caller."""
    model, x = build_model(soldiers, duties, existing, settings, reserve_dist, coverage="soft")
    covered = sum(x.values()) if x else 0
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    if settings.seed is not None:
        solver.parameters.random_seed = settings.seed
    # Stage 1: maximise coverage.
    model.Maximize(covered)
    st1 = solver.Solve(model)
    if solver.StatusName(st1) not in ("OPTIMAL", "FEASIBLE"):
        return SolverResult(assignments=[], status=solver.StatusName(st1),
                            seed=(settings.seed or DEFAULT_SOLVER_SEED), relaxed=[])
    best = int(solver.ObjectiveValue())
    # Stage 2: lock coverage, optimise the real fairness objective.
    if x:
        model.Add(covered >= best)
    _apply_fairness_objective(model, x, soldiers, duties, settings, reserve_dist)  # see note
    st2 = solver.Solve(model)
    status = solver.StatusName(st2)
    assignments = [Assignment(duty_id=duties[di].id, soldier_id=soldiers[si].id)
                   for (di, si), v in x.items() if solver.Value(v)]
    assignments.sort(key=lambda a: a.duty_id)
    return SolverResult(assignments=assignments, status=status,
                        seed=(settings.seed or DEFAULT_SOLVER_SEED), relaxed=[])
```

**Implementation note for `_apply_fairness_objective`:** the fairness objective is currently built *inside* `build_model`. Extract the objective-construction block ([model.py:271-321](../../../backend/app/algorithm/model.py)) into a module-level `build_fairness_objective(model, x, soldiers, duties, settings, reserve_dist, eligible)` that returns the `Maximize`-able expression, and call it from both `build_model` (hard path, unchanged behaviour) and `_solve_soft_coverage` (stage 2). If extraction is too invasive in one step, an acceptable interim is to call `build_model(..., coverage="soft")` for stage 2 with a fresh model that has `covered >= best` added — but prefer the single-model extraction to avoid double model-build cost. Verify the hard-path golden tests stay identical after extraction.

- [ ] **Step 5: Run + full algorithm suite**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_soft_coverage_covers_max_without_infeasible -v` → PASS.
Run: `uv run pytest app/algorithm/ -q` → PASS (golden + fairness unchanged — proves the objective extraction was behaviour-preserving).

- [ ] **Step 6: Commit**
```bash
git add app/algorithm/model.py app/algorithm/solver.py app/algorithm/tests/test_solver.py
git commit -m "feat: soft-coverage lexicographic solve (max coverage, then fairness)"
```

---

### Task 3: `_effort_round_solve` — the three phases

**Files:**
- Modify: `backend/app/algorithm/solver.py`
- Test: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Write the failing tests**

```python
def _line_duties(base, dt, n, is_reserve=False):
    return [_single_day_duty(base + timedelta(days=i), dt, is_reserve=is_reserve) for i in range(n)]

def test_effort_rounds_small_component_single_round() -> None:
    # <= round_soldier_count soldiers => one Phase-1 round = whole solve, no relaxation.
    dt = uuid4()
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100)
                for _ in range(5)]
    duties = _line_duties(date(2026,6,1), dt, 5)
    from app.algorithm.solver import _effort_round_solve
    res = _effort_round_solve(soldiers, duties, [], SolverSettings(round_soldier_count=50, batch_time_limit_seconds=10),
                              reserve_dist=None, cancel_event=None)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert len(res.assignments) == 5
    assert all(not r.startswith("LAST_RESORT") for r in res.relaxed)

def test_effort_rounds_two_groups_cover_all() -> None:
    # 4 soldiers, group size 2 => Phase 1 has two disjoint groups; all duties covered.
    dt = uuid4()
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026,1,1), cumulative_score=Decimal(str(i)), active_days=100)
                for i in range(4)]
    duties = _line_duties(date(2026,6,1), dt, 8)   # 8 single-day duties on distinct days
    from app.algorithm.solver import _effort_round_solve
    res = _effort_round_solve(soldiers, duties, [], SolverSettings(round_soldier_count=2, batch_time_limit_seconds=10),
                              reserve_dist=None, cancel_event=None)
    assert len(res.assignments) == 8   # full coverage across the two groups
```

- [ ] **Step 2: Run, expect FAIL** — `ImportError: _effort_round_solve`.

- [ ] **Step 3: Implement `_effort_round_solve`** (operates per component; mirrors `_decomposed_solve`'s component loop + carry-forward, but soldier-grouped):

```python
def _effort_round_solve(soldiers, duties, existing, settings, reserve_dist, cancel_event, progress_cb=None):
    work = [dataclasses.replace(s) for s in soldiers]
    duty_by_id = {d.id: d for d in duties}
    pairs = _eligible_pairs(work, duties)
    components = _connected_components(len(duties), len(work), pairs)

    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    n = settings.round_soldier_count

    component_jobs = [(d_idxs, s_idxs) for d_idxs, s_idxs in components if s_idxs]
    if progress_cb:
        progress_cb(0, max(len(component_jobs), 1))

    for done, (duty_idxs, soldier_idxs) in enumerate(component_jobs, start=1):
        if cancel_event is not None and cancel_event.is_set():
            return SolverResult(assignments=[], status="CANCELLED",
                                seed=(settings.seed or DEFAULT_SOLVER_SEED), relaxed=relaxed)
        # Order soldiers by INITIAL effort ascending, chunk into disjoint groups of n.
        ordered = sorted(soldier_idxs, key=lambda si: work[si].effort_offset)
        groups = [ordered[i:i + n] for i in range(0, len(ordered), n)]

        carry = [e for e in existing]                 # real existing load for this component
        residual = set(duty_idxs)
        base = dataclasses.replace(settings, time_limit_seconds=settings.batch_time_limit_seconds)

        def _solve_subset(active_sidx, duty_subset, relax_settings):
            sub_soldiers = [work[si] for si in active_sidx]
            sub_duties = [duties[di] for di in duty_subset]
            r = _solve_soft_coverage(sub_soldiers, sub_duties, carry, relax_settings, None, cancel_event)
            return r

        def _absorb(r):
            for a in r.assignments:
                all_assignments.append(a)
                d = duty_by_id[a.duty_id]
                carry.append(ExistingAssignment(soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                             start_date=d.start_date, end_date=d.end_date, is_reserve=d.is_reserve))
                s = work[next(si for si in soldier_idxs if work[si].id == a.soldier_id)]
                s.effort_offset += s.effort_per_milli * _block_score(d)
            # find duty indices that got assigned
            assigned = {a.duty_id for a in r.assignments}
            for di in list(residual):
                if duties[di].id in assigned:
                    residual.discard(di)

        # PHASE 1: disjoint groups at hard BASE caps (no relaxation), lowest-effort first.
        for g in groups:
            if not residual:
                break
            _absorb(_solve_subset(g, list(residual), base))

        # PHASE 2: full pool, graduated relaxation (R then T) up to the ceilings.
        if residual:
            full = ordered
            r2 = _phase2_relax(lambda st: _solve_subset(full, list(residual), st), base, settings)
            relaxed.extend(r2_relaxed_for(r2))   # collect the R->/T-> entries used
            _absorb(r2)

        # PHASE 3: still residual -> last resort beyond ceilings, flagged.
        if residual:
            lr = dataclasses.replace(base, R=settings.Wr, T=settings.Wt,  # caps == window length = no density limit
                                     relax_r_ceiling=settings.Wr, relax_t_ceiling=settings.Wt)
            r3 = _solve_subset(ordered, list(residual), lr)
            if r3.assignments:
                relaxed.append("LAST_RESORT")
                _absorb(r3)

        if progress_cb:
            progress_cb(done, len(component_jobs))

    all_assignments.sort(key=lambda a: a.duty_id)
    assigned_ids = {a.duty_id for a in all_assignments}
    status = "OPTIMAL" if len(assigned_ids) == len(duties) else "FEASIBLE"
    if not all_assignments and duties:
        status = "INFEASIBLE"
    return SolverResult(assignments=all_assignments, status=status,
                        seed=(settings.seed or DEFAULT_SOLVER_SEED), relaxed=relaxed)
```

Add a small `_phase2_relax(solve_fn, base_settings, settings)` helper that re-implements the existing graduated step (start at base; if residual remains, raise `R += 2` toward `relax_r_ceiling`, then `T += 2` toward `relax_t_ceiling`, re-solving via `solve_fn(current_settings)` each step) and returns the best result plus the list of `"R→k"`/`"T→k"` strings actually applied. Reuse the exact stepping logic from `_infeasibility_relaxation_chain` (lines ~290-306) so behaviour matches; factor that stepping into a shared helper if clean.

(Note: `_solve_soft_coverage` uses `settings.time_limit_seconds`; here we pass `relax_settings` derived from `base` whose `time_limit_seconds == batch_time_limit_seconds`.)

- [ ] **Step 4: Run + suite**

Run: `uv run pytest app/algorithm/tests/test_solver.py -k effort_rounds -v` → PASS.
Run: `uv run pytest app/algorithm/ -q` → PASS.

- [ ] **Step 5: Commit**
```bash
git add app/algorithm/solver.py app/algorithm/tests/test_solver.py
git commit -m "feat: two-phase effort-round decomposition (_effort_round_solve)"
```

---

### Task 4: Dispatch `solve()` on `settings.decomposition`

**Files:**
- Modify: `backend/app/algorithm/solver.py` (`solve`)
- Test: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Failing test** — an adversarial instance the calendar batcher drops but effort-rounds covers. One component, continuous duties spanning > `batch_window_days`, a narrow soldier pool, with a cluster at the day-28 boundary:

```python
def test_effort_rounds_covers_what_calendar_drops() -> None:
    dt = uuid4()
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100)
                for _ in range(6)]
    base = date(2026, 6, 1)
    # Dense run 06-01..07-05 (35 days > batch_window_days=28) so calendar makes a trailing batch.
    duties = [_single_day_duty(base + timedelta(days=i), dt, is_reserve=False) for i in range(35)]
    cal = solve(soldiers, duties, [], SolverSettings(decomposition="calendar", batch_window_days=28,
                Wt=14, Wr=28, T=2, R=2, batch_time_limit_seconds=10, time_limit_seconds=10))
    er  = solve(soldiers, duties, [], SolverSettings(decomposition="effort_rounds", round_soldier_count=50,
                Wt=14, Wr=28, T=2, R=2, batch_time_limit_seconds=10, time_limit_seconds=10))
    assert len(er.assignments) >= len(cal.assignments)
    assert len(er.assignments) == 35   # effort-rounds covers all
```

(If this exact fixture does not reproduce a calendar shortfall, strengthen it until `cal` drops ≥1 and `er` covers all; the design guarantees `er` is coverage-complete here.)

- [ ] **Step 2: Run, expect FAIL** (effort_rounds not yet dispatched → falls through to whole/calendar).

- [ ] **Step 3: Add dispatch** in `solve` ([solver.py:53-63](../../../backend/app/algorithm/solver.py)):

```python
    if settings.decomposition == "effort_rounds" and settings.batching_enabled:
        return _effort_round_solve(soldiers, duties, existing, settings, reserve_dist,
                                   cancel_event=cancel_event, progress_cb=progress_cb)
    if settings.decomposition == "calendar" and settings.batching_enabled:
        return _decomposed_solve(soldiers, duties, existing, settings, reserve_dist,
                                 cancel_event=cancel_event, progress_cb=progress_cb)
    # "none" or batching disabled → whole solve.
    if progress_cb: progress_cb(0, 1)
    result = _infeasibility_relaxation_chain(soldiers, duties, existing, settings, reserve_dist, cancel_event=cancel_event)
    if progress_cb: progress_cb(1, 1)
    return result
```

- [ ] **Step 4: Run + suite + commit**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_effort_rounds_covers_what_calendar_drops -v` → PASS.
Run: `uv run pytest app/algorithm/ -q` → PASS.
```bash
git add app/algorithm/solver.py app/algorithm/tests/test_solver.py
git commit -m "feat: dispatch solve() on decomposition strategy (effort_rounds default)"
```

---

### Task 5: Reasons on partial / last-resort jobs

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py` (`run_algorithm_job`, after `persist_results`)
- Test: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Failing test** — construct shifts that over-subscribe a duty type so the run is partial, submit a job, poll until done, assert the response carries `reasons` (non-empty) even though status is `done`.

```python
def test_partial_job_reports_reasons(client, admin_session):
    # Build a tiny over-subscribed scenario: 1 eligible soldier, a shift needing 2 on the same day.
    dm, _ = _setup_dm(admin_session, "route_partial_01")
    # ... create duty_type, location, ONE soldier eligible, a shift with required_count=2 ...
    # submit job (shadow), poll until status == "done"
    # assert resp.json()["reasons"] is non-empty (diagnose ran on the partial result)
    ...
```

(Use the existing helpers `_make_shift`, `create_soldier`, `auth_headers`, and the poll pattern from `test_algorithm_cancel.py` / `test_algorithm_jobs_list.py`. Keep the instance tiny so it solves in <5s.)

- [ ] **Step 2: Run, expect FAIL** (`reasons` empty for `done` jobs today).

- [ ] **Step 3: Implement** — in `run_algorithm_job`, after `persist_results(...)` and before/at marking `done`, when the result is incomplete or last-resort fired:

```python
                assigned_ct = len(result.assignments)
                last_resort = any(r == "LAST_RESORT" for r in result.relaxed)
                if assigned_ct < len(duties) or last_resort:
                    from app.algorithm.diagnose import diagnose_infeasibility
                    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
                    reasons = diagnose_infeasibility(soldiers, duties, existing, dt_names)
                    job.error_message = _json.dumps({
                        "status": "PARTIAL",
                        "assigned": assigned_ct,
                        "total": len(duties),
                        "last_resort": last_resort,
                        "relaxed": result.relaxed,
                        "reasons": reasons,
                    })
```

The job stays `status="done"`; the existing `_parse_failure` in [algorithm.py](../../../backend/app/routes/algorithm.py) already reads `relaxed`/`reasons` from `error_message`, so `JobOut` surfaces them. Confirm `get_job` returns them for `done` jobs (it parses `error_message` unconditionally).

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/integration/test_algorithm_routes.py::test_partial_job_reports_reasons -v` → PASS.
Run: `uv run pytest tests/integration/test_algorithm_routes.py -q` → PASS.
```bash
git add app/services/algorithm_bridge.py tests/integration/test_algorithm_routes.py
git commit -m "feat: surface diagnose reasons on partial / last-resort algorithm jobs"
```

---

### Task 6: Real-data benchmark (evidence before changing the default)

**Files:**
- Create: `backend/_bench_decomposition.py` (scratch — NOT committed)

- [ ] **Step 1: Write the benchmark** — load the latest `AlgorithmJob`'s inputs the same way `run_algorithm_job` does (reuse `load_duty_blocks_from_shifts`, `load_soldier_inputs`, effort injection, `load_existing_assignments`; build the localhost DB URL from `../.env` like the earlier diagnostics). For each `decomposition in ("calendar", "effort_rounds", "none")`, call `solve(...)` and record: assigned/total, the post-run effort spread (max−min over eligible soldiers), wall time, and `relaxed`.

- [ ] **Step 2: Run it**

Run: `PYTHONUTF8=1 uv run python _bench_decomposition.py`
Expected: `effort_rounds` covers **410/410** on the real job (vs `calendar` 396/410); record the effort spread and solve time for all three.

- [ ] **Step 3: Record results** in the spec's “Verification” section (append a short results block with the three rows), then delete the scratch file:
```bash
rm backend/_bench_decomposition.py
git add docs/superpowers/specs/2026-06-13-effort-round-decomposition-design.md
git commit -m "docs: record effort-round decomposition benchmark results"
```

- [ ] **Step 4: Full regression** — `uv run pytest app/algorithm/ app/services/ -q` and `uv run pytest tests/integration/test_algorithm_routes.py -q` → all PASS.

---

## Self-Review Notes

- **Spec coverage:** settings → T1; soft coverage → T2; three-phase orchestration → T3; default dispatch → T4; partial-job reasons → T5; benchmark/verification → T6.
- **First-appearance rule:** honoured structurally — Phase 1 uses uniform **base** caps (`_solve_subset(..., base)`, no relaxation), Phase 2/3 are the only places caps relax, and by then every soldier is a repeater. No per-soldier caps anywhere.
- **Tractability:** Phase-1 groups are `round_soldier_count` soldiers; residual shrinks each round so Phase 2 runs on a small leftover; ≤-group-size components do exactly one Phase-1 round.
- **Coverage guarantee (decision b):** Phase 3 sets caps to the window length (no effective density limit) and flags `LAST_RESORT`; only a genuine zero-eligible component can then remain (and that is reported by `diagnose_infeasibility`).
- **No silent drop:** Task 5 attaches reasons whenever `assigned < total` or last-resort fired.
- **Risk flagged:** `_solve_soft_coverage` relies on extracting `build_fairness_objective` from `build_model`; Task 2 Step 5 re-runs the golden/fairness suite to prove the extraction is behaviour-preserving before anything depends on it.
