# Telegram Linked Indicator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface a `telegram_linked` boolean on every soldier API response, and display a Telegram logo + checkbox indicator in the soldiers table and hierarchy tree.

**Architecture:** Add `telegram_linked: bool` to `SoldierOut` / `SoldierDTO`. The backend queries `telegram_links` in bulk (one extra query per list call, not N+1) and passes the flag into the existing `_out()` helper. The frontend renders a shared `TelegramBadge` component in both `TeamHierarchyPage` (table column) and `HierarchyTree` (tree row).

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript/Tailwind (frontend), pytest (tests).

---

### Task 1: Add `telegram_linked` to `SoldierOut` and `_out()`

**Files:**
- Modify: `backend/app/routes/soldiers.py`

- [ ] **Step 1: Add the field to `SoldierOut`**

In `backend/app/routes/soldiers.py`, add one line to the `SoldierOut` class after `last_alal_date`:

```python
class SoldierOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    phone: str | None
    must_change_password: bool
    left_at: str | None
    # Profile fields
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: date_type | None = None
    mandatory_end_date: date_type | None = None
    discharge_date: date_type | None = None
    last_mitvahim_date: date_type | None = None
    last_alal_date: date_type | None = None
    telegram_linked: bool = False
```

- [ ] **Step 2: Add `TelegramLink` import**

At the top of `backend/app/routes/soldiers.py`, update the models import line:

```python
from app.db.models import HierarchyNode, Soldier, SoldierFieldUpdate, TelegramLink
```

- [ ] **Step 3: Update `_out()` to accept and pass the flag**

Replace the existing `_out()` function:

```python
def _out(s: Soldier, *, include_gender: bool = False, telegram_linked: bool = False) -> SoldierOut:
    return SoldierOut(
        id=s.id,
        personal_number=s.personal_number,
        full_name=s.full_name,
        role=s.role,
        hierarchy_node_id=s.hierarchy_node_id,
        phone=s.phone,
        must_change_password=s.must_change_password,
        left_at=s.left_at.isoformat() if s.left_at else None,
        gender=s.gender if include_gender else None,
        is_officer=s.is_officer,
        rank=s.rank,
        bahad1_graduate=s.bahad1_graduate,
        enlistment_date=s.enlistment_date,
        mandatory_end_date=s.mandatory_end_date,
        discharge_date=s.discharge_date,
        last_mitvahim_date=s.last_mitvahim_date,
        last_alal_date=s.last_alal_date,
        telegram_linked=telegram_linked,
    )
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/soldiers.py
git commit -m "feat: add telegram_linked field to SoldierOut"
```

---

### Task 2: Populate `telegram_linked` in list and single-soldier endpoints

**Files:**
- Modify: `backend/app/routes/soldiers.py`

- [ ] **Step 1: Update `list_soldiers` to bulk-fetch linked IDs**

Replace the existing `list_soldiers` function body:

```python
@router.get("", response_model=list[SoldierOut])
def list_soldiers(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[SoldierOut]:
    linked_ids: set[uuid.UUID] = {
        row for (row,) in session.execute(
            select(TelegramLink.soldier_id).where(TelegramLink.is_verified == True)
        ).all()
    }
    if user.role == "admin":
        rows = session.execute(select(Soldier)).scalars().all()
        return [_out(s, telegram_linked=s.id in linked_ids) for s in rows]
    roots = scope_root_ids(session, user)
    if not roots:
        return [_out(user, telegram_linked=user.id in linked_ids)]
    rows = session.execute(select(Soldier)).scalars().all()
    out: list[SoldierOut] = []
    for s in rows:
        node = _node_of(session, s)
        if node is not None and any(r in node.path_ids for r in roots):
            out.append(_out(s, telegram_linked=s.id in linked_ids))
    return out
```

- [ ] **Step 2: Update single-soldier `GET /{soldier_id}` to include the flag**

Find the `get_soldier` endpoint (around line 357). Replace its body:

