# Shift Potential-Split Quotas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a duty manager auto-populate a shift's per-node quotas by proportionally splitting `required_count` across a chosen parent node's direct children, weighted by each child's total active-soldier count — plus a lowest-common-ancestor sanity label and a one-click shift-scoped algorithm rerun.

**Architecture:** One new read-only backend endpoint (`GET /shifts/quota-split-preview`) computes the proportional split server-side using the largest-remainder rounding method, so the sum always equals `required_count` exactly. The frontend (`ShiftFormModal`) calls it from a new button (also used for "recompute"), optionally auto-triggers it when a system setting is on, shows a client-side-computed LCA label from already-fetched hierarchy `path_ids`, and adds a button that submits a normal algorithm job scoped to just the edited shift via the existing `/algorithm/jobs` endpoint.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + Vitest/RTL (frontend), Alembic not needed (no schema change — reuses `system_settings` key-value table and existing `duty_shift_node_quotas`).

## Global Constraints

- Backend tests: run via `pytest -q` from `backend/` (venv activated). New tests must pass without `--slow`.
- Frontend tests: `npm test` from `frontend/`. `npm run lint` must stay at zero warnings.
- Hebrew UI strings only, in `frontend/src/i18n/he.json` under existing namespaces — no new i18n files.
- No schema/Alembic migration in this plan — `system_settings` is schemaless JSONB and `duty_shift_node_quotas` already exists.
- Follow existing patterns exactly: `ShiftQuotaError` for service-layer validation, `authorize`/`require_duty_manager_or_admin` for route auth, `t("shifts.xxx")` for all new frontend copy.
- Commit after each task with a `feat:`/`test:` message per the repo's small-per-task-commit convention.

---

### Task 1: `compute_potential_split` service function

**Files:**
- Modify: `backend/app/services/shift_quotas.py`
- Test: `backend/app/services/tests/test_shift_quotas.py`

**Interfaces:**
- Consumes: `app.db.models.HierarchyNode`, `app.db.models.Soldier` (existing), `tests.helpers.create_node`, `tests.helpers.create_soldier` (existing).
- Produces: `compute_potential_split(session, *, parent_node_id: uuid.UUID, required_count: int) -> list[dict]`, each dict shaped `{"hierarchy_node_id": uuid.UUID, "node_name": str, "count": int, "weight": int}`. Raises `ShiftQuotaError` (already defined in this module) for `required_count < 1` and for a parent with no direct children. Does **not** raise for an unknown `parent_node_id` — that check belongs to the route (Task 2), since the service assumes a valid node was already resolved.

- [ ] **Step 1: Write the failing tests**

Add to `backend/app/services/tests/test_shift_quotas.py` (append; keep existing imports, add `Soldier` and `create_soldier`, and import the new function):

```python
from app.db.models import AuditLog, DutyLocation, Soldier
from app.services.duty_config import create_duty_type
from app.services.shift_quotas import (
    ShiftQuotaError,
    compute_potential_split,
    get_shift_quotas,
    set_shift_quotas,
)
from app.services.shifts import create_shift
from tests.helpers import create_node, create_soldier
```

