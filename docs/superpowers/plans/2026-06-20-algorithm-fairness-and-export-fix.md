# Algorithm Fairness Bug + Export-Inputs Replay Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Make `GET /api/algorithm/jobs/{id}/export-inputs` actually replay a *completed* job's real inputs instead of returning an empty dump, and (2) fix the root cause of the 105%-CV duty-concentration bug in the CP-SAT fairness objective, including the 4 pre-existing failing tests that already documented this exact failure mode.

**Architecture:** Part 1 persists a JSON snapshot of solver inputs on the `AlgorithmJob` row at solve time (instead of re-deriving inputs from live DB state, which silently goes empty once a job's shifts are staffed). Part 2 corrects a date-convention bug in test fixtures (`start_date == end_date` is read as a zero-length block by the exclusive-end-date convention in `_block_score`/`_duty_dates`) and raises the `count_w` tie-breaker weight in the L1 fairness objective from `10_000` to `100_000`, which empirical testing in this session proved fixes lopsided duty concentration without changing the documented tier ordering (L1 ≫ prior ≫ count-spread; `100_000 < prior_w=1_000_000`).

**Tech Stack:** Python, FastAPI, SQLAlchemy + Alembic, OR-Tools CP-SAT, pytest.

**Context this plan assumes you have (do not re-derive):**
- `export_solver_inputs` (`backend/app/services/algorithm_bridge.py:1087`) calls `load_duty_blocks_from_shifts`, which subtracts already-filled assignments — so after a job completes and its assignments are published/drafted, every shift shows 0 unfilled slots and `duties` comes back `[]`. This was confirmed directly: a real completed job's export dump had `"duties":[]` while the job's own stored `result_metadata` showed it actually solved 802 real blocks with `outcome: "OPTIMAL"`.
- The same job's `result_metadata.fairness_after` showed `cv: 1.0503`, `mean: 10.89`, `max: 37.0`, with 33/119 fully-eligible, unconstrained soldiers getting **zero** duty-days across a full year. Reconstructing the real historical inputs from the DB (ignoring the "filled" subtraction) and re-solving with the current code reproduced the same pathology: `CV≈0.91`, 31/119 soldiers at zero, others up to 30 duties.
- Four pre-existing test failures on `master` (unrelated to any work in this session): `test_infeasibility_relaxation`, `test_does_not_concentrate_duties_on_lowest_effort_soldier`, `test_low_marginal_effort_soldier_absorbs_more`, `test_relaxation_relaxes_R_before_T`, all in `backend/app/algorithm/tests/test_solver.py`.
- Direct experiment in this session: changing `test_does_not_concentrate_duties_on_lowest_effort_soldier`'s duty fixtures from `end_date=date(2026, 6, d)` (same day as start — a zero-length block under the exclusive-end convention) to `end_date=date(2026, 6, d) + timedelta(days=1)` made the test **pass immediately** with the unmodified `model.py`, producing the exact expected `F=4, A=1, B=1` distribution. The same fix pattern was verified for `test_infeasibility_relaxation` (relaxation now correctly triggers).
- Direct experiment: replaying a solver's *actual* lopsided result through `build_model` (fixing variables to match) gave objective `-110000000020000.0`; a hand-built *even-spread* alternative scored `-110000000010000.0` — **higher** (better, since the model maximizes), by exactly one `count_w` unit (`10_000`). The solver had returned `FEASIBLE`, not `OPTIMAL` — it never proved its own answer was even feasible-optimal. Giving it 60s instead of 20s with the stall-guard disabled did **not** change the result. Raising `count_w` did: a scan on a 20-soldier/15-duty repro showed `count_w=10_000` (current) → 8 soldiers at zero, two doubled up; `count_w=100_000` (10×) → exactly 5 at zero (the unavoidable minimum since duties < soldiers) and nobody doubled up. `count_w=1_000_000` through `100_000_000` gave the identical optimal result, so `100_000` is the minimal effective value and conservatively stays below `prior_w=1_000_000`.
- This investigation has **not yet been validated at full production scale** (the 802-duty/119-soldier case) with the new `count_w=100_000`. Task 10 covers that validation explicitly, with a documented escalation path if it's insufficient at that scale.

---

## Part 1: Make export-inputs replay real historical inputs

### Task 1: Add `solver_input_snapshot` column to `algorithm_jobs`

**Files:**
- Create: `backend/alembic/versions/0054_add_solver_input_snapshot.py`
- Modify: `backend/app/db/models.py:567-573` (inside `AlgorithmJob`)

- [ ] **Step 1: Write the migration**

```python
# backend/alembic/versions/0054_add_solver_input_snapshot.py
"""add solver_input_snapshot to algorithm_jobs

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("solver_input_snapshot", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("algorithm_jobs", "solver_input_snapshot")
```

- [ ] **Step 2: Add the model field**

In `backend/app/db/models.py`, inside `class AlgorithmJob`, right after the `result_metadata` field (currently at line 571-573):

```python
    result_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    solver_input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
```

- [ ] **Step 3: Run the migration**

```bash
cd backend
DATABASE_URL="postgresql+psycopg://db_admin:db_admin_pw@localhost:5432/cod2" .venv/Scripts/python.exe -m alembic upgrade head
```
Expected: `Running upgrade 0053 -> 0054, add solver_input_snapshot to algorithm_jobs`

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0054_add_solver_input_snapshot.py backend/app/db/models.py
git commit -m "feat: add solver_input_snapshot column to algorithm_jobs"
```

---

### Task 2: Extract a shared solver-input serializer

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:1087-1190` (the body of `export_solver_inputs`)

The three inline closures (`_soldier_dict`, `_duty_dict`, `_existing_dict`) and the final dict assembly currently live only inside `export_solver_inputs`. Extract them into a standalone module-level function so `run_algorithm_job` can build the exact same shape to persist as a snapshot.

- [ ] **Step 1: Add the new function above `export_solver_inputs`**

Insert this new function immediately before `def export_solver_inputs(` (currently line 1087):

```python
def serialize_solver_inputs(
    *,
    job_id: uuid.UUID,
    planning_start: date,
    planning_end: date,
    settings: SolverSettings,
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    existing: list[ExistingAssignment],
    block_to_shift_map: dict[uuid.UUID, uuid.UUID],
) -> dict:
    """Build the JSON-serializable solver-input dump shape.

    Shared by run_algorithm_job (to persist a snapshot at solve time) and
    export_solver_inputs (to return it later, or to live-reconstruct for jobs
    that predate the snapshot).
    """

    def _soldier_dict(s: SoldierInput) -> dict:
        return {
            "id": str(s.id),
            "enrolled_at": s.enrolled_at.isoformat(),
            "cumulative_score": float(s.cumulative_score),
            "active_days": s.active_days,
            "hierarchy_node_id": str(s.hierarchy_node_id) if s.hierarchy_node_id else None,
            "approved_constraint_dates": [
                [a.isoformat(), b.isoformat()] for a, b in s.approved_constraint_dates
            ],
            "exempted_duty_type_ids": [str(e) for e in s.exempted_duty_type_ids],
            "effort_offset": s.effort_offset,
            "effort_per_milli": s.effort_per_milli,
        }

    def _duty_dict(d: DutyBlock) -> dict:
        return {
            "id": str(d.id),
            "duty_type_id": str(d.duty_type_id),
            "duty_location_id": str(d.duty_location_id),
            "start_date": d.start_date.isoformat(),
            "end_date": d.end_date.isoformat(),
            "score_per_day": float(d.score_per_day),
            "is_reserve": d.is_reserve,
            "eligible_node_ids": [str(n) for n in d.eligible_node_ids] if d.eligible_node_ids else None,
            "shift_id": str(block_to_shift_map[d.id]) if d.id in block_to_shift_map else None,
        }

    def _existing_dict(e: ExistingAssignment) -> dict:
        return {
            "soldier_id": str(e.soldier_id),
            "duty_type_id": str(e.duty_type_id),
            "start_date": e.start_date.isoformat(),
            "end_date": e.end_date.isoformat(),
            "is_reserve": e.is_reserve,
        }

    settings_dict = dataclasses.asdict(settings)
    settings_dict["alpha"] = float(settings_dict["alpha"])
    settings_dict["reserve_hierarchy_weight"] = float(settings_dict["reserve_hierarchy_weight"])

    return {
        "job_id": str(job_id),
        "planning_start": planning_start.isoformat(),
        "planning_end": planning_end.isoformat(),
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "settings": settings_dict,
        "soldiers": [_soldier_dict(s) for s in soldiers],
        "duties": [_duty_dict(d) for d in duties],
        "existing_assignments": [_existing_dict(e) for e in existing],
    }
```

- [ ] **Step 2: Replace `export_solver_inputs`'s body to use it**

Replace the tail of `export_solver_inputs` (the `_soldier_dict`/`_duty_dict`/`_existing_dict` closures and the final `return {...}`, i.e. lines 1139-1189) with:

```python
    return serialize_solver_inputs(
        job_id=job.id,
        planning_start=planning_start,
        planning_end=planning_end,
        settings=settings,
        soldiers=soldiers,
        duties=duties,
        existing=existing,
        block_to_shift_map=block_to_shift_map,
    )
```

Leave everything above that (the live-reconstruction logic: `resolve_solver_settings`, `load_duty_blocks_from_shifts`, `load_soldier_inputs`, `compute_effort_data`, `inject_effort_scores`, `load_existing_assignments`) exactly as-is — Task 3 makes this whole block a *fallback*, not the primary path.

- [ ] **Step 3: Run a quick import sanity check**

```bash
cd backend
.venv/Scripts/python.exe -c "from app.services.algorithm_bridge import serialize_solver_inputs, export_solver_inputs; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "refactor: extract serialize_solver_inputs from export_solver_inputs"
```

---

### Task 3: Persist the snapshot at run time, read it back at export time

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py` (`run_algorithm_job`, around lines 880-910; `export_solver_inputs`, now starting around line 1087)

- [ ] **Step 1: Persist the snapshot in `run_algorithm_job`**

In `run_algorithm_job`, find this block (existing code, right after `existing = load_existing_assignments(...)` and the `if not soldiers:` early-return check — i.e. right before the line that computes `hier_parent, hier_children, ... = build_hierarchy_maps(session)`):

```python
                if not soldiers:
                    job.status = "failed"
                    job.error_message = "no_soldiers_or_duties"
                    job.finished_at = datetime.now(tz=UTC)
                    session.commit()
                    return

                hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)
