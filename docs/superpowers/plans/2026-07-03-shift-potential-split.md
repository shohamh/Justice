# Shift Potential-Based Quota Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When creating or editing a shift, auto-suggest a per-sub-unit `DutyShiftNodeQuota` split proportional to each direct child's potential (largest-remainder rounding), pre-filling an editable quota table; add a "Recompute quotas" action for existing shifts and wire a "Re-run assignment algorithm" action alongside it; display the shift's lowest-common-ancestor "responsible node."

**Architecture:** A new `backend/app/services/shift_potential_split.py` module computes the suggested split by calling `compute_potential` (from the potential-core plan) on each direct child of the shift's eligible root, using largest-remainder rounding to make counts sum exactly to `required_count`. A new route returns this suggestion (without saving) and writes a `shift.potential_split_suggested` audit entry; the existing `PUT /{shift_id}/quotas` route (unchanged) is what actually persists the DM's final choice. The "responsible node" is a pure `path_ids`-based lowest-common-ancestor computation, exposed as a read-only field. The "re-run assignment algorithm" action reuses the existing `POST /api/algorithm/jobs` endpoint with `shift_ids: [shift_id]` — no new backend endpoint needed for that part.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, React + TypeScript.

**Depends on:** `docs/superpowers/plans/2026-07-03-potential-core.md` (must be implemented first — this plan imports `app.services.potential.compute_potential`).

---

### Task 1: Largest-remainder proportional split algorithm

**Files:**
- Create: `backend/app/services/shift_potential_split.py`
- Test: `backend/app/services/tests/test_shift_potential_split.py`

- [ ] **Step 1: Write the failing test for the pure rounding function**

```python
# backend/app/services/tests/test_shift_potential_split.py
from __future__ import annotations

import uuid

from app.services.shift_potential_split import largest_remainder_split


def test_largest_remainder_split_exact_ratio():
    node_a, node_b = uuid.uuid4(), uuid.uuid4()
    result = largest_remainder_split({node_a: 60, node_b: 40}, total=10)
    assert result[node_a] + result[node_b] == 10
    assert result[node_a] == 6
    assert result[node_b] == 4


def test_largest_remainder_split_uneven_ratio_sums_to_total():
    node_a, node_b, node_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    result = largest_remainder_split({node_a: 7, node_b: 5, node_c: 3}, total=9)
    assert sum(result.values()) == 9
    # 7/15*9=4.2, 5/15*9=3.0, 3/15*9=1.8 -> floors 4,3,1=8, one remainder to largest fractional (node_a: .2 vs node_c: .8)
    assert result[node_c] == 2
    assert result[node_a] == 4
    assert result[node_b] == 3


def test_largest_remainder_split_zero_potential_nodes_get_zero(app_session=None):
    node_a, node_b = uuid.uuid4(), uuid.uuid4()
    result = largest_remainder_split({node_a: 0, node_b: 10}, total=5)
    assert result[node_a] == 0
    assert result[node_b] == 5


def test_largest_remainder_split_all_zero_potential_returns_all_zero():
    node_a, node_b = uuid.uuid4(), uuid.uuid4()
    result = largest_remainder_split({node_a: 0, node_b: 0}, total=5)
    assert result[node_a] == 0
    assert result[node_b] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_shift_potential_split.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the split function**

```python
# backend/app/services/shift_potential_split.py
from __future__ import annotations

import uuid


def largest_remainder_split(potentials: dict[uuid.UUID, int], *, total: int) -> dict[uuid.UUID, int]:
    """Split `total` slots proportionally across node potentials, using the
    largest-remainder method so counts always sum exactly to `total`.

    Nodes with non-positive potential get 0 slots and are excluded from the
    weighted distribution entirely (they don't compete for the total pool
    unless every node has non-positive potential, in which case all get 0).
    """
    positive = {n: p for n, p in potentials.items() if p > 0}
    result = {n: 0 for n in potentials}
    if not positive or total <= 0:
        return result

    weight_sum = sum(positive.values())
    exact = {n: (p / weight_sum) * total for n, p in positive.items()}
    floors = {n: int(v) for n, v in exact.items()}
    assigned = sum(floors.values())
    remainder = total - assigned

    remainders = sorted(positive.keys(), key=lambda n: exact[n] - floors[n], reverse=True)
    for i in range(remainder):
        floors[remainders[i % len(remainders)]] += 1

    result.update(floors)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_shift_potential_split.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shift_potential_split.py backend/app/services/tests/test_shift_potential_split.py
