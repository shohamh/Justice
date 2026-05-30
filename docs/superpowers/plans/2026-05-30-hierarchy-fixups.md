# Hierarchy & Soldier Editor Fixups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement post-user-testing fixes to the hierarchy tree editor on the /team page.

**Architecture:** Backend (FastAPI + SQLAlchemy) changes to add two new hierarchy levels and relax level validation; frontend (React + Tailwind) changes to add inline soldier quick-add per tree node, a soldier edit modal, and cosmetic button fixes.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / Alembic / PostgreSQL — React 18 / TypeScript / Tailwind CSS / react-i18next / Vitest + Playwright (E2E)

---

### Task 1: Add `division` and `unit` to the hierarchy level enum (models)

**Files:**
- Modify: `backend/app/db/models.py:89-91`

- [ ] **Step 1: Add division and unit to the SQLAlchemy Enum**

In `backend/app/db/models.py:89-91`, expand the Enum values from `("department", "branch", "group", "team")` to `("division", "unit", "department", "branch", "group", "team")`.

```python
    level: Mapped[str] = mapped_column(
        Enum("division", "unit", "department", "branch", "group", "team", name="hierarchy_level")
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(db): add division and unit to hierarchy_level enum"
```

---

### Task 2: Update LEVEL_ORDER and relax child-level validation (service)

**Files:**
- Modify: `backend/app/services/hierarchy.py`

- [ ] **Step 1: Update LEVEL_ORDER and relax `_expected_child_level`**

Change `LEVEL_ORDER` from `["department", "branch", "group", "team"]` to `["division", "unit", "department", "branch", "group", "team"]`.

Replace `_expected_child_level` (which returned only the exact next level) with a function that validates the child level is ANY level below the parent, not just the immediate next. Keep the validate function name but change the semantics.

```python
LEVEL_ORDER = ["division", "unit", "department", "branch", "group", "team"]


def _validate_child_level(parent_level: str, child_level: str) -> bool:
    """Return True if child_level is any level below parent_level."""
    try:
        return LEVEL_ORDER.index(child_level) > LEVEL_ORDER.index(parent_level)
    except ValueError:
        return False
```

- [ ] **Step 2: Update callsites in the service**

In `create_node` (line 43), change:
```python
if _expected_child_level(parent.level) != level:
    raise HierarchyError(
        f"a {parent.level} can only contain {_expected_child_level(parent.level)} nodes"
    )
```
to:
```python
if not _validate_child_level(parent.level, level):
    raise HierarchyError(
        f"a {parent.level} cannot contain {level} nodes"
    )
```

In `move_node` (line 89), change:
```python
if _expected_child_level(parent.level) != node.level:
    raise HierarchyError(
        f"a {parent.level} can only contain {_expected_child_level(parent.level)} nodes"
    )
```
to:
```python
if not _validate_child_level(parent.level, node.level):
    raise HierarchyError(
        f"a {parent.level} cannot contain {node.level} nodes"
    )
```

Also remove unused `_expected_child_level` import/function if it's now fully replaced.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/hierarchy.py
git commit -m "feat(hierarchy): relax child-level validation to any level below"
```

---

### Task 3: Update CreateNodeRequest regex pattern (route)

**Files:**
- Modify: `backend/app/routes/hierarchy.py:30`

- [ ] **Step 1: Expand the regex to include new levels**

Change the `CreateNodeRequest.level` field pattern from `^(department|branch|group|team)$` to `^(division|unit|department|branch|group|team)$`.

```python
    level: str = Field(pattern="^(division|unit|department|branch|group|team)$")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/routes/hierarchy.py