```

Insert the snapshot-persist call between those two statements:

```python
                if not soldiers:
                    job.status = "failed"
                    job.error_message = "no_soldiers_or_duties"
                    job.finished_at = datetime.now(tz=UTC)
                    session.commit()
                    return

                job.solver_input_snapshot = serialize_solver_inputs(
                    job_id=job.id,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    settings=settings,
                    soldiers=soldiers,
                    duties=duties,
                    existing=existing,
                    block_to_shift_map=block_to_shift_map,
                )
                session.commit()

                hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)
```

This captures inputs exactly as they were about to be fed to `solve()` — before any solving happens, so it's unaffected by solve outcome (including cancellation or failure).

- [ ] **Step 2: Make `export_solver_inputs` prefer the snapshot**

At the very top of `export_solver_inputs` (currently line 1087-1091):

```python
def export_solver_inputs(job: "AlgorithmJob", session: "Session") -> dict:
    """Reconstruct solver inputs from a stored job and return as a JSON-serializable dict."""
    from app.services.settings_loader import get_setting

    settings = resolve_solver_settings(session, job.settings_json)
```

Change to:

```python
def export_solver_inputs(job: "AlgorithmJob", session: "Session") -> dict:
    """Return this job's solver inputs.

    If a snapshot was captured at run time (jobs created after the
    solver_input_snapshot column was added), return it verbatim with a fresh
    exported_at timestamp — this is the only path that reflects the duties
    actually solved, since by the time a job is done, load_duty_blocks_from_shifts
    no longer finds anything to (re)generate (its slots are filled). For
    legacy jobs with no snapshot, fall back to live reconstruction (best-effort;
    will return empty duties for a completed legacy job whose shifts are filled).
    """
    if job.solver_input_snapshot is not None:
        return {**job.solver_input_snapshot, "exported_at": datetime.now(tz=UTC).isoformat()}

    from app.services.settings_loader import get_setting

    settings = resolve_solver_settings(session, job.settings_json)
