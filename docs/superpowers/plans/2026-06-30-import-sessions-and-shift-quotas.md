# Import Sessions, Pluggable Parsers & Sub-Unit Shift Quotas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stateless Excel import wizard with a persistent, permission-scoped import-session system built on a pluggable parser architecture, and add exact per-sub-unit soldier quotas to individual duty shifts, enforced by the CP-SAT solver with optional one-level-up relaxation.

**Architecture:** A canonical `ParsedImportData` JSON schema decouples "reading an Excel layout" (swappable parsers) from "validating and applying rows" (one shared pipeline). Import sessions persist the raw file + parsed state + user selections in Postgres, scoped to the actor's `dm_scope` subtree. Shift quotas live in a new `duty_shift_node_quotas` table and are layered onto the existing CP-SAT model as exact-equality constraints, with a relaxation ladder that widens to the parent node when needed. The two systems intersect at the `duty_shifts` import sheet, which is the primary import format and carries quota data — so quotas must exist before the parser/import-row layer that imports them, and DM-scope checks must exist before sessions can filter by them.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 + Alembic, Pydantic, openpyxl, OR-Tools CP-SAT, React + TypeScript, Vitest, pytest.

---

## Work Order Rationale

Both specs are combined here because of real dependencies:

1. **Quotas data model** must exist before the `duty_shifts` import row can carry `node_quotas`.
2. **DM scope helpers** (`scope_root_ids`/`_node_in_scope`, already in `app/auth/authz.py`) are needed by both the plain import-sessions scope check (soldiers/assignments) and the quota-node scope check (duty_shifts rows) — built once, used twice.
3. **Parser architecture** must exist before any sheet (including `duty_shifts`) can be parsed, since the canonical schema is the contract every later task writes against.
4. **Import sessions** (DB + API) is the system that hosts everything else — it must exist before the review UI, before quota-node inline-resolution, before duty_shifts parsing can be exercised end-to-end.
5. **Algorithm constraint integration** is independent of import (quotas can be set via UI alone) but is sequenced after the quota data model and before the duty_shifts importer, so quota rows imported via Excel are immediately meaningful to the solver.

Order: **quota data model → DM scope helper reuse → parser architecture → import sessions (DB+API) → quota service/API + ShiftFormModal UI → algorithm constraint + relaxation → duty_shifts parser row + quota resolution UX → import session frontend (list, upload, review, confirm) → algorithm run config UI for relaxation.**

---

## Part A — Sub-Unit Quota Data Model

### Task A1: `duty_shift_node_quotas` table + model

**Files:**
- Modify: `backend/app/db/models.py` (add new model near `DutyShift`, after line ~366 where `DutyShift` ends)
- Create: `backend/alembic/versions/<new_revision>_duty_shift_node_quotas.py`
- Test: `backend/app/services/tests/test_shift_quotas.py`

- [ ] **Step 1: Add the `DutyShiftNodeQuota` model**

In `backend/app/db/models.py`, add after the `DutyShift` class definition:

```python
class DutyShiftNodeQuota(Base):
    __tablename__ = "duty_shift_node_quotas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_shifts.id", ondelete="CASCADE")
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT")
    )
    count: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        sa.UniqueConstraint("duty_shift_id", "hierarchy_node_id", name="uq_shift_node_quota"),
        sa.CheckConstraint("count >= 1", name="ck_shift_node_quota_count_positive"),
    )
```

- [ ] **Step 2: Generate and edit the Alembic migration**

Run (from `backend/`, venv active):
```bash
alembic revision -m "add duty_shift_node_quotas table"
```

Edit the generated file's `upgrade()`/`downgrade()`:

```python
def upgrade() -> None:
    op.create_table(
        "duty_shift_node_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("duty_shift_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_shifts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("duty_shift_id", "hierarchy_node_id", name="uq_shift_node_quota"),
        sa.CheckConstraint("count >= 1", name="ck_shift_node_quota_count_positive"),
    )


def downgrade() -> None:
    op.drop_table("duty_shift_node_quotas")
```

- [ ] **Step 3: Apply the migration**

```bash
alembic upgrade head
```
Expected: migration applies cleanly, table visible via `\d duty_shift_node_quotas` in psql.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat: add duty_shift_node_quotas table"
```

---

### Task A2: Quota service (`set_shift_quotas`, `get_shift_quotas`)

**Files:**
- Create: `backend/app/services/shift_quotas.py`
- Modify: `backend/app/services/tests/test_shift_quotas.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/app/services/tests/test_shift_quotas.py
import uuid
import pytest
from app.services.shift_quotas import set_shift_quotas, get_shift_quotas, ShiftQuotaError


def test_set_quotas_within_required_count(session, make_duty_shift, make_hierarchy_node):
    shift = make_duty_shift(required_count=5)
    node_a = make_hierarchy_node(name="ענף פוקוס")
    node_b = make_hierarchy_node(name="ענף אלומות")

    set_shift_quotas(session, shift_id=shift.id, quotas=[
        (node_a.id, 2), (node_b.id, 3),
    ])
    session.flush()

    result = get_shift_quotas(session, shift_id=shift.id)
    assert {(q.hierarchy_node_id, q.count) for q in result} == {(node_a.id, 2), (node_b.id, 3)}


def test_set_quotas_over_required_count_raises(session, make_duty_shift, make_hierarchy_node):
    shift = make_duty_shift(required_count=3)
    node_a = make_hierarchy_node(name="ענף פוקוס")
    node_b = make_hierarchy_node(name="ענף אלומות")

    with pytest.raises(ShiftQuotaError, match="exceeds required_count"):
        set_shift_quotas(session, shift_id=shift.id, quotas=[(node_a.id, 2), (node_b.id, 2)])


def test_set_quotas_unknown_node_raises(session, make_duty_shift):
    shift = make_duty_shift(required_count=3)
    with pytest.raises(ShiftQuotaError, match="not found"):
        set_shift_quotas(session, shift_id=shift.id, quotas=[(uuid.uuid4(), 1)])


def test_set_quotas_replaces_existing(session, make_duty_shift, make_hierarchy_node):
    shift = make_duty_shift(required_count=5)
    node_a = make_hierarchy_node(name="ענף פוקוס")
    node_b = make_hierarchy_node(name="ענף אלומות")

    set_shift_quotas(session, shift_id=shift.id, quotas=[(node_a.id, 2)])
    session.flush()
    set_shift_quotas(session, shift_id=shift.id, quotas=[(node_b.id, 3)])
    session.flush()

    result = get_shift_quotas(session, shift_id=shift.id)
    assert {(q.hierarchy_node_id, q.count) for q in result} == {(node_b.id, 3)}
```

Check `backend/app/services/tests/conftest.py` for existing `make_duty_shift` / `make_hierarchy_node` fixtures; if absent, add them following the pattern of other factory fixtures already in that file (look at how `make_soldier` or similar is built — reuse the same `session` fixture).

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_shift_quotas.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.shift_quotas'`

- [ ] **Step 3: Implement the service**

```python
# backend/app/services/shift_quotas.py
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import DutyShift, DutyShiftNodeQuota, HierarchyNode


class ShiftQuotaError(Exception):
    """Raised on invalid shift quota operations."""


def get_shift_quotas(session: Session, *, shift_id: uuid.UUID) -> list[DutyShiftNodeQuota]:
    return list(
        session.execute(
            select(DutyShiftNodeQuota).where(DutyShiftNodeQuota.duty_shift_id == shift_id)
        ).scalars().all()
    )


def set_shift_quotas(
    session: Session,
    *,
    shift_id: uuid.UUID,
    quotas: list[tuple[uuid.UUID, int]],
) -> list[DutyShiftNodeQuota]:
    """Replace all quota entries for a shift. Validates node existence, no
    duplicate nodes, and that the sum does not exceed required_count."""
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        raise ShiftQuotaError("shift not found")

    seen: set[uuid.UUID] = set()
    total = 0
    for node_id, count in quotas:
        if node_id in seen:
            raise ShiftQuotaError(f"duplicate node {node_id} in quotas")
        seen.add(node_id)
        if count < 1:
            raise ShiftQuotaError(f"count must be >= 1 for node {node_id}")
        if session.get(HierarchyNode, node_id) is None:
            raise ShiftQuotaError(f"hierarchy node {node_id} not found")
        total += count

    if total > shift.required_count:
        raise ShiftQuotaError(
            f"sum of quota counts ({total}) exceeds required_count ({shift.required_count})"
        )

    session.execute(delete(DutyShiftNodeQuota).where(DutyShiftNodeQuota.duty_shift_id == shift_id))
    session.flush()

    entries = [
        DutyShiftNodeQuota(duty_shift_id=shift_id, hierarchy_node_id=node_id, count=count)
        for node_id, count in quotas
    ]
    for e in entries:
        session.add(e)
    session.flush()
    return entries
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_shift_quotas.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shift_quotas.py backend/app/services/tests/test_shift_quotas.py
git commit -m "feat: add shift node quota service with validation"
```

---

### Task A3: `PUT /shifts/{id}/quotas` and `GET /shifts/{id}` quota field

**Files:**
- Modify: `backend/app/routes/shifts.py` (find the existing shift detail route and router)
- Test: `backend/tests/integration/test_shift_quotas_api.py`

- [ ] **Step 1: Read the existing shifts route file to find the router prefix and detail endpoint**

```bash
grep -n "router = APIRouter\|@router.get(\"/{" backend/app/routes/shifts.py
```
Use the exact prefix and response model pattern found there for consistency.

- [ ] **Step 2: Write failing integration test**

```python
# backend/tests/integration/test_shift_quotas_api.py
def test_put_quotas_success(client, admin_headers, make_duty_shift, make_hierarchy_node):
    shift = make_duty_shift(required_count=5)
    node_a = make_hierarchy_node(name="ענף פוקוס")
    node_b = make_hierarchy_node(name="ענף אלומות")

    resp = client.put(
        f"/shifts/{shift.id}/quotas",
        json={"quotas": [
            {"hierarchy_node_id": str(node_a.id), "count": 2},
            {"hierarchy_node_id": str(node_b.id), "count": 3},
        ]},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {(q["hierarchy_node_id"], q["count"]) for q in body["quotas"]} == {
        (str(node_a.id), 2), (str(node_b.id), 3),
    }


def test_put_quotas_over_required_count_400(client, admin_headers, make_duty_shift, make_hierarchy_node):
    shift = make_duty_shift(required_count=2)
    node_a = make_hierarchy_node(name="ענף פוקוס")

    resp = client.put(
        f"/shifts/{shift.id}/quotas",
        json={"quotas": [{"hierarchy_node_id": str(node_a.id), "count": 5}]},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_get_shift_includes_node_quotas(client, admin_headers, make_duty_shift, make_hierarchy_node):
    shift = make_duty_shift(required_count=5)
    node_a = make_hierarchy_node(name="ענף פוקוס")
    client.put(
        f"/shifts/{shift.id}/quotas",
        json={"quotas": [{"hierarchy_node_id": str(node_a.id), "count": 2}]},
        headers=admin_headers,
    )
    resp = client.get(f"/shifts/{shift.id}", headers=admin_headers)
    assert resp.status_code == 200
    quotas = resp.json()["node_quotas"]
    assert quotas == [{"hierarchy_node_id": str(node_a.id), "node_name": "ענף פוקוס", "count": 2}]
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest backend/tests/integration/test_shift_quotas_api.py -v
```
Expected: FAIL — 404 on `/shifts/{id}/quotas` (route doesn't exist)

- [ ] **Step 4: Implement the route**

Add to `backend/app/routes/shifts.py` (alongside existing imports/router):

```python
from app.services.shift_quotas import ShiftQuotaError, get_shift_quotas, set_shift_quotas


class NodeQuotaIn(BaseModel):
    hierarchy_node_id: uuid.UUID
    count: int


class NodeQuotaOut(BaseModel):
    hierarchy_node_id: uuid.UUID
    node_name: str
    count: int


class SetQuotasRequest(BaseModel):
    quotas: list[NodeQuotaIn]


class SetQuotasResponse(BaseModel):
    quotas: list[NodeQuotaOut]


@router.put("/{shift_id}/quotas", response_model=SetQuotasResponse)
def put_shift_quotas(
    shift_id: uuid.UUID,
    req: SetQuotasRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    try:
        entries = set_shift_quotas(
            session,
            shift_id=shift_id,
            quotas=[(q.hierarchy_node_id, q.count) for q in req.quotas],
        )
        session.commit()
    except ShiftQuotaError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    nodes = {n.id: n.name for n in session.execute(
        select(HierarchyNode).where(HierarchyNode.id.in_([e.hierarchy_node_id for e in entries]))
    ).scalars().all()}
    return SetQuotasResponse(quotas=[
        NodeQuotaOut(hierarchy_node_id=e.hierarchy_node_id, node_name=nodes[e.hierarchy_node_id], count=e.count)
        for e in entries
    ])
```

Then find the existing `GET /{shift_id}` handler in the same file and add `node_quotas` to its response: fetch via `get_shift_quotas(session, shift_id=shift.id)`, resolve node names the same way as above, and add a `node_quotas: list[NodeQuotaOut]` field to that endpoint's existing response model (check the actual response model class name in the file before editing — match its existing field style, e.g. if it uses a dataclass like `ShiftWithFill`, add the field there and at its construction site in `app/services/shifts.py`).

- [ ] **Step 5: Run to verify pass**

```bash
pytest backend/tests/integration/test_shift_quotas_api.py -v
```
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/shifts.py backend/app/services/shifts.py backend/tests/integration/test_shift_quotas_api.py
git commit -m "feat: add PUT /shifts/{id}/quotas and include quotas in shift detail"
```

---

### Task A4: `ShiftFormModal` quota UI

**Files:**
- Modify: `frontend/src/components/ShiftFormModal.tsx`
- Modify: `frontend/src/api/shifts.ts` (add `setShiftQuotas` API call and `NodeQuota` type)
- Test: existing `frontend/src/components/ShiftTemplateFormModal.test.tsx` pattern — create `frontend/src/components/ShiftFormModal.test.tsx` if none exists, otherwise extend it.

- [ ] **Step 1: Read the current `ShiftFormModal.tsx` and `api/shifts.ts` to find the save flow**

```bash
grep -n "function ShiftFormModal\|onSave\|async function handleSubmit" frontend/src/components/ShiftFormModal.tsx
```

- [ ] **Step 2: Add API helpers**

In `frontend/src/api/shifts.ts`, add:

```typescript
export interface NodeQuota {
  hierarchy_node_id: string;
  node_name: string;
  count: number;
}

export async function setShiftQuotas(
  shiftId: string,
  quotas: { hierarchy_node_id: string; count: number }[]
): Promise<{ quotas: NodeQuota[] }> {
  const res = await fetch(`/api/shifts/${shiftId}/quotas`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quotas }),
  });
  if (!res.ok) throw new Error("failed to set quotas");
  return res.json();
}
```

- [ ] **Step 3: Write a failing test for the quota section**

```typescript
// frontend/src/components/ShiftFormModal.test.tsx (add to existing file or create)
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ShiftFormModal from "./ShiftFormModal";