git commit -m "feat: add largest-remainder proportional split algorithm"
```

---

### Task 2: Suggest split for a shift, using direct children of the eligible root

**Files:**
- Modify: `backend/app/services/shift_potential_split.py`
- Modify: `backend/app/services/tests/test_shift_potential_split.py`

- [ ] **Step 1: Write failing tests**

```python
# append to backend/app/services/tests/test_shift_potential_split.py
from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType, Soldier
from app.services.hierarchy import create_node
from app.services.shift_potential_split import suggest_shift_quota_split


def _make_soldier(session, node_id):
    s = Soldier(personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x", hierarchy_node_id=node_id)
    session.add(s)
    session.flush()
    return s


def test_suggest_split_across_direct_children_of_eligible_root(app_session):
    root = create_node(app_session, level="גדוד", name="Battalion", parent_id=None)
    app_session.flush()
    co_a = create_node(app_session, level="פלוגה", name="Co A", parent_id=root.id)
    co_b = create_node(app_session, level="פלוגה", name="Co B", parent_id=root.id)
    app_session.flush()

    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    loc = DutyLocation(name="שער")
    app_session.add_all([dt, loc])
    app_session.flush()

    for _ in range(6):
        _make_soldier(app_session, co_a.id)
    for _ in range(4):
        _make_soldier(app_session, co_b.id)

    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 10), end_date=date(2026, 7, 11),
        required_count=10, eligible_node_ids=[root.id],
    )
    app_session.add(shift)
    app_session.commit()

    result = suggest_shift_quota_split(app_session, shift_id=shift.id)
    assert result[co_a.id] == 6
    assert result[co_b.id] == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_shift_potential_split.py::test_suggest_split_across_direct_children_of_eligible_root -v`
Expected: FAIL — `suggest_shift_quota_split` not defined. (Check `DutyLocation` model field requirements first: `grep -n "class DutyLocation" -A 15 backend/app/db/models.py` — adjust the fixture if it requires more fields than just `name`.)

- [ ] **Step 3: Implement**

Append to `backend/app/services/shift_potential_split.py`:

```python
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyShift, HierarchyNode
from app.services.potential import compute_potential


class ShiftPotentialSplitError(Exception):
    """Raised when a shift's potential split cannot be computed."""


def suggest_shift_quota_split(session: Session, *, shift_id: uuid.UUID) -> dict[uuid.UUID, int]:
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        raise ShiftPotentialSplitError("shift_not_found")

    all_nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    node_by_id = {n.id: n for n in all_nodes}

    if shift.eligible_node_ids:
        root_ids = list(shift.eligible_node_ids)
    else:
        root_ids = [n.id for n in all_nodes if n.parent_id is None]

    direct_children: list[HierarchyNode] = []
    for root_id in root_ids:
        root = node_by_id.get(root_id)
        if root is None:
            continue
        children = [n for n in all_nodes if n.parent_id == root_id]
        if children:
            direct_children.extend(children)
        else:
            direct_children.append(root)  # leaf eligible root: no children to split across

    if not direct_children:
        raise ShiftPotentialSplitError("no_eligible_nodes")

    potentials: dict[uuid.UUID, int] = {}
    for child in direct_children:
        result = compute_potential(session, node_id=child.id, reference_date=shift.start_date)
        potentials[child.id] = max(0, result.final_potential)

    return largest_remainder_split(potentials, total=shift.required_count)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest app/services/tests/test_shift_potential_split.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shift_potential_split.py backend/app/services/tests/test_shift_potential_split.py