```

- [ ] **Step 3: Run a quick import sanity check**

```bash
cd backend
.venv/Scripts/python.exe -c "from app.services.algorithm_bridge import run_algorithm_job, export_solver_inputs; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "fix: snapshot solver inputs at run time so export-inputs can replay completed jobs"
```

---

### Task 4: Integration test — export-inputs replays a completed, published job

**Files:**
- Modify: `backend/tests/integration/test_algorithm_routes.py` (append a new test; reuses the existing `_setup_dm`, `_make_shift` helpers already defined at the top of this file)

- [ ] **Step 1: Write the test**

Append to the end of `backend/tests/integration/test_algorithm_routes.py`:

```python
def test_export_inputs_replays_completed_published_job(client, admin_session):
    """Regression test: export-inputs must return the duties that were actually
    solved, even after the job's shifts are fully staffed (published/drafted).

    Before the solver_input_snapshot fix, export-inputs re-derived duties from
    live DB state (load_duty_blocks_from_shifts subtracts already-filled slots),
    so a completed job's export came back with duties=[] — useless for replay.
    """
    dm, _node = _setup_dm(admin_session, "route_alg_export")
    shift, _dt, _loc = _make_shift(admin_session, "route_export", "2027-11-01")
    create_soldier(admin_session, personal_number="route_soldier_export", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202, create_resp.text
    job_id = create_resp.json()["id"]

    poll = None
    for _ in range(15):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] == "done":
            break
        time.sleep(2)
    assert poll is not None and poll.json()["status"] == "done", poll.json() if poll else "no response"

    proposals = poll.json().get("proposals", [])
    if not proposals:
        pytest.skip("solver returned no proposals")

    # Publish the proposal — this is what makes the shift "fully staffed" and
    # is exactly the state that broke export-inputs before the fix.
    asgn_id = proposals[0]["assignment_id"]
    accept_resp = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/accept",
        headers=auth_headers(dm),
    )
    assert accept_resp.status_code == 200

    export_resp = client.get(
        f"/api/algorithm/jobs/{job_id}/export-inputs",
        headers=auth_headers(dm),
    )
    assert export_resp.status_code == 200
    dump = export_resp.json()
    assert len(dump["duties"]) > 0, "export-inputs returned no duties for a completed job — snapshot fix regressed"
    assert dump["duties"][0]["shift_id"] == str(shift.id)