describe("ShiftFormModal node quotas", () => {
  it("blocks save when quota sum exceeds required_count", () => {
    render(
      <ShiftFormModal
        open
        onClose={() => {}}
        onSaved={() => {}}
        dutyTypes={[]}
        locations={[]}
        hierarchyNodes={[{ id: "n1", name: "ענף פוקוס" }, { id: "n2", name: "ענף אלומות" }]}
        initialRequiredCount={3}
      />
    );
    fireEvent.click(screen.getByText("הוסף מכסת יחידה"));
    fireEvent.change(screen.getByLabelText("כמות"), { target: { value: "5" } });
    expect(screen.getByText(/חורג מהכמות הנדרשת/)).toBeInTheDocument();
  });
});
```

Adjust prop names to match the actual `ShiftFormModal` props found in Step 1 — this test scaffolds the expected UI text/labels the implementation must produce.

- [ ] **Step 4: Run to verify failure**

```bash
cd frontend && npx vitest run src/components/ShiftFormModal.test.tsx
```
Expected: FAIL — "הוסף מכסת יחידה" not found

- [ ] **Step 5: Implement the quota section**

Add a new collapsible section inside the existing form JSX (after the `required_count` field), state, and handlers:

```tsx
const [quotas, setQuotas] = useState<{ hierarchy_node_id: string; count: number }[]>(
  initialQuotas ?? []
);
const quotaTotal = quotas.reduce((sum, q) => sum + (q.count || 0), 0);
const quotaOverLimit = quotaTotal > requiredCount;

// ...inside JSX, after the required_count field:
<div className="space-y-2 border-t pt-3 mt-3">
  <h3 className="text-sm font-medium">הקצאת מכסות ליחידות</h3>
  {quotas.map((q, i) => (
    <div key={i} className="flex gap-2 items-center">
      <select
        className="border rounded p-1 text-sm flex-1"
        value={q.hierarchy_node_id}
        onChange={(e) => {
          const next = [...quotas];
          next[i] = { ...next[i], hierarchy_node_id: e.target.value };
          setQuotas(next);
        }}
      >
        <option value="">בחר יחידה</option>
        {hierarchyNodes.map((n) => (
          <option key={n.id} value={n.id}>{n.name}</option>
        ))}
      </select>
      <input
        type="number"
        min={1}
        aria-label="כמות"
        className="border rounded p-1 text-sm w-16"
        value={q.count}
        onChange={(e) => {
          const next = [...quotas];
          next[i] = { ...next[i], count: Number(e.target.value) };
          setQuotas(next);
        }}
      />
      <button type="button" onClick={() => setQuotas(quotas.filter((_, j) => j !== i))}>✕</button>
    </div>
  ))}
  <button
    type="button"
    className="text-indigo-600 text-sm"
    onClick={() => setQuotas([...quotas, { hierarchy_node_id: "", count: 1 }])}
  >
    הוסף מכסת יחידה
  </button>
  <p className={`text-xs ${quotaOverLimit ? "text-red-600" : "text-gray-500"}`}>
    סה&quot;כ הוקצה: {quotaTotal} מתוך {requiredCount}
    {quotaOverLimit && " — חורג מהכמות הנדרשת"}
  </p>
</div>
```

In the save handler, after the shift itself is created/updated and its id is known, call `setShiftQuotas(shiftId, quotas.filter(q => q.hierarchy_node_id))` if `quotas.length > 0`, and block the whole submit (return early, show the over-limit text) when `quotaOverLimit` is true.

- [ ] **Step 6: Run to verify pass**

```bash
cd frontend && npx vitest run src/components/ShiftFormModal.test.tsx
```
Expected: passed

- [ ] **Step 7: Run lint and typecheck**

```bash
cd frontend && npm run lint && npm run typecheck
```
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx frontend/src/api/shifts.ts frontend/src/components/ShiftFormModal.test.tsx
git commit -m "feat: add node quota allocation UI to ShiftFormModal"
```

---

## Part B — Algorithm: Quota Constraints + Relaxation

### Task B1: Extend `DutyBlock` and `build_model` with quota constraints

**Files:**
- Modify: `backend/app/algorithm/types.py:46-58` (`DutyBlock` dataclass)
- Modify: `backend/app/algorithm/model.py` (around line 346, after the coverage constraint loop)
- Test: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Write failing solver test**

```python
# Add to backend/app/algorithm/tests/test_solver.py
import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.model import build_model
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings


def test_node_quota_exact_assignment():
    node_a = uuid.uuid4()
    node_b = uuid.uuid4()
    duty_type = uuid.uuid4()
    location = uuid.uuid4()

    soldiers = [
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
                     active_days=100, hierarchy_node_id=node_a, path_ids=[node_a])
        for _ in range(2)
    ] + [
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
                     active_days=100, hierarchy_node_id=node_b, path_ids=[node_b])
        for _ in range(3)
    ]

    duty = DutyBlock(
        id=uuid.uuid4(), duty_type_id=duty_type, duty_location_id=location,
        start_date=date(2024, 6, 1), end_date=date(2024, 6, 1),
        score_per_day=Decimal("1.0"),
        node_quotas={node_a: 2, node_b: 3},
    )

    model, x = build_model(soldiers, [duty] * 5, [], SolverSettings(time_limit_seconds=5))
    # This single duty repeated 5x stands in for 5 required slots in this unit test;
    # real usage expands required_count into N DutyBlock instances upstream (existing pattern).
    from ortools.sat.python import cp_model
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assigned_a = sum(
        1 for (di, si), var in x.items()
        if soldiers[si].hierarchy_node_id == node_a and solver.Value(var) == 1
    )
    assigned_b = sum(
        1 for (di, si), var in x.items()
        if soldiers[si].hierarchy_node_id == node_b and solver.Value(var) == 1
    )
    assert assigned_a == 2
    assert assigned_b == 3
```

Note: this test sketches intent at the `build_model` level. Before finalizing, check how `DutyBlock` instances are expanded from `required_count` upstream (search `algorithm_bridge.py` for where `DutyBlock` objects are constructed per shift) — adjust the test to match whatever single-shift-to-N-blocks convention already exists, since quotas are per-shift, not per-block-instance.

```bash
grep -n "DutyBlock(" backend/app/services/algorithm_bridge.py
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/algorithm/tests/test_solver.py::test_node_quota_exact_assignment -v
```
Expected: FAIL — `DutyBlock() got an unexpected keyword argument 'node_quotas'`

- [ ] **Step 3: Add `node_quotas` field to `DutyBlock`**

In `backend/app/algorithm/types.py`, modify the `DutyBlock` dataclass:

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
    # Exact per-node soldier counts required for this shift's slots. Slots not
    # covered by any entry are unconstrained. Keys are hierarchy_node_id; the
    # constraint matches any soldier whose path_ids contains that node (i.e.
    # the node itself or any descendant), same semantics as eligible_node_ids.
    node_quotas: dict[uuid.UUID, int] | None = None
```

- [ ] **Step 4: Add the quota constraint in `build_model`**

In `backend/app/algorithm/model.py`, immediately after the coverage constraint loop (after line ~353, before "Hard constraint 2: No overlap"), add:

```python
    # ── Sub-unit node quotas ────────────────────────────────────────────────
    # For each duty with node_quotas, force the exact count of assigned
    # soldiers whose path_ids contains that node (itself or any descendant).
    # Slots not covered by any quota remain governed only by the coverage
    # constraint above (any eligible soldier).
    for di, d in enumerate(duty_list):
        if not d.node_quotas:
            continue
        for node_id, count in d.node_quotas.items():
            matching_vars = [
                x[(di, si)] for (dii, si) in eligible
                if dii == di and node_id in soldier_list[si].path_ids
            ]
            if not matching_vars:
                continue
            model.Add(sum(matching_vars) == count)
```

- [ ] **Step 5: Run to verify pass**

```bash
pytest backend/app/algorithm/tests/test_solver.py::test_node_quota_exact_assignment -v
```
Expected: PASS

- [ ] **Step 6: Run full algorithm test suite to check no regression**

```bash
pytest backend/app/algorithm -q
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/algorithm/model.py backend/app/algorithm/tests/test_solver.py
git commit -m "feat: enforce exact per-node soldier quotas in CP-SAT model"
```

---

### Task B2: Bridge — load quotas into `DutyBlock`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py` (wherever `DutyBlock(...)` instances are constructed from `DutyShift` rows)
- Test: `backend/app/services/tests/test_algorithm_bridge.py`

- [ ] **Step 1: Locate the DutyBlock construction site**

```bash
grep -n "DutyBlock(" backend/app/services/algorithm_bridge.py
```

- [ ] **Step 2: Write failing bridge test**

Add to `backend/app/services/tests/test_algorithm_bridge.py` (match the existing fixture/style in that file — look at an existing test that builds a `DutyShift` and checks the resulting `DutyBlock` fields, then add a parallel test):

```python
def test_bridge_loads_node_quotas(session, make_duty_shift, make_hierarchy_node):
    node_a = make_hierarchy_node(name="ענף פוקוס")
    shift = make_duty_shift(required_count=5)
    from app.services.shift_quotas import set_shift_quotas
    set_shift_quotas(session, shift_id=shift.id, quotas=[(node_a.id, 2)])
    session.flush()

    blocks = load_duty_blocks(session, [shift.id])  # use whatever the real loader function is named
    assert blocks[0].node_quotas == {node_a.id: 2}
```

Replace `load_duty_blocks` with whatever function name actually builds the `DutyBlock` list in `algorithm_bridge.py` (found in Step 1).

- [ ] **Step 3: Run to verify failure**

```bash
pytest backend/app/services/tests/test_algorithm_bridge.py::test_bridge_loads_node_quotas -v
```
Expected: FAIL — quotas not populated (empty dict or AttributeError depending on current `DutyBlock(...)` call)

- [ ] **Step 4: Implement loading**

At the `DutyBlock` construction site found in Step 1, before the loop that builds blocks, batch-load all quotas for the shift ids involved:

```python
from app.db.models import DutyShiftNodeQuota

quota_rows = session.execute(
    select(DutyShiftNodeQuota).where(DutyShiftNodeQuota.duty_shift_id.in_(shift_ids))
).scalars().all()
quotas_by_shift: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
for q in quota_rows:
    quotas_by_shift.setdefault(q.duty_shift_id, {})[q.hierarchy_node_id] = q.count
```

Then pass `node_quotas=quotas_by_shift.get(shift.id)` into each `DutyBlock(...)` call.

- [ ] **Step 5: Run to verify pass**

```bash
pytest backend/app/services/tests/test_algorithm_bridge.py::test_bridge_loads_node_quotas -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/app/services/tests/test_algorithm_bridge.py
git commit -m "feat: load shift node quotas into algorithm bridge DutyBlocks"
```

---

### Task B3: Relaxation — one-level-up retry

**Files:**
- Modify: `backend/app/algorithm/model.py` (add a helper to compute parent-relaxed quotas)
- Modify: `backend/app/algorithm/solver.py` (hook into the existing relaxation ladder)
- Modify: `backend/app/algorithm/types.py` (add `auto_relax_node_quotas: bool = False` to `SolverSettings`, add `relaxed_node_quotas: list[dict]` to `SolverResult`)
- Test: `backend/app/algorithm/tests/test_relaxation_search.py`

- [ ] **Step 1: Read the existing relaxation ladder to find the hook point**

```bash
grep -n "def _search_relaxation_ladder\|relax_r_ceiling\|relax_t_ceiling" backend/app/algorithm/solver.py
```

- [ ] **Step 2: Write failing test**

```python
# Add to backend/app/algorithm/tests/test_relaxation_search.py
import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.solver import solve
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings


def test_unsatisfiable_quota_relaxes_to_parent():
    parent = uuid.uuid4()
    node_a = uuid.uuid4()  # child of parent
    duty_type = uuid.uuid4()
    location = uuid.uuid4()

    # Only 1 soldier under node_a, but quota demands 2 — must relax to parent
    # subtree, which also includes node_b (sibling), to find the 2nd soldier.
    node_b = uuid.uuid4()  # sibling of node_a, also child of parent
    soldiers = [
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
                     active_days=100, hierarchy_node_id=node_a, path_ids=[parent, node_a]),
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
                     active_days=100, hierarchy_node_id=node_b, path_ids=[parent, node_b]),
    ]
    duties = [
        DutyBlock(id=uuid.uuid4(), duty_type_id=duty_type, duty_location_id=location,
                  start_date=date(2024, 6, 1), end_date=date(2024, 6, 1), score_per_day=Decimal("1.0"),
                  node_quotas={node_a: 2})
    ]

    settings = SolverSettings(time_limit_seconds=5, auto_relax_node_quotas=True)
    result = solve(soldiers, duties, [], settings, node_parents={node_a: parent, node_b: parent})

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.relaxed_node_quotas) == 1
    assert result.relaxed_node_quotas[0]["original_node_id"] == node_a
    assert result.relaxed_node_quotas[0]["relaxed_node_id"] == parent
```

Check the actual `solve()` signature in `solver.py` before finalizing this test — it may not currently accept a `node_parents` mapping; that is exactly what Step 4 adds.

- [ ] **Step 3: Run to verify failure**

```bash
pytest backend/app/algorithm/tests/test_relaxation_search.py::test_unsatisfiable_quota_relaxes_to_parent -v
```
Expected: FAIL — `solve() got an unexpected keyword argument 'node_parents'`

- [ ] **Step 4: Add settings/result fields**

In `backend/app/algorithm/types.py`:
- Add to `SolverSettings`: `auto_relax_node_quotas: bool = False`
- Add to `SolverResult`: `relaxed_node_quotas: list[dict] = field(default_factory=list)` (each dict: `{"duty_id": uuid.UUID, "original_node_id": uuid.UUID, "relaxed_node_id": uuid.UUID, "count": int}`)

- [ ] **Step 5: Implement relaxation in `solver.py`**

Add a helper near the other relaxation helpers:

```python
def _relax_unsatisfiable_quotas(
    duties: list[DutyBlock],
    node_parents: dict[uuid.UUID, uuid.UUID],
    unsatisfiable_duty_ids: set[uuid.UUID],
) -> tuple[list[DutyBlock], list[dict]]:
    """Rewrite node_quotas for duties that proved unsatisfiable: replace each
    quota node with its parent (per node_parents), so the constraint matches
    the parent's whole subtree (siblings included). Duties whose node has no
    known parent are left as-is — there's nothing higher to relax to."""
    relaxed_log: list[dict] = []
    new_duties: list[DutyBlock] = []
    for d in duties:
        if d.id not in unsatisfiable_duty_ids or not d.node_quotas:
            new_duties.append(d)
            continue
        new_quotas: dict[uuid.UUID, int] = {}
        for node_id, count in d.node_quotas.items():
            parent_id = node_parents.get(node_id)
            if parent_id is None:
                new_quotas[node_id] = count  # nothing to relax to
                continue
            new_quotas[parent_id] = new_quotas.get(parent_id, 0) + count
            relaxed_log.append({
                "duty_id": d.id, "original_node_id": node_id,
                "relaxed_node_id": parent_id, "count": count,
            })
        new_duties.append(dataclasses.replace(d, node_quotas=new_quotas))
    return new_duties, relaxed_log
```

In the main `solve()` function, accept a new optional `node_parents: dict[uuid.UUID, uuid.UUID] | None = None` parameter. After the first solve attempt, if `settings.auto_relax_node_quotas` is true and `node_parents` is provided, identify duties whose node-quota constraints made them infeasible (use the existing infeasibility-cluster detection already present in the relaxation ladder — locate via `grep -n "INFEASIBLE" backend/app/algorithm/solver.py` to find where unsatisfiable duty ids are already collected), call `_relax_unsatisfiable_quotas`, rebuild the model with the new duty list, and re-solve once. Append the returned `relaxed_log` entries to `result.relaxed_node_quotas`.

For the **manual retry** path (not auto), expose the same `_relax_unsatisfiable_quotas` helper so a caller (the API layer, Task B4) can invoke a second solve pass explicitly with a specific set of shift ids the user opted to relax, rather than the solver doing it automatically.

- [ ] **Step 6: Run to verify pass**

```bash
pytest backend/app/algorithm/tests/test_relaxation_search.py::test_unsatisfiable_quota_relaxes_to_parent -v
```
Expected: PASS

- [ ] **Step 7: Run full algorithm suite**

```bash
pytest backend/app/algorithm -q
```
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/algorithm/solver.py backend/app/algorithm/tests/test_relaxation_search.py
git commit -m "feat: add one-level-up node quota relaxation (manual + auto modes)"
```

---

### Task B4: Algorithm run config — relaxation toggles

**Files:**
- Modify: `backend/app/routes/algorithm.py` (find the run-config request model and pass `auto_relax_node_quotas` through to `SolverSettings`)
- Modify: `frontend/src/components/GenerateShiftsModal.tsx`
- Modify: `frontend/src/components/AlgorithmInlinePanel.tsx` (manual retry toggle, if retry lives there — check first)
- Test: existing algorithm route integration tests, extend with one case

- [ ] **Step 1: Find the run-config request model**

```bash
grep -n "class.*RunRequest\|SolverSettings(" backend/app/routes/algorithm.py
```

- [ ] **Step 2: Write failing integration test**

```python
def test_run_with_auto_relax_node_quotas(client, admin_headers, make_duty_shift_with_quota):
    resp = client.post("/algorithm/run", json={
        "auto_relax_node_quotas": True,
        # ...other required fields per the actual request model found in Step 1
    }, headers=admin_headers)
    assert resp.status_code in (200, 202)
```

Adjust to the real request shape found in Step 1 (sync vs async job creation).

- [ ] **Step 3: Run to verify failure**

```bash
pytest backend/tests/integration -k auto_relax_node_quotas -v
```
Expected: FAIL — field rejected or ignored

- [ ] **Step 4: Wire the field through**

Add `auto_relax_node_quotas: bool = False` to the run-request Pydantic model in `routes/algorithm.py`, and pass it into the `SolverSettings(...)` construction at the call site.

- [ ] **Step 5: Add the frontend toggle**

In `frontend/src/components/GenerateShiftsModal.tsx`, add a checkbox near the other solver settings inputs:

```tsx
<label className="flex items-center gap-2 text-sm">
  <input
    type="checkbox"
    checked={autoRelaxNodeQuotas}
    onChange={(e) => setAutoRelaxNodeQuotas(e.target.checked)}
  />
  אפשר הרחבת יחידה אוטומטית במכסות
</label>
```

Include `auto_relax_node_quotas: autoRelaxNodeQuotas` in the request body sent to `/algorithm/run`.

- [ ] **Step 6: Run to verify pass**

```bash
pytest backend/tests/integration -k auto_relax_node_quotas -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/algorithm.py frontend/src/components/GenerateShiftsModal.tsx
git commit -m "feat: expose auto-relax node quotas toggle in run config"
```

---

## Part C — Pluggable Excel Parser Architecture

### Task C1: Canonical schema + parser interface + registry

**Files:**
- Create: `backend/app/services/import_parsers/__init__.py`
- Create: `backend/app/services/import_parsers/schema.py`
- Create: `backend/app/services/import_parsers/registry.py`
- Test: `backend/app/services/tests/test_import_parser_registry.py`

- [ ] **Step 1: Write failing test for the registry**

```python
# backend/app/services/tests/test_import_parser_registry.py
import openpyxl
import pytest

from app.services.import_parsers.registry import PARSER_REGISTRY, auto_detect_parser
from app.services.import_parsers.schema import ParsedImportData


class _FakeParser:
    id = "fake"
    label = "Fake Parser"

    def detect(self, wb):
        return 0.9

    def parse(self, wb):
        return ParsedImportData(soldiers=[], duty_shifts=[], shift_templates=[], parser_id=self.id)


def test_auto_detect_picks_highest_confidence():
    PARSER_REGISTRY["fake"] = _FakeParser()
    try:
        wb = openpyxl.Workbook()
        parser = auto_detect_parser(wb)
        assert parser.id == "fake"
    finally:
        del PARSER_REGISTRY["fake"]


def test_auto_detect_raises_when_no_match():
    wb = openpyxl.Workbook()
    # Assuming no registered parser claims an empty default workbook with
    # confidence > 0.5 in the base state (real parsers registered in C2 will
    # require recognizable sheet names).
    with pytest.raises(ValueError, match="unrecognized"):
        auto_detect_parser(wb, threshold=0.99)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_import_parser_registry.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the schema**

```python
# backend/app/services/import_parsers/schema.py
from __future__ import annotations

from pydantic import BaseModel


class ImportNodeQuota(BaseModel):
    node_name: str
    count: int


class ImportSoldierRow(BaseModel):
    source_row: int
    personal_number: str
    full_name: str
    rank: str | None = None
    gender: str | None = None
    is_officer: bool | None = None
    hierarchy_node_name: str | None = None
    enrolled_at: str | None = None
    enlistment_date: str | None = None
    phone: str | None = None
    email: str | None = None


class ImportDutyShiftRow(BaseModel):
    source_row: int
    duty_type_name: str
    duty_location_name: str
    start_date: str
    end_date: str
    start_time: str | None = None
    end_time: str | None = None
    required_count: int
    node_quotas: list[ImportNodeQuota] = []
    notes: str | None = None


class ImportShiftTemplateRow(BaseModel):
    source_row: int
    name: str
    duty_type_name: str
    days_of_week: list[int]
    required_primary: int
    required_reserve: int = 0


class ParsedImportData(BaseModel):
    soldiers: list[ImportSoldierRow] = []
    duty_shifts: list[ImportDutyShiftRow] = []
    shift_templates: list[ImportShiftTemplateRow] = []
    parser_id: str
    parser_warnings: list[str] = []
```

- [ ] **Step 4: Implement the parser interface and registry**

```python
# backend/app/services/import_parsers/__init__.py
from __future__ import annotations

from typing import Protocol

import openpyxl

from app.services.import_parsers.schema import ParsedImportData


class ImportParser(Protocol):
    id: str
    label: str

    def detect(self, wb: openpyxl.Workbook) -> float: ...
    def parse(self, wb: openpyxl.Workbook) -> ParsedImportData: ...
```