git commit -m "feat: suggest per-child quota split for a shift from potential ratios"
```

---

### Task 3: Route — suggest split (read-only, audited)

**Files:**
- Modify: `backend/app/routes/shifts.py`

- [ ] **Step 1: Check the audit writer import already present**

Run: `cd backend && grep -n "write_audit\|from app.audit" app/routes/shifts.py`

If not imported, add `from app.audit.writer import write_audit` near the top.

- [ ] **Step 2: Write the failing test**

```python
# add to an existing shifts route test file — find it first:
# grep -rl "def test_.*create_shift\|/api/shifts" backend/app --include=*.py | grep test
```

Add (adapting to whatever auth helper pattern that file already uses):

```python
def test_suggest_quota_split_route(client, admin_session):
    # Reuse the file's existing shift/hierarchy/soldier fixtures to create a shift
    # with eligible_node_ids covering a root with two children populated with
    # soldiers in a 6:4 ratio (mirror Task 2's service-level test setup), then:
    resp = authed_client.get(f"/api/shifts/{shift.id}/quotas/suggest")
    assert resp.status_code == 200
    body = resp.json()
    assert sum(q["count"] for q in body["suggestions"]) == shift.required_count
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && pytest -k suggest_quota_split -v`
Expected: FAIL (404).

- [ ] **Step 4: Implement the route**

Add to `backend/app/routes/shifts.py`, near `put_shift_quotas` (around line 208):

```python
from app.services.shift_potential_split import ShiftPotentialSplitError, suggest_shift_quota_split


class SuggestedQuota(BaseModel):
    hierarchy_node_id: uuid.UUID
    node_name: str
    count: int


class SuggestQuotasResponse(BaseModel):
    suggestions: list[SuggestedQuota]


