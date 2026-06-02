# Soldier Clickable Names & Role-Based Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every soldier name in the frontend becomes a clickable link that opens a role-aware `UnifiedSoldierModal` via a global React context.

**Architecture:** A `SoldierModalContext` wraps the app inside `AuthProvider`; it holds one modal instance that fetches the soldier + score + nodes on open. `UnifiedSoldierModal` drops its `user` prop (reads from `useAuth()` internally) and gains a `score` prop; it renders tabs conditionally based on viewer role. A `SoldierLink` component replaces every plain-text soldier name across the codebase.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React 18 + TypeScript + Tailwind + react-i18next (frontend).

**Depends on:** The duty-history plan (`2026-06-01-soldier-duty-history-timeline.md`) must be implemented first — Task 3 of this plan modifies that route.

**Feature branch:** `feature/soldier-clickable-names` (create from `feature/soldier-duty-history` or master after duty-history lands)

---

## File map

| File | Change |
|---|---|
| `backend/app/routes/soldiers.py` | Relax GET `/{id}` auth; add GET `/{id}/score`; add viewer-role filter to GET `/{id}/duty-history` |
| `frontend/src/api/soldiers.ts` | Add `getSoldier(id)`, `getSoldierScore(id)`, `SoldierScoreDTO` |
| `frontend/src/contexts/SoldierModalContext.tsx` | **New** — context + provider + singleton modal |
| `frontend/src/components/SoldierLink.tsx` | **New** — clickable name button |
| `frontend/src/components/UnifiedSoldierModal.tsx` | Drop `user` prop; add `score` prop; role-based tab visibility |
| `frontend/src/App.tsx` | Wrap routes with `SoldierModalProvider` |
| `frontend/src/i18n/he.json` | Add `common.no_permission` key |
| `frontend/src/pages/TeamHierarchyPage.tsx` | Use `openSoldierModal`; remove `editSoldier` state |
| `frontend/src/components/HierarchyTree.tsx` | `SoldierLink` for soldier names |
| `frontend/src/pages/TransparencyPage.tsx` | `SoldierLink` for name column |
| `frontend/src/components/EntriesExitsPanel.tsx` | `SoldierLink` for soldier names |
| `frontend/src/components/ShiftDetailPanel.tsx` | `SoldierLink` for assignee names |
| `frontend/src/components/UpcomingSnapshot.tsx` | `SoldierLink` for badge names |
| `frontend/src/components/ApprovalsFeed.tsx` | `SoldierLink` for item names |
| `frontend/src/components/AlgorithmPlanningWindow.tsx` | `SoldierLink` in proposal table cells |
| `frontend/src/pages/ApprovalsPage.tsx` | `SoldierLink` via `soldierDisplay()` |

---

### Task 0: Create feature branch

- [ ] **Step 1: Create and checkout the branch**

```bash
git checkout -b feature/soldier-clickable-names
```

Expected: `Switched to a new branch 'feature/soldier-clickable-names'`

---

### Task 1: Backend — relax GET /soldiers/{id} for plain soldiers

**Files:**
- Modify: `backend/app/routes/soldiers.py`

**Context:** The route at line ~278 currently calls `authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))` for non-self reads. Plain soldiers should be allowed to read any soldier's public info (the `SoldierOut` schema already includes phone, rank, unit).

- [ ] **Step 1: Update the GET /{soldier_id} route**

Find this block in `backend/app/routes/soldiers.py`:

```python
@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    if str(s.id) != str(user.id):
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
```

Replace the body with:

```python
@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    if str(s.id) != str(user.id) and user.role not in ("soldier",):
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
```

Plain soldiers skip the `authorize` call; admin/DM/commander still go through it (and will 403 if out of scope).

- [ ] **Step 2: Verify backend starts**

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