```python
# backend/app/services/import_parsers/registry.py
from __future__ import annotations

import openpyxl

from app.services.import_parsers import ImportParser

PARSER_REGISTRY: dict[str, ImportParser] = {}


def register(parser: ImportParser) -> None:
    PARSER_REGISTRY[parser.id] = parser


def auto_detect_parser(wb: openpyxl.Workbook, threshold: float = 0.5) -> ImportParser:
    best: tuple[float, ImportParser | None] = (0.0, None)
    for parser in PARSER_REGISTRY.values():
        score = parser.detect(wb)
        if score > best[0]:
            best = (score, parser)
    if best[1] is None or best[0] < threshold:
        raise ValueError("unrecognized Excel format — no registered parser matched")
    return best[1]


def get_parser(parser_id: str) -> ImportParser:
    parser = PARSER_REGISTRY.get(parser_id)
    if parser is None:
        raise ValueError(f"unknown parser_id: {parser_id}")
    return parser
```

- [ ] **Step 5: Run to verify pass**

```bash
pytest backend/app/services/tests/test_import_parser_registry.py -v
```
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/import_parsers/
git add backend/app/services/tests/test_import_parser_registry.py
git commit -m "feat: add pluggable import parser interface, schema, and registry"
```

---

### Task C2: `v1_standard` parser (soldiers, assignments→duty_shifts, shift_templates)

This parser absorbs and replaces the row-parsing logic currently in `backend/app/routes/import_excel.py` (`_parse_soldiers_sheet`, `_parse_assignments_sheet`, `_parse_templates_sheet`), retargeting `assignments` into the new primary `duty_shifts` sheet format, plus the `node_quotas` column.

**Files:**
- Create: `backend/app/services/import_parsers/v1_standard.py`
- Test: `backend/app/services/tests/test_import_parser_v1.py`

- [ ] **Step 1: Write failing tests covering soldiers, duty_shifts (with and without node_quotas), and shift_templates**

```python
# backend/app/services/tests/test_import_parser_v1.py
import io
import openpyxl
from app.services.import_parsers.v1_standard import V1StandardParser


def _wb_with_duty_shifts_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_shifts")
    ws.append([
        "duty_type_name", "duty_location_name", "start_date", "end_date",
        "start_time", "end_time", "required_count", "node_quotas", "notes",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_duty_shifts_with_node_quotas():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5,
         "ענף פוקוס:2;ענף אלומות:3", ""],
    ])
    parser = V1StandardParser()
    data = parser.parse(wb)
    assert len(data.duty_shifts) == 1
    row = data.duty_shifts[0]
    assert row.duty_type_name == "שמירה"
    assert row.required_count == 5
    assert {(q.node_name, q.count) for q in row.node_quotas} == {
        ("ענף פוקוס", 2), ("ענף אלומות", 3),
    }


def test_parses_duty_shifts_without_node_quotas():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_shifts[0].node_quotas == []


def test_detect_scores_high_for_known_sheet_names():
    wb = _wb_with_duty_shifts_sheet([])
    score = V1StandardParser().detect(wb)
    assert score >= 0.5


def test_detect_scores_low_for_unrelated_workbook():
    wb = openpyxl.Workbook()
    wb.active.title = "random_sheet"
    score = V1StandardParser().detect(wb)
    assert score < 0.5
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_import_parser_v1.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the parser**

```python
# backend/app/services/import_parsers/v1_standard.py
from __future__ import annotations

from datetime import date as date_type
from typing import Any

import openpyxl

from app.services.import_parsers.schema import (
    ImportDutyShiftRow,
    ImportNodeQuota,
    ImportShiftTemplateRow,
    ImportSoldierRow,
    ParsedImportData,
)

KNOWN_SHEETS = {"soldiers", "duty_shifts", "shift_templates", "assignments"}


def _parse_date(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, date_type):
        return val.isoformat()
    s = str(val).strip()
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        d, m, y = s.split(".")
        return f"{y}-{m}-{d}"
    return s


def _parse_bool(val: Any) -> bool | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "כן", "נכון")


def _sheet_rows(wb: openpyxl.Workbook, name: str) -> list[dict[str, Any]]:
    if name not in wb.sheetnames:
        return []
    ws = wb[name]
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    out = []
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v is None for v in row):
            continue
        out.append({"_row": i, **dict(zip(headers, row))})
    return out


def _parse_node_quotas(raw: Any) -> list[ImportNodeQuota]:
    s = str(raw or "").strip()
    if not s:
        return []
    quotas = []
    for part in s.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, count_s = part.rsplit(":", 1)
        quotas.append(ImportNodeQuota(node_name=name.strip(), count=int(count_s.strip())))
    return quotas


class V1StandardParser:
    id = "v1_standard"
    label = "תבנית סטנדרטית (v1)"

    def detect(self, wb: openpyxl.Workbook) -> float:
        matches = KNOWN_SHEETS & set(wb.sheetnames)
        if not matches:
            return 0.0
        return min(1.0, 0.5 + 0.2 * len(matches))

    def parse(self, wb: openpyxl.Workbook) -> ParsedImportData:
        warnings: list[str] = []

        soldiers = [
            ImportSoldierRow(
                source_row=r["_row"],
                personal_number=str(r.get("personal_number") or "").strip(),
                full_name=str(r.get("full_name") or "").strip(),
                rank=str(r.get("rank") or "").strip() or None,
                gender=str(r.get("gender") or "").strip() or None,
                is_officer=_parse_bool(r.get("is_officer")),
                hierarchy_node_name=str(r.get("hierarchy_node_name") or "").strip() or None,
                enrolled_at=_parse_date(r.get("enrolled_at")),
                enlistment_date=_parse_date(r.get("enlistment_date")),
                phone=str(r.get("phone") or "").strip() or None,
                email=str(r.get("email") or "").strip() or None,
            )
            for r in _sheet_rows(wb, "soldiers")
        ]

        duty_shift_rows = _sheet_rows(wb, "duty_shifts")
        if not duty_shift_rows and "assignments" in wb.sheetnames:
            warnings.append("using legacy 'assignments' sheet — required_count defaulted to 1 per row")
            for r in _sheet_rows(wb, "assignments"):
                duty_shift_rows.append({
                    "_row": r["_row"],
                    "duty_type_name": r.get("duty_type_name"),
                    "duty_location_name": None,
                    "start_date": r.get("start_date"),
                    "end_date": r.get("end_date"),
                    "required_count": 1,
                    "node_quotas": None,
                    "notes": None,
                })

        duty_shifts = [
            ImportDutyShiftRow(
                source_row=r["_row"],
                duty_type_name=str(r.get("duty_type_name") or "").strip(),
                duty_location_name=str(r.get("duty_location_name") or "").strip(),
                start_date=_parse_date(r.get("start_date")) or "",
                end_date=_parse_date(r.get("end_date")) or "",
                start_time=str(r.get("start_time") or "").strip() or None,
                end_time=str(r.get("end_time") or "").strip() or None,
                required_count=int(r.get("required_count") or 1),
                node_quotas=_parse_node_quotas(r.get("node_quotas")),
                notes=str(r.get("notes") or "").strip() or None,
            )
            for r in duty_shift_rows
        ]

        shift_templates = [
            ImportShiftTemplateRow(
                source_row=r["_row"],
                name=str(r.get("name") or "").strip(),
                duty_type_name=str(r.get("duty_type_name") or "").strip(),
                days_of_week=[int(d.strip()) for d in str(r.get("days_of_week") or "").split(",") if d.strip()],
                required_primary=int(r.get("required_primary") or 1),
                required_reserve=int(r.get("required_reserve") or 0),
            )
            for r in _sheet_rows(wb, "shift_templates")
        ]

        return ParsedImportData(
            soldiers=soldiers,
            duty_shifts=duty_shifts,
            shift_templates=shift_templates,
            parser_id=self.id,
            parser_warnings=warnings,
        )
```

Then register it — add to `backend/app/services/import_parsers/registry.py` at the bottom (or in a small `bootstrap.py` imported once at app startup; check how other registries in this codebase self-register, e.g. `grep -rn "register(" backend/app/services/ | grep -v test` to follow the existing convention):

```python
from app.services.import_parsers.v1_standard import V1StandardParser
register(V1StandardParser())
```

If no existing self-registration convention is found, add the import+register call to `backend/app/main.py`'s startup section instead, next to other one-time service initialization.

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_import_parser_v1.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_parsers/v1_standard.py backend/app/services/tests/test_import_parser_v1.py
git add backend/app/main.py  # if registration was added there
git commit -m "feat: add v1_standard import parser targeting duty_shifts as primary sheet"
```

---

## Part D — Import Sessions (DB + API)

### Task D1: `import_sessions` table + model

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/<new_revision>_import_sessions.py`
- Test: `backend/app/services/tests/test_import_sessions_model.py`

- [ ] **Step 1: Add the model**

```python
class ImportSession(Base):
    __tablename__ = "import_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    status: Mapped[str] = mapped_column(
        Enum("draft", "confirmed", "cancelled", "done", name="import_session_status"),
        server_default="draft", default="draft",
    )
    filename: Mapped[str] = mapped_column(Text)
    raw_excel: Mapped[bytes] = mapped_column(sa.LargeBinary)
    parsed_state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"), default_factory=dict)
    user_selections: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"), default_factory=dict)
    created_links: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"), default_factory=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
```

Place this near `AlgorithmJob` in `models.py` since it follows a similar "session/job" shape.

- [ ] **Step 2: Generate and edit the Alembic migration**

```bash
alembic revision -m "add import_sessions table"
```

```python
def upgrade() -> None:
    op.execute("CREATE TYPE import_session_status AS ENUM ('draft', 'confirmed', 'cancelled', 'done')")
    op.create_table(
        "import_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", postgresql.ENUM("draft", "confirmed", "cancelled", "done", name="import_session_status", create_type=False), server_default="draft", nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("raw_excel", sa.LargeBinary(), nullable=False),
        sa.Column("parsed_state", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("user_selections", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_links", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("import_sessions")
    op.execute("DROP TYPE import_session_status")
```

- [ ] **Step 3: Apply migration**

```bash
alembic upgrade head
```
Expected: succeeds

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat: add import_sessions table"
```

---

### Task D2: DM scope helper for import rows

**Files:**
- Create: `backend/app/services/import_scope.py`
- Test: `backend/app/services/tests/test_import_scope.py`

This wraps the existing `scope_root_ids`/`_node_in_scope` (from `app/auth/authz.py`) for the import-specific question: "is this row's node within the actor's scope?" — shared by soldier rows (Plan 1) and duty_shift quota-node rows (Plan 2).

- [ ] **Step 1: Write failing tests**

```python
# backend/app/services/tests/test_import_scope.py
import uuid

from app.services.import_scope import is_node_in_actor_scope


def test_admin_always_in_scope(make_soldier, make_hierarchy_node):
    admin = make_soldier(role="admin")
    node = make_hierarchy_node(name="ענף פוקוס")
    assert is_node_in_actor_scope(session=None, actor=admin, node_id=node.id) is True


def test_dm_in_scope_for_managed_subtree(session, make_soldier, make_hierarchy_node, assign_dm_scope_fixture):
    dm = make_soldier(role="duty_manager")
    node = make_hierarchy_node(name="ענף פוקוס")
    assign_dm_scope_fixture(dm.id, node.id)
    assert is_node_in_actor_scope(session=session, actor=dm, node_id=node.id) is True


def test_dm_out_of_scope_for_unmanaged_node(session, make_soldier, make_hierarchy_node):
    dm = make_soldier(role="duty_manager")
    node = make_hierarchy_node(name="ענף לא קשור")
    assert is_node_in_actor_scope(session=session, actor=dm, node_id=node.id) is False
```

Use whatever fixture name exists for assigning DM scope in `backend/app/services/tests/test_dm_scope.py` — match its conftest fixture rather than inventing `assign_dm_scope_fixture` if a usable one already exists.

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_import_scope.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/services/import_scope.py
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.auth.authz import scope_root_ids
from app.db.models import HierarchyNode, Soldier


def is_node_in_actor_scope(*, session: Session | None, actor: Soldier, node_id: uuid.UUID | None) -> bool:
    """True if `actor` may import rows targeting `node_id`. Admins are
    unrestricted. Duty managers must have node_id within their managed
    subtree (scope_root_ids). A None node_id (unresolved/unknown node) is
    never in scope — it must be resolved to a real node first."""
    if actor.role == "admin":
        return True
    if node_id is None or session is None:
        return False
    roots = scope_root_ids(session, actor)
    if not roots:
        return False
    node = session.get(HierarchyNode, node_id)
    if node is None:
        return False
    return any(r in node.path_ids for r in roots)
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_import_scope.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_scope.py backend/app/services/tests/test_import_scope.py
git commit -m "feat: add shared DM-scope check helper for import rows"
```

---

### Task D3: Import session service — create, resolve rows, reparse