```

- [ ] **Step 2: Run it**

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/integration/test_algorithm_routes.py::test_export_inputs_replays_completed_published_job -v
```
Expected: `PASSED` (or a `SKIPPED` with reason `"solver returned no proposals"` on an unlucky run — if that happens, re-run once; if it persists, investigate before continuing, since a single soldier + single shift should always produce a proposal).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_algorithm_routes.py
git commit -m "test: export-inputs replays a completed, published job's real inputs"
```

---

## Part 2: Fix the fairness-objective concentration bug

### Task 5: Fix the 4 pre-existing failing tests (date-convention bug)

**Files:**
- Modify: `backend/app/algorithm/tests/test_solver.py` (4 separate edits)

All four currently use `start_date == end_date` to mean "one day," but `_block_score`/`_duty_dates` in `backend/app/algorithm/model.py` treat the end date as **exclusive** (`days = (end_date - start_date).days`; a same-day block has `days=0`). A zero-day block contributes zero score weight to the fairness objective and is invisible to every T/R rolling-window check (`_duty_dates` returns `[]` for it). Fix: use `end_date = start_date + timedelta(days=1)` for every single-day duty in these four tests.

- [ ] **Step 1: Fix `test_infeasibility_relaxation`** (currently lines 147-168)

```python
def test_infeasibility_relaxation() -> None:
    soldier_a = uuid4()
    duty_type = uuid4()
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                  score_per_day=Decimal("1.00")),
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 2), end_date=date(2026, 6, 3),
                  score_per_day=Decimal("1.00")),
    ]
    # Force infeasibility: 1 soldier must cover both duties (coverage constraint),
    # but T=1, W=2 allows at most 1 duty-day in any 2-day window.
    # The window [June 1, June 2] contains both → violates T=1.
    # The relaxation chain should raise T→2 and find a feasible solution.
    result = solve(soldiers, duties, [], SolverSettings(T=1, Wt=2, Wr=4, time_limit_seconds=5))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.relaxed) > 0  # T was relaxed
```

(Only the two `end_date` values changed: `date(2026, 6, 1)` → `date(2026, 6, 2)`, and `date(2026, 6, 2)` → `date(2026, 6, 3)`.)

- [ ] **Step 2: Fix `test_does_not_concentrate_duties_on_lowest_effort_soldier`** (currently lines 321-364)

Change the duty list (lines 347-352) from:

```python
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d),
                  score_per_day=Decimal("4.00"))
        for d in range(1, 7)
    ]
```

to:

```python
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d) + timedelta(days=1),
                  score_per_day=Decimal("4.00"))
        for d in range(1, 7)
    ]
