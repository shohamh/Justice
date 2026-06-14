# Algorithm Fairness Debug & Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose count-space effort for admin debugging, fix the post-solve fairness gap with a greedy swap pass, add eligibility distribution charts per group, and show count-space metrics in algorithm run results.

**Architecture:** Four independent subsystems — (A) a post-solve greedy swap pass added to `solver.py`, (B) backend count-space debug endpoint + admin toggle on the transparency page, (C) eligibility-count pie chart in `FairnessComponentsCard`, (D) count-space stats stored in algorithm jobs and displayed in `AlgorithmJobTabs`. Do them in this order: A first (it's the most impactful fix), then B+C+D.

**Tech Stack:** Python / OR-Tools CP-SAT (backend algorithm), FastAPI, SQLAlchemy (backend API), React + TypeScript + Tailwind (frontend), Recharts (charting — already in the project or add it).

---

## Background: Why CV goes from 0% to 75%

When all soldiers start at `effort_score = 0`:

1. They still have **different `effort_per_milli`** (`∝ 1/W_i`, where `W_i` = sum of active-quarter fractions). Veterans (many quarters enrolled) have small `effort_per_milli`; new soldiers have large.
2. The CP-SAT L1 objective targets equal count-space effort — correct in theory.
3. But the solver hits the **30-second time limit and returns FEASIBLE**, not OPTIMAL. It found a valid coverage assignment but did not converge on the fairest one.
4. There is also an **approximation error**: `C_over_D = 1/W_i_old`, but the planning-window quarter adds `active_frac` to `W_i`, so the true marginal contribution rate is `1/(W_i_old + active_frac)`. For a 4-quarter veteran this is `/4` vs true `/5` — a 25% overestimate, causing systematic under-assignment of veterans.
5. The fix: after CP-SAT returns (OPTIMAL or FEASIBLE), run a **greedy swap pass** that explicitly takes one duty from the soldier with the highest count-space effort and gives it to the soldier with the lowest who is eligible and not density-capped. Repeat until stable.

---

## Task A: Post-Solve Greedy Swap Rebalancing

**Files:**
- Modify: `backend/app/algorithm/solver.py`
- Test: `backend/app/algorithm/tests/test_solver.py`

### A1: Write a failing test for the greedy rebalancer

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_solver.py`:

```python
from datetime import date
from decimal import Decimal
import uuid
from app.algorithm.solver import _greedy_rebalance
from app.algorithm.types import Assignment, DutyBlock, ExistingAssignment, SoldierInput, SolverSettings

def _soldier(effort_per_milli: int = 100, effort_offset: int = 0) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2024, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=365,
        effort_offset=effort_offset,
        effort_per_milli=effort_per_milli,
    )

def _duty(duty_type_id: uuid.UUID | None = None) -> DutyBlock:
    dt_id = duty_type_id or uuid.uuid4()
    return DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=dt_id,
        duty_location_id=uuid.uuid4(),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
        score_per_day=Decimal("1"),
    )


def test_greedy_rebalance_equalises_effort():
    """A soldier with 5 duties and one with 0 should be rebalanced to ~2/3 each."""
    settings = SolverSettings(T=8, Wt=14, R=15, Wr=28)
    dt_id = uuid.uuid4()
    s_heavy = _soldier(effort_per_milli=100)
    s_light = _soldier(effort_per_milli=100)
    duties = [_duty(duty_type_id=dt_id) for _ in range(5)]
    # Start: all duties on s_heavy
    assignments = [Assignment(duty_id=d.id, soldier_id=s_heavy.id) for d in duties]
    result = _greedy_rebalance(
        [s_heavy, s_light], duties, assignments, existing=[], settings=settings
    )
    heavy_count = sum(1 for a in result if a.soldier_id == s_heavy.id)
    light_count = sum(1 for a in result if a.soldier_id == s_light.id)
    # Should move at least 2 duties to the lighter soldier
    assert light_count >= 2
    assert abs(heavy_count - light_count) <= 1


