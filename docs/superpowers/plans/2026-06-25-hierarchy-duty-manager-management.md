# Hierarchy-Page Duty-Manager Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two modals to the hierarchy page so admins and commanders can assign/remove duty managers per node and manage a duty manager's full portfolio of nodes, on top of the existing `DutyManagerScope` backend.

**Architecture:** Backend: extend `NodeOut` with a per-node `duty_managers` list and a viewer-specific `dm_manageable` flag (computed via the existing `can()`/`is_commander`/`is_duty_manager` capability checks); scope-filter `GET /duty-manager-scope` for non-admin viewers. Frontend: two new modal components reusing existing patterns (`AssignCommanderDialog`'s search-to-add box, `ProfilePage`'s scope-list-with-remove), wired into `HierarchyTree` (per-node button + DM-name links) and `TeamHierarchyPage` (soldier-table entry point).

**Tech Stack:** Python/FastAPI/SQLAlchemy backend, pytest; React/TypeScript frontend, vitest.

**Spec:** `docs/superpowers/specs/2026-06-25-hierarchy-duty-manager-management-design.md`

---

## Task 1: Backend — extend `NodeOut` with `duty_managers`/`dm_manageable`

**Files:**
- Modify: `backend/app/routes/hierarchy.py`
- Test: `backend/tests/integration/test_hierarchy_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_hierarchy_api.py`:

```python
def test_tree_includes_duty_managers_and_manageable_flag(client: TestClient, admin_session: Session):
    from app.db.models import DutyManagerScope
    node = create_node(admin_session, level="department", name="dm-out-node")
    admin = create_soldier(admin_session, personal_number="dmout-001", role="admin")
    dm = create_soldier(admin_session, personal_number="dmout-002", hierarchy_node_id=node.id)
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()

    r = client.get("/api/hierarchy/tree", params={"all": True}, headers=auth_headers(admin))
    assert r.status_code == 200
    out_node = next(n for n in r.json() if n["id"] == str(node.id))
    assert out_node["dm_manageable"] is True
    assert len(out_node["duty_managers"]) == 1
    assert out_node["duty_managers"][0]["soldier_id"] == str(dm.id)
    assert out_node["duty_managers"][0]["name"] == dm.full_name


def test_tree_dm_manageable_false_when_rank_insufficient(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="dm-rank-node")
    cmd = create_soldier(admin_session, personal_number="dmout-004", role="commander")
    node.commander_id = cmd.id
    cmd.rank = "סרן"  # below רס"ן
    admin_session.commit()

    r = client.get("/api/hierarchy/tree", headers=auth_headers(cmd))
    assert r.status_code == 200
    out_node = next(n for n in r.json() if n["id"] == str(node.id))
    assert out_node["dm_manageable"] is False


def test_tree_dm_manageable_true_for_commander_with_rank(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="dm-rank-node-2")
    cmd = create_soldier(admin_session, personal_number="dmout-005", role="commander")
    node.commander_id = cmd.id
    cmd.rank = "רסן"
    admin_session.commit()

    r = client.get("/api/hierarchy/tree", headers=auth_headers(cmd))
    assert r.status_code == 200
    out_node = next(n for n in r.json() if n["id"] == str(node.id))
    assert out_node["dm_manageable"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/Scripts/activate && pytest tests/integration/test_hierarchy_api.py -k "duty_managers_and_manageable or dm_manageable" -v`