(Replace the existing top-of-file import block with the above — it's the same imports plus `Soldier`, `create_soldier`, and `compute_potential_split`.)

Then append these test functions:

```python
def test_compute_potential_split_even_weights(admin_session):
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

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_shift_quotas.py -v -k compute_potential_split`
Expected: FAIL with `ImportError: cannot import name 'compute_potential_split'`

- [ ] **Step 3: Implement `compute_potential_split`**

In `backend/app/services/shift_quotas.py`, change the import block at the top from:

```python
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyShift, DutyShiftNodeQuota, HierarchyNode
```

to:

```python
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyShift, DutyShiftNodeQuota, HierarchyNode, Soldier
```

Then append this function at the end of the file:

```python
def compute_potential_split(
    session: Session, *, parent_node_id: uuid.UUID, required_count: int
) -> list[dict]:
    """Proportionally split `required_count` across `parent_node_id`'s direct
    children, weighted by each child's total active-soldier subtree count.
    Uses the largest-remainder method so counts always sum to exactly
    `required_count`. Falls back to an even split if every child has zero
    weight (otherwise the split would be all-zero and useless)."""
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

    weights = [
        session.execute(
            select(func.count())
            .select_from(Soldier)
            .join(HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id)
            .where(HierarchyNode.path_ids.any(child.id), Soldier.left_at.is_(None))
        ).scalar_one()
        for child in children
    ]

    n = len(children)
    total_weight = sum(weights)
    if total_weight == 0:
        base, extra = divmod(required_count, n)
        shares = [base + (1 if i < extra else 0) for i in range(n)]
    else:
        raw_shares = [required_count * w / total_weight for w in weights]
        shares = [int(r) for r in raw_shares]
        remainder = required_count - sum(shares)
        order_by_fraction = sorted(
            range(n), key=lambda i: raw_shares[i] - shares[i], reverse=True
        )
        for i in order_by_fraction[:remainder]:
            shares[i] += 1

    return [
        {
            "hierarchy_node_id": child.id,
            "node_name": child.name,
            "count": shares[i],
            "weight": weights[i],
        }
        for i, child in enumerate(children)
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_shift_quotas.py -v -k compute_potential_split`
Expected: 6 passed

- [ ] **Step 5: Run the full service test file to check no regressions**

Run: `cd backend && pytest app/services/tests/test_shift_quotas.py -v`
Expected: all passed (11 total: 5 existing + 6 new)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/shift_quotas.py backend/app/services/tests/test_shift_quotas.py
git commit -m "feat: add compute_potential_split service for proportional shift quotas"
```

---

### Task 2: `GET /shifts/quota-split-preview` route

**Files:**
- Modify: `backend/app/routes/shifts.py`
- Test: `backend/tests/integration/test_shift_quotas_api.py`

**Interfaces:**
- Consumes: `compute_potential_split` from Task 1 (`app.services.shift_quotas`), `ShiftQuotaError` (existing), `require_duty_manager_or_admin` (existing, `app.auth.deps`).
- Produces: `GET /shifts/quota-split-preview?parent_node_id=<uuid>&required_count=<int>` → `200 {"entries": [{"hierarchy_node_id": str, "node_name": str, "count": int, "weight": int}, ...]}`. `404 {"detail": "not_found"}` for unknown `parent_node_id`. `400 {"detail": "<ShiftQuotaError message>"}` for no-children/invalid-count. `403` for non-DM/non-admin callers.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_shift_quotas_api.py` (add `Soldier` to the model import if not already, and `create_node`/`create_soldier` are already imported):

```python
def test_quota_split_preview_returns_entries_summing_to_required_count(client, admin_session):
    dm, dt, loc, parent = _setup(admin_session, "sp_001")
    child_a = create_node(admin_session, level="branch", name="sp_001_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="sp_001_b", parent=parent)
    create_soldier(admin_session, personal_number="sp_001_s1", hierarchy_node_id=child_a.id)
    create_soldier(admin_session, personal_number="sp_001_s2", hierarchy_node_id=child_b.id)
    admin_session.commit()

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": str(parent.id), "required_count": 5},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()["entries"]
    assert sum(e["count"] for e in entries) == 5
    assert {e["node_name"] for e in entries} == {"sp_001_a", "sp_001_b"}


def test_quota_split_preview_unknown_parent_returns_404(client, admin_session):
    dm, dt, loc, _parent = _setup(admin_session, "sp_002")

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": "00000000-0000-0000-0000-000000000000", "required_count": 3},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 404


def test_quota_split_preview_no_children_returns_400(client, admin_session):
    dm, dt, loc, leaf = _setup(admin_session, "sp_003")

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": str(leaf.id), "required_count": 3},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400


def test_quota_split_preview_forbidden_for_plain_soldier(client, admin_session):
    dm, dt, loc, parent = _setup(admin_session, "sp_004")
    create_node(admin_session, level="branch", name="sp_004_a", parent=parent)
    plain = create_soldier(admin_session, personal_number="sp_004_plain", role="soldier")
    admin_session.commit()

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": str(parent.id), "required_count": 3},
        headers=auth_headers(plain),
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_shift_quotas_api.py -v -k quota_split_preview`
Expected: FAIL on all 4 — the request path `/shifts/quota-split-preview` currently matches the existing `GET /shifts/{shift_id}` route (no dedicated route registered yet), so FastAPI tries to parse `"quota-split-preview"` as a UUID path param and returns `422`, not the status codes each test asserts.

- [ ] **Step 3: Implement the route**

In `backend/app/routes/shifts.py`, add to the import line:

```python
from app.services.shift_quotas import ShiftQuotaError, compute_potential_split, get_shift_quotas, set_shift_quotas
```

(replacing the existing `from app.services.shift_quotas import ShiftQuotaError, get_shift_quotas, set_shift_quotas` line).

Then insert the following **immediately after `list_shifts` and before `create_shift`** (so it's registered before `GET /{shift_id}` and isn't shadowed by the `{shift_id}` path parameter):

```python
class QuotaSplitEntry(BaseModel):
    hierarchy_node_id: uuid.UUID
    node_name: str
    count: int
    weight: int


class QuotaSplitPreviewOut(BaseModel):
    entries: list[QuotaSplitEntry]


@router.get("/quota-split-preview", response_model=QuotaSplitPreviewOut)
def quota_split_preview(
    parent_node_id: uuid.UUID,
    required_count: int,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
) -> QuotaSplitPreviewOut:
    parent = session.get(HierarchyNode, parent_node_id)
    if parent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        entries = compute_potential_split(
            session, parent_node_id=parent_node_id, required_count=required_count
        )
    except ShiftQuotaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return QuotaSplitPreviewOut(entries=[QuotaSplitEntry(**e) for e in entries])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_shift_quotas_api.py -v`
Expected: all passed (7 total: 3 existing + 4 new)

- [ ] **Step 5: Run the full backend duty-marked suite to check no regressions**

Run: `cd backend && pytest -m duty -q`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/shifts.py backend/tests/integration/test_shift_quotas_api.py
git commit -m "feat: add GET /shifts/quota-split-preview endpoint"
```

---

### Task 3: `shifts.auto_split_node_quotas` system setting

**Files:**
- Modify: `backend/app/routes/public_settings.py`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`

**Interfaces:**
- Consumes: existing `SystemSetting` model, existing `GET/PUT /admin/system-settings` routes (no route changes needed — they already accept/return arbitrary keys), existing `GET /settings/public`.
- Produces: `shifts.auto_split_node_quotas` becomes readable via `GET /settings/public` (default absent/`undefined` until an admin sets it, which Task 5's frontend code must treat as `false`) and editable in the admin Settings UI.

No test file changes in this task — no existing tests cover `_PUBLIC_KEYS` membership or `SETTING_GROUPS` entries (this is bare declarative config, consistent with every other entry in both files).

- [ ] **Step 1: Add the key to `_PUBLIC_KEYS`**

In `backend/app/routes/public_settings.py`, change:

```python
_PUBLIC_KEYS = {
    "gimalim.enabled",
    "gimalim.default_rest_days",
    "gimalim.reserve_fate",
}
```

to:

```python
_PUBLIC_KEYS = {
    "gimalim.enabled",
    "gimalim.default_rest_days",
    "gimalim.reserve_fate",
    "shifts.auto_split_node_quotas",
}
```

- [ ] **Step 2: Add the admin settings UI entry**

In `frontend/src/pages/SystemSettingsPage.tsx`, add a new group to the `SETTING_GROUPS` array, right after the `"פירוק וקבוצות (אלגוריתם)"` group (before `"דף הבית"`):

```typescript
  {
    label: "משמרות",
    settings: [
      {
        key: "shifts.auto_split_node_quotas",
        label: "פיצול מכסות אוטומטי לפי פוטנציאל",
        description: "כשמופעל, מכסות ליחידות-בת מחושבות אוטומטית לפי פוטנציאל (סה\"כ חיילים) בכל פעם שנבחרת יחידת-אב יחידה ונקבע מספר נדרש בטופס משמרת",
        type: "boolean" as const,
        defaultValue: false,
      },
    ],
  },
```

- [ ] **Step 3: Verify manually**

Run: `cd backend && pytest app/routes -q -k public_settings` (should report "no tests ran" — expected, there are none; this just confirms the file still imports cleanly)
Run: `cd frontend && npm run typecheck`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/public_settings.py frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: add shifts.auto_split_node_quotas system setting"
```

---

### Task 4: Frontend API client for split preview

**Files:**
- Modify: `frontend/src/api/shifts.ts`

**Interfaces:**
- Produces: `interface QuotaSplitEntry { hierarchy_node_id: string; node_name: string; count: number; weight: number }` and `getQuotaSplitPreview(parentNodeId: string, requiredCount: number): Promise<QuotaSplitEntry[]>`, both exported from `../api/shifts` for Task 5 to import.

No dedicated test file for this task — it's a thin fetch wrapper, matching every other function in this file (none have their own unit test; they're exercised via `ShiftFormModal.test.tsx`'s mocks, which Task 5 covers).

- [ ] **Step 1: Add the type and function**

In `frontend/src/api/shifts.ts`, add after the `NodeQuota` interface (after line 27):

```typescript
export interface QuotaSplitEntry {
  hierarchy_node_id: string;
  node_name: string;
  count: number;
  weight: number;
}
```

Then add after the `setShiftQuotas` function (after the existing function ending at line 74):

```typescript
export async function getQuotaSplitPreview(
  parentNodeId: string,
  requiredCount: number
): Promise<QuotaSplitEntry[]> {
  const r = await api.get<{ entries: QuotaSplitEntry[] }>("/shifts/quota-split-preview", {
    params: { parent_node_id: parentNodeId, required_count: requiredCount },
  });
  return r.data.entries;
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npm run typecheck`
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/shifts.ts
git commit -m "feat: add getQuotaSplitPreview API client function"
```

---

### Task 5: Split / recompute button in `ShiftFormModal`

**Files:**
- Modify: `frontend/src/components/ShiftFormModal.tsx`
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/components/ShiftFormModal.test.tsx`

**Interfaces:**
- Consumes: `getQuotaSplitPreview` from Task 4 (`../api/shifts`).
- Produces: no new exports — internal component behavior. `quotaRows` state gets overwritten by split results (count > 0 entries only). This task also extends `flattenNodes`/`nodeOptions` to carry `path_ids`, which Task 7 (LCA) depends on.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/ShiftFormModal.test.tsx`, replace the `vi.mock("../api/shifts", ...)` block and `mockNodes` with:

```typescript
const mockCreateShift = vi.fn(() => Promise.resolve({ id: "new-shift-1" }));
const mockUpdateShift = vi.fn(() => Promise.resolve({}));
const mockGetQuotaSplitPreview = vi.fn(() =>
  Promise.resolve([
    { hierarchy_node_id: "n1", node_name: "פלוגה א", count: 3, weight: 6 },
    { hierarchy_node_id: "n2", node_name: "פלוגה ב", count: 2, weight: 4 },
  ])
);
vi.mock("../api/shifts", async () => {
  const actual = await vi.importActual<typeof import("../api/shifts")>("../api/shifts");
  return {
    ...actual,
    createShift: (...args: unknown[]) => mockCreateShift(...args),
    updateShift: (...args: unknown[]) => mockUpdateShift(...args),
    setShiftQuotas: vi.fn(() => Promise.resolve({ quotas: [] })),
    getQuotaSplitPreview: (...args: unknown[]) => mockGetQuotaSplitPreview(...args),
  };
});

vi.mock("../api/publicSettings", () => ({
  getPublicSettings: vi.fn(() => Promise.resolve({})),
}));

vi.mock("../api/algorithm", () => ({
  submitJob: vi.fn(() => Promise.resolve({ id: "job-1", status: "queued" })),
  getAlgorithmDefaults: vi.fn(() => Promise.resolve({ T: 8, Wt: 14, R: 15, Wr: 28 })),
}));

const mockNodes = [
  {
    id: "root", name: "אוגדה", path_ids: ["root"], children: [
      { id: "n1", name: "פלוגה א", path_ids: ["root", "n1"], children: [] },
      { id: "n2", name: "פלוגה ב", path_ids: ["root", "n2"], children: [] },
    ],
  },
];
vi.mock("../api/hierarchy", () => ({
  fetchTree: vi.fn(() => Promise.resolve(mockNodes)),
}));
```

Update the `beforeEach` to also clear the new mock:

```typescript
beforeEach(() => {
  mockCreateShift.mockClear();
  mockUpdateShift.mockClear();
  mockGetQuotaSplitPreview.mockClear();
});
```

Add these new test functions at the end of the file:

```typescript
test("split-by-potential button is hidden until exactly one scope node is selected", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  expect(screen.queryByText("shifts.quotas_split_by_potential")).not.toBeInTheDocument();

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));
  expect(await screen.findByText("shifts.quotas_split_by_potential")).toBeInTheDocument();

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה ב" }));
  expect(screen.queryByText("shifts.quotas_split_by_potential")).not.toBeInTheDocument();
});

test("clicking split-by-potential populates quota rows from the API response", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));
  fireEvent.click(await screen.findByText("shifts.quotas_split_by_potential"));

  await waitFor(() => expect(mockGetQuotaSplitPreview).toHaveBeenCalledWith("n1", 1));
  const counts = await screen.findAllByTestId("quota-count-input");
  expect(counts.map((el) => (el as HTMLInputElement).value)).toEqual(["3", "2"]);
});

test("clicking split-by-potential again (recompute) overwrites existing rows", async () => {
  mockGetQuotaSplitPreview
    .mockResolvedValueOnce([{ hierarchy_node_id: "n1", node_name: "פלוגה א", count: 1, weight: 1 }])
    .mockResolvedValueOnce([{ hierarchy_node_id: "n1", node_name: "פלוגה א", count: 4, weight: 8 }]);

  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());
  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));

  const splitButton = await screen.findByText("shifts.quotas_split_by_potential");
  fireEvent.click(splitButton);
  await waitFor(async () =>
    expect((await screen.findAllByTestId("quota-count-input"))[0]).toHaveValue(1)
  );

  fireEvent.click(splitButton);
  await waitFor(async () =>
    expect((await screen.findAllByTestId("quota-count-input"))[0]).toHaveValue(4)
  );
  expect(await screen.findAllByTestId("quota-count-input")).toHaveLength(1);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: FAIL — `getQuotaSplitPreview` export doesn't exist yet in the mock target module signature used by the component, and `shifts.quotas_split_by_potential` text never renders.

- [ ] **Step 3: Implement in `ShiftFormModal.tsx`**

Change the imports at the top of the file:

```typescript
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { CreateShiftInput, DutyShift, createShift, updateShift, setShiftQuotas, getQuotaSplitPreview } from "../api/shifts";
import { DutyType, DutyLocation, createLocation } from "../api/dutyConfig";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import Combobox from "./Combobox";
import SubHierarchySelector from "./SubHierarchySelector";
import { lastDutyDay, toExclusiveEndDate } from "../utils/formatDate";
```

Change `flattenNodes` to carry `path_ids`:

```typescript
function flattenNodes(nodes: NodeDTO[]): { id: string; name: string; path_ids: string[] }[] {
  const result: { id: string; name: string; path_ids: string[] }[] = [];
  for (const n of nodes) {
    result.push({ id: n.id, name: n.name, path_ids: n.path_ids });
    if (n.children?.length) result.push(...flattenNodes(n.children));
  }
  return result;
}
```

Change the `nodeOptions` state type declaration:

```typescript
  const [nodeOptions, setNodeOptions] = useState<{ id: string; name: string; path_ids: string[] }[]>([]);
```

Add split-button state and handler right after the existing `updateQuotaRow` function (after line 71):

```typescript
  const [splitting, setSplitting] = useState(false);

  async function handleSplitByPotential() {
    if (scopeNodeIds.length !== 1) return;
    setSplitting(true);
    setError(null);
    try {
      const entries = await getQuotaSplitPreview(scopeNodeIds[0], count);
      setQuotaRows(
        entries
          .filter((e) => e.count > 0)
          .map((e) => ({ hierarchy_node_id: e.hierarchy_node_id, count: e.count }))
      );
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setSplitting(false);
    }
  }
```

Add the button in the JSX, inside the quotas section `<div className="border ...">` block, right before the closing `</div>` of the quota rows list (i.e. right after the `</div>` that closes `<div className="space-y-1">...quotaRows.map...</div>` and before the existing `+ {t("shifts.quotas_add")}` button — insert it as a new button next to that one):

Find:
```typescript
            <button
              type="button"
              onClick={addQuotaRow}
              className="mt-2 text-xs text-blue-600 dark:text-blue-400 hover:underline"
            >
              + {t("shifts.quotas_add")}
            </button>
```

Replace with:
```typescript
            <div className="mt-2 flex items-center gap-3">
              <button
                type="button"
                onClick={addQuotaRow}
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                + {t("shifts.quotas_add")}
              </button>
              {scopeNodeIds.length === 1 && (
                <button
                  type="button"
                  onClick={handleSplitByPotential}
                  disabled={splitting}
                  className="text-xs text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
                >
                  {t("shifts.quotas_split_by_potential")}
                </button>
              )}
            </div>
```

- [ ] **Step 4: Add the translation key**

In `frontend/src/i18n/he.json`, in the `shifts` block, add after `"quotas_select_node": "בחר יחידה",`:

```json
    "quotas_split_by_potential": "חלק לפי פוטנציאל לתתי מסגרות",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: all passed (5 total: 2 existing + 3 new)

- [ ] **Step 6: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx frontend/src/components/ShiftFormModal.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add split-by-potential button to ShiftFormModal quota editor"
```

---

### Task 6: Auto-split via system setting

**Files:**
- Modify: `frontend/src/components/ShiftFormModal.tsx`
- Test: `frontend/src/components/ShiftFormModal.test.tsx`

**Interfaces:**
- Consumes: `getPublicSettings` (existing, `../api/publicSettings`), `getQuotaSplitPreview` (Task 4), `handleSplitByPotential` logic (Task 5, refactored into a reusable function).
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/ShiftFormModal.test.tsx`:

```typescript
test("auto-splits quota rows when the system setting is enabled and a single node is selected", async () => {
  const { getPublicSettings } = await import("../api/publicSettings");
  vi.mocked(getPublicSettings).mockResolvedValueOnce({ "shifts.auto_split_node_quotas": true });

  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));

  await waitFor(() => expect(mockGetQuotaSplitPreview).toHaveBeenCalled());
  const counts = await screen.findAllByTestId("quota-count-input");
  expect(counts.map((el) => (el as HTMLInputElement).value)).toEqual(["3", "2"]);
  expect(screen.getByText("shifts.quotas_auto_split_hint")).toBeInTheDocument();
});

test("does not auto-split when the system setting is disabled", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByRole("checkbox", { name: "פלוגה א" }));

  await new Promise((r) => setTimeout(r, 500));
  expect(mockGetQuotaSplitPreview).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: FAIL — auto-split effect doesn't exist yet.

- [ ] **Step 3: Implement auto-split**

In `frontend/src/components/ShiftFormModal.tsx`, add to the imports:

```typescript
import { getPublicSettings } from "../api/publicSettings";
```

Refactor `handleSplitByPotential` to extract a reusable core (added in Task 5) — replace it with:

```typescript
  const [splitting, setSplitting] = useState(false);
  const [autoSplitEnabled, setAutoSplitEnabled] = useState(false);
  const [autoSplitApplied, setAutoSplitApplied] = useState(false);

  useEffect(() => {
    void getPublicSettings()
      .then((settings) => setAutoSplitEnabled(settings["shifts.auto_split_node_quotas"] === true))
      .catch(() => {});
  }, []);

  async function runSplit(): Promise<boolean> {
    if (scopeNodeIds.length !== 1 || count < 1) return false;
    setSplitting(true);
    setError(null);
    try {
      const entries = await getQuotaSplitPreview(scopeNodeIds[0], count);
      setQuotaRows(
        entries
          .filter((e) => e.count > 0)
          .map((e) => ({ hierarchy_node_id: e.hierarchy_node_id, count: e.count }))
      );
      return true;
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
      return false;
    } finally {
      setSplitting(false);
    }
  }

  async function handleSplitByPotential() {
    setAutoSplitApplied(false);
    await runSplit();
  }

  useEffect(() => {
    if (!autoSplitEnabled || scopeNodeIds.length !== 1 || count < 1) return;
    const timer = setTimeout(() => {
      void runSplit().then((ok) => setAutoSplitApplied(ok));
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSplitEnabled, scopeNodeIds, count]);
```

(This replaces the plain `handleSplitByPotential` added in Task 5 with the same name but now backed by shared `runSplit`, and adds the debounced auto-trigger effect.)

Add the hint text in the JSX, right after the quota-rows-and-buttons block, before the existing `quotaTotal` paragraph:

Find:
```typescript
            <p className={`text-xs mt-2 ${quotaOverAllocated ? "text-red-500" : "text-gray-500 dark:text-gray-400"}`}>
              {t("shifts.quotas_total")}: {quotaTotal} / {count}
            </p>
```

Replace with:
```typescript
            {autoSplitApplied && (
              <p className="text-xs mt-2 text-gray-500 dark:text-gray-400">{t("shifts.quotas_auto_split_hint")}</p>
            )}
            <p className={`text-xs mt-2 ${quotaOverAllocated ? "text-red-500" : "text-gray-500 dark:text-gray-400"}`}>
              {t("shifts.quotas_total")}: {quotaTotal} / {count}
            </p>
```

- [ ] **Step 4: Add the translation key**

In `frontend/src/i18n/he.json`, in the `shifts` block, add after `"quotas_split_by_potential": "חלק לפי פוטנציאל לתתי מסגרות",`:

```json
    "quotas_auto_split_hint": "מכסות חושבו אוטומטית לפי פוטנציאל",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: all passed (7 total)

- [ ] **Step 6: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx frontend/src/components/ShiftFormModal.test.tsx frontend/src/i18n/he.json
git commit -m "feat: auto-split shift quotas by potential when system setting is enabled"
```

---

### Task 7: Lowest-common-ancestor label

**Files:**
- Modify: `frontend/src/components/ShiftFormModal.tsx`
- Test: `frontend/src/components/ShiftFormModal.test.tsx`

**Interfaces:**
- Consumes: `nodeOptions` (now carrying `path_ids`, from Task 5), `quotaRows`.
- Produces: no new exports.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/ShiftFormModal.test.tsx`:

```typescript
test("shows the common-ancestor label when 2+ quota rows share a parent", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(screen.getByText(/quotas_add/));
  fireEvent.click(screen.getByText(/quotas_add/));
  const selects = screen.getAllByLabelText("shifts.quotas_select_node");
  fireEvent.change(selects[0], { target: { value: "n1" } });
  fireEvent.change(selects[1], { target: { value: "n2" } });

  expect(await screen.findByText("shifts.quotas_common_ancestor")).toBeInTheDocument();
});

test("hides the common-ancestor label with fewer than 2 quota rows", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(screen.getByText(/quotas_add/));
  const select = screen.getAllByLabelText("shifts.quotas_select_node")[0];
  fireEvent.change(select, { target: { value: "n1" } });

  expect(screen.queryByText("shifts.quotas_common_ancestor")).not.toBeInTheDocument();
});
```

Update the `useTranslation` mock at the top of the file to pass through the `name` interpolation option so the test can match on the base key (it already forwards `opts`, but the mock's default branch returns just `key` — that's fine since the test asserts on the literal key text `"shifts.quotas_common_ancestor"`, matching the existing pattern for other interpolated keys like `quotas_over_allocated` which uses a special-cased branch; here we don't need a special case because the test only checks the key renders, not its interpolated content).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: FAIL — label doesn't exist yet.

- [ ] **Step 3: Implement the LCA computation and label**

In `frontend/src/components/ShiftFormModal.tsx`, add this helper function above the `ShiftFormModal` component definition (after `flattenNodes`):

```typescript
function commonAncestorName(
  nodeIds: string[],
  nodeOptions: { id: string; name: string; path_ids: string[] }[]
): string | null {
  const paths = nodeIds
    .map((id) => nodeOptions.find((n) => n.id === id)?.path_ids)
    .filter((p): p is string[] => !!p && p.length > 0);
  if (paths.length < 2) return null;

  const minLen = Math.min(...paths.map((p) => p.length));
  let commonLength = 0;
  for (let i = 0; i < minLen; i++) {
    if (paths.every((p) => p[i] === paths[0][i])) {
      commonLength = i + 1;
    } else {
      break;
    }
  }
  if (commonLength === 0) return null;
  const ancestorId = paths[0][commonLength - 1];
  return nodeOptions.find((n) => n.id === ancestorId)?.name ?? null;
}
```

Inside the `ShiftFormModal` component, add this derived value near `quotaTotal`/`quotaOverAllocated` (after line 58):

```typescript
  const commonAncestor = commonAncestorName(
    quotaRows.map((r) => r.hierarchy_node_id).filter(Boolean),
    nodeOptions
  );
```

In the JSX, add the label right after the `{t("shifts.quotas_title")}` header paragraph and before the `<div className="space-y-1">` quota rows list:

Find:
```typescript
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">{t("shifts.quotas_title")}</p>
            <div className="space-y-1">
```

Replace with:
```typescript
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">{t("shifts.quotas_title")}</p>
            {commonAncestor && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                {t("shifts.quotas_common_ancestor", { name: commonAncestor })}
              </p>
            )}
            <div className="space-y-1">
```

- [ ] **Step 4: Add the translation key**

In `frontend/src/i18n/he.json`, in the `shifts` block, add after `"quotas_auto_split_hint": "מכסות חושבו אוטומטית לפי פוטנציאל",`:

```json
    "quotas_common_ancestor": "מסגרת אם משותפת: {{name}}",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: all passed (9 total)

- [ ] **Step 6: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx frontend/src/components/ShiftFormModal.test.tsx frontend/src/i18n/he.json
git commit -m "feat: show lowest-common-ancestor label for shift quota rows"
```

---

### Task 8: Rerun-algorithm button

**Files:**
- Modify: `frontend/src/components/ShiftFormModal.tsx`
- Test: `frontend/src/components/ShiftFormModal.test.tsx`

**Interfaces:**
- Consumes: `submitJob`, `getAlgorithmDefaults`, `SolverSettings` (existing, `../api/algorithm`, mocked in Task 5's test setup).
- Produces: no new exports.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/ShiftFormModal.test.tsx`:

```typescript
test("rerun-algorithm button is hidden for a new (unsaved) shift", async () => {
  render(
    <ShiftFormModal dutyTypes={dutyTypes} locations={locations} onSaved={() => {}} onClose={() => {}} />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());
  expect(screen.queryByText("shifts.rerun_algorithm")).not.toBeInTheDocument();
});

test("rerun-algorithm button submits a job scoped to the existing shift", async () => {
  const { submitJob } = await import("../api/algorithm");
  const existingShift = {
    id: "shift-42",
    duty_type_id: "d1",
    duty_location_id: "l1",
    start_date: "2026-07-01",
    end_date: "2026-07-02",
    required_count: 3,
    notes: null,
    assigned_count: 0,
    reserve_assigned_count: 0,
    fill_status: "empty" as const,
    status: "active" as const,
    node_quotas: [],
  };

  render(
    <ShiftFormModal
      dutyTypes={dutyTypes}
      locations={locations}
      existing={existingShift}
      onSaved={() => {}}
      onClose={() => {}}
    />
  );
  await waitFor(() => expect(screen.getByText("shifts.quotas_title")).toBeInTheDocument());

  fireEvent.click(await screen.findByText("shifts.rerun_algorithm"));

  await waitFor(() =>
    expect(submitJob).toHaveBeenCalledWith(
      expect.objectContaining({ shift_ids: ["shift-42"], mode: "shadow" })
    )
  );
  expect(await screen.findByText(/rerun_algorithm_success/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: FAIL — button doesn't exist yet.

- [ ] **Step 3: Implement the rerun button**

In `frontend/src/components/ShiftFormModal.tsx`, add to the imports:

```typescript
import { submitJob, getAlgorithmDefaults, SolverSettings } from "../api/algorithm";
```

Add this constant near the top of the file, after the `flattenNodes`/`commonAncestorName` helpers and before the `Props` interface:

```typescript
const DEFAULT_RERUN_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30, num_workers: 1,
  auto_relax_node_quotas: false,
};
```

Add state and a handler inside the component, after the `autoSplitApplied` state block:

```typescript
  const [rerunning, setRerunning] = useState(false);
  const [rerunResult, setRerunResult] = useState<string | null>(null);

  async function handleRerunAlgorithm() {
    if (!existing) return;
    setRerunning(true);
    setRerunResult(null);
    setError(null);
    try {
      const defaults = await getAlgorithmDefaults();
      const settings: SolverSettings = { ...DEFAULT_RERUN_SETTINGS, ...defaults };
      const resp = await submitJob({ shift_ids: [existing.id], mode: "shadow", settings });
      setRerunResult(t("shifts.rerun_algorithm_success", { id: resp.id }));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setRerunning(false);
    }
  }
```

Add the button in the JSX, right after the quotas section's closing `</div>` (after the `quotaOverAllocated` error paragraph block, before the `{error && ...}` line):

Find:
```typescript
            {quotaOverAllocated && (
              <p className="text-red-500 text-xs">
                {t("shifts.quotas_over_allocated", { total: quotaTotal, required: count })}
              </p>
            )}
          </div>
          {error && <p className="text-red-500 text-xs">{error}</p>}
```

Replace with:
```typescript
            {quotaOverAllocated && (
              <p className="text-red-500 text-xs">
                {t("shifts.quotas_over_allocated", { total: quotaTotal, required: count })}
              </p>
            )}
          </div>
          {existing && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleRerunAlgorithm}
                disabled={rerunning}
                className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50"
              >
                {t("shifts.rerun_algorithm")}
              </button>
              {rerunResult && <span className="text-xs text-green-600 dark:text-green-400">{rerunResult}</span>}
            </div>
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
```

- [ ] **Step 4: Add the translation keys**

In `frontend/src/i18n/he.json`, in the `shifts` block, add after `"quotas_common_ancestor": "מסגרת אם משותפת: {{name}}",`:

```json
    "rerun_algorithm": "הרץ אלגוריתם",
    "rerun_algorithm_success": "הוגשה עבודת אלגוריתם (מס' {{id}})",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- ShiftFormModal`
Expected: all passed (11 total)

- [ ] **Step 6: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx frontend/src/components/ShiftFormModal.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add rerun-algorithm button to ShiftFormModal for existing shifts"
```

---

### Task 9: Full verification pass

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Run the full backend fast suite**

Run: `cd backend && pytest -q`
Expected: all passed.

- [ ] **Step 2: Run the full frontend unit suite**

Run: `cd frontend && npm test`
Expected: all passed.

- [ ] **Step 3: Run lint and typecheck one more time**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, no type errors.

- [ ] **Step 4: Manual smoke test via dev stack**

Run: `.\dev.ps1` from the repo root, then in the browser:
1. Log in as an admin, go to Settings, enable "פיצול מכסות אוטומטי לפי פוטנציאל" under "משמרות", save.
2. Go to a hierarchy node with 2+ children that have soldiers assigned, note their names.
3. Open "משמרות" (Shifts), create a new shift, set required count, select that parent node as the sole scope node — confirm quota rows auto-populate and sum to the required count, and the hint text appears.
4. Edit an existing shift with 2+ quota rows under different children — confirm the common-ancestor label appears with the correct name.
5. Click "הרץ אלגוריתם" on an existing shift — confirm a success message with a job id appears, and check the algorithm jobs list shows a new job scoped to that shift.

No code changes in this task — if the manual smoke test surfaces a bug, fix it as a follow-up commit and re-run the affected task's automated tests.
