# Plan B — UI / Nav Bug Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five independent UI bugs: nav badge count, hierarchy tree text color, selectbox sort + color, broken clear-assignments, and inconsistent date formatting.

**Architecture:** All frontend-only except the clear-assignments investigation (which may touch the backend). Each task is completely independent. The `formatDate` utility from Plan A is a dependency for Task 5 — if Plan A is not yet complete, create the utility here first.

**Tech Stack:** React, Tailwind, FastAPI

---

### Task 1: Fix commander nav badge count

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`

**Current state:** `pendingCount = constraints + exemptions + fieldUpdates`. Enrollment requests are not included.

- [ ] **Step 1: Read current `UnifiedNav.tsx`**

Open `frontend/src/components/UnifiedNav.tsx` lines 37–47. Confirm it does NOT include `listPendingEnrollments`.

- [ ] **Step 2: Add enrollment import**

At the top of `UnifiedNav.tsx`, add:
```tsx
import { listPendingEnrollments } from "../api/enrollment";
```

- [ ] **Step 3: Update the pending count effect**

Replace the `useEffect` that sets `pendingCount` (currently at lines ~38–47):
```tsx
useEffect(() => {
  if (!canApprove) return;
  void (async () => {
    const [c, e, f, enr] = await Promise.all([
      getPendingCount().catch(() => 0),
      getPendingExemptionCount().catch(() => 0),
      getPendingFieldUpdateCount().catch(() => 0),
      listPendingEnrollments().then((list) => list.length).catch(() => 0),
    ]);
    setPendingCount(c + e + f + enr);
  })();
}, [canApprove, location.pathname]);
```

- [ ] **Step 4: Run lint and verify**

```bash
cd frontend && pnpm lint
```
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx
git commit -m "fix: commander nav badge includes enrollment requests in count"
```

---

### Task 2: Fix hierarchy tree text color

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`
- Modify: `frontend/src/components/SubHierarchySelector.tsx`
- Modify: `frontend/src/pages/TransparencyPage.tsx` (inline tree `TreeNode` component)

- [ ] **Step 1: Fix `HierarchyTree.tsx`**

Search for any `text-gray-700` class applied to node name labels that lack a dark mode counterpart. Replace with `text-gray-900 dark:text-white`. Specifically, find the unselected node button class (look for the ternary on `isSelected`) and ensure the non-selected branch uses:
```tsx
"hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-900 dark:text-white"
```
(It currently says `text-gray-700 dark:text-gray-300` — change to `text-gray-900 dark:text-white`.)

- [ ] **Step 2: Fix `SubHierarchySelector.tsx`**

Find the `<span className="text-sm">` on node name. Change to:
```tsx
<span className="text-sm text-gray-900 dark:text-white">{node.name}</span>
```

- [ ] **Step 3: Fix `TransparencyPage.tsx` inline `TreeNode`**

In `TransparencyPage.tsx`, find the `TreeNode` component's non-selected button class (same pattern). Change from `text-gray-700 dark:text-gray-300` to `text-gray-900 dark:text-white`.

- [ ] **Step 4: Verify visually**

Open Commander page and Hierarchy page. Confirm node names are clearly readable on both light and dark backgrounds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HierarchyTree.tsx frontend/src/components/SubHierarchySelector.tsx frontend/src/pages/TransparencyPage.tsx
git commit -m "fix: hierarchy tree node names use high-contrast text color"
```

---

### Task 3: Selectbox sort by hierarchy + white-on-white fix

**Files:**
- Create: `frontend/src/utils/sortNodesByTree.ts`
- Modify: any component with a `<select>` listing hierarchy nodes

- [ ] **Step 1: Create tree-sort utility**

Create `frontend/src/utils/sortNodesByTree.ts`:
```ts
import { NodeDTO } from "../api/hierarchy";

export function flattenByDfs(nodes: NodeDTO[]): NodeDTO[] {
  const result: NodeDTO[] = [];
  function visit(node: NodeDTO) {
    result.push(node);
    node.children?.forEach(visit);
  }
  nodes.forEach(visit);
  return result;
}
```

- [ ] **Step 2: Find affected selects**

Search the codebase for `<select` elements that list hierarchy nodes:
```bash
grep -r "hierarchy" frontend/src --include="*.tsx" -l
```
Common culprits: `AssignCommanderDialog.tsx`, `SoldierEditModal.tsx` / `UnifiedSoldierModal.tsx`, any "העבר" (transfer) dialog. Check each file for `<option>` elements that use node data.

- [ ] **Step 3: Apply sort + color to each affected select**

For each affected `<select>`, replace the options mapping with DFS-ordered options and add explicit color classes. Example pattern — before:
```tsx
{nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
```
After:
```tsx
import { flattenByDfs } from "../utils/sortNodesByTree";
// ...
{flattenByDfs(nodes).map((n) => (
  <option key={n.id} value={n.id}>{n.name}</option>
))}
```