git commit -m "fix(hierarchy): update CreateNodeRequest regex for new levels"
```

---

### Task 4: Add hierarchy_node_id to soldier update endpoint

**Files:**
- Modify: `backend/app/routes/soldiers.py:42-44` (UpdateRequest)
- Modify: `backend/app/services/soldiers.py:94-116` (update_soldier)
- Modify: `backend/app/api/soldiers.ts` (frontend API client)

- [ ] **Step 1: Add hierarchy_node_id to UpdateRequest**

```python
class UpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    hierarchy_node_id: uuid.UUID | None = None
```

- [ ] **Step 2: Update update_soldier service function to handle hierarchy_node_id**

Modify `backend/app/services/soldiers.py`:

```python
def update_soldier(
    session: Session,
    *,
    soldier: Soldier,
    full_name: str | None,
    phone: str | None,
    hierarchy_node_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Soldier:
    before: dict[str, Any] = {
        "full_name": soldier.full_name,
        "phone": soldier.phone,
        "hierarchy_node_id": str(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None,
    }
    if full_name is not None:
        soldier.full_name = full_name
    if phone is not None:
        soldier.phone = phone
    if hierarchy_node_id is not None:
        if session.get(HierarchyNode, hierarchy_node_id) is None:
            raise SoldierError("hierarchy node not found")
        soldier.hierarchy_node_id = hierarchy_node_id
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.update",
        entity_type="soldier",
        entity_id=soldier.id,
        before=before,
        after={
            "full_name": soldier.full_name,
            "phone": soldier.phone,
            "hierarchy_node_id": str(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None,
        },
    )
    return soldier
```

Add `from typing import Any` at the top of `soldiers.py` if not already there.

- [ ] **Step 3: Pass hierarchy_node_id from route to service**

In `backend/app/routes/soldiers.py`, update the `update` endpoint:
```python
svc.update_soldier(
    session, soldier=s, full_name=body.full_name, phone=body.phone,
    hierarchy_node_id=body.hierarchy_node_id, actor_id=user.id
)
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/soldiers.py backend/app/services/soldiers.py
git commit -m "feat(soldiers): support hierarchy_node_id in update endpoint"
```

---

### Task 5: Create Alembic migration 0017

**Files:**
- Create: `backend/alembic/versions/0017_add_division_unit_levels.py`

- [ ] **Step 1: Write the migration**

```python
"""add division and unit to hierarchy_level enum

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-30
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE hierarchy_level ADD VALUE IF NOT EXISTS 'division'")
    op.execute("ALTER TYPE hierarchy_level ADD VALUE IF NOT EXISTS 'unit'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum.
    # Downgrade would require creating a new type, migrating, and dropping.
    # This is a no-op — production rollback would be handled by restoring from backup.
    pass
```

- [ ] **Step 2: Commit**

```bash
git add backend/alembic/versions/0017_add_division_unit_levels.py
git commit -m "feat(db): migration 0017 — add division and unit to hierarchy_level"
```

---

### Task 6: Update backend unit tests for new levels and flexible validation

**Files:**
- Modify: `backend/tests/unit/test_hierarchy_service.py`

- [ ] **Step 1: Update existing test `test_move_enforces_level_rules` and `test_create_child_must_be_exactly_one_level_down`**

The test `test_move_enforces_level_rules` moves `g1` (group) under `d2` (department). With the relaxed validation, group IS below department, so this test should now PASS. Update the test name and assertion:

```python
def test_move_allows_any_level_below(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    d2 = seed_node(admin_session, level="department", name="d2")
    # Moving group under department directly is now allowed (any level below)
    move_node(admin_session, node_id=g1.id, new_parent_id=d2.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(g1)
    assert g1.parent_id == d2.id
```

Rename the test `test_create_child_must_be_exactly_one_level_down` to reflect the new behavior (creating a team directly under department is now allowed):

```python
def test_create_child_allows_any_level_below(admin_session):
    dept = seed_node(admin_session, level="department", name="חיל")
    # Creating team directly under department is now allowed
    team = create_node(
        admin_session, level="team", name="צוות", parent_id=dept.id, actor_id=None
    )
    admin_session.commit()
    assert team.path_ids == [dept.id, team.id]
```

- [ ] **Step 2: Run the backend tests**

Run: `cd backend; pytest tests/unit/test_hierarchy_service.py -v`

Expected: All tests pass (the two modified tests should reflect new relaxed validation).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_hierarchy_service.py
git commit -m "test(hierarchy): update tests for flexible level validation"
```

---

### Task 7: Update backend integration tests for new levels

**Files:**
- Modify: `backend/tests/integration/test_hierarchy_api.py`

- [ ] **Step 1: Update `test_create_skipping_level_rejected`**

This test creates a `team` under `department` and expects 400. With relaxed validation, this should now succeed. Rename and update the test:

```python
def test_create_any_level_below_allowed(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000002", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "team", "name": "צוות", "parent_id": str(dept.id)},
    )
    assert r.status_code == 201
```

- [ ] **Step 2: Run integration tests**

Run: `cd backend; pytest tests/integration/test_hierarchy_api.py -v`

Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_hierarchy_api.py
git commit -m "test(hierarchy): update integration tests for flexible level validation"
```

---

### Task 8: Update frontend NodeDTO and i18n translations

**Files:**
- Modify: `frontend/src/api/hierarchy.ts`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add division and unit to NodeDTO.level type union**

```typescript
export interface NodeDTO {
  id: string;
  level: "division" | "unit" | "department" | "branch" | "group" | "team";
  name: string;
  parent_id: string | null;
  commander_id: string | null;
  commander_name: string | null;
  path_ids: string[];
}
```

- [ ] **Step 2: Add new i18n keys and update translations**

In `frontend/src/i18n/he.json`, update the `team` section:
- Change `level_department` from `"אגף"` to match the spec's Hebrew display names
- Add `level_division`: `"מערך"`
- Add `level_unit`: `"יחידה"`
- Update `level_department`: `"מרכז"`
- Update `level_branch`: `"ענף"`
- Update `level_group`: `"מדור"`
- Keep `level_team`: `"צוות"`

```json
"level_division": "מערך",
"level_unit": "יחידה",
"level_department": "מרכז",
"level_branch": "ענף",
"level_group": "מדור",
"level_team": "צוות"
```

- [ ] **Step 3: Add `edit_soldier` i18n key for the upcoming edit modal**

```json
"edit_soldier": "עריכת חייל",
```

- [ ] **Step 4: Update LEVEL_COLORS in HierarchyTree.tsx to include new levels**

```typescript
const LEVEL_COLORS: Record<string, string> = {
  division: "text-purple-700 bg-purple-50",
  unit: "text-indigo-700 bg-indigo-50",
  department: "text-blue-700 bg-blue-50",
  branch: "text-green-700 bg-green-50",
  group: "text-yellow-700 bg-yellow-50",
  team: "text-gray-700 bg-gray-100",
};
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/hierarchy.ts frontend/src/i18n/he.json frontend/src/components/HierarchyTree.tsx
git commit -m "feat(ui): add division/unit types and i18n keys"
```

---

### Task 9: Update AddChildNodeDialog to show all sub-levels

**Files:**
- Modify: `frontend/src/components/AddChildNodeDialog.tsx`

- [ ] **Step 1: Replace CHILD_LEVELS with LEVEL_ORDER and filter logic**

```typescript
const LEVEL_ORDER = ["division", "unit", "department", "branch", "group", "team"];

interface Props {
  parent: NodeDTO;
  onClose: () => void;
  onCreated: () => void;
}

export default function AddChildNodeDialog({ parent, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");

  const parentIndex = LEVEL_ORDER.indexOf(parent.level);
  const possibleLevels = LEVEL_ORDER.slice(parentIndex + 1);
  const [level, setLevel] = useState(possibleLevels[0] ?? "");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await createNode({ level, name, parent_id: parent.id });
    onCreated();
    onClose();
  }

  if (possibleLevels.length === 0) return null;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="add-child-dialog">
        <h3 className="font-semibold mb-4">{t("team.add_child_node")}: {parent.name}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <select className="border rounded p-1 w-full" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="child-level">
            {possibleLevels.map((l) => (
              <option key={l} value={l}>{t(`team.level_${l}`)}</option>
            ))}
          </select>
          <input className="border rounded p-1 w-full" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("team.node_name")} required data-testid="child-name" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("duty_config.delete")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="child-submit">{t("team.add_soldier")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

Remove the `CHILD_LEVELS` constant entirely.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/AddChildNodeDialog.tsx
git commit -m "feat(ui): show all sub-levels in AddChildNodeDialog"
```

---

### Task 10: Fix AssignCommanderDialog placeholder text

**Files:**
- Modify: `frontend/src/components/AssignCommanderDialog.tsx`

- [ ] **Step 1: Change the placeholder from `t("my_requests.reason")` to "חפש חייל..."**

Change line 41:
```typescript
          <input className="border rounded p-1 w-full" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("my_requests.reason")} data-testid="commander-search" />
```
to:
```typescript
          <input className="border rounded p-1 w-full" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("team.search_soldier_placeholder")} data-testid="commander-search" />
```

- [ ] **Step 2: Add the i18n key `team.search_soldier_placeholder` to he.json**

```json
"search_soldier_placeholder": "חפש חייל..."
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AssignCommanderDialog.tsx frontend/src/i18n/he.json
git commit -m "fix(ui): fix AssignCommanderDialog placeholder text"
```

---

### Task 11: Create SoldierSearchAutocomplete component

**Files:**
- Create: `frontend/src/components/SoldierSearchAutocomplete.tsx`

- [ ] **Step 1: Write the reusable SoldierSearchAutocomplete**

This is a debounced search/autocomplete that fetches soldiers via the existing `listSoldiers` API (for now; no dedicated search endpoint exists) and displays matching results.

```typescript
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { listSoldiers, SoldierDTO } from "../api/soldiers";

interface Props {
  nodeId: string;
  onSelect: (soldier: SoldierDTO | null) => void;
  onCreateNew: (personalNumber: string, fullName: string) => void;
}

export default function SoldierSearchAutocomplete({ nodeId, onSelect, onCreateNew }: Props) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [results, setResults] = useState<SoldierDTO[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selected, setSelected] = useState<SoldierDTO | null>(null);
  const [newPn, setNewPn] = useState("");
  const [newName, setNewName] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void (async () => {
      const all = await listSoldiers();
      setSoldiers(all);
    })();
  }, []);

  useEffect(() => {
    if (!query.trim() || selected) {
      setResults([]);
      return;
    }
    const q = query.toLowerCase();
    const filtered = soldiers.filter(
      (s) => s.full_name.toLowerCase().includes(q) || s.personal_number.includes(q)
    );
    setResults(filtered.slice(0, 10));
  }, [query, soldiers, selected]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleSelect(s: SoldierDTO) {
    setSelected(s);
    setQuery(`${s.full_name} (${s.personal_number})`);
    setShowDropdown(false);
    onSelect(s);
  }

  function handleClear() {
    setSelected(null);
    setQuery("");
    onSelect(null);
  }

  function handleCreateNew() {
    setShowCreateForm(true);
    setShowDropdown(false);
  }

  function handleSubmitNew() {
    onCreateNew(newPn || query, newName || query);
    setShowCreateForm(false);
    setNewPn("");
    setNewName("");
  }

  return (
    <div ref={ref} className="relative">
      {!showCreateForm ? (
        <>
          <input
            className="border rounded p-1 w-full"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setShowDropdown(true);
            }}
            onFocus={() => setShowDropdown(true)}
            placeholder={t("team.search_soldier_placeholder")}
            data-testid="soldier-search-input"
          />
          {showDropdown && results.length > 0 && (
            <ul className="absolute z-10 bg-white border rounded w-full mt-1 shadow-lg max-h-48 overflow-y-auto" data-testid="soldier-search-dropdown">
              {results.map((s) => (
                <li
                  key={s.id}
                  className="px-2 py-1 hover:bg-indigo-50 cursor-pointer text-sm"
                  onClick={() => handleSelect(s)}
                  data-testid={`soldier-search-result-${s.personal_number}`}
                >
                  {s.full_name} ({s.personal_number})
                </li>
              ))}
              <li
                className="px-2 py-1 hover:bg-gray-50 cursor-pointer text-sm text-indigo-600 border-t"
                onClick={handleCreateNew}
                data-testid="soldier-search-create-new"
              >
                {t("team.create_new_soldier")}
              </li>
            </ul>
          )}
          {selected && (
            <button className="text-xs text-red-500 mt-1" onClick={handleClear} data-testid="soldier-search-clear">
              {t("duty_config.delete")}
            </button>
          )}
        </>
      ) : (
        <div className="space-y-2 border rounded p-2 mt-1" data-testid="soldier-create-form">
          <input
            className="border rounded p-1 w-full"
            value={newPn}
            onChange={(e) => setNewPn(e.target.value)}
            placeholder={t("team.personal_number")}
            data-testid="soldier-create-pn"
          />
          <input
            className="border rounded p-1 w-full"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("team.full_name")}
            data-testid="soldier-create-name"
          />
          <button className="bg-indigo-600 text-white px-3 py-1 rounded text-sm" onClick={handleSubmitNew} data-testid="soldier-create-submit">
            {t("team.add_soldier")}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add new i18n keys for the autocomplete**

In `he.json`, add:
```json
"search_soldier_placeholder": "חפש חייל...",
"create_new_soldier": "צור חייל חדש"
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SoldierSearchAutocomplete.tsx frontend/src/i18n/he.json
git commit -m "feat(ui): create SoldierSearchAutocomplete component"
```

---

### Task 12: Create SoldierEditModal component

**Files:**
- Create: `frontend/src/components/SoldierEditModal.tsx`

- [ ] **Step 1: Write the SoldierEditModal**

This modal lets authorized users edit a soldier's full name, phone, and reassign them to a different hierarchy node.

```typescript
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { SoldierDTO } from "../api/soldiers";

interface Props {
  soldier: SoldierDTO;
  nodeId: string;
  onSave: (data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null }) => Promise<void>;
  onClose: () => void;
}

export default function SoldierEditModal({ soldier, nodeId, onSave, onClose }: Props) {
  const { t } = useTranslation();
  const [fullName, setFullName] = useState(soldier.full_name);
  const [phone, setPhone] = useState(soldier.phone ?? "");
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [hierarchyNodeId, setHierarchyNodeId] = useState(soldier.hierarchy_node_id ?? "");

  useEffect(() => {
    void (async () => {
      const all = await fetchTree();
      setNodes(all);
    })();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null } = {};
    if (fullName !== soldier.full_name) data.full_name = fullName;
    if (phone !== (soldier.phone ?? "")) data.phone = phone || null;
    if (hierarchyNodeId !== (soldier.hierarchy_node_id ?? "")) data.hierarchy_node_id = hierarchyNodeId || null;
    await onSave(data);
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="soldier-edit-modal">
        <h3 className="font-semibold mb-4">{t("team.edit_soldier")}: {soldier.full_name}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <label className="block">
            <span className="text-xs">{t("team.full_name")}</span>
            <input className="border rounded p-1 w-full" value={fullName} onChange={(e) => setFullName(e.target.value)} required data-testid="edit-soldier-name" />
          </label>
          <label className="block">
            <span className="text-xs">{t("profile.phone")}</span>
            <input className="border rounded p-1 w-full" value={phone} onChange={(e) => setPhone(e.target.value)} data-testid="edit-soldier-phone" />
          </label>
          <label className="block">
            <span className="text-xs">{t("team.title")}</span>
            <select className="border rounded p-1 w-full" value={hierarchyNodeId} onChange={(e) => setHierarchyNodeId(e.target.value)} data-testid="edit-soldier-node">
              <option value="">—</option>
              {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("duty_config.delete")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="edit-soldier-submit">{t("duty_config.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add i18n key for phone in `he.json`**

Add under `"profile"` section:
```json
"phone": "טלפון"
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SoldierEditModal.tsx frontend/src/i18n/he.json
git commit -m "feat(ui): create SoldierEditModal component"
```

---

### Task 13: Update HierarchyTree with soldier quick-add, edit modal, and button fix

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`
- Modify: `frontend/src/api/soldiers.ts` (add `updateSoldier` function)

- [ ] **Step 1: Add the `updateSoldier` API function**

In `frontend/src/api/soldiers.ts`, add:
```typescript
export async function updateSoldier(
  id: string,
  input: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null }
): Promise<SoldierDTO> {
  return (await api.patch<SoldierDTO>(`/soldiers/${id}`, input)).data;
}
```

- [ ] **Step 2: Rewrite HierarchyTree.tsx**

The major changes to `HierarchyTree.tsx`:
1. Fix the "פטורים" button label from `t("exemptions.title")` to `t("team.assign_commander")`
2. Add a "+" button on each node to expand an inline quick-add form using SoldierSearchAutocomplete
3. Show soldiers assigned to each node under the tree node
4. Add an edit button on each soldier row that opens SoldierEditModal
5. Update LEVEL_COLORS to include division/unit
6. Update canHaveChildren logic for new levels

Full file rewrite:

```typescript
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, deleteNode } from "../api/hierarchy";
import { SoldierDTO, updateSoldier, listSoldiers } from "../api/soldiers";
import { onboardSoldier } from "../api/soldiers";
import AddChildNodeDialog from "./AddChildNodeDialog";
import AssignCommanderDialog from "./AssignCommanderDialog";
import RenameNodeDialog from "./RenameNodeDialog";
import SoldierSearchAutocomplete from "./SoldierSearchAutocomplete";
import SoldierEditModal from "./SoldierEditModal";

const LEVEL_COLORS: Record<string, string> = {
  division: "text-purple-700 bg-purple-50",
  unit: "text-indigo-700 bg-indigo-50",
  department: "text-blue-700 bg-blue-50",
  branch: "text-green-700 bg-green-50",
  group: "text-yellow-700 bg-yellow-50",
  team: "text-gray-700 bg-gray-100",
};

// All levels except the last can have children
const LEVEL_ORDER = ["division", "unit", "department", "branch", "group", "team"];

interface Props {
  nodes: NodeDTO[];
  soldiers: SoldierDTO[];
  isAdmin: boolean;
  onChanged: () => void;
}

export default function HierarchyTree({ nodes, soldiers, isAdmin, onChanged }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set(nodes.filter((n) => n.path_ids.length <= 2).map((n) => n.id)));
  const [addDialog, setAddDialog] = useState<NodeDTO | null>(null);
  const [commanderDialog, setCommanderDialog] = useState<NodeDTO | null>(null);
  const [renameDialog, setRenameDialog] = useState<NodeDTO | null>(null);
  const [quickAddNode, setQuickAddNode] = useState<string | null>(null);
  const [editSoldier, setEditSoldier] = useState<{ soldier: SoldierDTO; nodeId: string } | null>(null);
  const [allSoldiers, setAllSoldiers] = useState<SoldierDTO[]>(soldiers);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function handleDelete(id: string) {
    if (!confirm(t("team.remove") + "?")) return;
    try {
      await deleteNode(id);
      onChanged();
    } catch {
      alert(t("errors.generic"));
    }
  }

  async function handleQuickAdd(nodeId: string, soldier: SoldierDTO | null, personalNumber: string, fullName: string) {
    if (soldier) {
      // Assign existing soldier to this node
      await updateSoldier(soldier.id, { hierarchy_node_id: nodeId });
    } else {
      // Create new soldier under this node
      await onboardSoldier({ personal_number: personalNumber, full_name: fullName, hierarchy_node_id: nodeId });
    }
    setQuickAddNode(null);
    const refreshed = await listSoldiers();
    setAllSoldiers(refreshed);
    onChanged();
  }

  async function handleEditSave(soldierId: string, data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null }) {
    await updateSoldier(soldierId, data);
    const refreshed = await listSoldiers();
    setAllSoldiers(refreshed);
    onChanged();
  }

  const childrenOf = (parentId: string | null) =>
    nodes.filter((n) => n.parent_id === parentId).sort((a, b) => a.name.localeCompare(b.name));

  const soldiersOf = (nodeId: string) =>
    allSoldiers.filter((s) => s.hierarchy_node_id === nodeId && !s.left_at);

  const canHaveChildren = (level: string) => {
    const idx = LEVEL_ORDER.indexOf(level);
    return idx >= 0 && idx < LEVEL_ORDER.length - 1;
  };

  function renderNode(node: NodeDTO, depth: number) {
    const children = childrenOf(node.id);
    const isExpanded = expanded.has(node.id);
    const hasChildren = children.length > 0;
    const nodeSoldiers = soldiersOf(node.id);

    return (
      <li key={node.id} className="select-none">
        <div className={`flex items-center gap-2 py-1 px-2 hover:bg-gray-50 rounded ${depth > 0 ? "mr-4" : ""}`}>
          <button
            className={`w-4 h-4 flex items-center justify-center text-xs ${hasChildren || nodeSoldiers.length > 0 ? "visible" : "invisible"}`}
            onClick={() => toggle(node.id)}
            data-testid={`tree-toggle-${node.id}`}
          >
            {isExpanded ? "▼" : "▶"}
          </button>
          <span className={`text-xs px-1.5 py-0.5 rounded ${LEVEL_COLORS[node.level] ?? ""}`}>
            {t(`team.level_${node.level}`)}
          </span>
          <span className="font-medium" data-testid={`tree-name-${node.id}`}>{node.name}</span>
          {node.commander_name && (
            <span className="text-xs text-gray-400" data-testid={`tree-commander-${node.id}`}>
              ({t("team.commander")}: {node.commander_name})
            </span>
          )}
          {isAdmin && (
            <span className="flex gap-1 ml-auto">
              {canHaveChildren(node.level) && (
                <button className="text-xs text-indigo-600 hover:underline" onClick={() => setAddDialog(node)} data-testid={`tree-add-child-${node.id}`}>
                  +{t("team.add_node")}
                </button>
              )}
              <button className="text-xs text-green-600 hover:underline" onClick={() => setQuickAddNode(node.id)} data-testid={`tree-add-soldier-${node.id}`}>
                +{t("team.add_soldier")}
              </button>
              <button className="text-xs text-green-600 hover:underline" onClick={() => setCommanderDialog(node)} data-testid={`tree-commander-btn-${node.id}`}>
                {t("team.assign_commander")}
              </button>
              <button className="text-xs text-amber-600 hover:underline" onClick={() => setRenameDialog(node)} data-testid={`tree-rename-${node.id}`}>
                {t("duty_config.save")}
              </button>
              {!node.commander_id && children.length === 0 && (
                <button className="text-xs text-red-500 hover:underline" onClick={() => handleDelete(node.id)} data-testid={`tree-delete-${node.id}`}>
                  {t("duty_config.delete")}
                </button>
              )}
            </span>
          )}
        </div>

        {quickAddNode === node.id && (
          <div className="mr-8 mb-2 px-2" data-testid={`quick-add-${node.id}`}>
            <SoldierSearchAutocomplete
              nodeId={node.id}
              onSelect={(s) => {
                if (s) {
                  void handleQuickAdd(node.id, s, "", "");
                }
              }}
              onCreateNew={(pn, name) => {
                void handleQuickAdd(node.id, null, pn || "", name || "");
              }}
            />
          </div>
        )}

        {isExpanded && nodeSoldiers.length > 0 && (
          <ul className="mr-8 mb-1" data-testid={`tree-soldiers-${node.id}`}>
            {nodeSoldiers.map((s) => (
              <li key={s.id} className="flex items-center gap-2 py-0.5 px-2 text-sm text-gray-600" data-testid={`tree-soldier-${s.personal_number}`}>
                <span className="w-1 h-1 bg-gray-300 rounded-full inline-block" />
                <span>{s.full_name}</span>
                <span className="text-xs text-gray-400">({s.personal_number})</span>
                {isAdmin && (
                  <button
                    className="text-xs text-indigo-600 hover:underline ml-auto"
                    onClick={() => setEditSoldier({ soldier: s, nodeId: node.id })}
                    data-testid={`edit-soldier-${s.personal_number}`}
                  >
                    {t("duty_config.save")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {hasChildren && isExpanded && (
          <ul className="border-r-2 border-gray-100 mr-2">
            {children.map((child) => renderNode(child, depth + 1))}
          </ul>
        )}
      </li>
    );
  }

  const roots = childrenOf(null);

  return (
    <>
      <ul className="text-sm text-gray-700" data-testid="node-tree">
        {roots.map((node) => renderNode(node, 0))}
      </ul>

      {addDialog && (
        <AddChildNodeDialog parent={addDialog} onClose={() => setAddDialog(null)} onCreated={onChanged} />
      )}
      {commanderDialog && (
        <AssignCommanderDialog node={commanderDialog} onClose={() => setCommanderDialog(null)} onAssigned={onChanged} />
      )}
      {renameDialog && (
        <RenameNodeDialog nodeId={renameDialog.id} currentName={renameDialog.name} onClose={() => setRenameDialog(null)} onRenamed={onChanged} />
      )}
      {editSoldier && (
        <SoldierEditModal
          soldier={editSoldier.soldier}
          nodeId={editSoldier.nodeId}
          onSave={(data) => handleEditSave(editSoldier.soldier.id, data)}
          onClose={() => setEditSoldier(null)}
        />
      )}
    </>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HierarchyTree.tsx frontend/src/api/soldiers.ts
git commit -m "feat(ui): add soldier quick-add, edit modal, and button fix to tree"
```

---

### Task 14: Update TeamHierarchyPage to pass soldiers to tree

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`

- [ ] **Step 1: Pass soldiers to HierarchyTree and remove inline soldier table**

Since soldiers are now shown directly in the tree, update the page to pass soldiers to the HierarchyTree and clean up the duplicated soldier table.

```typescript
export default function TeamHierarchyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [pn, setPn] = useState("");
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [tempPw, setTempPw] = useState<string | null>(null);
  const [selected, setSelected] = useState<SoldierDTO | null>(null);
  const canManageExemptions = user?.role === "admin" || user?.role === "commander" || user?.role === "duty_manager";
  const isAdmin = user?.role === "admin";

  async function refresh() {
    setNodes(await fetchTree());
    const all = await listSoldiers();
    setSoldiers(all);
  }
  useEffect(() => { void refresh(); }, []);

  // ... onboard and department creation stay the same ...

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6" data-testid="team-page">
        <h2 className="text-xl font-semibold">{t("team.title")}</h2>

        <div className="flex items-center gap-3">
          <h3 className="font-medium">{t("team.title")}</h3>
          {isAdmin && (
            <button onClick={addDepartment} className="text-sm text-indigo-600" data-testid="add-department">
              {t("team.add_node")}
            </button>
          )}
        </div>
        <HierarchyTree nodes={nodes} soldiers={soldiers} isAdmin={isAdmin} onChanged={refresh} />

        {isAdmin && (
          <form onSubmit={addSoldier} className="flex flex-wrap items-end gap-2" data-testid="onboard-form">
            <label className="block">
              <span className="text-xs">{t("team.personal_number")}</span>
              <input className="block border rounded p-1" value={pn} onChange={(e) => setPn(e.target.value)} required data-testid="onboard-pn" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.full_name")}</span>
              <input className="block border rounded p-1" value={name} onChange={(e) => setName(e.target.value)} required data-testid="onboard-name" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.title")}</span>
              <select className="block border rounded p-1" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="onboard-node">
                <option value="">—</option>
                {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
              </select>
            </label>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="onboard-submit">
              {t("team.add_soldier")}
            </button>
          </form>
        )}

        {tempPw && <div className="text-sm text-green-600" data-testid="temp-password">{t("team.temp_password_is", { pw: tempPw })}</div>}

        <table className="w-full text-sm" data-testid="soldier-table">
          <thead>
            <tr className="text-right text-gray-500">
              <th className="py-1">{t("team.personal_number")}</th>
              <th>{t("team.full_name")}</th>
              <th>{t("team.role")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {soldiers.map((s) => (
              <tr key={s.id} className="border-t" data-testid={`soldier-row-${s.personal_number}`}>
                <td className="py-1">{s.personal_number}</td>
                <td>{s.full_name}</td>
                <td>{s.role}</td>
                <td className="space-x-2 space-x-reverse">
                  <button onClick={() => onReset(s.id)} className="text-indigo-600" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
                  <button onClick={() => onRemove(s.id)} className="text-red-600" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
                  <button onClick={() => setSelected(s)} className="text-indigo-600" data-testid={`exemptions-${s.personal_number}`}>{t("exemptions.title")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {selected && canManageExemptions && (
          <div className="border-t pt-4" data-testid="manage-exemptions">
            <div className="text-sm text-gray-500">{selected.full_name} ({selected.personal_number})</div>
            <ExemptionsPanel soldierId={selected.id} canManage={true} />
          </div>
        )}
      </section>
    </Layout>
  );
}
```

Key changes:
- Pass `soldiers` prop to `HierarchyTree`
- Wrap the onboard form in `{isAdmin && ...}` to hide from non-admins
- The soldier table is kept for admin operations (reset password, remove, exemptions)

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/TeamHierarchyPage.tsx
git commit -m "feat(ui): pass soldiers to HierarchyTree, gate onboard form by admin"
```

---

### Task 15: Update E2E tests for new behavior

**Files:**
- Modify: `frontend/tests/e2e/hierarchy.spec.ts`

- [ ] **Step 1: Update the existing hierarchy spec**

The existing test checks for button label `t("exemptions.title")` which is now changed to `t("team.assign_commander")`. Update the tree-commander-btn test-id to verify the dialog still opens, and add tests for the new soldier quick-add and edit features.

```typescript
import { test, expect, type Page } from "@playwright/test";

async function loginAsAdmin(page: Page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test.describe("Hierarchy tree", () => {
  test("admin sees tree, adds child node, assigns commander, renames node", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    await expect(page.getByTestId("node-tree")).toBeVisible();

    const firstAddChild = page.getByTestId(/^tree-add-child-/).first();
    await firstAddChild.click();
    await expect(page.getByTestId("add-child-dialog")).toBeVisible();
    await page.getByTestId("child-name").fill(`תת-יחידת בדיקה ${Date.now() % 10000}`);
    await page.getByTestId("child-submit").click();
    await expect(page.getByTestId("add-child-dialog")).not.toBeVisible();

    const firstRename = page.getByTestId(/^tree-rename-/).first();
    await firstRename.click();
    await expect(page.getByTestId("rename-dialog")).toBeVisible();
    await page.getByTestId("rename-input").fill(`שם חדש ${Date.now() % 10000}`);
    await page.getByTestId("rename-submit").click();
    await expect(page.getByTestId("rename-dialog")).not.toBeVisible();

    const firstCommanderBtn = page.getByTestId(/^tree-commander-btn-/).first();
    await firstCommanderBtn.click();
    await expect(page.getByTestId("assign-commander-dialog")).toBeVisible();
    await page.getByTestId("commander-select").selectOption({ index: 1 });
    await page.getByTestId("commander-submit").click();
    await expect(page.getByTestId("assign-commander-dialog")).not.toBeVisible();
  });

  test("admin can add soldier to node via quick-add button", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);
    await expect(page.getByTestId("node-tree")).toBeVisible();

    const firstAddSoldier = page.getByTestId(/^tree-add-soldier-/).first();
    await firstAddSoldier.click();
    await expect(page.getByTestId(/^quick-add-/)).toBeVisible();
  });

  test("soldiers appear under tree node with edit button", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByTestId("nav-team").click();
    await expect(page).toHaveURL(/\/team$/);

    // Wait for tree to load and expand first node
    await expect(page.getByTestId("node-tree")).toBeVisible();
    const firstToggle = page.getByTestId(/^tree-toggle-/).first();
    await firstToggle.click();

    // Check soldier rows appear under the node if any exist
    const soldierRows = page.getByTestId(/^tree-soldier-/);
    const count = await soldierRows.count();
    if (count > 0) {
      // Verify edit button exists on soldier row
      const firstEdit = page.getByTestId(/^edit-soldier-/).first();
      await expect(firstEdit).toBeVisible();
      await firstEdit.click();
      await expect(page.getByTestId("soldier-edit-modal")).toBeVisible();
    }
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/tests/e2e/hierarchy.spec.ts
git commit -m "test(e2e): update hierarchy spec for fixups"
```

---

### Task 16: Verify everything compiles and tests pass

- [ ] **Step 1: Run backend tests**

```bash
cd backend; pytest tests/ -v
```

Expected: All backend tests pass.

- [ ] **Step 2: Run frontend TypeScript check**

```bash
cd frontend; npx tsc --noEmit
```

Expected: No type errors.

- [ ] **Step 3: Run frontend lint**

```bash
cd frontend; npx eslint src/
```

Expected: No lint errors.

- [ ] **Step 4: Final commit if any fixes needed**

- [ ] **Step 5: Commit the plan document**

```bash
git add docs/superpowers/plans/2026-05-30-hierarchy-fixups.md
git commit -m "docs: hierarchy fixups implementation plan"
```