```

This requires `timedelta` to be imported in this file — check the top of `test_solver.py`; if `from datetime import date, timedelta` isn't already present, add `timedelta` to whatever existing `from datetime import ...` line is there.

- [ ] **Step 3: Fix `test_low_marginal_effort_soldier_absorbs_more`** (currently lines 391-422)

Change the duty list (lines 409-413) from:

```python
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d),
                  score_per_day=Decimal("4.00"))
        for d in range(1, 7)
    ]
```

to:

```python
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d) + timedelta(days=1),
                  score_per_day=Decimal("4.00"))
        for d in range(1, 7)
    ]
```

- [ ] **Step 4: Fix `test_relaxation_relaxes_R_before_T`**

Find this test (search for `def test_relaxation_relaxes_R_before_T`). It currently builds duties as:

```python
        duties = [
            DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                      start_date=base + timedelta(days=i), end_date=base + timedelta(days=i),
                      score_per_day=Decimal("1.00"), is_reserve=False)
            for i in range(8)  # 8 real duty-days in a 14-day window
        ]
```

Change the `end_date` to be exclusive (one day after `start_date`):

```python
        duties = [
            DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                      start_date=base + timedelta(days=i), end_date=base + timedelta(days=i + 1),
                      score_per_day=Decimal("1.00"), is_reserve=False)
            for i in range(8)  # 8 real duty-days in a 14-day window
        ]
```

- [ ] **Step 5: Run all four to confirm they pass**

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest app/algorithm/tests/test_solver.py::test_infeasibility_relaxation app/algorithm/tests/test_solver.py::test_does_not_concentrate_duties_on_lowest_effort_soldier app/algorithm/tests/test_solver.py::test_low_marginal_effort_soldier_absorbs_more app/algorithm/tests/test_solver.py::test_relaxation_relaxes_R_before_T -v
```
Expected: all 4 `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/tests/test_solver.py
git commit -m "fix: correct single-day duty fixtures to use exclusive end dates

start_date == end_date was being read as a zero-length block by
_block_score/_duty_dates' exclusive-end convention, silently zeroing out
score weighting and density-cap accounting in 4 tests."
```

---

### Task 6: Add a regression test for the duty-concentration bug

**Files:**
- Modify: `backend/app/algorithm/tests/test_solver.py` (append new test)

This codifies the 20-soldier/15-duty repro built and validated in this session: with uniform per-soldier effort rates and fewer duties than soldiers, the fair outcome is for the deficit (5 soldiers with none) to be spread with everyone else getting exactly 1 — never zero-here/double-there.

- [ ] **Step 1: Write the failing test**

Append to `backend/app/algorithm/tests/test_solver.py`:

```python
def test_spreads_duties_evenly_when_soldiers_outnumber_duties() -> None:
    """Regression for the 105%-CV production bug: with uniform effort rates and
    duties < soldiers, the fair split gives everyone at most 1 duty (5 get none,
    unavoidably, since there are only 15 duties for 20 soldiers) — never some
    soldiers at 0 while others get doubled up, which is what a too-weak
    count-spread tiebreaker (count_w) allowed before this fix."""
    duty_type = uuid4()
    loc = uuid4()
    soldiers = [
        _eff_soldier(uuid4(), offset=0, per_milli=1000)
        for _ in range(20)
    ]
    base = date(2026, 6, 1)
    duties = []
    for i in range(10):
        d = base + timedelta(days=i * 6)
        duties.append(DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                                 start_date=d, end_date=d + timedelta(days=1), score_per_day=Decimal("4.00")))
    for i in range(5):
        d = base + timedelta(days=i * 11)
        duties.append(DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                                 start_date=d, end_date=d + timedelta(days=8), score_per_day=Decimal("4.00")))

    settings = SolverSettings(T=8, Wt=14, R=15, Wr=28, time_limit_seconds=20,
                               decomposition="none", batching_enabled=False)
    result = solve(soldiers, duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 15

    counts: dict = {s.id: 0 for s in soldiers}
    for a in result.assignments:
        counts[a.soldier_id] += 1
    counts_list = sorted(counts.values())

    assert max(counts_list) <= 1, f"no soldier should be doubled up while another sits idle, got {counts_list}"
    assert counts_list.count(0) == 5, f"exactly 5 soldiers should be idle (15 duties / 20 soldiers), got {counts_list}"
```