Expected: FAIL with `KeyError: 'dm_manageable'` (field doesn't exist on `NodeOut` yet).

- [ ] **Step 3: Add the fields and compute them**

In `backend/app/routes/hierarchy.py`, update the imports:

```python
from app.auth.authz import Action, authorize, can, is_commander, is_duty_manager, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import DutyManagerScope, HierarchyLevelType, HierarchyNode, Soldier, SystemSetting
```

Add a new model and extend `NodeOut` (right before `class CreateNodeRequest`):

```python
class DutyManagerEntryOut(BaseModel):
    scope_id: uuid.UUID
    soldier_id: uuid.UUID
    name: str


class NodeOut(BaseModel):
    id: uuid.UUID
    level: str
    name: str
    parent_id: uuid.UUID | None
    commander_id: uuid.UUID | None
    commander_name: str | None = None
    path_ids: list[uuid.UUID]
    duty_managers: list[DutyManagerEntryOut] = []
    dm_manageable: bool = False
```

Replace `_out()` entirely — it now requires `user` and the caller's precomputed capability info (computing `is_commander`/`is_duty_manager`/`scope_root_ids` once per request, not once per node, matters when `get_tree` calls this in a loop over every node):

```python
def _out(
    n: HierarchyNode,
    session: Session,
    *,
    user: Soldier,
    user_roots: set[uuid.UUID],
    user_is_commander: bool,
    user_is_duty_manager: bool,
) -> NodeOut:
    commander_name = None
    if n.commander_id:
        cmdr = session.get(Soldier, n.commander_id)
        if cmdr:
            commander_name = cmdr.full_name

    dm_rows = session.execute(
        select(DutyManagerScope, Soldier.full_name)
        .join(Soldier, Soldier.id == DutyManagerScope.duty_manager_id)
        .where(DutyManagerScope.hierarchy_node_id == n.id)
    ).all()
    duty_managers = [
        DutyManagerEntryOut(scope_id=entry.id, soldier_id=entry.duty_manager_id, name=name)
        for entry, name in dm_rows
    ]

    dm_manageable = can(
        user,
        Action.DM_SCOPE_MANAGE,
        target_node=n,
        roots=user_roots,
        is_commander=user_is_commander,
        is_duty_manager=user_is_duty_manager,
    )

    return NodeOut(
        id=n.id,
        level=n.level,
        name=n.name,
        parent_id=n.parent_id,
        commander_id=n.commander_id,
        commander_name=commander_name,
        path_ids=list(n.path_ids),
        duty_managers=duty_managers,
        dm_manageable=dm_manageable,
    )
```

- [ ] **Step 4: Update every `_out()` call site to compute and pass the per-request capability info once**

In `create_node` (around line 89-105), change the return:

```python
@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
def create_node(
    body: CreateNodeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NodeOut:
    parent = session.get(HierarchyNode, body.parent_id) if body.parent_id else None
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=parent)
    try:
        node = svc.create_node(
            session, level=body.level, name=body.name, parent_id=body.parent_id, actor_id=user.id
        )
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(
        node, session, user=user,
        user_roots=scope_root_ids(session, user),
        user_is_commander=is_commander(session, user.id),
        user_is_duty_manager=is_duty_manager(session, user.id),
    )
```

In `update_node` (around line 108-132), change the return the same way:

```python
    session.commit()
    session.refresh(node)
    return _out(
        node, session, user=user,
        user_roots=scope_root_ids(session, user),
        user_is_commander=is_commander(session, user.id),
        user_is_duty_manager=is_duty_manager(session, user.id),
    )
```

In `move_node` (around line 135-156), same change to its return:

```python
    session.commit()
    session.refresh(node)
    return _out(
        node, session, user=user,
        user_roots=scope_root_ids(session, user),
        user_is_commander=is_commander(session, user.id),
        user_is_duty_manager=is_duty_manager(session, user.id),
    )
```

In `get_tree` (around line 178-210), compute the capability info once before the final list comprehension:

```python
@router.get("/tree", response_model=list[NodeOut])
def get_tree(
    all: bool = False,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NodeOut]:
    root_node_id = _get_root_node_id(session)

    if all or user.role == "admin":
        nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    elif user.role == "soldier":
        if user.hierarchy_node_id is None:
            return []
        node = session.get(HierarchyNode, user.hierarchy_node_id)
        nodes = [node] if node else []
    else:
        roots = scope_root_ids(session, user)
        if not roots:
            nodes = []
        else:
            nodes = [
                n
                for n in session.execute(select(HierarchyNode)).scalars().all()
                if any(r in n.path_ids for r in roots)
            ]

    # Always include the system root node so every role can use it as a calendar default.
    if root_node_id and not any(n.id == root_node_id for n in nodes):
        root_node = session.get(HierarchyNode, root_node_id)
        if root_node:
            nodes = [root_node, *nodes]

    user_roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    return [
        _out(
            n, session, user=user,
            user_roots=user_roots,
            user_is_commander=user_is_commander,
            user_is_duty_manager=user_is_duty_manager,
        )
        for n in nodes
    ]
```

(Note `get_tree` already computes `roots = scope_root_ids(session, user)` in the `else` branch above for the existing scope-filter logic — that's a separate, branch-local variable; `user_roots` here is computed unconditionally afterward and reused for every node's `dm_manageable`, which is correct since `scope_root_ids` is idempotent and cheap to call again, and keeping the two computations separate avoids coupling the new feature to the existing branch structure.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && source .venv/Scripts/activate && pytest tests/integration/test_hierarchy_api.py -v`
Expected: PASS (all tests in the file, including the three new ones).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && source .venv/Scripts/activate && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/hierarchy.py backend/tests/integration/test_hierarchy_api.py
git commit -m "feat: expose duty_managers list and dm_manageable flag on NodeOut"
```

---

## Task 2: Backend — scope-filter `GET /duty-manager-scope`

**Files:**
- Modify: `backend/app/routes/dm_scope.py`
- Test: `backend/tests/integration/test_dm_scope_routes.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_dm_scope_routes.py` (it already imports `create_node`, `create_soldier`, `auth_headers`, `DutyManagerScope`, and has a `_uid()` helper — reuse them):

```python
def test_list_scope_filtered_for_commander_in_scope(client, admin_session):
    a = create_node(admin_session, level="department", name=f"list-scope-a-{_uid()}")
    b = create_node(admin_session, level="department", name=f"list-scope-b-{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"lsf-{_uid()}", role="commander")
    a.commander_id = cmd.id
    cmd.rank = "רסן"
    dm = create_soldier(admin_session, personal_number=f"lsf-{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=a.id))
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=b.id))
    admin_session.commit()

    resp = client.get(f"/api/duty-manager-scope?soldier_id={dm.id}", headers=auth_headers(cmd))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["hierarchy_node_id"] == str(a.id)


def test_list_scope_empty_for_commander_with_no_overlap(client, admin_session):
    other = create_node(admin_session, level="department", name=f"list-scope-c-{_uid()}")
    unrelated = create_node(admin_session, level="department", name=f"list-scope-d-{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"lsf-{_uid()}", role="commander")
    other.commander_id = cmd.id
    cmd.rank = "רסן"
    dm = create_soldier(admin_session, personal_number=f"lsf-{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=unrelated.id))
    admin_session.commit()

    resp = client.get(f"/api/duty-manager-scope?soldier_id={dm.id}", headers=auth_headers(cmd))
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/Scripts/activate && pytest tests/integration/test_dm_scope_routes.py -k "filtered_for_commander or empty_for_commander" -v`
Expected: FAIL with 403 (current code: `if user.role != "admin" and user.id != soldier_id: raise 403` — a commander viewing someone else's portfolio is always rejected today).

- [ ] **Step 3: Scope-filter instead of all-or-nothing**

In `backend/app/routes/dm_scope.py`, change the import line:

```python
from app.auth.authz import Action, authorize, scope_root_ids
```

Replace `list_scope`:

```python
@router.get("", response_model=list[ScopeEntryOut])
def list_scope(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user=Depends(require_password_changed),
) -> list[ScopeEntryOut]:
    entries = (
        session.execute(
            select(DutyManagerScope).where(DutyManagerScope.duty_manager_id == soldier_id)
        )
        .scalars()
        .all()
    )
    if user.role != "admin" and user.id != soldier_id:
        roots = scope_root_ids(session, user)
        nodes_by_id = {
            n.id: n
            for n in session.execute(
                select(HierarchyNode).where(
                    HierarchyNode.id.in_([e.hierarchy_node_id for e in entries])
                )
            ).scalars().all()
        }
        entries = [
            e
            for e in entries
            if any(r in nodes_by_id[e.hierarchy_node_id].path_ids for r in roots)
        ]
    return [
        ScopeEntryOut(
            id=e.id,
            duty_manager_id=e.duty_manager_id,
            hierarchy_node_id=e.hierarchy_node_id,
        )
        for e in entries
    ]
```

(The admin and self-view cases keep returning everything, matching today's behavior exactly. The `nodes_by_id` lookup is skipped entirely when `entries` is empty, since `HierarchyNode.id.in_([])` would just return nothing anyway — no special-casing needed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source .venv/Scripts/activate && pytest tests/integration/test_dm_scope_routes.py -v`
Expected: PASS (all tests in the file, including the existing `test_list_scope` admin-view test, which must keep passing unchanged).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && source .venv/Scripts/activate && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/dm_scope.py backend/tests/integration/test_dm_scope_routes.py
git commit -m "feat: scope-filter GET /duty-manager-scope for commanders, not admin/self only"
```

---

## Task 3: Frontend — types and API module

**Files:**
- Modify: `frontend/src/api/hierarchy.ts`
- Create: `frontend/src/api/dmScope.ts`

- [ ] **Step 1: Extend `NodeDTO`**

In `frontend/src/api/hierarchy.ts`, add a new interface and extend `NodeDTO`:

```typescript
export interface DutyManagerEntry {
  scope_id: string;
  soldier_id: string;
  name: string;
}

export interface NodeDTO {
  id: string;
  level: "corps" | "division" | "unit" | "department" | "branch" | "group" | "team";
  name: string;
  parent_id: string | null;
  commander_id: string | null;
  commander_name: string | null;
  path_ids: string[];
  duty_managers: DutyManagerEntry[];
  dm_manageable: boolean;
  children?: NodeDTO[];
}
```

- [ ] **Step 2: Create the `dmScope` API module**

Create `frontend/src/api/dmScope.ts`:

```typescript
import { api } from "./client";

export interface DmScopeEntry {
  id: string;
  duty_manager_id: string;
  hierarchy_node_id: string;
}

export async function listDmScope(soldierId: string): Promise<DmScopeEntry[]> {
  return (await api.get<DmScopeEntry[]>("/duty-manager-scope", { params: { soldier_id: soldierId } })).data;
}

export async function assignDmScope(soldierId: string, nodeId: string): Promise<DmScopeEntry> {
  return (await api.post<DmScopeEntry>("/duty-manager-scope", { soldier_id: soldierId, node_id: nodeId })).data;
}

export async function removeDmScope(entryId: string): Promise<void> {
  await api.delete(`/duty-manager-scope/${entryId}`);
}
```

- [ ] **Step 3: Run the frontend suite and typecheck**

Run: `cd frontend && npm test -- --run`
Run: `cd frontend && npx tsc --noEmit`
Expected: both PASS. (Adding required fields to `NodeDTO` will surface a typecheck error in any test fixture/mock that constructs a `NodeDTO` literal without them — fix any such fixture by adding `duty_managers: []` and `dm_manageable: false` to it; do not make the fields optional to paper over a missing fixture update.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/hierarchy.ts frontend/src/api/dmScope.ts
git commit -m "feat: add DutyManagerEntry/dm_manageable types and dmScope API module"
```

---

## Task 4: Frontend — `AssignDutyManagersDialog.tsx` (modal 1)

**Files:**
- Create: `frontend/src/components/AssignDutyManagersDialog.tsx`
- Create: `frontend/src/components/AssignDutyManagersDialog.test.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add the i18n keys**

In `frontend/src/i18n/he.json`, inside the existing `"team": { ... }` object (anywhere among the other `team.*` keys, e.g. right after `"assign_commander": "קביעת מפקד",`), add:

```json
    "assign_duty_managers": "קביעת אחראי תורנויות",
    "no_duty_managers": "אין אחראי תורנויות",
    "duty_managers": "אחראי תורנויות",
    "duty_manager_portfolio": "אחריות אחראי תורנויות",
    "no_duty_manager_scopes": "אין יחידות באחריות",
    "manage_portfolio": "ניהול אחריות תורנויות",
    "add": "הוסף",
```

(Keep valid JSON — add a trailing comma after the line you insert after, and no trailing comma after your last new line if it's immediately followed by another existing key, which it will be.)

- [ ] **Step 2: Write the component test**

Create `frontend/src/components/AssignDutyManagersDialog.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AssignDutyManagersDialog from "./AssignDutyManagersDialog";
import type { NodeDTO } from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockAssign = vi.fn();
const mockRemove = vi.fn();
vi.mock("../api/dmScope", () => ({
  assignDmScope: (...args: unknown[]) => mockAssign(...args),
  removeDmScope: (...args: unknown[]) => mockRemove(...args),
}));

const mockListSoldiers = vi.fn();
vi.mock("../api/soldiers", () => ({
  listSoldiers: () => mockListSoldiers(),
}));

function node(overrides: Partial<NodeDTO> = {}): NodeDTO {
  return {
    id: "node-1",
    level: "department",
    name: "מרכז א",
    parent_id: null,
    commander_id: null,
    commander_name: null,
    path_ids: ["node-1"],
    duty_managers: [],
    dm_manageable: true,
    ...overrides,
  };
}

beforeEach(() => {
  mockAssign.mockReset();
  mockRemove.mockReset();
  mockListSoldiers.mockReset();
  mockListSoldiers.mockResolvedValue([
    { id: "s1", personal_number: "1001", full_name: "דני כהן" },
  ]);
  mockAssign.mockResolvedValue({ id: "scope-1", duty_manager_id: "s1", hierarchy_node_id: "node-1" });
  mockRemove.mockResolvedValue(undefined);
});

test("renders existing duty managers with a remove button each", () => {
  const n = node({
    duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }],
  });
  render(<AssignDutyManagersDialog node={n} onClose={vi.fn()} onChanged={vi.fn()} />);
  expect(screen.getByTestId("duty-managers-list")).toBeInTheDocument();
  expect(screen.getByText("דני כהן")).toBeInTheDocument();
  expect(screen.getByTestId("remove-dm-scope-1")).toBeInTheDocument();
});

test("shows empty state when node has no duty managers", () => {
  render(<AssignDutyManagersDialog node={node()} onClose={vi.fn()} onChanged={vi.fn()} />);
  expect(screen.queryByTestId("duty-managers-list")).not.toBeInTheDocument();
});

test("clicking remove calls removeDmScope and onChanged", async () => {
  const onChanged = vi.fn();
  const n = node({
    duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }],
  });
  render(<AssignDutyManagersDialog node={n} onClose={vi.fn()} onChanged={onChanged} />);
  fireEvent.click(screen.getByTestId("remove-dm-scope-1"));
  await waitFor(() => expect(mockRemove).toHaveBeenCalledWith("scope-1"));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

test("typing and selecting a soldier calls assignDmScope and onChanged", async () => {
  const onChanged = vi.fn();
  render(<AssignDutyManagersDialog node={node()} onClose={vi.fn()} onChanged={onChanged} />);
  await waitFor(() => expect(mockListSoldiers).toHaveBeenCalled());
  const input = screen.getByTestId("duty-manager-search");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "דני" } });
  await waitFor(() => expect(screen.getByTestId("duty-manager-option-s1")).toBeInTheDocument());
  fireEvent.mouseDown(screen.getByTestId("duty-manager-option-s1"));
  await waitFor(() => expect(mockAssign).toHaveBeenCalledWith("s1", "node-1"));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test -- --run AssignDutyManagersDialog`
Expected: FAIL — the component module doesn't exist yet.

- [ ] **Step 4: Implement the component**

Create `frontend/src/components/AssignDutyManagersDialog.tsx`:

```tsx
import Fuse from "fuse.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO } from "../api/hierarchy";
import { assignDmScope, removeDmScope } from "../api/dmScope";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

interface Props {
  node: NodeDTO;
  onClose: () => void;
  onChanged: () => void;
}

export default function AssignDutyManagersDialog({ node, onClose, onChanged }: Props) {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [inputText, setInputText] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void listSoldiers().then(setSoldiers);
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const fuse = useMemo(
    () => new Fuse(soldiers, { keys: ["full_name", "personal_number"], threshold: 0.4 }),
    [soldiers]
  );

  const filtered = inputText
    ? fuse.search(inputText).map((r) => r.item).slice(0, 20)
    : soldiers.slice(0, 20);

  async function handleAdd(s: SoldierDTO) {
    setInputText("");
    setOpen(false);
    try {
      await assignDmScope(s.id, node.id);
      onChanged();
    } catch {
      alert(t("errors.generic"));
    }
  }

  async function handleRemove(scopeId: string) {
    try {
      await removeDmScope(scopeId);
      onChanged();
    } catch {
      alert(t("errors.generic"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96"
        onClick={(e) => e.stopPropagation()}
        data-testid="assign-duty-managers-dialog"
      >
        <h3 className="font-semibold mb-4 dark:text-gray-100">
          {t("team.assign_duty_managers")}: {node.name}
        </h3>

        {node.duty_managers.length === 0 ? (
          <p className="text-sm text-gray-500 mb-3">{t("team.no_duty_managers")}</p>
        ) : (
          <ul className="space-y-1 mb-3" data-testid="duty-managers-list">
            {node.duty_managers.map((dm) => (
              <li
                key={dm.scope_id}
                className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1"
              >
                <span>{dm.name}</span>
                <button
                  type="button"
                  className="text-red-500 hover:text-red-700 text-xs"
                  onClick={() => void handleRemove(dm.scope_id)}
                  data-testid={`remove-dm-${dm.scope_id}`}
                >
                  {t("notifications.remove")}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div ref={containerRef} className="relative">
          <input
            className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={inputText}
            onChange={(e) => { setInputText(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            placeholder={t("team.search_soldier_placeholder")}
            data-testid="duty-manager-search"
            autoComplete="off"
          />
          {open && filtered.length > 0 && (
            <ul className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto">
              {filtered.map((s) => (
                <li
                  key={s.id}
                  className="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 dark:text-gray-100"
                  onMouseDown={(e) => { e.preventDefault(); void handleAdd(s); }}
                  data-testid={`duty-manager-option-${s.id}`}
                >
                  {s.full_name}{" "}
                  <span className="text-gray-400 text-xs">({s.personal_number})</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button
            type="button"
            className="border rounded px-3 py-1 dark:text-gray-100 dark:border-gray-600"
            onClick={onClose}
            data-testid="duty-managers-done"
          >
            {t("team.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- --run AssignDutyManagersDialog`
Expected: PASS (all 4 tests).

- [ ] **Step 6: Run the full frontend suite and lint**

Run: `cd frontend && npm test -- --run && npm run lint`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AssignDutyManagersDialog.tsx frontend/src/components/AssignDutyManagersDialog.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add AssignDutyManagersDialog (per-node DM list with add/remove)"
```

---

## Task 5: Frontend — `DutyManagerPortfolioDialog.tsx` (modal 2)

**Files:**
- Create: `frontend/src/components/DutyManagerPortfolioDialog.tsx`
- Create: `frontend/src/components/DutyManagerPortfolioDialog.test.tsx`

- [ ] **Step 1: Write the component test**

Create `frontend/src/components/DutyManagerPortfolioDialog.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DutyManagerPortfolioDialog from "./DutyManagerPortfolioDialog";
import type { NodeDTO } from "../api/hierarchy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockList = vi.fn();
const mockAssign = vi.fn();
const mockRemove = vi.fn();
vi.mock("../api/dmScope", () => ({
  listDmScope: (...args: unknown[]) => mockList(...args),
  assignDmScope: (...args: unknown[]) => mockAssign(...args),
  removeDmScope: (...args: unknown[]) => mockRemove(...args),
}));

function node(overrides: Partial<NodeDTO> = {}): NodeDTO {
  return {
    id: "node-1",
    level: "department",
    name: "מרכז א",
    parent_id: null,
    commander_id: null,
    commander_name: null,
    path_ids: ["node-1"],
    duty_managers: [],
    dm_manageable: true,
    ...overrides,
  };
}

const nodes: NodeDTO[] = [
  node({ id: "node-1", name: "מרכז א", dm_manageable: true }),
  node({ id: "node-2", name: "מרכז ב", parent_id: null, dm_manageable: false }),
];

beforeEach(() => {
  mockList.mockReset();
  mockAssign.mockReset();
  mockRemove.mockReset();
  mockList.mockResolvedValue([{ id: "scope-1", duty_manager_id: "s1", hierarchy_node_id: "node-1" }]);
  mockAssign.mockResolvedValue({ id: "scope-2", duty_manager_id: "s1", hierarchy_node_id: "node-2" });
  mockRemove.mockResolvedValue(undefined);
});

test("loads and renders the soldier's current portfolio", async () => {
  render(
    <DutyManagerPortfolioDialog soldierId="s1" soldierName="דני כהן" nodes={nodes} onClose={vi.fn()} onChanged={vi.fn()} />
  );
  await waitFor(() => expect(mockList).toHaveBeenCalledWith("s1"));
  await waitFor(() => expect(screen.getByText("מרכז א")).toBeInTheDocument());
});

test("only offers dm_manageable nodes in the add combobox", async () => {
  render(
    <DutyManagerPortfolioDialog soldierId="s1" soldierName="דני כהן" nodes={nodes} onClose={vi.fn()} onChanged={vi.fn()} />
  );
  await waitFor(() => expect(mockList).toHaveBeenCalled());
  const combo = screen.getByTestId("portfolio-add-node");
  fireEvent.focus(combo);
  expect(screen.queryByText("מרכז ב")).not.toBeInTheDocument();
});

test("removing an entry calls removeDmScope, refetches, and calls onChanged", async () => {
  const onChanged = vi.fn();
  render(
    <DutyManagerPortfolioDialog soldierId="s1" soldierName="דני כהן" nodes={nodes} onClose={vi.fn()} onChanged={onChanged} />
  );
  await waitFor(() => expect(screen.getByTestId("remove-portfolio-scope-1")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("remove-portfolio-scope-1"));
  await waitFor(() => expect(mockRemove).toHaveBeenCalledWith("scope-1"));
  await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- --run DutyManagerPortfolioDialog`
Expected: FAIL — the component module doesn't exist yet.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/DutyManagerPortfolioDialog.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO } from "../api/hierarchy";
import { assignDmScope, DmScopeEntry, listDmScope, removeDmScope } from "../api/dmScope";
import Combobox from "./Combobox";
import { sortNodesByTree } from "../utils/sortNodesByTree";

interface Props {
  soldierId: string;
  soldierName: string;
  nodes: NodeDTO[];
  onClose: () => void;
  onChanged: () => void;
}

export default function DutyManagerPortfolioDialog({ soldierId, soldierName, nodes, onClose, onChanged }: Props) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<DmScopeEntry[]>([]);
  const [addNodeId, setAddNodeId] = useState("");
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setEntries(await listDmScope(soldierId));
  }
  useEffect(() => { void refresh(); }, [soldierId]);

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  // Sort the FULL tree first so depth/indentation reflects real hierarchy, then
  // hide rows the viewer can't manage — filtering before sorting would orphan a
  // manageable subtree whose own parent isn't manageable.
  const manageableSorted = sortNodesByTree(nodes).filter(({ node }) => node.dm_manageable);

  async function handleAdd() {
    if (!addNodeId) return;
    setLoading(true);
    try {
      await assignDmScope(soldierId, addNodeId);
      setAddNodeId("");
      await refresh();
      onChanged();
    } catch {
      alert(t("errors.generic"));
    } finally {
      setLoading(false);
    }
  }

  async function handleRemove(entryId: string) {
    try {
      await removeDmScope(entryId);
      await refresh();
      onChanged();
    } catch {
      alert(t("errors.generic"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96"
        onClick={(e) => e.stopPropagation()}
        data-testid="duty-manager-portfolio-dialog"
      >
        <h3 className="font-semibold mb-4 dark:text-gray-100">
          {t("team.duty_manager_portfolio")}: {soldierName}
        </h3>

        {entries.length === 0 ? (
          <p className="text-sm text-gray-500 mb-3">{t("team.no_duty_manager_scopes")}</p>
        ) : (
          <ul className="space-y-1 mb-3" data-testid="portfolio-list">
            {entries.map((e) => (
              <li
                key={e.id}
                className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1"
              >
                <span>{nodeById.get(e.hierarchy_node_id)?.name ?? e.hierarchy_node_id}</span>
                <button
                  type="button"
                  className="text-red-500 hover:text-red-700 text-xs"
                  onClick={() => void handleRemove(e.id)}
                  data-testid={`remove-portfolio-${e.id}`}
                >
                  {t("notifications.remove")}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-2 items-end pt-2 border-t dark:border-gray-600">
          <div className="flex-1">
            <Combobox
              items={manageableSorted.map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
              value={addNodeId}
              onChange={setAddNodeId}
              placeholder="—"
              testId="portfolio-add-node"
            />
          </div>
          <button
            type="button"
            className="bg-indigo-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
            disabled={!addNodeId || loading}
            onClick={() => void handleAdd()}
            data-testid="portfolio-add-submit"
          >
            {t("team.add")}
          </button>
        </div>

        <div className="flex justify-end mt-4">
          <button
            type="button"
            className="border rounded px-3 py-1 dark:text-gray-100 dark:border-gray-600"
            onClick={onClose}
          >
            {t("team.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- --run DutyManagerPortfolioDialog`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Run the full frontend suite and lint**

Run: `cd frontend && npm test -- --run && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DutyManagerPortfolioDialog.tsx frontend/src/components/DutyManagerPortfolioDialog.test.tsx
git commit -m "feat: add DutyManagerPortfolioDialog (per-soldier DM scope list with add/remove)"
```

---

## Task 6: Frontend — wire both modals into `HierarchyTree.tsx`

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`

- [ ] **Step 1: Add the new props to `DroppableNodeRow`**

In `frontend/src/components/HierarchyTree.tsx`, update `DroppableNodeRow`'s prop destructuring and type (around lines 107-139):

```tsx
function DroppableNodeRow({
  node,
  depth,
  isAdmin,
  canHaveChildren,
  onAddChild,
  onAddSoldier,
  onAssignCommander,
  onManageDutyManagers,
  onOpenPortfolio,
  onRename,
  onDelete,
  hasChildren,
  hasSoldiers,
  isExpanded,
  onToggle,
  levelLabel,
  t,
}: {
  node: NodeDTO;
  depth: number;
  isAdmin: boolean;
  canHaveChildren: boolean;
  onAddChild: () => void;
  onAddSoldier: () => void;
  onAssignCommander: () => void;
  onManageDutyManagers: () => void;
  onOpenPortfolio: (soldierId: string, name: string) => void;
  onRename: () => void;
  onDelete: () => void;
  hasChildren: boolean;
  hasSoldiers: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  levelLabel: string;
  t: (k: string) => string;
}) {
```

- [ ] **Step 2: Render duty-manager names and the new button**

In the same component's JSX, replace the commander-name block and the admin-only actions block (around lines 183-210) with:

```tsx
      {node.commander_name && (
        <span className="text-xs text-gray-400" data-testid={`tree-commander-${node.id}`}>
          ({t("team.commander")}: {node.commander_name})
        </span>
      )}
      {node.duty_managers.length > 0 && (
        <span className="text-xs text-gray-400" data-testid={`tree-dm-list-${node.id}`}>
          ({t("team.duty_managers")}:{" "}
          {node.duty_managers.map((dm, i) => (
            <span key={dm.scope_id}>
              {i > 0 && ", "}
              <button
                type="button"
                className="hover:underline text-indigo-600 dark:text-indigo-300"
                onClick={() => onOpenPortfolio(dm.soldier_id, dm.name)}
                data-testid={`tree-dm-link-${dm.scope_id}`}
              >
                {dm.name}
              </button>
            </span>
          ))})
        </span>
      )}
      {(isAdmin || node.dm_manageable) && (
        <span className="flex gap-1 ml-auto">
          {isAdmin && canHaveChildren && (
            <button className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline" onClick={onAddChild} data-testid={`tree-add-child-${node.id}`}>
              +{t("team.add_node")}
            </button>
          )}
          {isAdmin && (
            <button className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline" onClick={onAddSoldier} data-testid={`tree-add-soldier-${node.id}`}>
              +{t("team.add_soldier")}
            </button>
          )}
          {isAdmin && (
            <button className="text-xs text-green-600 hover:underline" onClick={onAssignCommander} data-testid={`tree-commander-btn-${node.id}`}>
              {t("team.assign_commander")}
            </button>
          )}
          {node.dm_manageable && (
            <button className="text-xs text-green-700 hover:underline" onClick={onManageDutyManagers} data-testid={`tree-dm-btn-${node.id}`}>
              {t("team.assign_duty_managers")}
            </button>
          )}
          {isAdmin && (
            <button className="text-xs text-amber-600 hover:underline" onClick={onRename} data-testid={`tree-rename-${node.id}`}>
              {t("team.edit")}
            </button>
          )}
          {isAdmin && !node.commander_id && !hasChildren && (
            <button className="text-xs text-red-500 hover:underline" onClick={onDelete} data-testid={`tree-delete-${node.id}`}>
              {t("duty_config.delete")}
            </button>
          )}
        </span>
      )}
```

(Every individual button keeps its own `isAdmin &&`/`node.dm_manageable &&` guard now, since the outer wrapping condition changed from `isAdmin` alone to `isAdmin || node.dm_manageable` — without per-button guards, a non-admin commander with `dm_manageable: true` would see the add-child/add-soldier/assign-commander/rename/delete buttons too, which must stay admin-only.)

- [ ] **Step 3: Add dialog state and imports to the main component**

Add the import (near the other component imports, around line 16):

```tsx
import AssignDutyManagersDialog from "./AssignDutyManagersDialog";
import DutyManagerPortfolioDialog from "./DutyManagerPortfolioDialog";
```

In `HierarchyTree` (around lines 215-223), add two new state variables alongside the existing dialog states:

```tsx
  const [dmDialogNodeId, setDmDialogNodeId] = useState<string | null>(null);
  const [portfolioSoldier, setPortfolioSoldier] = useState<{ id: string; name: string } | null>(null);
```

- [ ] **Step 4: Wire the new props in `renderNode`**

In `renderNode` (around lines 343-367), add the two new props to the `<DroppableNodeRow ... />` call:

```tsx
        <DroppableNodeRow
          node={node}
          depth={depth}
          isAdmin={isAdmin}
          canHaveChildren={canHaveChildrenFn(node.level)}
          onAddChild={() => setAddDialog(node)}
          onAddSoldier={() => setQuickAddNode(node.id)}
          onAssignCommander={() => setCommanderDialog(node)}
          onManageDutyManagers={() => setDmDialogNodeId(node.id)}
          onOpenPortfolio={(soldierId, name) => setPortfolioSoldier({ id: soldierId, name })}
          onRename={() => setRenameDialog(node)}
          onDelete={() => void handleDelete(node.id)}
          hasChildren={hasChildren}
          hasSoldiers={nodeSoldiers.length > 0}
          isExpanded={isExpanded}
          onToggle={() => toggle(node.id)}
          levelLabel={labelByKey.get(node.level) ?? node.level}
          t={t}
        />
```

- [ ] **Step 5: Render the two dialogs**

In the final return block (around lines 426-453), add after the existing `{commanderDialog && (...)}` block:

```tsx
      {dmDialogNodeId && (() => {
        const dmNode = nodes.find((n) => n.id === dmDialogNodeId);
        return dmNode ? (
          <AssignDutyManagersDialog
            node={dmNode}
            onClose={() => setDmDialogNodeId(null)}
            onChanged={onChanged}
          />
        ) : null;
      })()}
      {portfolioSoldier && (
        <DutyManagerPortfolioDialog
          soldierId={portfolioSoldier.id}
          soldierName={portfolioSoldier.name}
          nodes={nodes}
          onClose={() => setPortfolioSoldier(null)}
          onChanged={onChanged}
        />
      )}
```

(Looking up `dmDialogNodeId` in the live `nodes` array on every render — rather than storing the `NodeDTO` snapshot directly, the way `commanderDialog`/`renameDialog` do — is deliberate: `AssignDutyManagersDialog` stays open across multiple add/remove actions, and each one calls `onChanged()` which triggers the parent page's `refresh()`, updating the `nodes` prop. Re-deriving `dmNode` from the fresh `nodes` array on every render means the dialog's duty-manager list updates live instead of going stale.)

- [ ] **Step 6: Write a test for the new button's visibility gating**

`frontend/src/components/HierarchyTree.test.tsx` does not exist yet — create it:

```tsx
import { render, screen } from "@testing-library/react";
import HierarchyTree from "./HierarchyTree";
import type { NodeDTO } from "../api/hierarchy";
import type { SoldierDTO } from "../api/soldiers";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../hooks/useLevelTypes", () => ({
  useLevelTypes: () => ({ levelTypes: [{ id: "lt1", key: "department", label: "מרכז", rank: 1 }] }),
}));

function node(overrides: Partial<NodeDTO> = {}): NodeDTO {
  return {
    id: "node-1",
    level: "department",
    name: "מרכז א",
    parent_id: null,
    commander_id: null,
    commander_name: null,
    path_ids: ["node-1"],
    duty_managers: [],
    dm_manageable: false,
    ...overrides,
  };
}

const soldiers: SoldierDTO[] = [];

test("does not show the assign-duty-managers button when dm_manageable is false and viewer is not admin", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: false })]} soldiers={soldiers} isAdmin={false} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-dm-btn-node-1")).not.toBeInTheDocument();
});

test("shows the assign-duty-managers button when dm_manageable is true, even for a non-admin commander", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true })]} soldiers={soldiers} isAdmin={false} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.getByTestId("tree-dm-btn-node-1")).toBeInTheDocument();
});

test("does not show admin-only buttons for a non-admin commander even when dm_manageable is true", () => {
  render(
    <HierarchyTree nodes={[node({ dm_manageable: true })]} soldiers={soldiers} isAdmin={false} canManageLevelTypes={false} onChanged={vi.fn()} />
  );
  expect(screen.queryByTestId("tree-commander-btn-node-1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("tree-rename-node-1")).not.toBeInTheDocument();
});

test("renders duty manager names as clickable links", () => {
  render(
    <HierarchyTree
      nodes={[node({ duty_managers: [{ scope_id: "scope-1", soldier_id: "s1", name: "דני כהן" }] })]}
      soldiers={soldiers}
      isAdmin={true}
      canManageLevelTypes={false}
      onChanged={vi.fn()}
    />
  );
  expect(screen.getByTestId("tree-dm-link-scope-1")).toHaveTextContent("דני כהן");
});
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npm test -- --run HierarchyTree`
Expected: PASS.

- [ ] **Step 8: Run the full frontend suite and lint**

Run: `cd frontend && npm test -- --run && npm run lint`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/HierarchyTree.tsx frontend/src/components/HierarchyTree.test.tsx
git commit -m "feat: wire duty-manager assignment and portfolio dialogs into HierarchyTree"
```

---

## Task 7: Frontend — soldier-table entry point in `TeamHierarchyPage.tsx`

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`

- [ ] **Step 1: Add state and import**

In `frontend/src/pages/TeamHierarchyPage.tsx`, add the import (near the other component imports, around line 13):

```tsx
import DutyManagerPortfolioDialog from "../components/DutyManagerPortfolioDialog";
```

Add state right after the existing `tempPw` state (around line 24):

```tsx
  const [portfolioSoldier, setPortfolioSoldier] = useState<{ id: string; name: string } | null>(null);
```

- [ ] **Step 2: Add the action link to the soldier table**

In the `actions` column's `cell` (around lines 161-170), add a new button before the existing ones:

```tsx
              {
                id: "actions",
                header: "",
                cell: (s) => (
                  <span className="space-x-2 space-x-reverse">
                    {(isAdmin || (user?.is_commander ?? false)) && (
                      <button
                        onClick={() => setPortfolioSoldier({ id: s.id, name: s.full_name })}
                        className="text-indigo-600 dark:text-indigo-300"
                        data-testid={`dm-portfolio-${s.personal_number}`}
                      >
                        {t("team.manage_portfolio")}
                      </button>
                    )}
                    <button onClick={() => openSoldierModal(s.id, refresh)} className="text-indigo-600 dark:text-indigo-300" data-testid={`edit-${s.personal_number}`}>{t("team.edit")}</button>
                    <button onClick={() => onReset(s.id)} className="text-indigo-600 dark:text-indigo-300" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
                    <button onClick={() => onRemove(s.id)} className="text-red-600" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
                  </span>
                ),
              },
```

(`isAdmin` and `user` are already in scope in this component — `isAdmin` from line 25, `user` from the `useAuth()` call at line 17.)

- [ ] **Step 3: Render the dialog**

Right before the closing `</Layout>` (around line 188-190), add:

```tsx
        {portfolioSoldier && (
          <DutyManagerPortfolioDialog
            soldierId={portfolioSoldier.id}
            soldierName={portfolioSoldier.name}
            nodes={nodes}
            onClose={() => setPortfolioSoldier(null)}
            onChanged={refresh}
          />
        )}
      </section>
    </Layout>
  );
}
```

(This replaces the existing trailing `</section>` / blank lines / `</Layout>` — make sure the dialog ends up as a sibling after `</section>`, inside the `<Layout>` wrapper, matching the existing structure.)

- [ ] **Step 4: Run the full frontend suite and lint**

Run: `cd frontend && npm test -- --run && npm run lint`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite one more time as a closing sanity check**

Run: `cd backend && source .venv/Scripts/activate && pytest -q`
Expected: PASS — this closes out the hierarchy-page duty-manager-management feature.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TeamHierarchyPage.tsx
git commit -m "feat: add duty-manager portfolio entry point to the soldier table"
```