```python
@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SoldierOut:
    s = session.get(Soldier, soldier_id)
    if s is None or s.left_at is not None:
        raise HTTPException(status_code=404, detail="not_found")
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == soldier_id,
            TelegramLink.is_verified == True,
        )
    ).scalar_one_or_none()
    return _out(s, include_gender=True, telegram_linked=link is not None)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/soldiers.py
git commit -m "feat: populate telegram_linked in list and get soldier endpoints"
```

---

### Task 3: Backend integration test for `telegram_linked`

**Files:**
- Modify: `backend/tests/integration/test_soldiers_api.py`
- (uses existing helpers: `create_soldier`, `auth_headers` from `tests/helpers.py`)

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `backend/tests/integration/test_soldiers_api.py`:

```python
from app.db.models import TelegramLink


def test_list_soldiers_telegram_linked_false_by_default(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000001", role="admin")
    s = create_soldier(admin_session, personal_number="5100001")
    admin_session.commit()
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 200
    found = next(x for x in r.json() if x["personal_number"] == "5100001")
    assert found["telegram_linked"] is False


def test_list_soldiers_telegram_linked_true_when_verified(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000002", role="admin")
    s = create_soldier(admin_session, personal_number="5100002")
    admin_session.commit()
    link = TelegramLink(
        soldier_id=s.id,
        is_verified=True,
        telegram_chat_id=999,
        telegram_username="testuser",
    )
    admin_session.add(link)
    admin_session.commit()
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 200
    found = next(x for x in r.json() if x["personal_number"] == "5100002")
    assert found["telegram_linked"] is True


def test_get_soldier_telegram_linked(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000003", role="admin")
    s = create_soldier(admin_session, personal_number="5100003")
    admin_session.commit()
    r = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(admin))
    assert r.json()["telegram_linked"] is False
    link = TelegramLink(soldier_id=s.id, is_verified=True, telegram_chat_id=111, telegram_username="u")
    admin_session.add(link)
    admin_session.commit()
    r2 = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(admin))
    assert r2.json()["telegram_linked"] is True
```

- [ ] **Step 2: Run tests — expect failures**

```bash
cd backend
.venv/Scripts/pytest tests/integration/test_soldiers_api.py::test_list_soldiers_telegram_linked_false_by_default tests/integration/test_soldiers_api.py::test_list_soldiers_telegram_linked_true_when_verified tests/integration/test_soldiers_api.py::test_get_soldier_telegram_linked -v
```

Expected: FAIL (field missing from response before Task 1/2 committed, or PASS if running after Task 2).

- [ ] **Step 3: Run tests — expect pass (after Task 1 & 2)**

```bash
cd backend
.venv/Scripts/pytest tests/integration/test_soldiers_api.py::test_list_soldiers_telegram_linked_false_by_default tests/integration/test_soldiers_api.py::test_list_soldiers_telegram_linked_true_when_verified tests/integration/test_soldiers_api.py::test_get_soldier_telegram_linked -v
```

