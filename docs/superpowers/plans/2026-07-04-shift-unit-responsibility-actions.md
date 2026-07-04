# Shift Unit-Responsibility Bulk Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three bulk actions to the Shift Schedule page's multi-select bar — set responsible unit(s), two-level potential-weighted quota split, and auto-assign unit responsibility — each behind a preview modal, with the existing general auto-assign (soldiers→shifts) button promoted to the large, primary position above them.

**Architecture:** "Responsible units" are a shift's existing `eligible_node_ids` (no new DB column). Backend gains: potential-weighted (not headcount-weighted) quota splitting, a two-level split (across responsible units, then across each one's children), and a fair-share auto-assign scorer that reuses `compute_node_effort_potential` from the effort-gap plan. Three new frontend modal components call these via three new API functions and apply results via the existing `updateShift`/`setShiftQuotas` calls.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript (frontend), pytest (backend tests).

Spec: [docs/superpowers/specs/2026-07-04-shift-responsibility-and-effort-gap-design.md](../specs/2026-07-04-shift-responsibility-and-effort-gap-design.md) — "Feature 1" section.

**Dependency:** Task 4 of this plan consumes `compute_node_effort_potential` from [docs/superpowers/plans/2026-07-04-effort-potential-gap-columns.md](2026-07-04-effort-potential-gap-columns.md) Task 2 (`backend/app/services/node_effort_potential.py`). That task must be merged before starting Task 4 here; Tasks 1-3 and 6-10 have no such dependency and can proceed independently.

## Global Constraints

- Backend area marker: new files under `backend/app/services/tests/` (e.g. `test_shift_quotas.py`, `test_shift_responsibility.py`) get the `duty` marker automatically (per `pyproject.toml`: "duty: assignments, shifts, swaps, constraints, exemptions, gimelim, hakpaza, duty config").
- `compute_potential_split`'s existing weight field is currently raw headcount; after Task 1 it must be `final_potential` (can legitimately be 0 for units with no eligible duty types configured — existing tests must be updated to set up a permissive `DutyType` so weights are nonzero, matching the pattern in `backend/app/services/tests/test_potential.py`).
- All three new bulk actions must go through a preview step before mutating anything (per the approved design) — no action may skip straight to apply.
- `DutyShiftNodeQuota.count` has a DB check constraint `count >= 1` (`backend/app/db/models.py:410`) — any split step that would produce a 0-count leaf entry must be filtered out before calling `setShiftQuotas`, exactly as `ShiftFormModal.tsx:168` already does (`.filter((e) => e.count > 0)`).

---

### Task 1: Weight `compute_potential_split` by `final_potential`, not headcount

**Files:**
- Modify: `backend/app/services/shift_quotas.py:81-135`
- Modify (update existing tests to match new weighting): `backend/app/services/tests/test_shift_quotas.py:101-181`

**Interfaces:**
- Produces: `compute_potential_split(session, *, parent_node_id, required_count, reference_date: date | None = None) -> list[dict]` — same return shape as today (`hierarchy_node_id`, `node_name`, `count`, `weight`), but `weight` is now each child's `final_potential` (from `compute_potential`) instead of raw active-soldier count. `reference_date` defaults to `date.today()` if omitted, so existing callers (the route in Task 3, and `ShiftFormModal.tsx`'s existing single-shift split button) keep working unchanged.

- [ ] **Step 1: Update the existing tests to expect potential-based weights**