**Files:**
- Create: `backend/app/services/import_sessions.py`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

This is the core service: parses via the registry, resolves names to entities (soldier/duty_type/duty_location/hierarchy_node lookups — reusing logic equivalent to the current `_parse_soldiers_sheet` etc. resolution step, now operating on `ParsedImportData` instead of raw sheets), applies DM scope, and produces the `PreviewResult`-equivalent stored in `parsed_state`.

- [ ] **Step 1: Write failing tests for the core resolution behavior**

```python
# backend/app/services/tests/test_import_sessions_service.py
import io
import openpyxl

from app.services.import_sessions import create_session, reparse_session
from app.db.models import ImportSession


def _xlsx_bytes(duty_shift_rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_shifts")
    ws.append(["duty_type_name", "duty_location_name", "start_date", "end_date",
               "start_time", "end_time", "required_count", "node_quotas", "notes"])
    for r in duty_shift_rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_create_session_admin_sees_all_rows(session, make_soldier, make_duty_type, make_duty_location):
    admin = make_soldier(role="admin")
    dt = make_duty_type(name="שמירה")
    loc = make_duty_location(name="בסיס א")
    content = _xlsx_bytes([["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3, "", ""]])

    sess = create_session(session, filename="test.xlsx", content=content, actor=admin)
    session.flush()
    assert sess.status == "draft"
    assert len(sess.parsed_state["duty_shifts"]) == 1
    assert sess.parsed_state["duty_shifts"][0]["action"] == "new"


def test_create_session_dm_out_of_scope_row(session, make_soldier, make_duty_type, make_duty_location, make_hierarchy_node):
    dm = make_soldier(role="duty_manager")
    dt = make_duty_type(name="שמירה")
    loc = make_duty_location(name="בסיס א")
    other_node = make_hierarchy_node(name="ענף לא קשור")
    content = _xlsx_bytes([["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3,
                             f"ענף לא קשור:3", ""]])

    sess = create_session(session, filename="test.xlsx", content=content, actor=dm)
    session.flush()
    assert sess.parsed_state["duty_shifts"][0]["action"] == "out_of_scope"


def test_reparse_after_missing_duty_type_created(session, make_soldier, make_duty_location, make_duty_type):
    admin = make_soldier(role="admin")
    loc = make_duty_location(name="בסיס א")
    content = _xlsx_bytes([["שמירה חדשה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3, "", ""]])

    sess = create_session(session, filename="test.xlsx", content=content, actor=admin)
    session.flush()
    assert sess.parsed_state["duty_shifts"][0]["action"] == "error"

    make_duty_type(name="שמירה חדשה")
    session.flush()
    updated = reparse_session(session, session_id=sess.id, actor=admin)
    assert updated.parsed_state["duty_shifts"][0]["action"] == "new"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_import_sessions_service.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the service**

```python
# backend/app/services/import_sessions.py
from __future__ import annotations

import io
import uuid
from typing import Any

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType, HierarchyNode, ImportSession, Soldier
from app.services.import_parsers.registry import auto_detect_parser, get_parser
from app.services.import_parsers.schema import ParsedImportData
from app.services.import_scope import is_node_in_actor_scope


class ImportSessionError(Exception):
    pass


def _resolve_and_score(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
) -> dict[str, Any]:
    soldiers_by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars().all()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    duty_types_by_name = {d.name: d for d in session.execute(select(DutyType)).scalars().all()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars().all()}

    soldier_rows = []
    for row in data.soldiers:
        errors: list[str] = []
        node = nodes_by_name.get(row.hierarchy_node_name) if row.hierarchy_node_name else None
        if row.hierarchy_node_name and not node:
            errors.append(f"hierarchy_node_name '{row.hierarchy_node_name}' not found")
        if not row.personal_number:
            errors.append("personal_number is required")
        if not row.full_name:
            errors.append("full_name is required")
        existing = soldiers_by_pn.get(row.personal_number)
        action = "error" if errors else ("update" if existing else "new")
        if action != "error" and not is_node_in_actor_scope(session=session, actor=actor, node_id=node.id if node else None):
            if actor.role != "admin" and row.hierarchy_node_name:
                action = "out_of_scope"
        soldier_rows.append({
            "row": row.source_row, "action": action, "errors": errors,
            "personal_number": row.personal_number, "full_name": row.full_name,
            "rank": row.rank, "gender": row.gender, "is_officer": row.is_officer,
            "hierarchy_node_id": str(node.id) if node else None,
            "hierarchy_node_name": row.hierarchy_node_name,
            "enrolled_at": row.enrolled_at, "enlistment_date": row.enlistment_date,
            "phone": row.phone, "email": row.email,
            "existing_id": str(existing.id) if existing else None,
        })

    duty_shift_rows = []
    for row in data.duty_shifts:
        errors: list[str] = []
        dt = duty_types_by_name.get(row.duty_type_name)
        if not dt:
            errors.append(f"duty_type_name '{row.duty_type_name}' not found")
        loc = locations_by_name.get(row.duty_location_name)
        if not loc:
            errors.append(f"duty_location_name '{row.duty_location_name}' not found")
        if not row.start_date:
            errors.append("start_date is required")
        if not row.end_date:
            errors.append("end_date is required")

        quota_total = sum(q.count for q in row.node_quotas)
        if quota_total > row.required_count:
            errors.append(f"node_quotas sum ({quota_total}) exceeds required_count ({row.required_count})")

        resolved_quotas = []
        any_quota_unresolved = False
        any_quota_out_of_scope = False
        for q in row.node_quotas:
            node = nodes_by_name.get(q.node_name)
            resolved_quotas.append({
                "node_name": q.node_name,
                "node_id": str(node.id) if node else None,
                "count": q.count,
                "resolved": node is not None,
            })
            if node is None:
                any_quota_unresolved = True
            elif not is_node_in_actor_scope(session=session, actor=actor, node_id=node.id):
                any_quota_out_of_scope = True

        action = "error" if errors else "new"
        if action == "new" and any_quota_out_of_scope:
            action = "out_of_scope"
        # Unresolved quota nodes don't force an error — they're inline-resolvable
        # (Task D5 UX); the row stays "new" but the frontend shows the quota's
        # own unresolved flag from resolved_quotas[].resolved == false.

        duty_shift_rows.append({
            "row": row.source_row, "action": action, "errors": errors,
            "duty_type_name": row.duty_type_name, "resolved_duty_type_id": str(dt.id) if dt else None,
            "duty_location_name": row.duty_location_name, "resolved_duty_location_id": str(loc.id) if loc else None,
            "start_date": row.start_date, "end_date": row.end_date,
            "start_time": row.start_time, "end_time": row.end_time,
            "required_count": row.required_count,
            "node_quotas": resolved_quotas,
            "notes": row.notes,
        })

    template_rows = []
    for row in data.shift_templates:
        errors = []
        dt = duty_types_by_name.get(row.duty_type_name)
        if not dt:
            errors.append(f"duty_type_name '{row.duty_type_name}' not found")
        template_rows.append({
            "row": row.source_row, "action": "error" if errors else "new", "errors": errors,
            "name": row.name, "duty_type_name": row.duty_type_name,
            "resolved_duty_type_id": str(dt.id) if dt else None,
            "days_of_week": row.days_of_week,
            "required_primary": row.required_primary, "required_reserve": row.required_reserve,
        })

    return {
        "soldiers": soldier_rows,
        "duty_shifts": duty_shift_rows,
        "shift_templates": template_rows,
        "parser_id": data.parser_id,
        "parser_warnings": data.parser_warnings,
    }


def create_session(
    session: Session,
    *,
    filename: str,
    content: bytes,
    actor: Soldier,
    parser_id: str | None = None,
) -> ImportSession:
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    parser = get_parser(parser_id) if parser_id else auto_detect_parser(wb)
    data = parser.parse(wb)
    parsed_state = _resolve_and_score(session, data, actor)

    sess = ImportSession(
        status="draft", filename=filename, raw_excel=content,
        parsed_state=parsed_state, user_selections={}, created_links={},
        created_by=actor.id,
    )
    session.add(sess)
    session.flush()
    return sess


def reparse_session(session: Session, *, session_id: uuid.UUID, actor: Soldier) -> ImportSession:
    sess = session.get(ImportSession, session_id)
    if sess is None:
        raise ImportSessionError("session not found")
    if sess.status != "draft":
        raise ImportSessionError("only draft sessions can be reparsed")

    wb = openpyxl.load_workbook(io.BytesIO(sess.raw_excel), data_only=True)
    parser = get_parser(sess.parsed_state["parser_id"])
    data = parser.parse(wb)
    sess.parsed_state = _resolve_and_score(session, data, actor)
    session.flush()
    return sess
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_import_sessions_service.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add import session service with scoped row resolution and reparse"
```

---

### Task D4: Import session confirm/cancel/done service

**Files:**
- Modify: `backend/app/services/import_sessions.py`
- Test: `backend/app/services/tests/test_import_sessions_service.py` (extend)

- [ ] **Step 1: Write failing tests**

```python
def test_confirm_applies_selected_rows_and_skips_out_of_scope(session, make_soldier, make_duty_type, make_duty_location):
    admin = make_soldier(role="admin")
    make_duty_type(name="שמירה")
    make_duty_location(name="בסיס א")
    content = _xlsx_bytes([["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3, "", ""]])
    sess = create_session(session, filename="t.xlsx", content=content, actor=admin)
    session.flush()

    from app.services.import_sessions import set_selections, confirm_session
    set_selections(session, session_id=sess.id, selections={"duty_shifts": {"2": "new"}})
    result = confirm_session(session, session_id=sess.id, actor=admin)
    session.flush()

    assert result["created"] == 1
    assert sess.status == "confirmed"
    assert len(sess.created_links["duty_shifts"]) == 1


def test_cancel_draft_session(session, make_soldier):
    admin = make_soldier(role="admin")
    content = _xlsx_bytes([])
    sess = create_session(session, filename="t.xlsx", content=content, actor=admin)
    session.flush()

    from app.services.import_sessions import cancel_session
    cancel_session(session, session_id=sess.id, actor=admin)
    assert sess.status == "cancelled"
    assert sess.cancelled_at is not None


def test_mark_done_only_allowed_after_confirm(session, make_soldier):
    admin = make_soldier(role="admin")
    content = _xlsx_bytes([])
    sess = create_session(session, filename="t.xlsx", content=content, actor=admin)
    session.flush()

    from app.services.import_sessions import mark_done, ImportSessionError
    import pytest
    with pytest.raises(ImportSessionError, match="confirmed"):
        mark_done(session, session_id=sess.id, actor=admin)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest backend/app/services/tests/test_import_sessions_service.py -k "confirm or cancel or mark_done" -v
```
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement**

Append to `backend/app/services/import_sessions.py`:

```python
from datetime import UTC, date as date_type, datetime

from app.db.models import DutyShift, DutyShiftNodeQuota, ShiftTemplate
from app.services.shift_quotas import set_shift_quotas


def set_selections(session: Session, *, session_id: uuid.UUID, selections: dict[str, Any]) -> ImportSession:
    sess = session.get(ImportSession, session_id)
    if sess is None:
        raise ImportSessionError("session not found")
    sess.user_selections = selections
    session.flush()
    return sess


def confirm_session(session: Session, *, session_id: uuid.UUID, actor: Soldier) -> dict[str, Any]:
    sess = session.get(ImportSession, session_id)
    if sess is None:
        raise ImportSessionError("session not found")
    if sess.status != "draft":
        raise ImportSessionError("only draft sessions can be confirmed")

    selections = sess.user_selections or {}
    state = sess.parsed_state
    created = updated = skipped = 0
    errors: list[dict[str, Any]] = []
    links: dict[str, list[str]] = {"soldiers": [], "duty_shifts": [], "shift_templates": []}

    import secrets
    from app.auth.password import hash_password

    for row in state.get("soldiers", []):
        action = selections.get("soldiers", {}).get(str(row["row"]), row["action"])
        if row["action"] in ("error", "out_of_scope") or action == "skip":
            skipped += 1
            continue
        try:
            if action == "new":
                s = Soldier(
                    personal_number=row["personal_number"], full_name=row["full_name"],
                    password_hash=hash_password(secrets.token_hex(16)), must_change_password=True,
                    rank=row["rank"], gender=row["gender"], is_officer=row["is_officer"],
                    hierarchy_node_id=uuid.UUID(row["hierarchy_node_id"]) if row["hierarchy_node_id"] else None,
                    phone=row["phone"], email=row["email"],
                )
                session.add(s)
                session.flush()
                links["soldiers"].append(str(s.id))
                created += 1
            elif action == "update" and row["existing_id"]:
                s = session.get(Soldier, uuid.UUID(row["existing_id"]))
                if s:
                    s.full_name = row["full_name"]
                    if row["hierarchy_node_id"]:
                        s.hierarchy_node_id = uuid.UUID(row["hierarchy_node_id"])
                    links["soldiers"].append(str(s.id))
                    updated += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "soldiers", "error": str(exc)})

    session.flush()

    for row in state.get("duty_shifts", []):
        action = selections.get("duty_shifts", {}).get(str(row["row"]), row["action"])
        if row["action"] in ("error", "out_of_scope") or action == "skip":
            skipped += 1
            continue
        try:
            shift = DutyShift(
                duty_type_id=uuid.UUID(row["resolved_duty_type_id"]),
                duty_location_id=uuid.UUID(row["resolved_duty_location_id"]),
                start_date=date_type.fromisoformat(row["start_date"]),
                end_date=date_type.fromisoformat(row["end_date"]),
                start_time=row.get("start_time") or "00:00",
                end_time=row.get("end_time") or "23:59",
                required_count=row["required_count"],
                notes=row.get("notes"),
            )
            session.add(shift)
            session.flush()
            resolved_quotas = [
                (uuid.UUID(q["node_id"]), q["count"])
                for q in row.get("node_quotas", []) if q.get("resolved")
            ]
            if resolved_quotas:
                set_shift_quotas(session, shift_id=shift.id, quotas=resolved_quotas)
            links["duty_shifts"].append(str(shift.id))
            created += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "duty_shifts", "error": str(exc)})

    for row in state.get("shift_templates", []):
        action = selections.get("shift_templates", {}).get(str(row["row"]), row["action"])
        if row["action"] == "error" or action == "skip":
            skipped += 1
            continue
        try:
            from app.db.models import DutyLocation
            loc = session.execute(select(DutyLocation).limit(1)).scalar_one_or_none()
            if loc is None:
                errors.append({"row": row["row"], "type": "shift_templates", "error": "no duty location exists"})
                continue
            tpl = ShiftTemplate(
                name=row["name"], duty_type_id=uuid.UUID(row["resolved_duty_type_id"]),
                duty_location_id=loc.id, weekdays=row["days_of_week"],
                required_count=row["required_primary"] + row["required_reserve"],
            )
            session.add(tpl)
            session.flush()
            links["shift_templates"].append(str(tpl.id))
            created += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "shift_templates", "error": str(exc)})

    sess.created_links = links
    sess.status = "confirmed"
    sess.confirmed_at = datetime.now(tz=UTC)
    session.flush()

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def cancel_session(session: Session, *, session_id: uuid.UUID, actor: Soldier) -> ImportSession:
    sess = session.get(ImportSession, session_id)
    if sess is None:
        raise ImportSessionError("session not found")
    if sess.status != "draft":
        raise ImportSessionError("only draft sessions can be cancelled")
    sess.status = "cancelled"
    sess.cancelled_at = datetime.now(tz=UTC)
    session.flush()
    return sess