@router.get("/{shift_id}/quotas/suggest", response_model=SuggestQuotasResponse)
def suggest_shift_quotas(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> SuggestQuotasResponse:
    try:
        split = suggest_shift_quota_split(session, shift_id=shift_id)
    except ShiftPotentialSplitError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    write_audit(
        session,
        actor_id=actor.id,
        action="shift.potential_split_suggested",
        entity_type="duty_shift",
        entity_id=shift_id,
        after={"suggestions": {str(k): v for k, v in split.items()}},
    )
    session.commit()

    names = {n.id: n.name for n in session.execute(select(HierarchyNode)).scalars().all()}
    return SuggestQuotasResponse(
        suggestions=[
            SuggestedQuota(hierarchy_node_id=node_id, node_name=names.get(node_id, "?"), count=count)
            for node_id, count in split.items()
        ]
    )
```

Check `HierarchyNode` and `select` are already imported in `shifts.py` (`grep -n "^from\|^import" app/routes/shifts.py`); add if missing.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest -k suggest_quota_split -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/shifts.py
git commit -m "feat: add GET /shifts/{id}/quotas/suggest route with audit trail"
```

---

### Task 4: Auto-populate quotas on shift creation

**Files:**
- Modify: `backend/app/routes/shifts.py`

- [ ] **Step 1: Write failing test**

```python
def test_create_shift_auto_populates_quotas_from_potential(client, admin_session):
    # Create hierarchy root + two children with soldiers in a known ratio (as in Task 2),
    # then POST /api/shifts with eligible_node_ids=[root.id], required_count=10.
    resp = authed_client.post("/api/shifts", json={
        "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-07-10", "end_date": "2026-07-11",
        "required_count": 10, "eligible_node_ids": [str(root.id)],
    })
    assert resp.status_code == 201
    shift_id = resp.json()["id"]
    quotas_resp = authed_client.get(f"/api/shifts/{shift_id}")
    node_quotas = quotas_resp.json()["node_quotas"]
    assert sum(q["count"] for q in node_quotas) == 10
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest -k auto_populates_quotas -v`
Expected: FAIL — no quotas exist after creation today.

- [ ] **Step 3: Wire auto-population into `create_shift`**

Modify the `create_shift` route (around line 166-191): after the shift is created and committed, call `suggest_shift_quota_split` and persist it via the existing `set_shift_quotas` service, then re-fetch for the response:

```python
@router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(
    body: CreateShiftRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    try:
        shift = svc.create_shift(
            session,
            duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id,
            start_date=body.start_date,
            end_date=body.end_date,
            start_time=body.start_time,
            end_time=body.end_time,
            required_count=body.required_count,
            notes=body.notes,
            reserve_count_override=body.reserve_count_override,
            eligible_node_ids=body.eligible_node_ids,
            actor_id=user.id,
        )
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        split = suggest_shift_quota_split(session, shift_id=shift.id)
        if split and sum(split.values()) > 0:
            set_shift_quotas(
                session, shift_id=shift.id,
                quotas=[(node_id, count) for node_id, count in split.items() if count > 0],
                actor_id=user.id,
            )
            write_audit(
                session, actor_id=user.id, action="shift.potential_split_suggested",
                entity_type="duty_shift", entity_id=shift.id,
                after={"suggestions": {str(k): v for k, v in split.items()}},
            )
    except ShiftPotentialSplitError:
        pass  # no eligible hierarchy to split across — leave quotas empty, DM can set manually

    session.commit()
    result = svc.get_shift_fill(session, shift_id=shift.id)
    return _out(result, session, node_quotas=_resolve_node_quotas(session, shift.id))
```

Note the `_out(...)` call at the end now also passes `node_quotas=...` — check `_out`'s signature (`grep -n "def _out" app/routes/shifts.py`) to confirm this parameter exists and matches the pattern used in `get_shift` (line ~202); adjust the call to match exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest -k auto_populates_quotas -v`
Expected: PASS

- [ ] **Step 5: Run the full shifts test suite for regressions**

Run: `cd backend && pytest -k shifts -v`
Expected: PASS — existing shift-creation tests that didn't set up an eligible hierarchy should hit the `ShiftPotentialSplitError` pass-through and behave exactly as before (empty quotas).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/shifts.py
git commit -m "feat: auto-populate shift quotas from potential split on creation"
```

---

### Task 5: Lowest-common-ancestor "responsible node" display

**Files:**
- Modify: `backend/app/routes/shifts.py`
- Test: as part of the same route test file

- [ ] **Step 1: Write failing test**

```python
def test_shift_responsible_node_is_lowest_common_ancestor(client, admin_session):
    # Shift quota'd across co_a and co_b, both children of `root` (Task 2 setup).
    resp = authed_client.get(f"/api/shifts/{shift_id}")
    assert resp.json()["responsible_node_id"] == str(root.id)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest -k responsible_node -v`
Expected: FAIL — field doesn't exist on the response.

- [ ] **Step 3: Implement the LCA helper and wire it into `_out`**

Add a helper function near the top of `backend/app/routes/shifts.py`:

```python
def _lowest_common_ancestor(node_paths: list[list[uuid.UUID]]) -> uuid.UUID | None:
    """Given multiple root-to-node path_ids lists, return the id of the deepest
    common ancestor, or None if there's no overlap (shouldn't happen for quotas
    all rooted under the same eligible scope, but handled defensively)."""
    if not node_paths:
        return None
    common: uuid.UUID | None = None
    for depth in range(min(len(p) for p in node_paths)):
        candidates = {p[depth] for p in node_paths}
        if len(candidates) == 1:
            common = next(iter(candidates))
        else:
            break
    return common
```

In `_out` (or wherever `ShiftOut` is constructed for `get_shift`/`create_shift`), add a `responsible_node_id: uuid.UUID | None` field to `ShiftOut`, computed from the current `node_quotas` list:

```python
    quota_node_ids = [q.hierarchy_node_id for q in node_quotas] if node_quotas else []
    responsible_node_id = None
    if quota_node_ids:
        nodes_by_id = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
        paths = [nodes_by_id[nid].path_ids for nid in quota_node_ids if nid in nodes_by_id]
        responsible_node_id = _lowest_common_ancestor(paths)
```

Wire `responsible_node_id=responsible_node_id` into the `ShiftOut(...)` construction, and add the field to the `ShiftOut` Pydantic model. Locate the exact `ShiftOut` class and `_out` function first with `grep -n "class ShiftOut\|def _out" app/routes/shifts.py` and adapt the snippet to its real parameter list rather than assuming a specific signature.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest -k responsible_node -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/shifts.py
git commit -m "feat: compute and expose shift responsible_node_id as lowest common ancestor of quotas"
```

---

### Task 6: Frontend — pre-filled editable quota table on shift create/edit

**Files:**
- Modify: `frontend/src/api/shifts.ts`
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`

- [ ] **Step 1: Add API client functions**

Append to `frontend/src/api/shifts.ts`:

```typescript
export interface SuggestedQuota {
  hierarchy_node_id: string;
  node_name: string;
  count: number;
}

export async function suggestShiftQuotas(shiftId: string): Promise<SuggestedQuota[]> {
  return (await api.get<{ suggestions: SuggestedQuota[] }>(`/shifts/${shiftId}/quotas/suggest`)).data.suggestions;
}
```

Also add `responsible_node_id: string | null` to the existing `Shift`/`ShiftOut` TypeScript interface in this file (`grep -n "interface Shift" src/api/shifts.ts` to find it).

- [ ] **Step 2: Inspect the existing quota-editing UI**

Run: `cd frontend && grep -n "node_quotas\|NodeQuota\|setShiftQuotas\|putShiftQuotas" src/pages/planning/ShiftsManagementPage.tsx`

Identify the exact component/state managing the quota table for a shift, since Task 4 (backend) means quotas already arrive pre-filled from `GET /shifts/{id}` right after creation — the frontend's existing quota table rendering should already show them without any new fetch. Confirm this is true by re-reading the component's data flow before making changes.

- [ ] **Step 3: Add "Recompute quotas" button for existing shifts**

In the shift edit view within `ShiftsManagementPage.tsx`, add a button that calls `suggestShiftQuotas(shiftId)`, replaces the in-memory (unsaved) quota table state with the returned suggestions, and requires the user to explicitly save (existing `PUT /{shift_id}/quotas` call) — do not auto-save on click.

```tsx
async function handleRecomputeQuotas(shiftId: string) {
  const suggestions = await suggestShiftQuotas(shiftId);
  setQuotaRows(suggestions.map((s) => ({ hierarchy_node_id: s.hierarchy_node_id, node_name: s.node_name, count: s.count })));
}
```

(Adapt `setQuotaRows` to whatever the existing state setter is actually named, per Step 2's inspection.)

- [ ] **Step 4: Show the responsible node**

In the shift detail/list view, render `shift.responsible_node_id` resolved to a node name (using whatever hierarchy-name lookup the page already has available, e.g. a `nodesById` map) as a read-only "אחראי משמרת" label.

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/shifts.ts frontend/src/pages/planning/ShiftsManagementPage.tsx
git commit -m "feat: add recompute-quotas action and responsible-node display to shift UI"
```

---

### Task 7: Frontend — "Re-run assignment algorithm" action for a shift

**Files:**
- Modify: `frontend/src/api/algorithm.ts`
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`

- [ ] **Step 1: Check the existing job-creation client function**

Run: `cd frontend && grep -n "createJob\|shift_ids" src/api/algorithm.ts`

Confirm it already accepts a `shift_ids` parameter (per the backend's `CreateJobRequest.shift_ids` seen during backend investigation); if the exported function's signature doesn't expose `shift_ids` yet, add it.

- [ ] **Step 2: Add the button**

In the shift detail view (near the "Recompute quotas" button from Task 6), add a "הרץ אלגוריתם מחדש למשמרת זו" button that calls the existing job-creation function scoped to `shift_ids: [shift.id]`, reusing whatever mode/settings defaults the page's existing full-run button already uses (inspect that call site first: `grep -n "createJob(" src/pages/planning/ShiftsManagementPage.tsx src/pages/AlgorithmPage.tsx`).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/algorithm.ts frontend/src/pages/planning/ShiftsManagementPage.tsx
git commit -m "feat: add per-shift re-run-algorithm action reusing existing job creation"
```

---

### Task 8: Full verification pass

- [ ] **Step 1: Run backend tests for touched areas**

Run: `cd backend && pytest -q app/services/tests/test_shift_potential_split.py -v`
Expected: PASS.

Run: `cd backend && pytest -k shifts -v`
Expected: PASS (no regressions in shift creation/quota routes).

- [ ] **Step 2: Run the full backend fast suite**

Run: `cd backend && pytest -q`
Expected: All PASS.

- [ ] **Step 3: Run frontend checks**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: no errors.

- [ ] **Step 4: Manual smoke check**

Start the dev stack. Create a shift scoped to a hierarchy root with at least two children that have soldiers in different counts; confirm the quota table is pre-filled proportionally and sums to `required_count`. Edit an existing shift, click "Recompute quotas," confirm the table refreshes without auto-saving. Click "Re-run assignment algorithm" and confirm a job is created scoped to that shift.

- [ ] **Step 5: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "fix: address issues found during shift-potential-split verification pass"
```