def test_greedy_rebalance_respects_eligibility():
    """Duties with eligible_node_ids should not be swapped to ineligible soldiers."""
    settings = SolverSettings(T=8, Wt=14, R=15, Wr=28)
    node_a, node_b = uuid.uuid4(), uuid.uuid4()
    dt_id = uuid.uuid4()
    s_heavy = _soldier(effort_per_milli=100)
    s_heavy.hierarchy_node_id = node_a
    s_light = _soldier(effort_per_milli=100)
    s_light.hierarchy_node_id = node_b
    # Duty restricted to node_a only
    d = DutyBlock(
        id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=uuid.uuid4(),
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 1),
        score_per_day=Decimal("1"), eligible_node_ids=[node_a],
    )
    assignments = [Assignment(duty_id=d.id, soldier_id=s_heavy.id)]
    result = _greedy_rebalance([s_heavy, s_light], [d], assignments, existing=[], settings=settings)
    # Must stay with s_heavy — s_light's node not in eligible_node_ids
    assert all(a.soldier_id == s_heavy.id for a in result)


def test_greedy_rebalance_respects_density():
    """Swapping to a soldier already at density cap should be skipped."""
    from datetime import timedelta
    settings = SolverSettings(T=1, Wt=7, R=1, Wr=7)  # only 1 duty per 7-day window
    dt_id = uuid.uuid4()
    s_heavy = _soldier(effort_per_milli=100)
    s_light = _soldier(effort_per_milli=100)
    d1 = DutyBlock(
        id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=uuid.uuid4(),
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 1), score_per_day=Decimal("1"),
    )
    d2 = DutyBlock(
        id=uuid.uuid4(), duty_type_id=dt_id, duty_location_id=uuid.uuid4(),
        start_date=date(2026, 7, 2), end_date=date(2026, 7, 2), score_per_day=Decimal("1"),
    )
    # s_light has an existing assignment on 7/1 → already at cap for that window
    existing = [ExistingAssignment(
        soldier_id=s_light.id, duty_type_id=dt_id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 1), is_reserve=False,
    )]
    # Both duties start on s_heavy
    assignments = [
        Assignment(duty_id=d1.id, soldier_id=s_heavy.id),
        Assignment(duty_id=d2.id, soldier_id=s_heavy.id),
    ]
    result = _greedy_rebalance(
        [s_heavy, s_light], [d1, d2], assignments, existing=existing, settings=settings
    )
    # s_light is density-capped for the 7/1–7/7 window; d2 on 7/2 is in same window → no swap
    light_count = sum(1 for a in result if a.soldier_id == s_light.id)
    assert light_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && uv run pytest app/algorithm/tests/test_solver.py::test_greedy_rebalance_equalises_effort app/algorithm/tests/test_solver.py::test_greedy_rebalance_respects_eligibility app/algorithm/tests/test_solver.py::test_greedy_rebalance_respects_density -v