Expected: all 3 PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_soldiers_api.py
git commit -m "test: telegram_linked field on soldier list and get endpoints"
```

---

### Task 4: Add `telegram_linked` to frontend `SoldierDTO`

**Files:**
- Modify: `frontend/src/api/soldiers.ts`

- [ ] **Step 1: Add the field**

In `frontend/src/api/soldiers.ts`, add `telegram_linked` to `SoldierDTO`:

```typescript
export interface SoldierDTO {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  phone: string | null;
  must_change_password: boolean;
  left_at: string | null;
  gender: string | null;
  is_officer: boolean | null;
  rank: string | null;
  bahad1_graduate: boolean;
  enlistment_date: string | null;
  mandatory_end_date: string | null;
  discharge_date: string | null;
  last_mitvahim_date: string | null;
  last_alal_date: string | null;
  telegram_linked: boolean;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/soldiers.ts
git commit -m "feat: add telegram_linked to SoldierDTO"
```

---

### Task 5: Create `TelegramBadge` component

**Files:**
- Create: `frontend/src/components/TelegramBadge.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/TelegramBadge.tsx`:

```tsx
interface Props {
  linked: boolean;
}

export default function TelegramBadge({ linked }: Props) {
  return (
    <span
      className="inline-flex items-center gap-0.5"
      title={linked ? "Telegram מקושר" : "Telegram לא מקושר"}
    >
      {/* Telegram paper-plane logo */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        className="w-3.5 h-3.5 flex-shrink-0"
        fill={linked ? "#229ED9" : "#9CA3AF"}
        aria-hidden="true"
      >
        <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12L8.32 13.617l-2.96-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.828.942z" />
      </svg>
      <input
        type="checkbox"
        checked={linked}
        readOnly
        className="w-3 h-3 cursor-default accent-[#229ED9]"
        tabIndex={-1}
        aria-label={linked ? "Telegram מקושר" : "Telegram לא מקושר"}
      />
    </span>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/TelegramBadge.tsx
git commit -m "feat: add TelegramBadge component"
```

---

### Task 6: Add Telegram column to the soldiers table

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`

- [ ] **Step 1: Import `TelegramBadge`**

At the top of `frontend/src/pages/TeamHierarchyPage.tsx`, add the import:

```tsx
import TelegramBadge from "../components/TelegramBadge";
```

- [ ] **Step 2: Add the column**

In the `soldierCols` array in `TeamHierarchyPage.tsx`, insert this column after the `role` column and before the `node` column:

```tsx
{
  id: "telegram",
  header: t("team.telegram"),
  cell: (s) => <TelegramBadge linked={s.telegram_linked} />,
  sortValue: (s) => (s.telegram_linked ? 0 : 1),
},
```

- [ ] **Step 3: Add the i18n key**

In `frontend/src/i18n/he.json`, inside the `"team"` object, add:

```json
"telegram": "טלגרם"
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TeamHierarchyPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add telegram linked column to soldiers table"
```

---

### Task 7: Add Telegram badge to the hierarchy tree

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`

- [ ] **Step 1: Import `TelegramBadge`**

At the top of `frontend/src/components/HierarchyTree.tsx`, add:

```tsx
import TelegramBadge from "./TelegramBadge";
```

- [ ] **Step 2: Add badge next to each soldier in the tree**

Find the `<li>` that renders each soldier in the tree (around line 169). It currently looks like:

```tsx
<li key={s.id} className="flex items-center gap-2 py-0.5 px-2 text-sm text-gray-600" data-testid={`tree-soldier-${s.personal_number}`}>
  <span className="w-1 h-1 bg-gray-300 rounded-full inline-block" />
  <SoldierLink id={s.id} name={s.full_name} />
  <span className="text-xs text-gray-400">({s.personal_number})</span>
  {isAdmin && (
    <button ...>{t("team.edit")}</button>
  )}
</li>
```

Replace it with:

```tsx
<li key={s.id} className="flex items-center gap-2 py-0.5 px-2 text-sm text-gray-600" data-testid={`tree-soldier-${s.personal_number}`}>
  <span className="w-1 h-1 bg-gray-300 rounded-full inline-block" />
  <SoldierLink id={s.id} name={s.full_name} />
  <span className="text-xs text-gray-400">({s.personal_number})</span>
  <TelegramBadge linked={s.telegram_linked} />
  {isAdmin && (
    <button
      className="text-xs text-indigo-600 hover:underline ml-auto"
      onClick={() => setEditSoldier(s)}
      data-testid={`edit-soldier-${s.personal_number}`}
    >
      {t("team.edit")}
    </button>
  )}
</li>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HierarchyTree.tsx
git commit -m "feat: add telegram badge to hierarchy tree soldier rows"
```

---

### Task 8: Push to master

- [ ] **Step 1: Run all backend tests to confirm nothing is broken**

```bash
cd backend
.venv/Scripts/pytest tests/integration/test_soldiers_api.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Push**

```bash
git push origin master
```