- [ ] **Step 2: Run it to confirm it currently FAILS (count_w still 10_000)**

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest app/algorithm/tests/test_solver.py::test_spreads_duties_evenly_when_soldiers_outnumber_duties -v
```
Expected: FAIL — `max(counts_list) <= 1` assertion fails (some soldier has 2).

- [ ] **Step 3: Commit (test-only, still red)**

```bash
git add backend/app/algorithm/tests/test_solver.py
git commit -m "test: add failing regression test for duty-concentration bug"
```

---

### Task 7: Raise `count_w` from `10_000` to `100_000`

**Files:**
- Modify: `backend/app/algorithm/model.py:120-124`

- [ ] **Step 1: Make the change**

Current code:

```python
    if eligible_total_exprs and alpha_int > 0:
        # Tiers (each ≫ the next): L1 ≫ prior ≫ count-spread.
        l1_w = 100_000_000_000  # 1e11
        prior_w = 1_000_000     # 1e6
        count_w = 10_000        # 1e4 — above the per-move reserve-distance term
```

Change to:

```python
    if eligible_total_exprs and alpha_int > 0:
        # Tiers (each ≫ the next): L1 ≫ prior ≫ count-spread.
        l1_w = 100_000_000_000  # 1e11
        prior_w = 1_000_000     # 1e6
        # 1e5 — empirically the minimum that reliably breaks L1-tied ties toward
        # an even count split instead of CP-SAT settling on a lopsided
        # near-tied allocation (verified: 1e4 leaves some soldiers at 0 while
        # others double up even given 3x the normal time budget with no stall
        # cutoff; 1e5 finds the genuinely even split). Still ≪ prior_w.
        count_w = 100_000        # 1e5 — above the per-move reserve-distance term
```

- [ ] **Step 2: Run the regression test from Task 6 — confirm it now PASSES**

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest app/algorithm/tests/test_solver.py::test_spreads_duties_evenly_when_soldiers_outnumber_duties -v
```
Expected: `PASSED`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/algorithm/model.py
git commit -m "fix: raise count-spread tiebreaker weight to fix duty-concentration bug

count_w=10_000 was too weak relative to l1_w=1e11: CP-SAT would settle on
a lopsided allocation (some soldiers at 0, others doubled up) that scores
within 1 count_w unit of a genuinely even split, without ever finding or
proving the better one — even given 3x time budget with no stall cutoff.
100_000 (still far below prior_w=1e6) reliably finds the even split."
```

---

### Task 8: Run the full algorithm test suite — confirm no regressions

**Files:** none (verification only)

- [ ] **Step 1: Run the fast algorithm suite**

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest app/algorithm/tests -v
```
Expected: **all tests pass**, including the 4 fixed in Task 5 and the new one from Task 6/7. If any other previously-passing test now fails, that's a real regression from the `count_w` change — stop and investigate before continuing (do not increase `count_w` further without re-checking against this full suite each time).

- [ ] **Step 2: Run the slow CP-SAT suite**

Note: `pytest -m slow` alone collects 0 tests in this repo — the `@pytest.mark.slow` tests are deselected by a `conftest.py` hook unless `--slow` is also passed.

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest --slow -m slow -q
```
Expected: all 8 large-scale CP-SAT tests pass (~11 min).

- [ ] **Step 3: Run the full fast backend suite**

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q -n 8
```
Expected: all tests pass (this also re-runs the Task 4 export-inputs integration test and anything else touched by Tasks 1-3).

---

### Task 9: Validate the fix against full production scale

**Files:** none (validation script, not committed — run ad hoc)

This re-runs the exact reproduction built during the original investigation, against the now-patched code, to confirm the fix actually resolves the production-scale CV problem and not just the small repro.

- [ ] **Step 1: Set up DB access**

The dev Postgres container must be running (`docker ps` should show a container exposing `5432`). All commands below use:

```bash
export DATABASE_URL="postgresql+psycopg://db_admin:db_admin_pw@localhost:5432/cod2"
```

- [ ] **Step 2: Find a real completed job to replay, OR create one**

If the original job `17453acf-0395-4e6c-a6fa-071ca7fe43a4` (the one that produced CV=1.05) still exists in your dev DB, reuse it. Otherwise, create a comparable one: a job covering ~100+ soldiers and ~150-250 shifts over a multi-month window (the original used 212 shifts, 119 soldiers, ~1 year), run it via the API exactly like Task 4's test does (`POST /api/algorithm/jobs`), and note its `job_id`.

- [ ] **Step 3: Write and run the reconstruction + replay script**

Save as `backend/_validate_production_fix.py` (do not commit — delete after use):