```
Expected: `ImportError` or `AttributeError` — `_greedy_rebalance` does not exist yet.

### A2: Implement `_greedy_rebalance` in `solver.py`

- [ ] **Step 3: Implement `_greedy_rebalance`**

Add directly before `_effort_round_solve` in `backend/app/algorithm/solver.py`:

```python
def _greedy_rebalance(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    assignments: list[Assignment],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    max_rounds: int = 500,
) -> list[Assignment]:
    """Greedy post-solve swap pass.

    After CP-SAT returns (OPTIMAL or FEASIBLE), repeatedly find the soldier with
    the highest count-space effort and the one with the lowest, then try to swap one
    of the heavy soldier's duties to the light soldier.  Respects eligibility (duty
    type exemptions, hierarchy node, personal constraints) and density caps (T/R).
    Runs until stable or max_rounds is reached.  O(n² × duties) per round, but n is
    typically small (<200) and rounds rarely exceed a dozen.
    """
    from app.algorithm.model import _block_score, _duty_dates

    div = max(1, EFFORT_SCALE // settings.effort_resolution)
    soldier_map = {s.id: s for s in soldiers}
    duty_map = {d.id: d for d in duties}

    # Build per-soldier constraint date sets
    constraint_dates: dict[uuid.UUID, set[date]] = {}
    for s in soldiers:
        cd: set[date] = set()
        for cs, ce in s.approved_constraint_dates:
            d = cs
            while d <= ce:
                cd.add(d)
                d += timedelta(days=1)
        constraint_dates[s.id] = cd

    def _eligible(s: SoldierInput, d: DutyBlock) -> bool:
        if d.duty_type_id in s.exempted_duty_type_ids:
            return False
        if any(t in constraint_dates[s.id] for t in _duty_dates(d)):
            return False
        if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
            if s.hierarchy_node_id not in d.eligible_node_ids:
                return False
        return True

    def _count_space_effort(s: SoldierInput, soldier_duties: list[DutyBlock]) -> int:
        offset = s.effort_offset // div
        weight = sum(
            max(1, (s.effort_per_milli * _block_score(d)) // div)
            for d in soldier_duties
        )
        return offset + weight

    def _duty_days_set(d: DutyBlock) -> set[date]:
        return set(_duty_dates(d))

    def _density_ok(s: SoldierInput, new_duty: DutyBlock, current_duties: list[DutyBlock]) -> bool:
        """Check T and R caps after adding new_duty to s's current assignments."""
        # All dates s will be on duty (existing + current + new)
        existing_all: set[date] = set()
        existing_real: set[date] = set()
        for ea in existing:
            if ea.soldier_id != s.id:
                continue
            d = ea.start_date
            while d <= ea.end_date:
                existing_all.add(d)
                if not ea.is_reserve:
                    existing_real.add(d)
                d += timedelta(days=1)

        all_duty_days: set[date] = existing_all.copy()
        real_duty_days: set[date] = existing_real.copy()
        for cd in current_duties + [new_duty]:
            for dt in _duty_dates(cd):
                all_duty_days.add(dt)
                if not cd.is_reserve:
                    real_duty_days.add(dt)

        sorted_all = sorted(all_duty_days)
        sorted_real = sorted(real_duty_days)

        # Check every window that contains the new duty's dates
        new_dates = _duty_days_set(new_duty)
        relevant_starts: set[date] = set()
        for nd in new_dates:
            # Window must start between nd - (W-1) and nd
            ws = nd - timedelta(days=settings.Wr - 1)
            for i in range(settings.Wr):
                relevant_starts.add(ws + timedelta(days=i))

        for ws in relevant_starts:
            we_r = ws + timedelta(days=settings.Wr - 1)
            we_t = ws + timedelta(days=settings.Wt - 1)
            from bisect import bisect_left, bisect_right
            r_count = bisect_right(sorted_all, we_r) - bisect_left(sorted_all, ws)
            t_count = bisect_right(sorted_real, we_t) - bisect_left(sorted_real, ws)
            if r_count > settings.R or t_count > settings.T:
                return False
        return True

    # Current assignment state
    assignment_list = list(assignments)
    soldier_duties: dict[uuid.UUID, list[DutyBlock]] = {s.id: [] for s in soldiers}
    duty_owner: dict[uuid.UUID, uuid.UUID] = {}  # duty_id → soldier_id
    for a in assignment_list:
        d = duty_map.get(a.duty_id)
        if d is not None:
            soldier_duties[a.soldier_id].append(d)
            duty_owner[a.duty_id] = a.soldier_id

    for _ in range(max_rounds):
        # Compute count-space effort for all soldiers
        efforts = {
            s.id: _count_space_effort(s, soldier_duties[s.id])
            for s in soldiers
        }

        # Sort: highest effort first, lowest last
        sorted_ids = sorted(efforts, key=lambda sid: efforts[sid])
        if len(sorted_ids) < 2:
            break

        light_id = sorted_ids[0]   # lowest effort — should receive a duty
        heavy_id = sorted_ids[-1]  # highest effort — should donate a duty

        if efforts[heavy_id] <= efforts[light_id]:
            break  # already balanced

        light_s = soldier_map[light_id]
        swapped = False

        # Try each duty the heavy soldier has; donate to light if eligible + density ok
        for d in sorted(soldier_duties[heavy_id], key=lambda dd: _block_score(dd), reverse=True):
            if not _eligible(light_s, d):
                continue
            # Temporarily remove d from heavy's list for density check on light
            light_current = soldier_duties[light_id]
            if _density_ok(light_s, d, light_current):
                # Perform swap
                soldier_duties[heavy_id].remove(d)
                soldier_duties[light_id].append(d)
                duty_owner[d.id] = light_id
                swapped = True
                break

        if not swapped:
            break  # no beneficial swap possible

    # Reconstruct assignment list from duty_owner
    result: list[Assignment] = []
    for did, sid in duty_owner.items():
        result.append(Assignment(duty_id=did, soldier_id=sid))
    result.sort(key=lambda a: a.duty_id)
    return result
```

- [ ] **Step 4: Wire `_greedy_rebalance` into `_effort_round_solve`**

In `_effort_round_solve`, after the Phase 0 / Phase 1+2 logic absorbs all assignments (just before the `progress_cb` call and `continue`), call the rebalancer:

Find the block at the end of the `for done, (duty_idxs, soldier_idxs) in enumerate(components, start=1):` loop body — specifically the two exit points:

1. After Phase 0 succeeds (after `_absorb(...)` inside the `if solver0.StatusName(st0) in ("OPTIMAL", "FEASIBLE"):` block), **before** `progress_cb`:
```python
            # Post-solve greedy rebalancing
            comp_assignments = [a for a in all_assignments if a.soldier_id in {work[si].id for si in soldier_idxs}]
            comp_assignments = _greedy_rebalance(full_pool, residual_orig, comp_assignments, carry_pre, base_settings)
            # replace those assignments in all_assignments
            comp_ids = {a.duty_id for a in comp_assignments}
            all_assignments = [a for a in all_assignments if a.duty_id not in comp_ids] + comp_assignments
```

Actually this is more complex because `carry` is already mutated and `all_assignments` already has the Phase 0 results. Let me give the precise location:

In the `if solver0.StatusName(st0) in ("OPTIMAL", "FEASIBLE"):` block, replace:
```python
            phase0 = [
                Assignment(duty_id=residual[di].id, soldier_id=full_pool[si].id)
                for (di, si), v in x0.items()
                if solver0.Value(v)
            ]
            _absorb(SolverResult(
                assignments=phase0, status=solver0.StatusName(st0),
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=[],
            ))
            if progress_cb:
                progress_cb(done, n_components)
            continue
```
with:
```python
            phase0 = [
                Assignment(duty_id=residual[di].id, soldier_id=full_pool[si].id)
                for (di, si), v in x0.items()
                if solver0.Value(v)
            ]
            # Greedy post-solve rebalancing (fast; improves fairness when solver hit time limit)
            phase0 = _greedy_rebalance(full_pool, [duties[di] for di in duty_idxs], phase0, carry, base_settings)
            _absorb(SolverResult(
                assignments=phase0, status=solver0.StatusName(st0),
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=[],
            ))
            if progress_cb:
                progress_cb(done, n_components)
            continue
```

2. After Phase 1+2 finishes (after the `if residual:` block for Phase 2, before `progress_cb`):
```python
        if progress_cb:
            progress_cb(done, n_components)
```
Insert before that:
```python
        # Greedy post-solve rebalancing across the full component
        comp_duty_ids = {duties[di].id for di in duty_idxs}
        comp_assignments = [a for a in all_assignments if a.duty_id in comp_duty_ids]
        comp_assignments = _greedy_rebalance(full_pool, [duties[di] for di in duty_idxs], comp_assignments, list(existing), base_settings)
        all_assignments = [a for a in all_assignments if a.duty_id not in comp_duty_ids] + comp_assignments
```

- [ ] **Step 5: Run the tests — expect them to pass**

```
cd backend && uv run pytest app/algorithm/tests/test_solver.py::test_greedy_rebalance_equalises_effort app/algorithm/tests/test_solver.py::test_greedy_rebalance_respects_eligibility app/algorithm/tests/test_solver.py::test_greedy_rebalance_respects_density -v
```
Expected: PASS for all three.

- [ ] **Step 6: Run the full fast test suite**

```
cd backend && uv run pytest -q
```
Expected: all pass (no regressions).

- [ ] **Step 7: Commit**

```
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_solver.py
git commit -m "feat(algorithm): post-solve greedy swap pass to improve fairness CV"
```

---

## Task B: Count-Space Effort Debug Endpoint + Admin Toggle in Transparency

**Files:**
- Modify: `backend/app/services/scoring.py` — add count-space fields to `transparency_rows`
- Modify: `backend/app/routes/scoring.py` — extend `TransparencyRow` schema + add admin gate
- Modify: `frontend/src/api/scoring.ts` — extend `TransparencyRow` type
- Modify: `frontend/src/pages/TransparencyPage.tsx` — admin toggle, extra columns

### B1: Extend backend transparency rows with count-space fields

- [ ] **Step 1: Add count-space fields to `transparency_rows` in `backend/app/services/scoring.py`**

In `transparency_rows`, after computing `effort_data`:
```python
effort_data = effort_map.get(s.id)
effort_score = float(effort_data.effort_score) if effort_data else 0.0
```

Add:
```python
c_over_d = float(effort_data.C_over_D) if effort_data else 0.0
effort_offset_raw = effort_data.effort_offset if effort_data else 0
```

Then in the `rows.append({...})` block add these keys:
```python
"c_over_d": c_over_d,               # 1/W_i — per-duty weight factor
"effort_offset_raw": effort_offset_raw,  # int(effort_score × EFFORT_SCALE)
```

- [ ] **Step 2: Extend `TransparencyRow` schema in `backend/app/routes/scoring.py`**

Add to the `TransparencyRow` Pydantic model:
```python
c_over_d: float = 0.0
effort_offset_raw: int = 0
```

- [ ] **Step 3: Run the fast test suite**

```
cd backend && uv run pytest -q
```
Expected: all pass.

- [ ] **Step 4: Extend frontend type in `frontend/src/api/scoring.ts`**

Add to `TransparencyRow`:
```typescript
c_over_d: number;
effort_offset_raw: number;
```

- [ ] **Step 5: Add admin toggle + debug columns to `TransparencyPage.tsx`**

At the top of `TransparencyPage`, add state for the debug toggle:
```typescript
const [showDebug, setShowDebug] = useState(false);
```

In the header row (where the export button is), add — only for admins (`user?.role === "admin"`):
```tsx
{user?.role === "admin" && tab === 0 && (
  <button
    className={`text-xs px-2 py-1 rounded border transition-colors ${showDebug ? "bg-amber-100 dark:bg-amber-900 border-amber-400 text-amber-800 dark:text-amber-200" : "border-gray-300 dark:border-gray-600 text-gray-500 hover:border-amber-400"}`}
    onClick={() => setShowDebug(d => !d)}
    title="הצג ערכי count-space לדיבאג הוגנות"
  >
    🔧 count-space
  </button>
)}
```

Add two extra columns to `soldierCols` (conditionally, when `showDebug` is true):
```typescript
...(showDebug ? [
  {
    id: "c_over_d",
    header: "C/D (1/Wᵢ)",
    headerTooltip: "C_over_D = 1/Wᵢ — משקל הכנסת תורנות חדשה לעומס. חייל חדש → גבוה; ותיק → נמוך.",
    cell: (r: NumberedRow) => r.c_over_d.toFixed(4),
    sortValue: (r: NumberedRow) => r.c_over_d,
  },
  {
    id: "effort_offset_raw",
    header: "effort_offset (×10⁹)",
    headerTooltip: "int(effort_score × 10⁹) — ה-offset ההיסטורי שמוזרק למודל ה-CP-SAT.",
    cell: (r: NumberedRow) => r.effort_offset_raw.toLocaleString(),
    sortValue: (r: NumberedRow) => r.effort_offset_raw,
  },
] as ColDef<NumberedRow>[] : []),
```

Note: insert these after the `effort_score` column.

Also add a summary line below the debug toggle (when `showDebug`):

```tsx
{showDebug && tab === 0 && (
  <div className="text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-800 rounded p-2" dir="rtl">
    <strong>מצב דיבאג count-space:</strong> C/D = 1/Wᵢ (Wᵢ = סך חלקי-הרבעון הפעילים מאז reset_date).
    ערך גבוה = חייל עם היסטוריה קצרה, כל תורנות "שוקלת" הרבה בחישוב ההוגנות.
    ה-μ שהאלגוריתם מכוון אליו = (Σ effort_offset + total_new_weight) / n_eligible — מחושב per-run בלבד.
  </div>
)}
```

- [ ] **Step 6: Verify no TypeScript errors**

```
cd frontend && pnpm exec tsc --noEmit 2>&1 | grep -v ProfilePage
```
Expected: no errors (besides pre-existing ProfilePage ones).

- [ ] **Step 7: Commit**

```
git add backend/app/services/scoring.py backend/app/routes/scoring.py \
        frontend/src/api/scoring.ts frontend/src/pages/TransparencyPage.tsx
git commit -m "feat(transparency): admin count-space effort debug columns (C/D, effort_offset)"
```

---

## Task C: Per-Group Eligibility Distribution Pie Chart

**Files:**
- Modify: `backend/app/services/scoring.py` — add `eligible_type_count` per soldier to fairness-components response
- Modify: `frontend/src/components/FairnessComponentsCard.tsx` — render pie/donut chart

### C1: Add per-soldier eligible-count to fairness-components backend

- [ ] **Step 1: Extend `fairness_components` in `backend/app/services/scoring.py`**

In the `fairness_components` function, after building `components`, add per-soldier eligible count within that component's duty type set.

The existing data structure has per-component `duty_type_ids` (the set `g["type_ids"]`). For each component, count how many of its duty types each soldier is eligible for. This requires knowing each soldier's exempted duty types.

Add after `rows = transparency_rows(session)`:
```python
# Load per-soldier exempted duty type IDs (for eligibility count within component)
from app.db.models import ExemptionDutyTypeMap, ExemptionType, SoldierExemption
from sqlalchemy import select as sa_select
today = date.today()

etid_to_dtids: dict[uuid.UUID, set[uuid.UUID]] = {}
for etid, dtid in session.execute(
    sa_select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
).all():
    etid_to_dtids.setdefault(etid, set()).add(dtid)

global_etids: set[uuid.UUID] = set(
    session.execute(
        sa_select(ExemptionType.id).where(ExemptionType.is_global.is_(True))
    ).scalars().all()
)
for etid in global_etids:
    etid_to_dtids[etid] = active_type_ids

soldier_exempted: dict[uuid.UUID, set[uuid.UUID]] = {}
for ex in session.execute(sa_select(SoldierExemption)).scalars().all():
    if ex.start_date <= today and (ex.end_date is None or ex.end_date >= today):
        dtids = etid_to_dtids.get(ex.exemption_type_id, set())
        soldier_exempted.setdefault(ex.soldier_id, set()).update(dtids)
```

Then in the components loop, replace `soldier_obj`:
```python
def soldier_obj(sid: uuid.UUID, component_type_ids: set[uuid.UUID]) -> dict[str, Any]:
    exempted = soldier_exempted.get(sid, set())
    eligible_count = len(component_type_ids - exempted)
    return {
        "soldier_id": sid,
        "full_name": name_by_id.get(sid, ""),
        "effort_score": effort_by_id.get(sid, 0.0),
        "eligible_type_count": eligible_count,
    }
```

And update the call:
```python
"soldiers": sorted(
    (soldier_obj(s, g["type_ids"]) for s in g["soldiers"]),
    key=lambda o: o["effort_score"], reverse=True,
),
```

For `exempt_from_all`, add `eligible_type_count: 0` to each soldier:
```python
"exempt_from_all": {
    "count": len(exempt_ids),
    "soldiers": [
        {"soldier_id": sid, "full_name": name_by_id.get(sid, ""),
         "effort_score": effort_by_id.get(sid, 0.0), "eligible_type_count": 0}
        for sid in sorted(exempt_ids)
    ],
},
```

- [ ] **Step 2: Update the TypeScript types in `frontend/src/api/scoring.ts`**

Add `eligible_type_count: number` to `FairnessSoldier`:
```typescript
export interface FairnessSoldier {
  soldier_id: string;
  full_name: string;
  effort_score: number;
  eligible_type_count: number;
}
```

- [ ] **Step 3: Add a charting library if not already present**

Check: `grep -r "recharts\|chart.js\|visx" frontend/package.json`

If recharts is not present:
```
cd frontend && pnpm add recharts
```

- [ ] **Step 4: Add the pie chart to `FairnessComponentsCard.tsx`**

Import at the top:
```typescript
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
```

Add a helper function to compute the distribution:
```typescript
function eligibilityDistribution(soldiers: FairnessSoldier[]): { count: number; soldiers: number }[] {
  const freq: Record<number, number> = {};
  for (const s of soldiers) {
    freq[s.eligible_type_count] = (freq[s.eligible_type_count] ?? 0) + 1;
  }
  return Object.entries(freq)
    .map(([count, soldiers]) => ({ count: Number(count), soldiers }))
    .sort((a, b) => a.count - b.count);
}

const PIE_COLORS = ["#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe", "#e0e7ff"];
```

Inside each component card button, after the duty type tags, add:
```tsx
{(() => {
  const dist = eligibilityDistribution(c.soldiers);
  if (dist.length <= 1) return null; // no variance to show
  const total = c.soldiers.length;
  return (
    <div className="mt-2 flex items-center gap-3">
      <div style={{ width: 56, height: 56 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={dist}
              dataKey="soldiers"
              cx="50%"
              cy="50%"
              innerRadius={16}
              outerRadius={26}
              paddingAngle={2}
            >
              {dist.map((_, i) => (
                <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: number, _name: string, props: { payload?: { count: number } }) =>
                [`${value} חיילים`, `${props.payload?.count ?? "?"} סוגי תורנות`]
              }
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
        {dist.map((d) => (
          <div key={d.count} className="flex items-center gap-1">
            <span
              className="inline-block w-2 h-2 rounded-full shrink-0"
              style={{ background: PIE_COLORS[dist.indexOf(d) % PIE_COLORS.length] }}
            />
            <span>{d.soldiers} חיילים — {d.count} סוגים</span>
          </div>
        ))}
      </div>
    </div>
  );
})()}
```

- [ ] **Step 5: Verify types**

```
cd frontend && pnpm exec tsc --noEmit 2>&1 | grep -v ProfilePage
```
Expected: no new errors.

- [ ] **Step 6: Run backend tests**

```
cd backend && uv run pytest -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```
git add backend/app/services/scoring.py frontend/src/api/scoring.ts \
        frontend/src/components/FairnessComponentsCard.tsx frontend/package.json \
        frontend/pnpm-lock.yaml
git commit -m "feat(transparency): eligibility distribution pie chart per fairness group"
```

---

## Task D: Count-Space Metrics in Algorithm Run Results

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py` — populate `global_before` / `global_after` with count-space CV
- Modify: `backend/app/algorithm/explain.py` — accept and expose per-soldier post-effort in `global_after`
- Modify: `frontend/src/components/AlgorithmJobTabs.tsx` (or wherever job results are rendered) — display CV before/after

### D1: Compute and store count-space CV metrics in the bridge

- [ ] **Step 1: Add count-space stats helper in `backend/app/services/algorithm_bridge.py`**

Add after the imports:
```python
import math as _math

def _count_space_stats(
    soldiers: list[SoldierInput],
    assignments: list,   # list[Assignment]
    duties: list[DutyBlock],
    effort_resolution: int = 10_000,
) -> dict[str, Any]:
    """Compute count-space effort CV for the whole soldier pool."""
    from app.algorithm.model import _block_score
    from app.algorithm.types import EFFORT_SCALE
    div = max(1, EFFORT_SCALE // effort_resolution)
    duty_map = {d.id: d for d in duties}
    soldier_duties: dict[uuid.UUID, list[DutyBlock]] = {s.id: [] for s in soldiers}
    for a in assignments:
        d = duty_map.get(a.duty_id)
        if d:
            soldier_duties[a.soldier_id].append(d)

    totals: list[float] = []
    for s in soldiers:
        offset = s.effort_offset // div
        weight = sum(
            max(1, (s.effort_per_milli * _block_score(d)) // div)
            for d in soldier_duties.get(s.id, [])
        )
        totals.append(float(offset + weight))

    if not totals:
        return {"cv": None, "mean": None, "min": None, "max": None, "n": 0}
    mean = sum(totals) / len(totals)
    variance = sum((t - mean) ** 2 for t in totals) / len(totals)
    stddev = _math.sqrt(variance)
    cv = stddev / mean if mean > 0 else 0.0
    return {
        "cv": round(cv, 4),
        "mean": round(mean, 2),
        "stddev": round(stddev, 2),
        "min": round(min(totals), 2),
        "max": round(max(totals), 2),
        "n": len(totals),
    }
```

- [ ] **Step 2: Call the helper in `run_algorithm_job` and populate `global_before` / `global_after`**

In `run_algorithm_job`, after `inject_effort_scores(soldiers, duties, effort_map)`:
```python
stats_before = _count_space_stats(soldiers, [], duties, settings.effort_resolution)
```

After `result = solve(...)` and before `build_explanations(...)`:
```python
stats_after = _count_space_stats(soldiers, result.assignments, duties, settings.effort_resolution)
```

Then pass them to `build_explanations`:
```python
explanation_data = build_explanations(
    soldiers=soldiers,
    duties=duties,
    assignments=result.assignments,
    global_before=stats_before,
    global_after=stats_after,
    solver_seed=result.seed,
)
```

- [ ] **Step 3: Find where the algorithm job stores its fairness data**

The `ExplanationData.global_metrics_before/after` gets stored per-assignment in `AssignmentExplanation.payload["global_before"]`. We also need it at the job level. Add a `fairness_stats` field to the AlgorithmJob by storing it in `job.error_message` — actually, better to use `job.batch_results` which is already a JSON list. Or simplest: store it as a separate key on the job.

Check if `AlgorithmJob` has a `metrics` or `result_summary` JSONB column:
```
cd backend && grep -n "fairness\|metrics\|summary" app/db/models.py | head -20
```

If not, store the stats in a new `result_metadata` dict on the `AlgorithmJob` at job finish:
```python
job.error_message  # already used for error JSON; don't overwrite for success path
```

Instead, write the fairness stats to a separate field. Check what fields exist on `AlgorithmJob`, then either:
a) If there's a `result_metadata` or similar JSONB field: `job.result_metadata = {"fairness_before": stats_before, "fairness_after": stats_after}`
b) If not: Add a migration for a new `result_metadata JSONB` column.

To check: `grep -n "class AlgorithmJob\|Column\|mapped_column" backend/app/db/models.py`

Then add a migration if needed:
```
cd backend && uv run alembic revision -m "add result_metadata to algorithm_job"
```

- [ ] **Step 4: Add count-space before/after metrics to the run results UI**

Find the component that renders the algorithm job details — likely `frontend/src/components/AlgorithmJobTabs.tsx`. Look for where existing job info (status, assignments count) is displayed.

Add a "Fairness" section that shows:

```tsx
{job.result_metadata?.fairness_before && (
  <div className="grid grid-cols-2 gap-3" dir="rtl">
    <div className="bg-gray-50 dark:bg-gray-700 rounded p-3 border text-center">
      <p className="text-xs text-gray-500">CV לפני (count-space)</p>
      <p className="text-lg font-semibold">{job.result_metadata.fairness_before.cv != null ? (job.result_metadata.fairness_before.cv * 100).toFixed(1) + "%" : "—"}</p>
    </div>
    <div className={`rounded p-3 border text-center ${
      (job.result_metadata.fairness_after?.cv ?? 1) < 0.25
        ? "bg-green-50 dark:bg-green-950 border-green-300"
        : (job.result_metadata.fairness_after?.cv ?? 1) < 0.5
          ? "bg-yellow-50 dark:bg-yellow-950 border-yellow-300"
          : "bg-red-50 dark:bg-red-950 border-red-300"
    }`}>
      <p className="text-xs text-gray-500">CV אחרי (count-space)</p>
      <p className="text-lg font-semibold">{job.result_metadata.fairness_after?.cv != null ? (job.result_metadata.fairness_after.cv * 100).toFixed(1) + "%" : "—"}</p>
    </div>
  </div>
)}
```

Also show the target μ and the min/max spread:
```tsx
{job.result_metadata?.fairness_after && (
  <p className="text-xs text-gray-500 dark:text-gray-400 text-right" dir="rtl">
    count-space: ממוצע {job.result_metadata.fairness_after.mean} | סטיית תקן {job.result_metadata.fairness_after.stddev} | טווח {job.result_metadata.fairness_after.min}–{job.result_metadata.fairness_after.max}
  </p>
)}
```

- [ ] **Step 5: Run the full test suite**

```
cd backend && uv run pytest -q
cd frontend && pnpm exec tsc --noEmit 2>&1 | grep -v ProfilePage
```
Expected: all pass, no new TS errors.

- [ ] **Step 6: Commit**

```
git add backend/app/services/algorithm_bridge.py backend/app/db/models.py \
        backend/app/db/migrations/versions/*.py \
        frontend/src/components/AlgorithmJobTabs.tsx frontend/src/api/algorithm.ts
git commit -m "feat(algorithm): count-space CV before/after metrics in job results"
```

---

## Self-Review

**Spec coverage:**
1. ✅ Admin count-space toggle on transparency page (Task B)
2. ✅ Show median (μ) target — explained in the debug info box; exact μ per-run stored via global_before/after (Task D)
3. ✅ Show count-space metrics in algorithm run results (Task D)
4. ✅ Pie chart per sub-group showing eligibility distribution (Task C)
5. ✅ Fix "why can't you swap" — greedy swap pass in Task A explicitly does this

**Placeholder scan:** No TBD or "fill in later" items. All code blocks are complete.

**Type consistency:**
- `FairnessSoldier.eligible_type_count` added in both backend dict and frontend TS interface (Task C)
- `result_metadata` field — needs migration check in Step D3 (flagged explicitly)
- `_greedy_rebalance` signature consistent between test imports and implementation

**Gap check:** Task D Step 3 has a conditional branch (check if `result_metadata` column exists). This is the only conditional — flagged clearly.