Expected: server starts without errors. Stop with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/soldiers.py
git commit -m "feat: allow plain soldiers to read any soldier profile"
```

---

### Task 2: Backend — new GET /soldiers/{id}/score endpoint

**Files:**
- Modify: `backend/app/routes/soldiers.py`

**Context:** The scoring service already has `cumulative_score(session, soldier_id=id)`, `active_days(session, soldier=s)`, `normalised_score(session, soldier=s)` in `backend/app/services/scoring.py`. These are imported in `backend/app/routes/scoring.py`; we just need to use them in the soldiers router too. The `Decimal` type must be serialized as a string.

- [ ] **Step 1: Add imports and schema to soldiers.py**

At the top of `backend/app/routes/soldiers.py`, add to existing imports:

```python
from decimal import Decimal
from app.services import scoring as scoring_svc
```

Add this Pydantic model after the existing schema classes (e.g., after `TimelineEventOut`):

```python
class SoldierScoreOut(BaseModel):
    soldier_id: uuid.UUID
    active_days: int
    cumulative_score: Decimal
    normalised_score: Decimal
```

- [ ] **Step 2: Add the route at the end of soldiers.py (before duty-history route)**

```python
@router.get("/{soldier_id}/score", response_model=SoldierScoreOut)
def get_soldier_score(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    ad = scoring_svc.active_days(session, soldier=s)
    cum = scoring_svc.cumulative_score(session, soldier_id=s.id)
    return SoldierScoreOut(
        soldier_id=s.id,
        active_days=ad,
        cumulative_score=cum,
        normalised_score=cum / Decimal(ad),
    )
```

**IMPORTANT:** This route must be declared BEFORE `/{soldier_id}/duty-history` in the file. FastAPI matches routes in order — if `/{soldier_id}` is declared first, `/score` would be matched as a UUID and fail. Since `soldiers.py` already has this ordering rule (see comment about `/ranks` and `/field-updates/pending`), add `/score` in the same protected block above `/{soldier_id}` catch-all routes.

- [ ] **Step 3: Verify with curl (server must be running)**

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

In another terminal (replace UUID with an actual soldier id from seed):
```bash
curl -s -H "Authorization: Bearer <token>" http://localhost:8000/soldiers/<uuid>/score
```
Expected: JSON with `soldier_id`, `active_days`, `cumulative_score`, `normalised_score`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/soldiers.py
git commit -m "feat: GET /soldiers/{id}/score endpoint"
```

---

### Task 3: Backend — filter duty-history events for plain-soldier viewers

**Files:**
- Modify: `backend/app/routes/soldiers.py`

**Context:** This task modifies the `get_soldier_duty_history` route added by the duty-history plan. A plain soldier viewing *another* soldier should only receive `assignment` and `cancellation` events — not `personal_constraint`, `exemption_request`, `dismissal`, or `call_up`.

- [ ] **Step 1: Update get_soldier_duty_history in soldiers.py**

Find the route:

```python
@router.get("/{soldier_id}/duty-history", response_model=list[TimelineEventOut])
def get_soldier_duty_history(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    if str(s.id) != str(user.id):
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    events = get_duty_history(session, soldier_id)
    return [
        TimelineEventOut(...)
        for e in events
    ]
```

Replace with:

```python
_PUBLIC_EVENT_TYPES = {"assignment", "cancellation"}

@router.get("/{soldier_id}/duty-history", response_model=list[TimelineEventOut])
def get_soldier_duty_history(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
):
    s = _load(session, soldier_id)
    is_self = str(s.id) == str(user.id)
    is_plain_soldier = user.role == "soldier"

    if not is_self and not is_plain_soldier:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))

    events = get_duty_history(session, soldier_id)

    if is_plain_soldier and not is_self:
        events = [e for e in events if e.event_type in _PUBLIC_EVENT_TYPES]

    return [
        TimelineEventOut(
            id=e.id,
            event_type=e.event_type,
            date=e.date,
            end_date=e.end_date,
            title=e.title,
            description=e.description,
            status=e.status,
            metadata=e.metadata,
        )
        for e in events
    ]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/routes/soldiers.py
git commit -m "feat: filter duty-history to public events for plain-soldier viewers"
```

---

### Task 4: Frontend API — getSoldier and getSoldierScore

**Files:**
- Modify: `frontend/src/api/soldiers.ts`

- [ ] **Step 1: Add SoldierScoreDTO interface and two fetch functions**

Add after the existing `SoldierDTO` interface:

```typescript
export interface SoldierScoreDTO {
  soldier_id: string;
  active_days: number;
  cumulative_score: string;
  normalised_score: string;
}
```

Add after the existing functions (e.g., after `getRanks`):

```typescript
export async function getSoldier(id: string): Promise<SoldierDTO> {
  return (await api.get<SoldierDTO>(`/soldiers/${id}`)).data;
}

export async function getSoldierScore(id: string): Promise<SoldierScoreDTO> {
  return (await api.get<SoldierScoreDTO>(`/soldiers/${id}/score`)).data;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/soldiers.ts
git commit -m "feat: getSoldier and getSoldierScore API functions"
```

---

### Task 5: Frontend — SoldierModalContext

**Files:**
- Create: `frontend/src/contexts/SoldierModalContext.tsx`

**Context:** The provider fetches the soldier, score, and hierarchy nodes when `openSoldierModal(id)` is called. It renders a single `UnifiedSoldierModal`. The `getHierarchyTree` function comes from `frontend/src/api/hierarchy.ts` and returns `NodeDTO[]`. The `openSoldierModal` accepts an optional `onRefresh` callback (called after the modal closes following an edit).

- [ ] **Step 1: Create the context file**

```tsx
// frontend/src/contexts/SoldierModalContext.tsx
import {
  createContext,
  useCallback,
  useContext,
  useState,
  ReactNode,
} from "react";
import { SoldierDTO, SoldierScoreDTO, getSoldier, getSoldierScore } from "../api/soldiers";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import UnifiedSoldierModal from "../components/UnifiedSoldierModal";

interface SoldierModalContextValue {
  openSoldierModal: (soldierId: string, onRefresh?: () => void) => void;
}

const SoldierModalContext = createContext<SoldierModalContextValue | null>(null);

export function useSoldierModal(): SoldierModalContextValue {
  const ctx = useContext(SoldierModalContext);
  if (!ctx) throw new Error("useSoldierModal used outside SoldierModalProvider");
  return ctx;
}

interface ModalState {
  soldier: SoldierDTO;
  score: SoldierScoreDTO | null;
  nodes: NodeDTO[];
  onRefresh?: () => void;
}

export function SoldierModalProvider({ children }: { children: ReactNode }) {
  const [modal, setModal] = useState<ModalState | null>(null);

  const openSoldierModal = useCallback(
    async (soldierId: string, onRefresh?: () => void) => {
      const [soldier, score, nodes] = await Promise.allSettled([
        getSoldier(soldierId),
        getSoldierScore(soldierId),
        fetchTree(),
      ]);

      if (soldier.status === "rejected") return; // 403 or 404 — silently ignore

      setModal({
        soldier: (soldier as PromiseFulfilledResult<SoldierDTO>).value,
        score:
          score.status === "fulfilled"
            ? (score as PromiseFulfilledResult<SoldierScoreDTO>).value
            : null,
        nodes:
          nodes.status === "fulfilled"
            ? (nodes as PromiseFulfilledResult<NodeDTO[]>).value
            : [],
        onRefresh,
      });
    },
    []
  );

  function handleClose() {
    setModal(null);
  }

  async function handleRefresh() {
    if (!modal) return;
    modal.onRefresh?.();
    // Re-fetch soldier data so edits are reflected if modal stays open
    const updated = await getSoldier(modal.soldier.id).catch(() => null);
    if (updated) setModal((prev) => prev && { ...prev, soldier: updated });
  }

  return (
    <SoldierModalContext.Provider value={{ openSoldierModal }}>
      {children}
      {modal && (
        <UnifiedSoldierModal
          soldier={modal.soldier}
          score={modal.score}
          nodes={modal.nodes}
          onClose={handleClose}
          onRefresh={handleRefresh}
        />
      )}
    </SoldierModalContext.Provider>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/contexts/SoldierModalContext.tsx
git commit -m "feat: SoldierModalContext and SoldierModalProvider"
```

---

### Task 6: Frontend — SoldierLink component

**Files:**
- Create: `frontend/src/components/SoldierLink.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/SoldierLink.tsx
import { useSoldierModal } from "../contexts/SoldierModalContext";

interface Props {
  id: string;
  name: string;
  className?: string;
}

export default function SoldierLink({ id, name, className }: Props) {
  const { openSoldierModal } = useSoldierModal();
  return (
    <button
      type="button"
      className={`text-indigo-600 hover:underline ${className ?? ""}`}
      onClick={(e) => {
        e.stopPropagation();
        void openSoldierModal(id);
      }}
    >
      {name}
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/SoldierLink.tsx
git commit -m "feat: SoldierLink component"
```

---

### Task 7: Frontend — update UnifiedSoldierModal for role-based visibility

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`

**Context:** The current modal receives `user` as a prop and uses `user?.role`. After this task, the modal reads the viewer from `useAuth()` internally. It also receives a new optional `score` prop used in the "limited details" view for plain soldiers. The `nodes` prop stays (needed for the unit edit dropdown).

The visibility rules:
- `canViewAll` (admin, duty_manager, commander): all 5 tabs; commander can approve/reject but not edit profile
- `isSelf` (soldier viewing self): "details" + "duty_history" tabs
- limited (soldier viewing other): "details" (read-only, shows score) + "duty_history" (filtered server-side)

- [ ] **Step 1: Update the Props interface and remove user prop**

Replace the existing `Props` interface:

```typescript
interface Props {
  soldier: SoldierDTO;
  score: SoldierScoreDTO | null;
  nodes: NodeDTO[];
  onClose: () => void;
  onRefresh: () => void;
}
```

Add the import for `useAuth`, `SoldierScoreDTO`:

```typescript
import { useAuth } from "../auth/AuthContext";
import { SoldierDTO, SoldierScoreDTO } from "../api/soldiers";
```

- [ ] **Step 2: Replace role-detection logic inside the component**

In the component body, replace the existing `const isAdmin = ...` block with:

```typescript
const { user } = useAuth();
const isSelf = user?.id === soldier.id;
const isAdmin = user?.role === "admin";
const isDutyManager = user?.role === "duty_manager";
const isCommander = user?.role === "commander";
const canManage = isAdmin || isDutyManager;
const canViewAll = isAdmin || isDutyManager || isCommander;
const isLimitedView = !canViewAll && !isSelf;
```

- [ ] **Step 3: Update the TABS constant**

Replace:

```typescript
const TABS = ["details", "profile", "exemptions", "constraints"] as const;
```

With:

```typescript
const ALL_TABS = ["details", "profile", "exemptions", "constraints", "duty_history"] as const;
type TabKey = (typeof ALL_TABS)[number];

const TABS: TabKey[] = canViewAll
  ? ["details", "profile", "exemptions", "constraints", "duty_history"]
  : ["details", "duty_history"];
```

Update `const [tab, setTab] = useState` to use `TabKey`:

```typescript
const [tab, setTab] = useState<TabKey>("details");
```

- [ ] **Step 4: Update the tab panel rendering**

After the existing `{tab === "constraints" && (...)}` block, add:

```tsx
{tab === "duty_history" && (
  <DutyHistoryPanel
    soldierId={soldier.id}
    canManage={canManage}
    isActive={tab === "duty_history"}
  />
)}
```

Import `DutyHistoryPanel` at the top:

```typescript
import DutyHistoryPanel from "./DutyHistoryPanel";
```

- [ ] **Step 5: Add limited-view details rendering**

The "details" tab currently shows an edit form. Wrap it so that when `isLimitedView` is true, it shows a read-only card with score instead:

Inside the `{tab === "details" && (...)}` block, replace the entire form with:

```tsx
{tab === "details" && (
  isLimitedView ? (
    <div className="space-y-3 text-sm">
      <div className="flex justify-between">
        <span className="text-gray-500">{t("team.full_name")}</span>
        <span className="font-medium">{soldier.full_name}</span>
      </div>
      {soldier.rank && (
        <div className="flex justify-between">
          <span className="text-gray-500">{t("soldier_profile.rank")}</span>
          <span>{soldier.rank}</span>
        </div>
      )}
      <div className="flex justify-between">
        <span className="text-gray-500">{t("team.node")}</span>
        <span>{nodes.find((n) => n.id === soldier.hierarchy_node_id)?.name ?? "—"}</span>
      </div>
      {soldier.phone && (
        <div className="flex justify-between">
          <span className="text-gray-500">{t("team.phone")}</span>
          <span dir="ltr">{soldier.phone}</span>
        </div>
      )}
      {score && (
        <div className="border-t pt-3 space-y-1">
          <div className="flex justify-between">
            <span className="text-gray-500">{t("transparency.active_days")}</span>
            <span>{score.active_days}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">{t("transparency.normalised")}</span>
            <span>{Number(score.normalised_score).toFixed(2)}</span>
          </div>
        </div>
      )}
    </div>
  ) : (
    /* existing edit form here — unchanged */
    <form onSubmit={handleSave} className="space-y-3">
      {/* ... entire existing form JSX unchanged ... */}
    </form>
  )
)}
```

**Note:** Keep the entire existing edit form JSX in the `else` branch — do not delete it.

- [ ] **Step 6: Hide profile tab content for commanders (read-only)**

In `{tab === "profile" && (...)}`, wrap the save button so commanders cannot edit:

```tsx
{!isCommander && (
  <div className="flex justify-end gap-2">
    <button type="button" ...>{t("team.cancel")}</button>
    <button type="submit" ...>{t("team.edit")}</button>
  </div>
)}
```

- [ ] **Step 7: Build to check TypeScript**

```bash
cd frontend && pnpm build 2>&1 | tail -30
```

Expected: zero TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "feat: role-based tab visibility in UnifiedSoldierModal"
```

---

### Task 8: Frontend — add i18n key and wrap App with provider

**Files:**
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add i18n key**

In `frontend/src/i18n/he.json`, add inside the `"common"` object:

```json
"no_permission": "אין הרשאה להציג מידע זה"
```

- [ ] **Step 2: Wrap App with SoldierModalProvider**

In `frontend/src/App.tsx`, add the import:

```typescript
import { SoldierModalProvider } from "./contexts/SoldierModalContext";
```

Wrap the `<Routes>` block with `<SoldierModalProvider>`. The provider must be inside `<AuthProvider>` (since it uses `useAuth` inside `UnifiedSoldierModal`):

```tsx
export default function App() {
  return (
    <AuthProvider>
      <SoldierModalProvider>
        <Routes>
          {/* ... all existing routes unchanged ... */}
        </Routes>
      </SoldierModalProvider>
    </AuthProvider>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/he.json frontend/src/App.tsx
git commit -m "feat: wrap app with SoldierModalProvider"
```

---

### Task 9: Frontend — update TeamHierarchyPage to use context

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`

**Context:** `TeamHierarchyPage` currently maintains `editSoldier` state and renders `<UnifiedSoldierModal>` directly. Replace with `openSoldierModal` from context; the soldier table "edit" button still exists for admins (opens modal), but the `<UnifiedSoldierModal>` block and `editSoldier` state are removed.

- [ ] **Step 1: Replace editSoldier state with context**

Remove:

```typescript
const [editSoldier, setEditSoldier] = useState<SoldierDTO | null>(null);
```

Add:

```typescript
import { useSoldierModal } from "../contexts/SoldierModalContext";
// inside component:
const { openSoldierModal } = useSoldierModal();
```

- [ ] **Step 2: Replace setEditSoldier calls with openSoldierModal**

In the DataTable soldier columns, the "edit" button currently calls `setEditSoldier(s)`. Replace with:

```tsx
<button
  onClick={() => openSoldierModal(s.id, refresh)}
  className="text-indigo-600"
  data-testid={`edit-${s.personal_number}`}
>
  {t("team.edit")}
</button>
```

- [ ] **Step 3: Remove the UnifiedSoldierModal block**

Delete the entire block:

```tsx
{editSoldier && (
  <UnifiedSoldierModal
    soldier={editSoldier}
    user={user}
    nodes={nodes}
    onClose={() => setEditSoldier(null)}
    onRefresh={refresh}
  />
)}
```

Also remove the `UnifiedSoldierModal` import from this file if it is now unused.

- [ ] **Step 4: Build to check TypeScript**

```bash
cd frontend && pnpm build 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TeamHierarchyPage.tsx
git commit -m "refactor: TeamHierarchyPage uses SoldierModalContext"
```

---

### Task 10: Frontend — HierarchyTree call site

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`

**Context:** Line ~170 renders `<span>{s.full_name}</span>` inside `nodeSoldiers.map`. The `s` object is a `SoldierDTO` with `s.id`.

- [ ] **Step 1: Add SoldierLink import and replace the name span**

Add import at top:

```typescript
import SoldierLink from "./SoldierLink";
```

Replace:

```tsx
<span>{s.full_name}</span>
```

With:

```tsx
<SoldierLink id={s.id} name={s.full_name} />
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/HierarchyTree.tsx
git commit -m "feat: SoldierLink in HierarchyTree"
```

---

### Task 11: Frontend — TransparencyPage call site

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

**Context:** The name column uses a DataTable `cell` renderer. Currently:

```tsx
cell: (r) =>
  r.soldier_id === user?.id ? (
    <button className="text-indigo-600" onClick={toggleOwn} data-testid="own-row-toggle">
      {r.full_name}
    </button>
  ) : (
    r.full_name
  ),
```

The `r` object has `r.soldier_id` and `r.full_name`.

- [ ] **Step 1: Add SoldierLink import and update the cell renderer**

Add import:

```typescript
import SoldierLink from "../components/SoldierLink";
```

Replace the cell renderer:

```tsx
cell: (r) =>
  r.soldier_id === user?.id ? (
    <button className="text-indigo-600" onClick={toggleOwn} data-testid="own-row-toggle">
      {r.full_name}
    </button>
  ) : (
    <SoldierLink id={r.soldier_id} name={r.full_name} />
  ),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: SoldierLink in TransparencyPage"
```

---

### Task 12: Frontend — EntriesExitsPanel call site

**Files:**
- Modify: `frontend/src/components/EntriesExitsPanel.tsx`

**Context:** Line ~86 renders `<td className="p-1">{s.full_name}</td>` where `s` is a SoldierDTO with `s.id`.

- [ ] **Step 1: Add import and replace**

Add import:

```typescript
import SoldierLink from "./SoldierLink";
```

Replace:

```tsx
<td className="p-1">{s.full_name}</td>
```

With:

```tsx
<td className="p-1"><SoldierLink id={s.id} name={s.full_name} /></td>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/EntriesExitsPanel.tsx
git commit -m "feat: SoldierLink in EntriesExitsPanel"
```

---

### Task 13: Frontend — ShiftDetailPanel call sites

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`

**Context:** `shift.assignees` is `CalendarShiftAssignee[]`, each with `assignment_id`, `soldier_id`, `soldier_name`. The `soldierName(id)` helper looks up an assignee by `assignment_id` and returns a `string`. There are three render locations:

1. Line ~50/98/124: `{a.soldier_name}` for primary/dismissed/reserve assignees — `a.soldier_id` is directly available.
2. Line ~72: `soldierName(a.reserve_assignment_id)` — returns name from assignment_id lookup.
3. Line ~78/136: `a.primary_assignment_ids.map(id => soldierName(id)).join(", ")` — an array join.

For cases 2 and 3, build an assignment→soldier map from `shift.assignees`.

- [ ] **Step 1: Add import and build assignee map**

Add import:

```typescript
import SoldierLink from "./SoldierLink";
```

After the component opening and existing state, add:

```typescript
// Map from assignment_id to { soldierId, name } for lookups
const assigneeById = Object.fromEntries(
  shift.assignees.map((a) => [a.assignment_id, { soldierId: a.soldier_id, name: a.soldier_name }])
);
```

Replace the existing `soldierName` helper with one that returns a `ReactNode`:

```typescript
function soldierNode(id: string | null): React.ReactNode {
  if (!id) return "—";
  const a = assigneeById[id];
  if (!a) return id.slice(0, 8);
  return <SoldierLink id={a.soldierId} name={a.name} />;
}
```

- [ ] **Step 2: Replace plain name spans with SoldierLink**

For primary/dismissed/reserve assignees (lines ~50, ~98, ~124), replace:

```tsx
<span className="font-medium">{a.soldier_name}</span>
```

With:

```tsx
<SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />
```

- [ ] **Step 3: Replace soldierName() calls with soldierNode()**

For the reserve covers list (line ~72):

```tsx
{t("reserve_standby")}: {soldierNode(a.reserve_assignment_id)}
```

For the multi-soldier "reserve covers" list (line ~78 and ~136) — replace `.join(", ")` pattern with JSX:

```tsx
{t("reserve_covers")}:{" "}
{a.primary_assignment_ids.map((id, i) => (
  <span key={id}>
    {i > 0 && ", "}
    {soldierNode(id)}
  </span>
))}
```

- [ ] **Step 4: Add React import if needed**

If `React` is not already imported for `React.ReactNode`:

```typescript
import React from "react";
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx
git commit -m "feat: SoldierLink in ShiftDetailPanel"
```

---

### Task 14: Frontend — UpcomingSnapshot call site

**Files:**
- Modify: `frontend/src/components/UpcomingSnapshot.tsx`

**Context:** `UpcomingAssignment` (from `api/commanderDashboard.ts`) has `soldier_id` and `soldier_name`. The name appears in:
1. The `Badge` component (line ~25) — `{a.soldier_name}` inside a button that already calls `onSelect(a)`. Keep the button behavior, add modal trigger.
2. The detail popup (line ~59) — `{selected.soldier_name}` — make it a link.

For the `Badge`, it's already a button (clicking it opens the detail popup). We don't replace the button with SoldierLink — instead, add a SoldierLink inside the detail popup heading.

- [ ] **Step 1: Add SoldierLink import**

```typescript
import SoldierLink from "./SoldierLink";
```

- [ ] **Step 2: Update the detail popup heading**

Replace:

```tsx
<div className="font-bold text-lg mb-3">{selected.soldier_name || "?"}</div>
```

With:

```tsx
<div className="font-bold text-lg mb-3">
  {selected.soldier_id ? (
    <SoldierLink id={selected.soldier_id} name={selected.soldier_name || "?"} />
  ) : (
    selected.soldier_name || "?"
  )}
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/UpcomingSnapshot.tsx
git commit -m "feat: SoldierLink in UpcomingSnapshot detail popup"
```

---

### Task 15: Frontend — ApprovalsFeed call site

**Files:**
- Modify: `frontend/src/components/ApprovalsFeed.tsx`

**Context:** `ApprovalItem` has `soldier_id` and `soldier_name`. Line ~51 renders `{item.soldier_name}`.

- [ ] **Step 1: Add import and replace name span**

Add import:

```typescript
import SoldierLink from "./SoldierLink";
```

Replace:

```tsx
<span className="font-medium">{item.soldier_name}</span>
```

With:

```tsx
<SoldierLink id={item.soldier_id} name={item.soldier_name} className="font-medium" />
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ApprovalsFeed.tsx
git commit -m "feat: SoldierLink in ApprovalsFeed"
```

---

### Task 16: Frontend — AlgorithmPlanningWindow call site

**Files:**
- Modify: `frontend/src/components/AlgorithmPlanningWindow.tsx`

**Context:** The `soldierName(id)` helper (line ~157) takes a `soldier_id` and returns a string by looking up from `soldiers` (a `SoldierDTO[]` array in scope). It's used in DataTable `cell` renderers (lines ~358, ~365). DataTable `cell` returns `ReactNode`, so we can return `<SoldierLink>` directly.

- [ ] **Step 1: Add import and add a soldierLink helper**

Add import:

```typescript
import SoldierLink from "./SoldierLink";
```

After the existing `soldierName` function, add:

```typescript
const soldierLink = (id: string): React.ReactNode => {
  const s = soldiers.find((s) => s.id === id);
  if (!s) return id.slice(0, 8);
  return <SoldierLink id={s.id} name={s.full_name} />;
};
```

- [ ] **Step 2: Replace cell renderers**

At line ~358, replace:

```tsx
cell: (p) => soldierName(p.soldier_id),
```

With:

```tsx
cell: (p) => soldierLink(p.soldier_id),
```

At line ~365, replace:

```tsx
cell: (p) => p.reserve_soldier_id ? soldierName(p.reserve_soldier_id) : "—",
```

With:

```tsx
cell: (p) => p.reserve_soldier_id ? soldierLink(p.reserve_soldier_id) : "—",
```

Keep `soldierName` — it may still be used for `sortValue` and `filterValue` which expect strings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlgorithmPlanningWindow.tsx
git commit -m "feat: SoldierLink in AlgorithmPlanningWindow"
```

---

### Task 17: Frontend — ApprovalsPage call site

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`

**Context:** `soldierDisplay(id)` returns `{ name, node }` and is called in the exemption requests and constraints sections as `{soldierDisplay(item.soldier_id).name}`. The `item` objects have `soldier_id`.

- [ ] **Step 1: Add import**

```typescript
import SoldierLink from "../components/SoldierLink";
```

- [ ] **Step 2: Replace all soldierDisplay(...).name with SoldierLink**

Find every occurrence of the pattern `{soldierDisplay(someId).name}` in the JSX and replace with:

```tsx
<SoldierLink id={someId} name={soldierDisplay(someId).name} />
```

There are typically 3-4 occurrences across the constraints, exemptions, field-updates, and swaps sections. Apply to each one.

- [ ] **Step 3: Build to check TypeScript**

```bash
cd frontend && pnpm build 2>&1 | tail -20
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "feat: SoldierLink in ApprovalsPage"
```

---

### Task 18: Smoke test and push

- [ ] **Step 1: Start dev servers**

Terminal 1:
```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

Terminal 2:
```bash
cd frontend && pnpm dev
```

- [ ] **Step 2: Smoke test as admin**

1. Log in as admin
2. Go to Transparency page — click any soldier name → modal opens with all 5 tabs
3. Go to Team page — click "Edit" on a soldier → modal opens via context (edit works)
4. Go to Approvals page — click a soldier name in any approval item → modal opens
5. Go to Unit Calendar → open a shift → click an assignee name → modal opens

- [ ] **Step 3: Smoke test as plain soldier**

1. Log in as a plain soldier
2. Go to Transparency page → click another soldier's name → modal opens with only 2 tabs (details + duty_history)
3. Details tab shows name, rank, unit, phone, score — no edit form
4. Duty History tab shows only assignments and cancellations (no constraints or exemptions)
5. Clicking own name → details + duty_history, all events visible

- [ ] **Step 4: Push branch**

```bash
git push -u origin feature/soldier-clickable-names
```