```python
import sys, time
from collections import Counter
from decimal import Decimal
from datetime import date, timedelta
import statistics
sys.path.insert(0, '.')
from sqlalchemy import select
from app.db.session import session_scope
from app.db.models import AlgorithmJob, DutyShift, DutyType
from app.services.algorithm_bridge import (
    load_soldier_inputs, resolve_solver_settings, inject_effort_scores,
    reserve_count_for_shift, effort_history_horizon,
)
from app.services.effort_score import compute_effort_data, quarter_start
from app.algorithm.types import DutyBlock
from app.algorithm.solver import solve

JOB_ID = "REPLACE_WITH_REAL_JOB_ID"

def load_honest_duty_blocks(session, shift_ids, standby_multiplier):
    import uuid as uuidlib
    shifts = session.execute(select(DutyShift).where(DutyShift.id.in_(shift_ids))).scalars().all()
    type_ids = {sh.duty_type_id for sh in shifts}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    score_map = {dt.id: dt.score_per_day for dt in types_q}
    blocks = []
    today = date.today()
    for shift in shifts:
        effective_start = max(shift.start_date, today)
        if effective_start > shift.end_date:
            continue
        score = score_map.get(shift.duty_type_id, Decimal("1.00"))
        for _ in range(shift.required_count):
            blocks.append(DutyBlock(id=uuidlib.uuid4(), duty_type_id=shift.duty_type_id,
                                     duty_location_id=shift.duty_location_id,
                                     start_date=effective_start, end_date=shift.end_date,
                                     score_per_day=score, is_reserve=False,
                                     eligible_node_ids=shift.eligible_node_ids))
        r_count = reserve_count_for_shift(session, shift=shift)
        r_score = score * standby_multiplier
        for _ in range(r_count):
            blocks.append(DutyBlock(id=uuidlib.uuid4(), duty_type_id=shift.duty_type_id,
                                     duty_location_id=shift.duty_location_id,
                                     start_date=effective_start, end_date=shift.end_date,
                                     score_per_day=r_score, is_reserve=True,
                                     eligible_node_ids=shift.eligible_node_ids))
    return blocks

with session_scope() as s:
    job = s.get(AlgorithmJob, JOB_ID)
    settings = resolve_solver_settings(s, job.settings_json)
    duties = load_honest_duty_blocks(s, job.shift_ids, Decimal("0.2"))
    planning_start = min(d.start_date for d in duties)
    planning_end = max(d.end_date for d in duties)
    soldiers = load_soldier_inputs(s, as_of=planning_start)
    reset_date = quarter_start(date(planning_start.year - 2, planning_start.month, 1))
    effort_horizon = effort_history_horizon(s, planning_start=planning_start)
    effort_map = compute_effort_data(s, soldiers=soldiers, planning_start=effort_horizon,
                                      planning_end=effort_horizon, reset_date=reset_date)
    effort_range = inject_effort_scores(soldiers, duties, effort_map)
    settings.effort_range_min, settings.effort_range_max = effort_range

    t0 = time.monotonic()
    result = solve(soldiers, duties, [], settings)
    print(f"status={result.status} time={round(time.monotonic()-t0,1)}s assigned={len(result.assignments)}/{len(duties)}")

    duty_by_id = {d.id: d for d in duties}
    per_soldier_score = Counter()
    for a in result.assignments:
        d = duty_by_id[a.duty_id]
        per_soldier_score[a.soldier_id] += float(d.score_per_day) * (d.end_date - d.start_date).days
    scores = [per_soldier_score.get(sd.id, 0.0) for sd in soldiers]
    mean = statistics.mean(scores)
    stdev = statistics.pstdev(scores)
    cv = stdev / mean if mean else 0.0
    print(f"n={len(scores)} mean={mean:.2f} stddev={stdev:.2f} cv={cv:.4f} min={min(scores):.2f} max={max(scores):.2f}")
    print("n_soldiers_with_zero:", sum(1 for x in scores if x == 0))
```

Run it:

```bash
cd backend
DATABASE_URL="postgresql+psycopg://db_admin:db_admin_pw@localhost:5432/cod2" PYTHONUTF8=1 .venv/Scripts/python.exe _validate_production_fix.py
```

- [ ] **Step 4: Compare against the baseline and decide**

Baseline (count_w=10_000, recorded in this investigation): `CV≈0.91-1.05`, `31-33/119 soldiers at zero`.