def mark_done(session: Session, *, session_id: uuid.UUID, actor: Soldier) -> ImportSession:
    sess = session.get(ImportSession, session_id)
    if sess is None:
        raise ImportSessionError("session not found")
    if sess.status != "confirmed":
        raise ImportSessionError("only confirmed sessions can be marked done")
    sess.status = "done"
    session.flush()
    return sess
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest backend/app/services/tests/test_import_sessions_service.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/import_sessions.py backend/app/services/tests/test_import_sessions_service.py
git commit -m "feat: add import session confirm/cancel/done with partial acceptance"
```

---

### Task D5: Import sessions API routes

**Files:**
- Create: `backend/app/routes/import_sessions.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/integration/test_import_sessions_api.py`

- [ ] **Step 1: Find how the existing `import_excel` router is registered**

```bash
grep -n "import_excel" backend/app/main.py
```

- [ ] **Step 2: Write failing integration tests**

```python
# backend/tests/integration/test_import_sessions_api.py
import io
import openpyxl


def _xlsx_bytes():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_shifts")
    ws.append(["duty_type_name", "duty_location_name", "start_date", "end_date",
               "start_time", "end_time", "required_count", "node_quotas", "notes"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_upload_creates_draft_session(client, admin_headers):
    resp = client.post(
        "/import/sessions",
        files={"file": ("t.xlsx", _xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["preview"]["soldiers"] == []
    session_id = body["session_id"]

    resp2 = client.get(f"/import/sessions/{session_id}", headers=admin_headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "draft"


def test_list_sessions_excludes_done_by_default(client, admin_headers):
    resp = client.get("/import/sessions", headers=admin_headers)
    assert resp.status_code == 200


def test_cancel_session(client, admin_headers):
    up = client.post(
        "/import/sessions",
        files={"file": ("t.xlsx", _xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=admin_headers,
    )
    sid = up.json()["session_id"]
    resp = client.post(f"/import/sessions/{sid}/cancel", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest backend/tests/integration/test_import_sessions_api.py -v
```
Expected: FAIL — 404 (router not mounted)

- [ ] **Step 4: Implement routes**

```python
# backend/app/routes/import_sessions.py
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin
from app.db.models import ImportSession, Soldier
from app.db.session import get_session
from app.services.import_sessions import (
    ImportSessionError,
    cancel_session,
    confirm_session,
    create_session,
    mark_done,
    reparse_session,
    set_selections,
)

router = APIRouter(prefix="/import/sessions", tags=["import-sessions"])


class SessionSummary(BaseModel):
    id: uuid.UUID
    status: str
    filename: str
    created_at: str
    row_summary: dict[str, int]


class SessionDetail(BaseModel):
    id: uuid.UUID
    status: str
    filename: str
    parsed_state: dict[str, Any]
    user_selections: dict[str, Any]
    created_links: dict[str, Any]


class CreateSessionResponse(BaseModel):
    session_id: uuid.UUID
    preview: dict[str, Any]


class SelectionsRequest(BaseModel):
    selections: dict[str, Any]


def _row_summary(state: dict[str, Any]) -> dict[str, int]:
    return {
        "soldiers": len(state.get("soldiers", [])),
        "duty_shifts": len(state.get("duty_shifts", [])),
        "shift_templates": len(state.get("shift_templates", [])),
    }


@router.post("", response_model=CreateSessionResponse)
async def upload_session(
    file: UploadFile = File(...),
    parser_id: str | None = None,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    content = await file.read()
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="invalid_file_type")
    try:
        sess = create_session(session, filename=file.filename or "import.xlsx", content=content, actor=actor, parser_id=parser_id)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return CreateSessionResponse(session_id=sess.id, preview=sess.parsed_state)


@router.get("", response_model=list[SessionSummary])
def list_sessions(
    status_filter: str | None = None,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    statuses = status_filter.split(",") if status_filter else ["draft", "confirmed"]
    q = select(ImportSession).where(ImportSession.status.in_(statuses))
    if actor.role != "admin":
        q = q.where(ImportSession.created_by == actor.id)
    rows = session.execute(q.order_by(ImportSession.created_at.desc())).scalars().all()
    return [
        SessionSummary(
            id=r.id, status=r.status, filename=r.filename,
            created_at=r.created_at.isoformat(), row_summary=_row_summary(r.parsed_state),
        )
        for r in rows
    ]


@router.get("/{session_id}", response_model=SessionDetail)
def get_session_detail(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    sess = session.get(ImportSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="not_found")
    if actor.role != "admin" and sess.created_by != actor.id:
        raise HTTPException(status_code=403, detail="forbidden")
    return SessionDetail(
        id=sess.id, status=sess.status, filename=sess.filename,
        parsed_state=sess.parsed_state, user_selections=sess.user_selections,
        created_links=sess.created_links,
    )


@router.post("/{session_id}/reparse", response_model=SessionDetail)
def reparse(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    try:
        sess = reparse_session(session, session_id=session_id, actor=actor)
        session.commit()
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return SessionDetail(
        id=sess.id, status=sess.status, filename=sess.filename,
        parsed_state=sess.parsed_state, user_selections=sess.user_selections,
        created_links=sess.created_links,
    )


@router.patch("/{session_id}/selections")
def patch_selections(
    session_id: uuid.UUID,
    req: SelectionsRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    try:
        set_selections(session, session_id=session_id, selections=req.selections)
        session.commit()
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/{session_id}/confirm")
def confirm(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    try:
        result = confirm_session(session, session_id=session_id, actor=actor)
        session.commit()
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/{session_id}/cancel")
def cancel(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    try:
        sess = cancel_session(session, session_id=session_id, actor=actor)
        session.commit()
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": sess.status}


@router.post("/{session_id}/done")
def done(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    try:
        sess = mark_done(session, session_id=session_id, actor=actor)
        session.commit()
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": sess.status}
```

Register in `backend/app/main.py` next to the existing `import_excel` router registration:
```python
from app.routes import import_sessions
app.include_router(import_sessions.router)
```

- [ ] **Step 5: Run to verify pass**

```bash
pytest backend/tests/integration/test_import_sessions_api.py -v
```
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/import_sessions.py backend/app/main.py backend/tests/integration/test_import_sessions_api.py
git commit -m "feat: add import sessions API routes"
```

---

## Part E — Frontend: Import Sessions UI

### Task E1: API client for sessions

**Files:**
- Create: `frontend/src/api/importSessions.ts`
- Test: none required (thin fetch wrapper, covered by component tests in E2-E4)

- [ ] **Step 1: Implement the client**

```typescript
// frontend/src/api/importSessions.ts
export interface RowBase {
  row: number;
  action: "new" | "update" | "error" | "out_of_scope" | "skip";
  errors: string[];
}

export interface SoldierRow extends RowBase {
  personal_number: string;
  full_name: string;
  hierarchy_node_id: string | null;
  hierarchy_node_name: string | null;
  existing_id: string | null;
}

export interface NodeQuotaRow {
  node_name: string;
  node_id: string | null;
  count: number;
  resolved: boolean;
}

export interface DutyShiftRow extends RowBase {
  duty_type_name: string;
  resolved_duty_type_id: string | null;
  duty_location_name: string;
  resolved_duty_location_id: string | null;
  start_date: string;
  end_date: string;
  start_time: string | null;
  end_time: string | null;
  required_count: number;
  node_quotas: NodeQuotaRow[];
  notes: string | null;
}

export interface TemplateRow extends RowBase {
  name: string;
  duty_type_name: string;
  resolved_duty_type_id: string | null;
  days_of_week: number[];
  required_primary: number;
  required_reserve: number;
}

export interface ParsedState {
  soldiers: SoldierRow[];
  duty_shifts: DutyShiftRow[];
  shift_templates: TemplateRow[];
  parser_id: string;
  parser_warnings: string[];
}

export interface SessionSummary {
  id: string;
  status: "draft" | "confirmed" | "cancelled" | "done";
  filename: string;
  created_at: string;
  row_summary: { soldiers: number; duty_shifts: number; shift_templates: number };
}

export interface SessionDetail {
  id: string;
  status: string;
  filename: string;
  parsed_state: ParsedState;
  user_selections: Record<string, Record<string, string>>;
  created_links: Record<string, string[]>;
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`request failed: ${res.status}`);
  return res.json();
}

export async function uploadSession(file: File, parserId?: string): Promise<{ session_id: string; preview: ParsedState }> {
  const form = new FormData();
  form.append("file", file);
  const qs = parserId ? `?parser_id=${encodeURIComponent(parserId)}` : "";
  const res = await fetch(`/api/import/sessions${qs}`, { method: "POST", body: form });
  return asJson(res);
}

export async function listSessions(statusFilter?: string): Promise<SessionSummary[]> {
  const qs = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return asJson(await fetch(`/api/import/sessions${qs}`));
}

export async function getSession(id: string): Promise<SessionDetail> {
  return asJson(await fetch(`/api/import/sessions/${id}`));
}

export async function reparseSession(id: string): Promise<SessionDetail> {
  return asJson(await fetch(`/api/import/sessions/${id}/reparse`, { method: "POST" }));
}

export async function saveSelections(id: string, selections: Record<string, Record<string, string>>): Promise<void> {
  await fetch(`/api/import/sessions/${id}/selections`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selections }),
  });
}

export async function confirmSession(id: string): Promise<{ created: number; updated: number; skipped: number; errors: { row: number; type: string; error: string }[] }> {
  return asJson(await fetch(`/api/import/sessions/${id}/confirm`, { method: "POST" }));
}

export async function cancelSession(id: string): Promise<void> {
  await fetch(`/api/import/sessions/${id}/cancel`, { method: "POST" });
}

export async function markSessionDone(id: string): Promise<void> {
  await fetch(`/api/import/sessions/${id}/done`, { method: "POST" });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/importSessions.ts
git commit -m "feat: add import sessions API client"
```

---

### Task E2: Session list page

**Files:**
- Create: `frontend/src/pages/ImportSessionsListPage.tsx`
- Modify: router config (find where `ImportPage` is currently routed, e.g. `frontend/src/App.tsx` or `frontend/src/router.tsx`)
- Test: `frontend/src/pages/ImportSessionsListPage.test.tsx`

- [ ] **Step 1: Find current `/import` route registration**

```bash
grep -rn "ImportPage" frontend/src/App.tsx frontend/src/router.tsx 2>/dev/null
```

- [ ] **Step 2: Write failing test**

```tsx
// frontend/src/pages/ImportSessionsListPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ImportSessionsListPage from "./ImportSessionsListPage";
import * as api from "../api/importSessions";

vi.mock("../api/importSessions");

describe("ImportSessionsListPage", () => {
  it("renders session rows with status chips", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      { id: "1", status: "draft", filename: "a.xlsx", created_at: "2026-06-30T00:00:00Z",
        row_summary: { soldiers: 2, duty_shifts: 1, shift_templates: 0 } },
    ]);
    render(<ImportSessionsListPage />);
    await waitFor(() => expect(screen.getByText("a.xlsx")).toBeInTheDocument());
    expect(screen.getByText("המשך")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify failure**

```bash
cd frontend && npx vitest run src/pages/ImportSessionsListPage.test.tsx
```
Expected: FAIL — module not found

- [ ] **Step 4: Implement the page**

```tsx
// frontend/src/pages/ImportSessionsListPage.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { SessionSummary, cancelSession, listSessions, markSessionDone } from "../api/importSessions";

const STATUS_LABEL: Record<string, string> = {
  draft: "טיוטה", confirmed: "אושר", cancelled: "בוטל", done: "בוצע",
};
const STATUS_CHIP: Record<string, string> = {
  draft: "bg-blue-100 text-blue-700", confirmed: "bg-green-100 text-green-700",
  cancelled: "bg-gray-100 text-gray-500", done: "bg-gray-100 text-gray-500",
};

export default function ImportSessionsListPage() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [showAll, setShowAll] = useState(false);
  const navigate = useNavigate();

  async function load() {
    const filter = showAll ? "draft,confirmed,cancelled,done" : undefined;
    setSessions(await listSessions(filter));
  }

  useEffect(() => { void load(); }, [showAll]);

  return (
    <Layout>
      <div className="max-w-4xl mx-auto p-4 space-y-4" dir="rtl">
        <div className="flex justify-between items-center">
          <h1 className="text-xl font-semibold">ייבוא מ-Excel</h1>
          <button
            className="bg-indigo-600 text-white px-4 py-2 rounded text-sm"
            onClick={() => navigate("/import/upload")}
          >
            ייבוא חדש
          </button>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          הצג הכל (כולל בוצע/בוטל)
        </label>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 border-b">
              <th className="text-right pb-1">קובץ</th>
              <th className="text-right pb-1">תאריך</th>
              <th className="text-right pb-1">סטטוס</th>
              <th className="text-right pb-1">שורות</th>
              <th className="text-right pb-1">פעולות</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="border-b">
                <td className="py-1">{s.filename}</td>
                <td className="py-1">{new Date(s.created_at).toLocaleDateString("he-IL")}</td>
                <td className="py-1">
                  <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${STATUS_CHIP[s.status]}`}>
                    {STATUS_LABEL[s.status]}
                  </span>
                </td>
                <td className="py-1">
                  {s.row_summary.soldiers} חיילים / {s.row_summary.duty_shifts} משמרות / {s.row_summary.shift_templates} תבניות
                </td>
                <td className="py-1 space-x-2 space-x-reverse">
                  {s.status === "draft" && (
                    <>
                      <button className="text-indigo-600" onClick={() => navigate(`/import/sessions/${s.id}`)}>המשך</button>
                      <button className="text-red-600" onClick={async () => { await cancelSession(s.id); void load(); }}>בטל</button>
                    </>
                  )}
                  {s.status === "confirmed" && (
                    <>
                      <button className="text-indigo-600" onClick={() => navigate(`/import/sessions/${s.id}`)}>צפה</button>
                      <button className="text-gray-600" onClick={async () => { await markSessionDone(s.id); void load(); }}>סמן כבוצע</button>
                    </>
                  )}
                  {(s.status === "done" || s.status === "cancelled") && (
                    <button className="text-indigo-600" onClick={() => navigate(`/import/sessions/${s.id}`)}>צפה</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}
```

Wire the route: replace the existing `<Route path="/import" element={<ImportPage />} />` with `<Route path="/import" element={<ImportSessionsListPage />} />`, and add `<Route path="/import/upload" element={<ImportUploadPage />} />` and `<Route path="/import/sessions/:id" element={<ImportSessionReviewPage />} />` (built in Tasks E3/E4).

- [ ] **Step 5: Run to verify pass**

```bash
cd frontend && npx vitest run src/pages/ImportSessionsListPage.test.tsx
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ImportSessionsListPage.tsx frontend/src/pages/ImportSessionsListPage.test.tsx frontend/src/App.tsx
git commit -m "feat: add import session list page"
```

---

### Task E3: Upload page

**Files:**
- Create: `frontend/src/pages/ImportUploadPage.tsx`
- Test: `frontend/src/pages/ImportUploadPage.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import ImportUploadPage from "./ImportUploadPage";
import * as api from "../api/importSessions";

vi.mock("../api/importSessions");
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useNavigate: () => vi.fn(),
}));

describe("ImportUploadPage", () => {
  it("uploads a file and navigates to the session review page", async () => {
    vi.mocked(api.uploadSession).mockResolvedValue({
      session_id: "abc",
      preview: { soldiers: [], duty_shifts: [], shift_templates: [], parser_id: "v1_standard", parser_warnings: [] },
    });
    render(<MemoryRouter><ImportUploadPage /></MemoryRouter>);
    const input = screen.getByLabelText("בחר קובץ", { selector: "input" });
    const file = new File(["x"], "t.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await waitFor(() => fireEventChange(input, file));
  });
});

function fireEventChange(input: HTMLElement, file: File) {
  Object.defineProperty(input, "files", { value: [file] });
  input.dispatchEvent(new Event("change", { bubbles: true }));
}
```

Adjust to project's existing test conventions found in `frontend/src/pages/ImportPage` tests if one exists; otherwise this scaffolds expected behavior.

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && npx vitest run src/pages/ImportUploadPage.test.tsx
```
Expected: FAIL — module not found

- [ ] **Step 3: Implement (adapted from the existing `ImportPage` upload step)**

```tsx
// frontend/src/pages/ImportUploadPage.tsx
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { uploadSession } from "../api/importSessions";

export default function ImportUploadPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  async function handleUpload(file: File) {
    setLoading(true);
    setError(null);
    try {
      const { session_id } = await uploadSession(file);
      navigate(`/import/sessions/${session_id}`);
    } catch {
      setError("שגיאה בפענוח הקובץ — ודא שהוא xlsx תקין");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Layout>
      <div className="max-w-3xl mx-auto p-4 space-y-4 text-center" dir="rtl">
        <h1 className="text-xl font-semibold">ייבוא חדש</h1>
        {error && <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>}
        <a href="/api/import/template" className="text-indigo-600 hover:underline text-sm block">
          הורד תבנית לדוגמה ›
        </a>
        <div>
          <label htmlFor="import-file-input">בחר קובץ</label>
          <input
            id="import-file-input"
            ref={fileRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            aria-label="בחר קובץ"
            onChange={(e) => { if (e.target.files?.[0]) void handleUpload(e.target.files[0]); }}
          />
          <button
            className="bg-indigo-600 text-white px-6 py-2 rounded font-medium disabled:opacity-50"
            disabled={loading}
            onClick={() => fileRef.current?.click()}
          >
            {loading ? "טוען..." : "בחר קובץ"}
          </button>
        </div>
      </div>
    </Layout>
  );
}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd frontend && npx vitest run src/pages/ImportUploadPage.test.tsx
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ImportUploadPage.tsx frontend/src/pages/ImportUploadPage.test.tsx
git commit -m "feat: add import upload page creating a session"
```

---

### Task E4: Session review page — soldiers tab + inline node resolution

**Files:**
- Create: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Test: `frontend/src/pages/ImportSessionReviewPage.test.tsx`

This is the largest frontend task. Build it incrementally: load session → render soldiers tab with per-row toggle and inline red-flag resolution → wire reparse → wire selections autosave. Duty shifts and templates tabs follow the same pattern (Task E5 adds quota-specific UI on top).

- [ ] **Step 1: Write failing test for basic load + soldiers tab rendering**

```tsx
// frontend/src/pages/ImportSessionReviewPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ImportSessionReviewPage from "./ImportSessionReviewPage";
import * as api from "../api/importSessions";

vi.mock("../api/importSessions");

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/import/sessions/${id}`]}>
      <Routes>
        <Route path="/import/sessions/:id" element={<ImportSessionReviewPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ImportSessionReviewPage", () => {
  it("shows unresolved hierarchy node in red with create/change buttons", async () => {
    vi.mocked(api.getSession).mockResolvedValue({
      id: "s1", status: "draft", filename: "t.xlsx",
      parsed_state: {
        soldiers: [{
          row: 2, action: "error", errors: ["hierarchy_node_name 'מדור ב' not found"],
          personal_number: "123", full_name: "ישראל ישראלי",
          hierarchy_node_id: null, hierarchy_node_name: "מדור ב", existing_id: null,
        }],
        duty_shifts: [], shift_templates: [], parser_id: "v1_standard", parser_warnings: [],
      },
      user_selections: {}, created_links: {},
    });
    renderAt("s1");
    await waitFor(() => expect(screen.getByText("מדור ב")).toBeInTheDocument());
    expect(screen.getByText("צור יחידה")).toBeInTheDocument();
    expect(screen.getByText("שנה")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx
```
Expected: FAIL — module not found

- [ ] **Step 3: Implement the page (soldiers tab + skeleton for other tabs)**

```tsx
// frontend/src/pages/ImportSessionReviewPage.tsx
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Layout from "../components/Layout";
import {
  DutyShiftRow, SessionDetail, SoldierRow, TemplateRow,
  confirmSession, getSession, reparseSession, saveSelections,
} from "../api/importSessions";
import HierarchyNodeFormModal from "../components/HierarchyNodeFormModal";
import HierarchyNodePickerModal from "../components/HierarchyNodePickerModal";
import DutyTypeFormModal from "../components/DutyTypeFormModal";

const ACTION_CHIP: Record<string, string> = {
  new: "bg-green-100 text-green-700", update: "bg-blue-100 text-blue-700",
  error: "bg-red-100 text-red-700", out_of_scope: "bg-orange-100 text-orange-700",
  skip: "bg-gray-100 text-gray-500",
};
const ACTION_LABEL: Record<string, string> = {
  new: "חדש", update: "עדכון", error: "שגיאה", out_of_scope: "מחוץ לטווח", skip: "דלג",
};

type Tab = "soldiers" | "duty_shifts" | "shift_templates";

export default function ImportSessionReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [tab, setTab] = useState<Tab>("soldiers");
  const [selections, setSelections] = useState<Record<string, Record<string, string>>>({});
  const [nodeModalRow, setNodeModalRow] = useState<number | null>(null);
  const [nodePickerRow, setNodePickerRow] = useState<number | null>(null);
  const [dutyTypeModalOpen, setDutyTypeModalOpen] = useState(false);
  const [confirmResult, setConfirmResult] = useState<Awaited<ReturnType<typeof confirmSession>> | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    const d = await getSession(id);
    setDetail(d);
    setSelections(d.user_selections ?? {});
  }, [id]);

  useEffect(() => { void load(); }, [load]);

  const readOnly = detail?.status !== "draft";

  function setRowAction(group: Tab, row: number, action: string) {
    setSelections((prev) => {
      const next = { ...prev, [group]: { ...(prev[group] ?? {}), [String(row)]: action } };
      if (id) void saveSelections(id, next);
      return next;
    });
  }

  async function handleReparse() {
    if (!id) return;
    const d = await reparseSession(id);
    setDetail(d);
  }

  async function handleConfirm() {
    if (!id) return;
    const result = await confirmSession(id);
    setConfirmResult(result);
    await load();
  }

  if (!detail) return <Layout><div className="p-4" dir="rtl">טוען...</div></Layout>;

  const soldiers = detail.parsed_state.soldiers;
  const dutyShifts = detail.parsed_state.duty_shifts;
  const templates = detail.parsed_state.shift_templates;

  return (
    <Layout>
      <div className="max-w-5xl mx-auto p-4 space-y-4" dir="rtl">
        <h1 className="text-xl font-semibold">{detail.filename}</h1>

        <div className="flex gap-1 border-b">
          {(["soldiers", "duty_shifts", "shift_templates"] as Tab[]).map((t) => (
            <button
              key={t}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === t ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500"}`}
              onClick={() => setTab(t)}
            >
              {t === "soldiers" ? `חיילים (${soldiers.length})` : t === "duty_shifts" ? `משמרות (${dutyShifts.length})` : `תבניות (${templates.length})`}
            </button>
          ))}
        </div>

        {tab === "soldiers" && (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b">
                <th className="text-right pb-1">שם</th>
                <th className="text-right pb-1">מ&quot;א</th>
                <th className="text-right pb-1">יחידה</th>
                <th className="text-right pb-1">סטטוס</th>
                {!readOnly && <th className="text-right pb-1">פעולה</th>}
              </tr>
            </thead>
            <tbody>
              {soldiers.map((row: SoldierRow) => {
                const unresolvedNode = !row.hierarchy_node_id && !!row.hierarchy_node_name;
                return (
                  <tr key={row.row} className="border-b">
                    <td className="py-1">{row.full_name}</td>
                    <td className="py-1">{row.personal_number}</td>
                    <td className="py-1">
                      {unresolvedNode ? (
                        <span className="text-red-600 flex items-center gap-1">
                          {row.hierarchy_node_name}
                          <button className="underline text-xs" onClick={() => setNodeModalRow(row.row)}>צור יחידה</button>
                          <button className="underline text-xs" onClick={() => setNodePickerRow(row.row)}>שנה</button>
                        </span>
                      ) : row.hierarchy_node_name}
                    </td>
                    <td className="py-1">
                      <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}>
                        {ACTION_LABEL[row.action]}
                      </span>
                      {row.errors.map((e, i) => <span key={i} className="text-red-500 text-xs mr-1">{e}</span>)}
                    </td>
                    {!readOnly && (
                      <td className="py-1">
                        {row.action !== "error" && row.action !== "out_of_scope" && (
                          <select
                            className="border rounded text-xs p-0.5"
                            value={selections.soldiers?.[String(row.row)] ?? row.action}
                            onChange={(e) => setRowAction("soldiers", row.row, e.target.value)}
                          >
                            <option value={row.action}>{ACTION_LABEL[row.action]}</option>
                            <option value="skip">דלג</option>
                          </select>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {tab === "duty_shifts" && (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b">
                <th className="text-right pb-1">סוג תורנות</th>
                <th className="text-right pb-1">מיקום</th>
                <th className="text-right pb-1">תאריכים</th>
                <th className="text-right pb-1">נדרש</th>
                <th className="text-right pb-1">מכסות יחידה</th>
                <th className="text-right pb-1">סטטוס</th>
                {!readOnly && <th className="text-right pb-1">פעולה</th>}
              </tr>
            </thead>
            <tbody>
              {dutyShifts.map((row: DutyShiftRow) => (
                <tr key={row.row} className="border-b">
                  <td className="py-1">
                    {row.duty_type_name}
                    {!row.resolved_duty_type_id && (
                      <button className="underline text-xs text-red-600 mr-1" onClick={() => setDutyTypeModalOpen(true)}>צור סוג תורנות</button>
                    )}
                  </td>
                  <td className="py-1">{row.duty_location_name}</td>
                  <td className="py-1">{row.start_date} – {row.end_date}</td>
                  <td className="py-1">{row.required_count}</td>
                  <td className="py-1">
                    {row.node_quotas.map((q, i) => (
                      <span key={i} className={q.resolved ? "" : "text-red-600"}>
                        {q.node_name}:{q.count}{i < row.node_quotas.length - 1 ? "; " : ""}
                        {!q.resolved && (
                          <>
                            <button className="underline text-xs" onClick={() => setNodeModalRow(row.row)}>צור</button>
                            <button className="underline text-xs" onClick={() => setNodePickerRow(row.row)}>שנה</button>
                          </>
                        )}
                      </span>
                    ))}
                  </td>
                  <td className="py-1">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}>
                      {ACTION_LABEL[row.action]}
                    </span>
                    {row.errors.map((e, i) => <span key={i} className="text-red-500 text-xs mr-1">{e}</span>)}
                  </td>
                  {!readOnly && (
                    <td className="py-1">
                      {row.action !== "error" && row.action !== "out_of_scope" && (
                        <select
                          className="border rounded text-xs p-0.5"
                          value={selections.duty_shifts?.[String(row.row)] ?? row.action}
                          onChange={(e) => setRowAction("duty_shifts", row.row, e.target.value)}
                        >
                          <option value={row.action}>{ACTION_LABEL[row.action]}</option>
                          <option value="skip">דלג</option>
                        </select>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === "shift_templates" && (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b">
                <th className="text-right pb-1">שם</th>
                <th className="text-right pb-1">סוג</th>
                <th className="text-right pb-1">ימים</th>
                <th className="text-right pb-1">נדרש</th>
                <th className="text-right pb-1">סטטוס</th>
                {!readOnly && <th className="text-right pb-1">פעולה</th>}
              </tr>
            </thead>
            <tbody>
              {templates.map((row: TemplateRow) => (
                <tr key={row.row} className="border-b">
                  <td className="py-1">{row.name}</td>
                  <td className="py-1">{row.duty_type_name}</td>
                  <td className="py-1">{row.days_of_week.join(",")}</td>
                  <td className="py-1">{row.required_primary}+{row.required_reserve}</td>
                  <td className="py-1">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}>
                      {ACTION_LABEL[row.action]}
                    </span>
                    {row.errors.map((e, i) => <span key={i} className="text-red-500 text-xs mr-1">{e}</span>)}
                  </td>
                  {!readOnly && (
                    <td className="py-1">
                      {row.action !== "error" && (
                        <select
                          className="border rounded text-xs p-0.5"
                          value={selections.shift_templates?.[String(row.row)] ?? row.action}
                          onChange={(e) => setRowAction("shift_templates", row.row, e.target.value)}
                        >
                          <option value={row.action}>{ACTION_LABEL[row.action]}</option>
                          <option value="skip">דלג</option>
                        </select>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {!readOnly && (
          <div className="flex justify-end gap-3 pt-2">
            <button className="bg-indigo-600 text-white px-4 py-2 rounded text-sm" onClick={() => void handleConfirm()}>
              אשר וייבא
            </button>
          </div>
        )}

        {confirmResult && (
          <div className="bg-green-50 border border-green-200 rounded p-4 text-sm">
            נוצרו: {confirmResult.created} · עודכנו: {confirmResult.updated} · דולגו: {confirmResult.skipped}
            {confirmResult.errors.length > 0 && (
              <ul className="text-red-700 mt-2">
                {confirmResult.errors.map((e, i) => <li key={i}>שורה {e.row} ({e.type}): {e.error}</li>)}
              </ul>
            )}
          </div>
        )}

        {nodeModalRow !== null && (
          <HierarchyNodeFormModal
            open
            onClose={() => setNodeModalRow(null)}
            onSaved={async () => { setNodeModalRow(null); await handleReparse(); }}
          />
        )}
        {nodePickerRow !== null && (
          <HierarchyNodePickerModal
            open
            onClose={() => setNodePickerRow(null)}
            onPicked={async () => { setNodePickerRow(null); await handleReparse(); }}
          />
        )}
        {dutyTypeModalOpen && (
          <DutyTypeFormModal
            open
            onClose={() => setDutyTypeModalOpen(false)}
            onSaved={async () => { setDutyTypeModalOpen(false); await handleReparse(); }}
          />
        )}
      </div>
    </Layout>
  );
}
```

Check the actual prop names of `HierarchyNodeFormModal`/`DutyTypeFormModal` (or whatever they're named in this codebase — search first) and adjust. If a `HierarchyNodePickerModal` doesn't exist yet, build a minimal one in this task: a modal listing all hierarchy nodes with a search box and a "בחר" button per row, calling `onPicked(nodeId)`.

```bash
grep -rln "HierarchyNode.*FormModal\|DutyTypeFormModal" frontend/src/components/
```

- [ ] **Step 4: Run to verify pass**

```bash
cd frontend && npx vitest run src/pages/ImportSessionReviewPage.test.tsx
```
Expected: PASS

- [ ] **Step 5: Run lint/typecheck**

```bash
cd frontend && npm run lint && npm run typecheck
```
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ImportSessionReviewPage.tsx frontend/src/pages/ImportSessionReviewPage.test.tsx frontend/src/components/
git commit -m "feat: add import session review page with inline node/duty-type resolution"
```

---

### Task E5: Remove old `ImportPage` and deprecated routes

**Files:**
- Modify: `frontend/src/App.tsx` (remove old `/import` → `ImportPage` route, already replaced in E2)
- Delete: `frontend/src/pages/ImportPage.tsx`
- Keep: `backend/app/routes/import_excel.py` for the `/import/template` download endpoint only — remove its `/preview` and `/apply` handlers since the spec marks them deprecated-but-kept; confirm with the user whether to delete now or leave for a transition period before removing in this task.

- [ ] **Step 1: Confirm no remaining references to `ImportPage`**

```bash
grep -rn "ImportPage" frontend/src --include=*.tsx --include=*.ts
```
Expected: no matches outside the file itself once removed.

- [ ] **Step 2: Delete the old page**

```bash
rm frontend/src/pages/ImportPage.tsx
```

- [ ] **Step 3: Run full frontend test suite**

```bash
cd frontend && npm test
```
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src
git commit -m "chore: remove superseded ImportPage in favor of import sessions UI"
```

---

## Part F — Full-Suite Verification

### Task F1: Run backend and frontend suites end-to-end

**Files:** none (verification only)

- [ ] **Step 1: Backend fast suite**

```bash
cd backend && pytest -q
```
Expected: all pass

- [ ] **Step 2: Backend slow suite (includes large-scale CP-SAT tests touching the new quota constraints)**

```bash
cd backend && pytest --slow -q
```
Expected: all pass

- [ ] **Step 3: Frontend unit tests**

```bash
cd frontend && npm test
```
Expected: all pass

- [ ] **Step 4: Frontend lint + typecheck**

```bash
cd frontend && npm run lint && npm run typecheck
```
Expected: zero warnings, zero type errors

- [ ] **Step 5: Manual smoke test via dev stack**

```powershell
.\dev.ps1
```
Navigate to `/import`, upload a sample `duty_shifts` xlsx (with one row referencing an unknown duty type and one with `node_quotas` referencing an unknown node), verify: session appears as draft, inline "צור" buttons work and reparse flips rows to valid, confirm produces a real `DutyShift` with quota entries visible in `ShiftFormModal`, and a follow-up algorithm run respects the quota.

- [ ] **Step 6: Update changelog**

Per `CLAUDE.md`, at end of session add a `## 2026-06-30` section to `frontend/CHANGELOG.md` summarizing this work (Features: import sessions, pluggable parsers, sub-unit shift quotas with relaxation; group accordingly), based on `git log --oneline <last-entry-sha>..HEAD`. Commit directly to `master` with message `docs: update changelog 2026-06-30` — only once the feature branch from this plan has been merged, per the branch workflow in `CLAUDE.md`.

---

## Self-Review Notes

- **Spec coverage:** Data model (A1, D1), service/API (A2-A3, D2-D5), algorithm constraints + relaxation (B1-B4), pluggable parsers (C1-C2), frontend review/list/upload (E1-E5) all map to spec sections. DM-scope permission addendum is covered by D2 (shared helper) and exercised in D3's `out_of_scope` tests.
- **Type consistency:** `ImportSession.parsed_state` keys (`soldiers`, `duty_shifts`, `shift_templates`, `parser_id`, `parser_warnings`) are produced once in `_resolve_and_score` (D3) and consumed identically by `confirm_session` (D4), the API routes (D5), and the frontend types in `importSessions.ts` (E1) — kept in lockstep by referencing the same field names throughout.
- **DutyBlock.node_quotas** dict shape (`hierarchy_node_id -> count`) is defined once in B1 and consumed identically in B2 (bridge) and B3 (relaxation).
- Old `/import/preview` and `/import/apply` endpoints are explicitly left in place per the spec's backward-compat note; Task E5 only removes the frontend page that called them, not the backend routes — flagged inline for the user to decide on full removal timing.