Replace `backend/app/services/tests/test_shift_quotas.py:101-181` (the six `compute_potential_split` tests) with versions that also create a permissive `DutyType` so `final_potential` is nonzero and equals headcount for simple eligible soldiers (mirroring `test_potential.py`'s pattern of `DutyType(name=..., score_per_day=Decimal("1.0"), requirements={})`):

```python
from app.db.models import DutyType


def _make_permissive_duty_type(session, name: str):
    dt = DutyType(name=name, score_per_day=Decimal("1.00"), requirements={})
    session.add(dt)
    session.flush()
    return dt


def test_compute_potential_split_even_weights(admin_session):
    _make_permissive_duty_type(admin_session, "dt_pot_even")
    parent = create_node(admin_session, level="unit", name="pot_even_parent")
    child_a = create_node(admin_session, level="branch", name="pot_even_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="pot_even_b", parent=parent)
    create_soldier(admin_session, personal_number="pe_a1", hierarchy_node_id=child_a.id)
    create_soldier(admin_session, personal_number="pe_a2", hierarchy_node_id=child_a.id)
    create_soldier(admin_session, personal_number="pe_b1", hierarchy_node_id=child_b.id)
    create_soldier(admin_session, personal_number="pe_b2", hierarchy_node_id=child_b.id)

    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=10)

    by_name = {r["node_name"]: r for r in result}
    assert by_name["pot_even_a"]["count"] == 5
    assert by_name["pot_even_b"]["count"] == 5
    assert by_name["pot_even_a"]["weight"] == 2
    assert by_name["pot_even_b"]["weight"] == 2
    assert sum(r["count"] for r in result) == 10


def test_compute_potential_split_uneven_weights_sums_exactly(admin_session):
    _make_permissive_duty_type(admin_session, "dt_pot_uneven")
    parent = create_node(admin_session, level="unit", name="pot_uneven_parent")
    child_a = create_node(admin_session, level="branch", name="pot_uneven_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="pot_uneven_b", parent=parent)
    child_c = create_node(admin_session, level="branch", name="pot_uneven_c", parent=parent)
    for i in range(3):
        create_soldier(admin_session, personal_number=f"pu_a{i}", hierarchy_node_id=child_a.id)
    for i in range(2):
        create_soldier(admin_session, personal_number=f"pu_b{i}", hierarchy_node_id=child_b.id)
    create_soldier(admin_session, personal_number="pu_c0", hierarchy_node_id=child_c.id)

    # weights 3:2:1 (total 6), required_count=10 -> raw shares 5.0:3.33:1.67
    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=10)

    assert sum(r["count"] for r in result) == 10
    by_name = {r["node_name"]: r["count"] for r in result}
    assert by_name["pot_uneven_a"] == 5
    assert by_name["pot_uneven_b"] == 3
    assert by_name["pot_uneven_c"] == 2


def test_compute_potential_split_zero_weight_child_gets_zero_count(admin_session):
    _make_permissive_duty_type(admin_session, "dt_pot_zero")
    parent = create_node(admin_session, level="unit", name="pot_zero_parent")
    child_a = create_node(admin_session, level="branch", name="pot_zero_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="pot_zero_b", parent=parent)
    create_soldier(admin_session, personal_number="pz_a1", hierarchy_node_id=child_a.id)

    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=4)

    by_name = {r["node_name"]: r for r in result}
    assert by_name["pot_zero_a"]["count"] == 4
    assert by_name["pot_zero_b"]["count"] == 0
    assert by_name["pot_zero_b"]["weight"] == 0


def test_compute_potential_split_all_zero_weight_falls_back_to_even_split(admin_session):
    # No DutyType created at all -> every child has final_potential == 0.
    parent = create_node(admin_session, level="unit", name="pot_allzero_parent")
    create_node(admin_session, level="branch", name="pot_allzero_a", parent=parent)
    create_node(admin_session, level="branch", name="pot_allzero_b", parent=parent)
    create_node(admin_session, level="branch", name="pot_allzero_c", parent=parent)

    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=10)

    assert sum(r["count"] for r in result) == 10
    counts = sorted(r["count"] for r in result)
    assert counts == [3, 3, 4]


def test_compute_potential_split_no_children_raises(admin_session):
    leaf = create_node(admin_session, level="team", name="pot_leaf")

    with pytest.raises(ShiftQuotaError, match="no direct children"):
        compute_potential_split(admin_session, parent_node_id=leaf.id, required_count=5)


def test_compute_potential_split_invalid_required_count_raises(admin_session):
    parent = create_node(admin_session, level="unit", name="pot_invalid_parent")
    create_node(admin_session, level="branch", name="pot_invalid_a", parent=parent)

    with pytest.raises(ShiftQuotaError, match="required_count must be"):
        compute_potential_split(admin_session, parent_node_id=parent.id, required_count=0)
```

- [ ] **Step 2: Run tests to verify they fail against the current (headcount-based) implementation**

Run: `pytest backend/app/services/tests/test_shift_quotas.py -k compute_potential_split -v`
Expected: `test_compute_potential_split_zero_weight_child_gets_zero_count` and the "even"/"uneven" tests still numerically pass by coincidence (headcount happens to equal potential here), but this step exists to confirm the suite runs; the real signal comes after Step 3 changes production code — re-run after Step 3 to confirm intent is now enforced by `final_potential`, not headcount. (If they already pass identically because headcount==potential in these fixtures, that's expected — the meaningful regression check is Step 4.)

- [ ] **Step 3: Update `compute_potential_split`**

In `backend/app/services/shift_quotas.py`, add the import and change the weighting:

```python
from datetime import date

from app.services.potential import compute_potential
```

Replace the `weights = [...]` block (lines 102-110) with:

```python
def compute_potential_split(
    session: Session, *, parent_node_id: uuid.UUID, required_count: int, reference_date: date | None = None
) -> list[dict]:
    """Proportionally split `required_count` across `parent_node_id`'s direct
    children, weighted by each child's final_potential (eligible-soldier count
    adjusted for exemptions/modifiers). Uses the largest-remainder method so
    counts always sum to exactly `required_count`. Falls back to an even split
    if every child has zero weight (otherwise the split would be all-zero and
    useless)."""
    if required_count < 1:
        raise ShiftQuotaError("required_count must be >= 1")

    children = list(
        session.execute(
            select(HierarchyNode)
            .where(HierarchyNode.parent_id == parent_node_id)
            .order_by(HierarchyNode.name)
        ).scalars().all()
    )
    if not children:
        raise ShiftQuotaError("parent node has no direct children")

    ref = reference_date or date.today()
    weights = [
        max(compute_potential(session, node_id=child.id, reference_date=ref).final_potential, 0)
        for child in children
    ]
```

(Leave the rest of the function — the largest-remainder distribution logic and return statement — unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_shift_quotas.py -k compute_potential_split -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full shift_quotas test file to check for regressions**

Run: `pytest backend/app/services/tests/test_shift_quotas.py -v`
Expected: PASS (all tests, including the `set_shift_quotas` ones which are unaffected by this change)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/shift_quotas.py backend/app/services/tests/test_shift_quotas.py
git commit -m "fix: weight compute_potential_split by final_potential instead of raw headcount"
```

---

### Task 2: Two-level split — `compute_potential_split_multi` + `compute_two_level_split`

**Files:**
- Modify: `backend/app/services/shift_quotas.py` (add two new functions)
- Test: `backend/app/services/tests/test_shift_quotas.py` (append)

**Interfaces:**
- Consumes: `compute_potential_split` (Task 1), `compute_potential` (`backend/app/services/potential.py:105`).
- Produces:
  ```python
  def compute_potential_split_multi(
      session: Session, *, node_ids: list[uuid.UUID], required_count: int, reference_date: date | None = None
  ) -> list[dict]:  # [{"hierarchy_node_id", "node_name", "count", "weight"}, ...] — same shape as compute_potential_split, but node_ids need not share a parent
  ```
  ```python
  def compute_two_level_split(
      session: Session, *, responsible_node_ids: list[uuid.UUID], required_count: int, reference_date: date | None = None
  ) -> list[dict]:  # [{"hierarchy_node_id", "node_name", "count", "weight", "parent_responsible_node_id"}, ...]
  ```
  Task 3's route consumes `compute_two_level_split` directly.

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/services/tests/test_shift_quotas.py`:

```python
from app.services.shift_quotas import compute_potential_split_multi, compute_two_level_split


def test_compute_potential_split_multi_arbitrary_nodes(admin_session):
    _make_permissive_duty_type(admin_session, "dt_multi")
    unrelated_parent_a = create_node(admin_session, level="unit", name="multi_parent_a")
    unrelated_parent_b = create_node(admin_session, level="unit", name="multi_parent_b")
    node_a = create_node(admin_session, level="branch", name="multi_a", parent=unrelated_parent_a)
    node_b = create_node(admin_session, level="branch", name="multi_b", parent=unrelated_parent_b)
    for i in range(3):
        create_soldier(admin_session, personal_number=f"multi_a{i}", hierarchy_node_id=node_a.id)
    create_soldier(admin_session, personal_number="multi_b0", hierarchy_node_id=node_b.id)

    result = compute_potential_split_multi(
        admin_session, node_ids=[node_a.id, node_b.id], required_count=8
    )

    by_name = {r["node_name"]: r["count"] for r in result}
    assert by_name["multi_a"] == 6
    assert by_name["multi_b"] == 2
    assert sum(r["count"] for r in result) == 8


def test_compute_two_level_split_splits_across_units_then_children(admin_session):
    _make_permissive_duty_type(admin_session, "dt_two_level")
    unit_a = create_node(admin_session, level="unit", name="two_level_unit_a")
    unit_b = create_node(admin_session, level="unit", name="two_level_unit_b")
    child_a1 = create_node(admin_session, level="branch", name="two_level_a1", parent=unit_a)
    child_a2 = create_node(admin_session, level="branch", name="two_level_a2", parent=unit_a)
    child_b1 = create_node(admin_session, level="branch", name="two_level_b1", parent=unit_b)
    # unit_a: 2 soldiers each under a1/a2 (potential 4 total); unit_b: 4 soldiers under b1 (potential 4 total)
    for i in range(2):
        create_soldier(admin_session, personal_number=f"tl_a1_{i}", hierarchy_node_id=child_a1.id)
        create_soldier(admin_session, personal_number=f"tl_a2_{i}", hierarchy_node_id=child_a2.id)
    for i in range(4):
        create_soldier(admin_session, personal_number=f"tl_b1_{i}", hierarchy_node_id=child_b1.id)

    result = compute_two_level_split(
        admin_session, responsible_node_ids=[unit_a.id, unit_b.id], required_count=8
    )

    # Step A: unit_a and unit_b each get 4 (equal potential 4:4).
    # Step B: unit_a's 4 split evenly 2:2 across a1/a2; unit_b's 4 all go to its only child b1.
    by_name = {r["node_name"]: r["count"] for r in result}
    assert by_name["two_level_a1"] == 2
    assert by_name["two_level_a2"] == 2
    assert by_name["two_level_b1"] == 4
    assert sum(r["count"] for r in result) == 8
    parent_map = {r["node_name"]: r["parent_responsible_node_id"] for r in result}
    assert parent_map["two_level_a1"] == unit_a.id
    assert parent_map["two_level_b1"] == unit_b.id


def test_compute_two_level_split_leaf_responsible_unit_with_no_children(admin_session):
    _make_permissive_duty_type(admin_session, "dt_two_level_leaf")
    leaf_unit = create_node(admin_session, level="branch", name="two_level_leaf")
    create_soldier(admin_session, personal_number="tl_leaf_0", hierarchy_node_id=leaf_unit.id)

    result = compute_two_level_split(
        admin_session, responsible_node_ids=[leaf_unit.id], required_count=3
    )

    # No children under leaf_unit -> its whole step-A share stays on itself.
    assert len(result) == 1
    assert result[0]["node_name"] == "two_level_leaf"
    assert result[0]["count"] == 3
    assert result[0]["parent_responsible_node_id"] == leaf_unit.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_shift_quotas.py -k "split_multi or two_level" -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

Append to `backend/app/services/shift_quotas.py`:

```python
def _largest_remainder_shares(required_count: int, weights: list[int]) -> list[int]:
    n = len(weights)
    total_weight = sum(weights)
    if total_weight == 0:
        base, extra = divmod(required_count, n)
        return [base + (1 if i < extra else 0) for i in range(n)]
    raw_shares = [required_count * w / total_weight for w in weights]
    shares = [int(r) for r in raw_shares]
    remainder = required_count - sum(shares)
    order_by_fraction = sorted(range(n), key=lambda i: raw_shares[i] - shares[i], reverse=True)
    for i in order_by_fraction[:remainder]:
        shares[i] += 1
    return shares


def compute_potential_split_multi(
    session: Session, *, node_ids: list[uuid.UUID], required_count: int, reference_date: date | None = None
) -> list[dict]:
    """Like compute_potential_split, but splits across an arbitrary list of
    nodes (not necessarily siblings under one parent), weighted by each
    node's own final_potential."""
    if required_count < 1:
        raise ShiftQuotaError("required_count must be >= 1")
    if not node_ids:
        raise ShiftQuotaError("node_ids must not be empty")

    nodes = [session.get(HierarchyNode, nid) for nid in node_ids]
    for nid, node in zip(node_ids, nodes):
        if node is None:
            raise ShiftQuotaError(f"hierarchy node {nid} not found")

    ref = reference_date or date.today()
    weights = [max(compute_potential(session, node_id=n.id, reference_date=ref).final_potential, 0) for n in nodes]
    shares = _largest_remainder_shares(required_count, weights)

    return [
        {"hierarchy_node_id": n.id, "node_name": n.name, "count": shares[i], "weight": weights[i]}
        for i, n in enumerate(nodes)
    ]


def compute_two_level_split(
    session: Session, *, responsible_node_ids: list[uuid.UUID], required_count: int, reference_date: date | None = None
) -> list[dict]:
    """Step A: split required_count across responsible_node_ids themselves,
    weighted by potential. Step B: split each responsible unit's share across
    its own direct children, weighted by potential. Returns a flat list of
    leaf-level entries (grandchildren, or the responsible unit itself if it
    has no children), each tagged with which responsible unit it came from."""
    ref = reference_date or date.today()
    step_a = compute_potential_split_multi(
        session, node_ids=responsible_node_ids, required_count=required_count, reference_date=ref
    )

    result: list[dict] = []
    for entry in step_a:
        if entry["count"] == 0:
            continue
        try:
            step_b = compute_potential_split(
                session, parent_node_id=entry["hierarchy_node_id"], required_count=entry["count"], reference_date=ref
            )
        except ShiftQuotaError:
            # No children under this responsible unit -> its whole share stays on itself.
            result.append({**entry, "parent_responsible_node_id": entry["hierarchy_node_id"]})
            continue
        for child_entry in step_b:
            result.append({**child_entry, "parent_responsible_node_id": entry["hierarchy_node_id"]})
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_shift_quotas.py -k "split_multi or two_level" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shift_quotas.py backend/app/services/tests/test_shift_quotas.py
git commit -m "feat: add compute_potential_split_multi and compute_two_level_split for multi-unit quota splitting"
```

---

### Task 3: `GET /shifts/{shift_id}/quota-split-preview-two-level` route

**Files:**
- Modify: `backend/app/routes/shifts.py` (add near existing `quota_split_preview`, `backend/app/routes/shifts.py:166-193`)
- Test: `backend/tests/integration/test_shift_quotas_api.py` (append)

**Interfaces:**
- Consumes: `compute_two_level_split` (Task 2).
- Produces: `GET /shifts/{shift_id}/quota-split-preview-two-level` → `{"entries": [{"hierarchy_node_id", "node_name", "count", "weight", "parent_responsible_node_id"}, ...]}`. Frontend `getTwoLevelSplitPreview()` (Task 6) consumes this shape.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/integration/test_shift_quotas_api.py` (match whatever client/session fixture names the existing tests in that file use — inspect the top of the file first):

```python
def test_two_level_split_preview_endpoint(admin_client, admin_session):
    from app.db.models import DutyType, DutyLocation
    from app.services.duty_config import create_duty_type
    from app.services.hierarchy import create_node
    from app.services.shifts import create_shift
    from tests.helpers import create_soldier
    from datetime import date
    from decimal import Decimal

    create_duty_type(admin_session, name="dt_two_level_api", score_per_day=Decimal("1.00"))
    unit = create_node(admin_session, level="unit", name="two_level_api_unit")
    child = create_node(admin_session, level="branch", name="two_level_api_child", parent=unit)
    create_soldier(admin_session, personal_number="tl_api_0", hierarchy_node_id=child.id)
    loc = DutyLocation(name="loc_two_level_api")
    admin_session.add(loc)
    admin_session.flush()
    dt = admin_session.execute(select(DutyType).where(DutyType.name == "dt_two_level_api")).scalar_one()
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        required_count=3, eligible_node_ids=[unit.id],
    )
    admin_session.commit()

    resp = admin_client.get(f"/shifts/{shift.id}/quota-split-preview-two-level")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["node_name"] == "two_level_api_child"
    assert entries[0]["count"] == 3
    assert entries[0]["parent_responsible_node_id"] == str(unit.id)


def test_two_level_split_preview_requires_eligible_node_ids(admin_client, admin_session):
    from app.db.models import DutyType, DutyLocation
    from app.services.duty_config import create_duty_type
    from app.services.shifts import create_shift
    from datetime import date
    from decimal import Decimal

    create_duty_type(admin_session, name="dt_two_level_api_none", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="loc_two_level_api_none")
    admin_session.add(loc)
    admin_session.flush()
    dt = admin_session.execute(select(DutyType).where(DutyType.name == "dt_two_level_api_none")).scalar_one()
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        required_count=3,
    )
    admin_session.commit()

    resp = admin_client.get(f"/shifts/{shift.id}/quota-split-preview-two-level")
    assert resp.status_code == 400
```

(`select` must be imported from `sqlalchemy` at the top of the test file if not already present — check first.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_shift_quotas_api.py -k two_level -v`
Expected: FAIL with 404 (route doesn't exist)

- [ ] **Step 3: Implement the route**

In `backend/app/routes/shifts.py`, add the import:

```python
from app.services.shift_quotas import ShiftQuotaError, compute_potential_split, compute_two_level_split, get_shift_quotas, set_shift_quotas
```

Add after the existing `quota_split_preview` handler (after line 193):

```python
class TwoLevelSplitEntry(BaseModel):
    hierarchy_node_id: uuid.UUID
    node_name: str
    count: int
    weight: int
    parent_responsible_node_id: uuid.UUID


class TwoLevelSplitPreviewOut(BaseModel):
    entries: list[TwoLevelSplitEntry]


@router.get("/{shift_id}/quota-split-preview-two-level", response_model=TwoLevelSplitPreviewOut)
def quota_split_preview_two_level(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> TwoLevelSplitPreviewOut:
    shift = _load(session, shift_id)
    if not shift.eligible_node_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift_has_no_responsible_units")
    try:
        entries = compute_two_level_split(
            session, responsible_node_ids=list(shift.eligible_node_ids), required_count=shift.required_count
        )
    except ShiftQuotaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TwoLevelSplitPreviewOut(entries=[TwoLevelSplitEntry(**e) for e in entries])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/integration/test_shift_quotas_api.py -k two_level -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/shifts.py backend/tests/integration/test_shift_quotas_api.py
git commit -m "feat: add GET /shifts/{shift_id}/quota-split-preview-two-level endpoint"
```

---

### Task 4: `auto_assign_responsibility` scoring service

**Files:**
- Create: `backend/app/services/shift_responsibility.py`
- Test: `backend/app/services/tests/test_shift_responsibility.py`

**Interfaces:**
- Consumes: `compute_node_effort_potential(session, *, reference_date) -> dict[uuid.UUID, NodeEffortPotential]` (from the effort-gap plan, `backend/app/services/node_effort_potential.py` — **must already exist**; `NodeEffortPotential.final_potential: int` and `.total_effort: float`).
- Produces:
  ```python
  @dataclass
  class ShiftResponsibilityAssignment:
      shift_id: uuid.UUID
      hierarchy_node_id: uuid.UUID
      node_name: str

  def auto_assign_responsibility(
      session: Session, *, shift_ids: list[uuid.UUID], reference_date: date | None = None
  ) -> list[ShiftResponsibilityAssignment]: ...
  ```
  Shifts with no `eligible_node_ids` or whose eligible nodes have no children are silently skipped (no candidates to choose from) — callers (Task 5's route) surface this by simply omitting those shift_ids from the result list.

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_shift_responsibility.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyType
from app.services.duty_config import create_duty_type
from app.services.hierarchy import create_node
from app.services.shift_responsibility import auto_assign_responsibility
from app.services.shifts import create_shift
from tests.helpers import create_soldier


def _make_shift(session, name_suffix: str, *, required_count: int, eligible_node_ids: list, start_date: date):
    dt = create_duty_type(session, name=f"dt_resp_{name_suffix}", score_per_day=Decimal("1.00"), requirements={})
    loc = DutyLocation(name=f"loc_resp_{name_suffix}")
    session.add(loc)
    session.flush()
    shift = create_shift(
        session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start_date, end_date=date(start_date.year, start_date.month, start_date.day + 1),
        required_count=required_count, eligible_node_ids=eligible_node_ids,
    )
    session.flush()
    return shift


def test_picks_candidate_with_higher_potential_and_no_past_effort(admin_session):
    parent = create_node(admin_session, level="unit", name="resp_parent_1")
    strong = create_node(admin_session, level="branch", name="resp_strong", parent=parent)
    weak = create_node(admin_session, level="branch", name="resp_weak", parent=parent)
    for i in range(5):
        create_soldier(admin_session, personal_number=f"resp_strong_{i}", hierarchy_node_id=strong.id)
    create_soldier(admin_session, personal_number="resp_weak_0", hierarchy_node_id=weak.id)
    shift = _make_shift(admin_session, "1", required_count=2, eligible_node_ids=[parent.id], start_date=date(2026, 7, 1))
    admin_session.commit()

    result = auto_assign_responsibility(admin_session, shift_ids=[shift.id], reference_date=date(2026, 7, 1))

    assert len(result) == 1
    assert result[0].shift_id == shift.id
    assert result[0].node_name == "resp_strong"


def test_spreads_load_across_batch_when_candidates_tied(admin_session):
    parent = create_node(admin_session, level="unit", name="resp_parent_2")
    unit_a = create_node(admin_session, level="branch", name="resp_tied_a", parent=parent)
    unit_b = create_node(admin_session, level="branch", name="resp_tied_b", parent=parent)
    for i in range(3):
        create_soldier(admin_session, personal_number=f"resp_tied_a_{i}", hierarchy_node_id=unit_a.id)
        create_soldier(admin_session, personal_number=f"resp_tied_b_{i}", hierarchy_node_id=unit_b.id)
    shift_1 = _make_shift(admin_session, "2a", required_count=2, eligible_node_ids=[parent.id], start_date=date(2026, 7, 1))
    shift_2 = _make_shift(admin_session, "2b", required_count=2, eligible_node_ids=[parent.id], start_date=date(2026, 7, 2))
    admin_session.commit()

    result = auto_assign_responsibility(
        admin_session, shift_ids=[shift_1.id, shift_2.id], reference_date=date(2026, 7, 1)
    )

    by_shift = {r.shift_id: r.node_name for r in result}
    # Tied potential -> the first shift (processed by start_date order) picks either
    # unit deterministically; the second shift must pick the OTHER unit, since the
    # first unit's running_batch_load now makes it less attractive.
    assert by_shift[shift_1.id] != by_shift[shift_2.id]


def test_skips_shifts_with_no_eligible_node_ids(admin_session):
    shift = _make_shift(admin_session, "3", required_count=1, eligible_node_ids=None, start_date=date(2026, 7, 1))
    admin_session.commit()

    result = auto_assign_responsibility(admin_session, shift_ids=[shift.id], reference_date=date(2026, 7, 1))

    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_shift_responsibility.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.shift_responsibility'`

- [ ] **Step 3: Implement**

```python
# backend/app/services/shift_responsibility.py
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyShift, HierarchyNode
from app.services.node_effort_potential import compute_node_effort_potential


@dataclass
class ShiftResponsibilityAssignment:
    shift_id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    node_name: str


def auto_assign_responsibility(
    session: Session, *, shift_ids: list[uuid.UUID], reference_date: date | None = None
) -> list[ShiftResponsibilityAssignment]:
    """For each shift (processed in start_date order), pick exactly one
    candidate unit = union of direct children of the shift's eligible_node_ids,
    scored by final_potential - (total_effort + running_batch_load), where
    running_batch_load accumulates required_count for whichever unit was
    picked by earlier shifts in this same batch (fair-share within the batch).
    Shifts with no eligible_node_ids, or whose eligible nodes have no direct
    children, are omitted from the result."""
    ref = reference_date or date.today()
    shifts = list(
        session.execute(select(DutyShift).where(DutyShift.id.in_(shift_ids))).scalars().all()
    )
    ordered_shifts = sorted(shifts, key=lambda s: (s.start_date, s.id))

    effort_potential = compute_node_effort_potential(session, reference_date=ref)
    running_batch_load: dict[uuid.UUID, float] = defaultdict(float)

    results: list[ShiftResponsibilityAssignment] = []
    for shift in ordered_shifts:
        if not shift.eligible_node_ids:
            continue
        candidate_ids: set[uuid.UUID] = set()
        for parent_id in shift.eligible_node_ids:
            children = session.execute(
                select(HierarchyNode).where(HierarchyNode.parent_id == parent_id)
            ).scalars().all()
            candidate_ids.update(c.id for c in children)
        if not candidate_ids:
            continue

        def score(node_id: uuid.UUID) -> float:
            ep = effort_potential.get(node_id)
            potential = ep.final_potential if ep else 0
            past_effort = ep.total_effort if ep else 0.0
            return potential - (past_effort + running_batch_load[node_id])

        best_id = max(candidate_ids, key=lambda nid: (score(nid), str(nid)))
        best_node = session.get(HierarchyNode, best_id)
        results.append(
            ShiftResponsibilityAssignment(shift_id=shift.id, hierarchy_node_id=best_id, node_name=best_node.name)
        )
        running_batch_load[best_id] += shift.required_count
    return results
```

(The `(score(nid), str(nid))` tiebreak key makes ties deterministic rather than dependent on Python `set` iteration order — necessary for `test_skips_shifts_with_no_eligible_node_ids`'s sibling test to reliably assert the two shifts diverge.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_shift_responsibility.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shift_responsibility.py backend/app/services/tests/test_shift_responsibility.py
git commit -m "feat: add auto_assign_responsibility (potential-vs-effort fair-share unit scoring)"
```

---

### Task 5: `POST /shifts/auto-assign-responsibility/preview` route

**Files:**
- Modify: `backend/app/routes/shifts.py`
- Test: `backend/tests/integration/test_shift_quotas_api.py` (append) — or a new `test_shift_responsibility_api.py` if that fits the existing integration test file's scope better; match this project's existing convention of one integration test file per route module vs. per feature (check `backend/tests/integration/` listing first).

**Interfaces:**
- Consumes: `auto_assign_responsibility` (Task 4).
- Produces: `POST /shifts/auto-assign-responsibility/preview` with body `{"shift_ids": ["...", ...]}` → `{"assignments": [{"shift_id", "hierarchy_node_id", "node_name"}, ...]}`. Frontend `getAutoAssignResponsibilityPreview()` (Task 6) consumes this shape. This is preview-only — applying happens via existing `PATCH /shifts/{shift_id}` calls from the frontend (Task 9), no new "apply" endpoint needed.

- [ ] **Step 1: Write the failing test**

```python
def test_auto_assign_responsibility_preview_endpoint(admin_client, admin_session):
    from app.db.models import DutyType, DutyLocation
    from app.services.duty_config import create_duty_type
    from app.services.hierarchy import create_node
    from app.services.shifts import create_shift
    from tests.helpers import create_soldier
    from datetime import date
    from decimal import Decimal

    parent = create_node(admin_session, level="unit", name="resp_api_parent")
    strong = create_node(admin_session, level="branch", name="resp_api_strong", parent=parent)
    create_node(admin_session, level="branch", name="resp_api_weak", parent=parent)
    for i in range(4):
        create_soldier(admin_session, personal_number=f"resp_api_{i}", hierarchy_node_id=strong.id)
    create_duty_type(admin_session, name="dt_resp_api", score_per_day=Decimal("1.00"), requirements={})
    loc = DutyLocation(name="loc_resp_api")
    admin_session.add(loc)
    admin_session.flush()
    dt = admin_session.execute(select(DutyType).where(DutyType.name == "dt_resp_api")).scalar_one()
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 2),
        required_count=2, eligible_node_ids=[parent.id],
    )
    admin_session.commit()

    resp = admin_client.post("/shifts/auto-assign-responsibility/preview", json={"shift_ids": [str(shift.id)]})
    assert resp.status_code == 200
    assignments = resp.json()["assignments"]
    assert len(assignments) == 1
    assert assignments[0]["shift_id"] == str(shift.id)
    assert assignments[0]["node_name"] == "resp_api_strong"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/integration/test_shift_quotas_api.py::test_auto_assign_responsibility_preview_endpoint -v`
Expected: FAIL with 404

- [ ] **Step 3: Implement the route**

In `backend/app/routes/shifts.py`, add the import:

```python
from app.services.shift_responsibility import auto_assign_responsibility
```

Add near the other shift-level routes:

```python
class AutoAssignResponsibilityRequest(BaseModel):
    shift_ids: list[uuid.UUID]


class ResponsibilityAssignmentOut(BaseModel):
    shift_id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    node_name: str


class AutoAssignResponsibilityPreviewOut(BaseModel):
    assignments: list[ResponsibilityAssignmentOut]


@router.post("/auto-assign-responsibility/preview", response_model=AutoAssignResponsibilityPreviewOut)
def auto_assign_responsibility_preview(
    body: AutoAssignResponsibilityRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> AutoAssignResponsibilityPreviewOut:
    results = auto_assign_responsibility(session, shift_ids=body.shift_ids)
    return AutoAssignResponsibilityPreviewOut(
        assignments=[
            ResponsibilityAssignmentOut(shift_id=r.shift_id, hierarchy_node_id=r.hierarchy_node_id, node_name=r.node_name)
            for r in results
        ]
    )
```

Place this route **before** the `@router.get("/{shift_id}")` handler (`backend/app/routes/shifts.py:225`) if FastAPI path-matching order matters here — check whether `/shifts/auto-assign-responsibility/preview` would otherwise be shadowed by `/shifts/{shift_id}`. Since this is a `POST` and `get_shift` is a `GET`, there's no conflict, but place it near the other `POST`/quota routes for readability regardless.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/integration/test_shift_quotas_api.py::test_auto_assign_responsibility_preview_endpoint -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/shifts.py backend/tests/integration/test_shift_quotas_api.py
git commit -m "feat: add POST /shifts/auto-assign-responsibility/preview endpoint"
```

---

### Task 6: Frontend API client additions

**Files:**
- Modify: `frontend/src/api/shifts.ts`

**Interfaces:**
- Produces:
  ```ts
  export interface TwoLevelSplitEntry { hierarchy_node_id: string; node_name: string; count: number; weight: number; parent_responsible_node_id: string; }
  export async function getTwoLevelSplitPreview(shiftId: string): Promise<TwoLevelSplitEntry[]>;
  export interface ResponsibilityAssignment { shift_id: string; hierarchy_node_id: string; node_name: string; }
  export async function getAutoAssignResponsibilityPreview(shiftIds: string[]): Promise<ResponsibilityAssignment[]>;
  ```
  Consumed by Task 8 (split modal) and Task 9 (auto-assign modal).

- [ ] **Step 1: Add the types + functions**

Append to `frontend/src/api/shifts.ts` (after the existing `getQuotaSplitPreview`, around line 93):

```ts
export interface TwoLevelSplitEntry {
  hierarchy_node_id: string;
  node_name: string;
  count: number;
  weight: number;
  parent_responsible_node_id: string;
}

export async function getTwoLevelSplitPreview(shiftId: string): Promise<TwoLevelSplitEntry[]> {
  const r = await api.get<{ entries: TwoLevelSplitEntry[] }>(`/shifts/${shiftId}/quota-split-preview-two-level`);
  return r.data.entries;
}

export interface ResponsibilityAssignment {
  shift_id: string;
  hierarchy_node_id: string;
  node_name: string;
}

export async function getAutoAssignResponsibilityPreview(shiftIds: string[]): Promise<ResponsibilityAssignment[]> {
  const r = await api.post<{ assignments: ResponsibilityAssignment[] }>(
    "/shifts/auto-assign-responsibility/preview",
    { shift_ids: shiftIds }
  );
  return r.data.assignments;
}
```

- [ ] **Step 2: Manually verify against the running backend**

Run the dev stack, then in the browser devtools console on the Shifts page (adjust API base path if different from `/api`):
```js
fetch("/api/shifts/auto-assign-responsibility/preview", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ shift_ids: [] }),
}).then(r => r.json()).then(console.log)
```
Expected: `{"assignments": []}`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/shifts.ts
git commit -m "feat: add getTwoLevelSplitPreview and getAutoAssignResponsibilityPreview API clients"
```

---

### Task 7: "Set responsible unit(s)" modal + wiring

**Files:**
- Create: `frontend/src/components/SetResponsibleUnitsModal.tsx`
- Modify: `frontend/src/pages/ShiftsPage.tsx` (wire the new button into `BulkActionBar`, `ShiftsPage.tsx:254-348`)

**Interfaces:**
- Consumes: `SubHierarchySelector` (`frontend/src/components/SubHierarchySelector.tsx` — `value: string[]`, `onChange: (selected: string[]) => void`), `updateShift(id, {eligible_node_ids}) -> Promise<DutyShift>` (`frontend/src/api/shifts.ts:70-72`, already exists, unchanged).
- Produces: `<SetResponsibleUnitsModal selectedShifts={DutyShift[]} onApplied={() => void} onClose={() => void} />`.

- [ ] **Step 1: Implement the modal component**

```tsx
// frontend/src/components/SetResponsibleUnitsModal.tsx
import { useState } from "react";
import { DutyShift, updateShift } from "../api/shifts";
import SubHierarchySelector from "./SubHierarchySelector";

interface Props {
  selectedShifts: DutyShift[];
  onApplied: () => void;
  onClose: () => void;
}

export default function SetResponsibleUnitsModal({ selectedShifts, onApplied, onClose }: Props) {
  const [nodeIds, setNodeIds] = useState<string[]>([]);
  const [stage, setStage] = useState<"pick" | "preview">("pick");
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleApply() {
    setApplying(true);
    setError(null);
    try {
      await Promise.all(
        selectedShifts.map((s) => updateShift(s.id, { eligible_node_ids: nodeIds }))
      );
      onApplied();
    } catch {
      setError("שגיאה בעדכון המשמרות");
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">קביעת יחידה אחראית</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        {stage === "pick" && (
          <>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">
              בחר יחידה אחת או יותר שתהיה אחראית על {selectedShifts.length} המשמרות שנבחרו.
            </p>
            <SubHierarchySelector value={nodeIds} onChange={setNodeIds} />
            <div className="flex justify-end gap-2 mt-4">
              <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
              <button
                type="button"
                disabled={nodeIds.length === 0}
                onClick={() => setStage("preview")}
                className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                המשך
              </button>
            </div>
          </>
        )}

        {stage === "preview" && (
          <>
            <p className="text-sm text-gray-700 dark:text-gray-200 mb-3">
              {selectedShifts.length} משמרות יעודכנו ליחידות אחראיות: {nodeIds.length} יחידות נבחרו.
            </p>
            {error && <p className="text-red-500 text-xs mb-2">{error}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setStage("pick")} disabled={applying} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50">חזרה</button>
              <button
                type="button"
                onClick={() => { void handleApply(); }}
                disabled={applying}
                className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {applying ? "מעדכן..." : "אישור"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `BulkActionBar`**

In `frontend/src/pages/ShiftsPage.tsx`, add the import:

```tsx
import SetResponsibleUnitsModal from "../components/SetResponsibleUnitsModal";
```

In the `BulkActionBar` function (`ShiftsPage.tsx:254`), add local modal-open state and a new button in a secondary row below the existing button group. Replace the closing `</div>` of the main button row (line 345-346) with a second row:

```tsx
  const [openModal, setOpenModal] = useState<"setResponsible" | null>(null);

  // ...inside the returned JSX, after the existing `<div className="flex flex-wrap gap-2">...</div>` block (lines 304-345):
      <div className="flex flex-wrap gap-2 basis-full">
        <button
          type="button"
          onClick={() => setOpenModal("setResponsible")}
          className="px-3 py-1 rounded text-sm font-medium bg-teal-600 text-white hover:bg-teal-700"
        >
          קביעת יחידה אחראית
        </button>
      </div>
      {openModal === "setResponsible" && (
        <SetResponsibleUnitsModal
          selectedShifts={selectedShifts}
          onApplied={() => { setOpenModal(null); onDone(); }}
          onClose={() => setOpenModal(null)}
        />
      )}
```

(`basis-full` on the new row forces it onto its own line within the existing `flex flex-wrap` container, achieving the "secondary row below the main button" layout without restructuring the whole bar — this is refined further in Task 10 once all three new buttons exist.)

- [ ] **Step 3: Manually verify in the browser**

Start the dev stack, go to the Shifts page, select 2+ shifts, click "קביעת יחידה אחראית", pick units in the tree, click through to the preview, confirm, and verify the shifts' "יחידות זכאיות" column now shows the chosen unit(s).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SetResponsibleUnitsModal.tsx frontend/src/pages/ShiftsPage.tsx
git commit -m "feat: add Set responsible unit(s) bulk action to Shifts page"
```

---

### Task 8: "Split in unit" modal + wiring

**Files:**
- Create: `frontend/src/components/SplitInUnitModal.tsx`
- Modify: `frontend/src/pages/ShiftsPage.tsx`

**Interfaces:**
- Consumes: `getTwoLevelSplitPreview(shiftId)` (Task 6), `setShiftQuotas(shiftId, quotas)` (`frontend/src/api/shifts.ts:78-83`, already exists).
- Produces: `<SplitInUnitModal selectedShifts={DutyShift[]} onApplied={() => void} onClose={() => void} />`.

- [ ] **Step 1: Implement the modal component**

```tsx
// frontend/src/components/SplitInUnitModal.tsx
import { useEffect, useState } from "react";
import { DutyShift, TwoLevelSplitEntry, getTwoLevelSplitPreview, setShiftQuotas } from "../api/shifts";

interface Props {
  selectedShifts: DutyShift[];
  onApplied: () => void;
  onClose: () => void;
}

interface ShiftPreview {
  shift: DutyShift;
  entries: TwoLevelSplitEntry[] | null;
  error: string | null;
}

export default function SplitInUnitModal({ selectedShifts, onApplied, onClose }: Props) {
  const [previews, setPreviews] = useState<ShiftPreview[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all(
      selectedShifts.map(async (shift) => {
        try {
          const entries = await getTwoLevelSplitPreview(shift.id);
          return { shift, entries, error: null } satisfies ShiftPreview;
        } catch {
          return { shift, entries: null, error: "לא ניתן לחשב פיצול (אין יחידה אחראית?)" } satisfies ShiftPreview;
        }
      })
    ).then((results) => { if (!cancelled) { setPreviews(results); setLoading(false); } });
    return () => { cancelled = true; };
  }, [selectedShifts]);

  async function handleApply() {
    setApplying(true);
    setApplyError(null);
    try {
      const applicable = previews.filter((p): p is ShiftPreview & { entries: TwoLevelSplitEntry[] } => !!p.entries);
      await Promise.all(
        applicable.map((p) =>
          setShiftQuotas(
            p.shift.id,
            p.entries.filter((e) => e.count > 0).map((e) => ({ hierarchy_node_id: e.hierarchy_node_id, count: e.count }))
          )
        )
      );
      onApplied();
    } catch {
      setApplyError("שגיאה בהחלת הפיצול");
    } finally {
      setApplying(false);
    }
  }

  const anyApplicable = previews.some((p) => p.entries && p.entries.length > 0);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">פיצול מכסות ביחידה</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        {loading && <p className="text-sm text-gray-500">מחשב פיצול...</p>}

        {!loading && (
          <div className="space-y-4">
            {previews.map((p) => (
              <div key={p.shift.id} className="border dark:border-gray-600 rounded p-2">
                <p className="text-sm font-medium mb-1">{p.shift.start_date} — {p.shift.required_count} נדרשים</p>
                {p.error && <p className="text-xs text-red-500">{p.error}</p>}
                {p.entries && (
                  <table className="w-full text-xs">
                    <tbody>
                      {p.entries.map((e) => (
                        <tr key={e.hierarchy_node_id}>
                          <td className="p-1">{e.node_name}</td>
                          <td className="p-1 text-left">{e.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        )}

        {applyError && <p className="text-red-500 text-xs mt-2">{applyError}</p>}

        <div className="flex justify-end gap-2 mt-4">
          <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
          <button
            type="button"
            disabled={loading || applying || !anyApplicable}
            onClick={() => { void handleApply(); }}
            className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {applying ? "מעדכן..." : "אישור"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `BulkActionBar`**

In `ShiftsPage.tsx`, add the import and a second `openModal` value:

```tsx
import SplitInUnitModal from "../components/SplitInUnitModal";
```

Change `const [openModal, setOpenModal] = useState<"setResponsible" | null>(null);` (from Task 7) to:

```tsx
const [openModal, setOpenModal] = useState<"setResponsible" | "splitInUnit" | null>(null);
```

Add a second button in the same secondary row added in Task 7:

```tsx
<button
  type="button"
  onClick={() => setOpenModal("splitInUnit")}
  className="px-3 py-1 rounded text-sm font-medium bg-teal-600 text-white hover:bg-teal-700"
>
  פיצול בתוך היחידה
</button>
```

And the modal render:

```tsx
{openModal === "splitInUnit" && (
  <SplitInUnitModal
    selectedShifts={selectedShifts}
    onApplied={() => { setOpenModal(null); onDone(); }}
    onClose={() => setOpenModal(null)}
  />
)}
```

- [ ] **Step 3: Manually verify in the browser**

Select shifts that already have a responsible unit with children (from Task 7's test), click "פיצול בתוך היחידה", confirm the per-shift breakdown appears, apply, and check the shift's quotas (edit the shift to see `node_quotas` populated) match the two-level split.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SplitInUnitModal.tsx frontend/src/pages/ShiftsPage.tsx
git commit -m "feat: add Split in unit bulk action to Shifts page"
```

---

### Task 9: "Auto assign unit responsibility" modal + wiring

**Files:**
- Create: `frontend/src/components/AutoAssignResponsibilityModal.tsx`
- Modify: `frontend/src/pages/ShiftsPage.tsx`

**Interfaces:**
- Consumes: `getAutoAssignResponsibilityPreview(shiftIds)` (Task 6), `updateShift(id, {eligible_node_ids})` (existing).
- Produces: `<AutoAssignResponsibilityModal selectedShifts={DutyShift[]} onApplied={() => void} onClose={() => void} />`.

- [ ] **Step 1: Implement the modal component**

```tsx
// frontend/src/components/AutoAssignResponsibilityModal.tsx
import { useEffect, useState } from "react";
import { DutyShift, ResponsibilityAssignment, getAutoAssignResponsibilityPreview, updateShift } from "../api/shifts";

interface Props {
  selectedShifts: DutyShift[];
  onApplied: () => void;
  onClose: () => void;
}

export default function AutoAssignResponsibilityModal({ selectedShifts, onApplied, onClose }: Props) {
  const [assignments, setAssignments] = useState<ResponsibilityAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAutoAssignResponsibilityPreview(selectedShifts.map((s) => s.id))
      .then((result) => { if (!cancelled) { setAssignments(result); setLoading(false); } })
      .catch(() => { if (!cancelled) { setError("שגיאה בחישוב שיבוץ אחריות"); setLoading(false); } });
    return () => { cancelled = true; };
  }, [selectedShifts]);

  const shiftById = new Map(selectedShifts.map((s) => [s.id, s]));

  async function handleApply() {
    setApplying(true);
    setError(null);
    try {
      await Promise.all(
        assignments.map((a) => updateShift(a.shift_id, { eligible_node_ids: [a.hierarchy_node_id] }))
      );
      onApplied();
    } catch {
      setError("שגיאה בהחלת השיבוץ");
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-lg w-full mx-4 max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">שיבוץ אוטומטי של אחריות יחידה</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        {loading && <p className="text-sm text-gray-500">מחשב שיבוץ...</p>}

        {!loading && (
          <table className="w-full text-sm mb-3">
            <thead>
              <tr>
                <th className="text-right p-1 font-medium">משמרת</th>
                <th className="text-right p-1 font-medium">יחידה אחראית מוצעת</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((a) => (
                <tr key={a.shift_id} className="border-t dark:border-gray-600">
                  <td className="p-1">{shiftById.get(a.shift_id)?.start_date ?? a.shift_id.slice(0, 8)}</td>
                  <td className="p-1">{a.node_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {!loading && assignments.length < selectedShifts.length && (
          <p className="text-xs text-gray-500 mb-2">
            {selectedShifts.length - assignments.length} משמרות דולגו (ללא יחידות זכאיות מוגדרות).
          </p>
        )}

        {error && <p className="text-red-500 text-xs mb-2">{error}</p>}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
          <button
            type="button"
            disabled={loading || applying || assignments.length === 0}
            onClick={() => { void handleApply(); }}
            className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {applying ? "מעדכן..." : "אישור"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `BulkActionBar`**

In `ShiftsPage.tsx`, add the import and extend the `openModal` union again:

```tsx
import AutoAssignResponsibilityModal from "../components/AutoAssignResponsibilityModal";
```

```tsx
const [openModal, setOpenModal] = useState<"setResponsible" | "splitInUnit" | "autoAssignResponsibility" | null>(null);
```

Add the third button in the secondary row:

```tsx
<button
  type="button"
  onClick={() => setOpenModal("autoAssignResponsibility")}
  className="px-3 py-1 rounded text-sm font-medium bg-teal-700 text-white hover:bg-teal-800"
>
  שיבוץ אוטומטי של אחריות יחידה
</button>
```

And the modal render:

```tsx
{openModal === "autoAssignResponsibility" && (
  <AutoAssignResponsibilityModal
    selectedShifts={selectedShifts}
    onApplied={() => { setOpenModal(null); onDone(); }}
    onClose={() => setOpenModal(null)}
  />
)}
```

- [ ] **Step 3: Manually verify in the browser**

Select shifts whose eligible units have children with varying headcounts, click "שיבוץ אוטומטי של אחריות יחידה", confirm the preview table shows a plausible unit per shift, apply, and verify each shift's eligible unit (single node) updated accordingly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AutoAssignResponsibilityModal.tsx frontend/src/pages/ShiftsPage.tsx
git commit -m "feat: add Auto assign unit responsibility bulk action to Shifts page"
```

---

### Task 10: Promote the general auto-assign button, finalize bulk-action-bar layout

**Files:**
- Modify: `frontend/src/pages/ShiftsPage.tsx:301-348` (the `BulkActionBar` return JSX)

**Interfaces:**
- No new interfaces — this is a pure layout pass over the JSX assembled incrementally in Tasks 7-9.

- [ ] **Step 1: Restructure the `BulkActionBar` JSX**

Replace the full `return (...)` block of `BulkActionBar` (`ShiftsPage.tsx:301-347`, as it now stands after Tasks 7-9) with:

```tsx
  return (
    <div className="flex flex-col gap-2 px-4 py-2.5 bg-indigo-50 dark:bg-indigo-950 rounded-lg border border-indigo-200 dark:border-indigo-800" dir="rtl">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{selectedShifts.length} נבחרו</span>
        {onAutoAssign && (
          <button
            type="button"
            onClick={onAutoAssign}
            className={`px-5 py-2 rounded text-base font-semibold transition-colors ${
              showAlgorithmPanel
                ? "bg-indigo-600 text-white hover:bg-indigo-700"
                : "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800"
            }`}
          >
            שיבוץ אוטומטי
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setOpenModal("setResponsible")}
          className="px-3 py-1 rounded text-sm font-medium bg-teal-600 text-white hover:bg-teal-700"
        >
          קביעת יחידה אחראית
        </button>
        <button
          type="button"
          onClick={() => setOpenModal("splitInUnit")}
          className="px-3 py-1 rounded text-sm font-medium bg-teal-600 text-white hover:bg-teal-700"
        >
          פיצול בתוך היחידה
        </button>
        <button
          type="button"
          onClick={() => setOpenModal("autoAssignResponsibility")}
          className="px-3 py-1 rounded text-sm font-medium bg-teal-700 text-white hover:bg-teal-800"
        >
          שיבוץ אוטומטי של אחריות יחידה
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => { void handleClear(); }}
          disabled={!!busy}
          className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-40"
        >
          {busy === "clear" && <Spinner />}
          {busy === "clear" ? "מנקה..." : "נקה שיבוצים"}
        </button>
        <button
          type="button"
          onClick={() => { void handleCancel(); }}
          disabled={!!busy || activeCount === 0}
          className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-40"
        >
          {busy === "cancel" && <Spinner />}
          {busy === "cancel" ? "מבטל..." : `בטל משמרות${activeCount < selectedShifts.length ? ` (${activeCount})` : ""}`}
        </button>
        <button
          type="button"
          onClick={() => { void handleDelete(); }}
          disabled={!!busy}
          className="flex items-center gap-1 px-3 py-1 rounded text-sm font-medium bg-red-600 text-white hover:bg-red-700 disabled:opacity-40"
        >
          {busy === "delete" && <Spinner />}
          {busy === "delete" ? "מוחק..." : "מחק משמרות"}
        </button>
      </div>
      {openModal === "setResponsible" && (
        <SetResponsibleUnitsModal
          selectedShifts={selectedShifts}
          onApplied={() => { setOpenModal(null); onDone(); }}
          onClose={() => setOpenModal(null)}
        />
      )}
      {openModal === "splitInUnit" && (
        <SplitInUnitModal
          selectedShifts={selectedShifts}
          onApplied={() => { setOpenModal(null); onDone(); }}
          onClose={() => setOpenModal(null)}
        />
      )}
      {openModal === "autoAssignResponsibility" && (
        <AutoAssignResponsibilityModal
          selectedShifts={selectedShifts}
          onApplied={() => { setOpenModal(null); onDone(); }}
          onClose={() => setOpenModal(null)}
        />
      )}
    </div>
  );
}
```

This produces three visually distinct rows: (1) selection count + the large primary "שיבוץ אוטומטי" button, (2) the three new unit-responsibility buttons, (3) the pre-existing clear/cancel/delete buttons — satisfying "make שיבוץ אוטומטי the main button that is larger and above all the rest."

- [ ] **Step 2: Manually verify in the browser**

Select 2+ shifts on the Shifts page and confirm: the "שיבוץ אוטומטי" button is visually larger and sits alone on the top row; the three new teal buttons form the second row; clear/cancel/delete remain on the third row and still function as before (no regression).

- [ ] **Step 3: Run the frontend test suite and lint**

Run: `npm test` (from `frontend/`)
Expected: PASS, no new failures.

Run: `npm run lint` (from `frontend/`)
Expected: zero warnings.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ShiftsPage.tsx
git commit -m "style: promote general auto-assign to primary button, group unit-responsibility actions"
```

---

## Self-Review Notes

- **Spec coverage:** All three buttons (Tasks 7-9), the two-level split semantics agreed in the design (Task 2), the fair-share batch scoring (Task 4), the preview-before-apply requirement (every modal has a preview/pick stage before its apply button), and the button layout (Task 10) are all covered.
- **Type consistency:** `TwoLevelSplitEntry`/`ResponsibilityAssignment` field names match exactly between backend Pydantic models (Tasks 3, 5) and frontend TS interfaces (Task 6); `hierarchy_node_id`/`node_name`/`count`/`weight`/`parent_responsible_node_id` are spelled identically everywhere they appear.
- **Placeholder scan:** no TBDs; every step has concrete code or an exact command with expected output.
- **Cross-plan dependency:** flagged at the top and again in Task 4 — do not start Task 4 until `backend/app/services/node_effort_potential.py` exists from the other plan.