- **If the new CV drops substantially (rule of thumb: below ~0.5, and zero-soldier count drops to single digits or zero)** — the fix generalizes to production scale. Proceed to Step 5.
- **If the new CV is still high (close to the baseline)** — `count_w=100_000` was sufficient at small scale but not at this much larger scale (more duties/soldiers means a larger L1 term, which `count_w` competes against). Escalate: try `count_w=1_000_000` (equal to `prior_w` — acceptable since `prior_term` is near-zero whenever historical `effort_offset` is near-zero across the board, which is the case in both the small repro and the real production data inspected in this session) and re-run. Re-run Task 8 in full after any further change to `count_w`, since this plan has only validated up to `100_000` against the full test suite.

- [ ] **Step 5: Delete the validation script (not meant to be committed)**

```bash
rm backend/_validate_production_fix.py
```

- [ ] **Step 6: Record the outcome**

Write down (in your handoff notes / PR description, not a new file) the final `count_w` value used and the before/after CV numbers from this validation — whoever reviews this fix needs that evidence to decide whether to take it.

---

## Addendum: Task 9 findings — `count_w` does not fix the production-scale bug

**This section records what was actually found when Task 9 ran, since it changes the plan's outcome.**

`count_w=100_000` (and `1_000_000`, and a deliberately extreme `10_000_000_000` — a million-fold range) all produced **statistically identical results** against the real production job (`17453acf-0395-4e6c-a6fa-071ca7fe43a4`, 119 soldiers, 802 duty blocks): CV 0.94–0.97, exactly 38 zero-duty soldiers every time, regardless of weight. The clean baseline (`count_w=10_000`, measured in this same environment) gave the same numbers. **`count_w` has zero measurable effect at this scale.**

Further diagnosis found the real mechanism:
- The production job goes through the default `effort_rounds` decomposition: 118 eligible soldiers are sorted by `(effort_offset, str(id))` — effectively random UUID order, since almost everyone's historical effort is ~0 — and chunked into 6 disjoint groups of ~20, each solved **sequentially** against a shared, shrinking pool of residual duties (`_effort_round_solve` in `app/algorithm/solver.py`).
- Per-round breakdown: zero-soldier *count* is roughly flat across rounds (2–8 per group of ~20) — not concentrated in later rounds. But total duty *volume* assigned per round collapses sharply and monotonically (309 duties in round 0's group → 33 in round 5's, a ~9x decline), confirming sequential pool consumption.
- Bypassing decomposition entirely (`decomposition="none"`, the same flat-model approach validated at small scale in Task 6) **could not find even one feasible solution in 30s** for the full 802-duty/118-soldier problem — confirming decomposition is a genuine necessity at this scale, not an arbitrary choice.

**Conclusion:** the `count_w` fix is correct and real for the symmetric-tie scenario Task 6's regression test targets (verified, harmless everywhere — Task 8's full suite passes). But the actual 105%-CV production bug is a **structural consequence of the `effort_rounds` decomposition**: each round's `build_fairness_objective` call only sees its own ~20 soldiers and has no mechanism to account for what other rounds already consumed or will consume. No amount of within-round tiebreaker tuning can fix a between-round allocation problem. Fixing this for real requires redesigning how fairness is tracked across the decomposition boundary (e.g., a global running quota/target carried forward between rounds, or a fundamentally different decomposition strategy) — a separate, properly-scoped piece of work, not a parameter change.

**Decision (made with the user after this finding):** ship the work that's solid (Part 1 export-inputs fix, Part 2's test fixes, and the harmless-but-insufficient `count_w` fix) as-is. The decomposition redesign is explicitly deferred to a future, separately-scoped plan.

---

### Task 10: Final full-suite check and handoff

**Files:** none (verification only)

- [ ] **Step 1: Re-run the full fast suite one more time** (in case `count_w` was changed again in Task 9)

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q -n 8
```
Expected: all pass.

- [ ] **Step 2: Re-run the slow suite one more time**

```bash
cd backend
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest --slow -m slow -q
```
Expected: all 8 pass.

- [ ] **Step 3: Review the full diff**

```bash
git log --oneline master..HEAD
git diff master..HEAD --stat
```

- [ ] **Step 4: Hand off**

This work is in an isolated worktree on branch `worktree-algorithm-fairness-fix`, specifically so the user can review and decide whether to merge it. Do not merge, push, or open a PR — leave that decision to the user. Use the `superpowers:finishing-a-development-branch` skill's options when the user is ready to decide.