And add color classes to the `<select>` element itself:
```tsx
className="border rounded p-1 text-gray-900 dark:text-white bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600"
```

- [ ] **Step 4: Verify**

Open the "העבר" (transfer) dialog in the commander page. Confirm nodes are in tree order and the select text is readable.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/sortNodesByTree.ts <all modified files>
git commit -m "fix: hierarchy selects sorted by DFS tree order; fix white-on-white text"
```

---

### Task 4: Fix clear assignments buttons

**Files:**
- Modify: `frontend/src/pages/DutyManagementPage.tsx` (investigate and fix)
- Possibly modify: `backend/app/routes/assignments.py`

- [ ] **Step 1: Read the current clear-assignments code**

In `frontend/src/pages/DutyManagementPage.tsx`, find the "נקה שיבוצים" and "נקה הכל" button handlers. Read what API call they make and trace it to the backend.

Also read `frontend/src/api/assignments.ts` — note that `clearAllAssignments()` calls `DELETE /assignments`. Check whether the backend handles this.

- [ ] **Step 2: Read the backend endpoint**

In `backend/app/routes/assignments.py`, find the `DELETE /assignments` handler. Verify it exists and is registered. Run:
```bash
curl -X DELETE http://localhost:8000/assignments -H "Authorization: Bearer <token>"
```
Expected: 200 or 204. If 404, the router is not registered or the route doesn't exist.

- [ ] **Step 3: Fix the identified issue**

**If the route is missing from `main.py`:** Find the assignments router registration and confirm it's included.

**If the handler is missing:** Add to `backend/app/routes/assignments.py`:
```python
@router.delete("", status_code=204)
def clear_all(
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.DELETE, "assignment")
    svc.clear_all_assignments(session)
```

And in `backend/app/services/assignments.py`, add:
```python
def clear_all_assignments(session: Session) -> None:
    session.execute(
        sa.update(DutyAssignment)
        .where(DutyAssignment.status.in_(["algorithm_draft", "published"]))
        .values(status="cancelled")
    )
    session.commit()
```

**If the frontend call is broken:** Check `handleCancelPublished` or similar in `DutyManagementPage.tsx` — ensure it `await`s the API call and calls `refreshDraftPreview()` after.

- [ ] **Step 4: Add confirmation dialog**

In `DutyManagementPage.tsx`, before the clear-all call:
```tsx
if (!window.confirm("האם לנקות את כל השיבוצים? פעולה זו אינה ניתנת לביטול.")) return;
```

- [ ] **Step 5: Test**

Create a test assignment manually, click "נקה הכל", confirm it disappears from the list.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/assignments.py backend/app/services/assignments.py frontend/src/pages/DutyManagementPage.tsx
git commit -m "fix: clear all assignments button now works with confirmation dialog"
```

---

### Task 5: Uniform date format dd.mm.yyyy

**Files:**
- Create: `frontend/src/utils/formatDate.ts` (if not done in Plan A)
- Modify: `frontend/src/components/dashboard/SwapStatusWidget.tsx`
- Modify: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx`
- Modify: `frontend/src/components/dashboard/DutyHistoryWidget.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`
- Modify: `frontend/src/pages/TransparencyPage.tsx`
- Modify: `frontend/src/components/AlgorithmProposalTable.tsx`
- Modify: any other files with `toLocaleDateString` or `.split("T")[0]` used for display

- [ ] **Step 1: Create `formatDate` (skip if Plan A already created it)**

Create `frontend/src/utils/formatDate.ts`:
```ts
export function formatDate(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d + "T00:00:00") : d;
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const yyyy = date.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

export function formatDateRange(start: string | Date, end: string | Date): string {
  const s = typeof start === "string" ? start : start.toISOString().split("T")[0];
  const e = typeof end === "string" ? end : end.toISOString().split("T")[0];
  if (s === e) return formatDate(s);
  return `${formatDate(s)} – ${formatDate(e)}`;
}
```

- [ ] **Step 2: Find all display-only date formatting calls**

```bash
grep -rn "toLocaleDateString\|\.toISOString()\.split\|new Date(" frontend/src --include="*.tsx" | grep -v "T00:00:00\|api\|\.ts\b"
```

For each match that is rendering a date for the user (not sending to API), replace with `formatDate(...)`.

Common replacements:
- `new Date(s.duty_date).toLocaleDateString("he-IL")` → `formatDate(s.duty_date)`
- `new Date(start).toLocaleDateString("he-IL")` → `formatDate(start)`
- Date columns in `DataTable` that format dates for display.

- [ ] **Step 3: Run lint**

```bash
cd frontend && pnpm lint
```
Expected: zero errors.

- [ ] **Step 4: Verify**

Navigate to homepage, transparency page, duty management, algorithm page. All dates should be in `dd.mm.yyyy` format.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/formatDate.ts <all modified files>
git commit -m "fix: all display dates use dd.mm.yyyy format via formatDate utility"
```
