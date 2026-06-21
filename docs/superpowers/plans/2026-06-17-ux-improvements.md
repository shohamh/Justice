# UX Improvements Sprint — June 2026

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 UX issues reported from real usage: urgency sorting on approvals, full-org calendar/transparency tree, gimelim scope enforcement, wider tables, HakpazaPage soldier picker with explanation, bigger pie chart, and all-units filter.

**Architecture:** Mostly surgical frontend edits and a few small backend adjustments. Issues 2 & 7 share one backend change (full-org tree endpoint option). All changes are independently shippable. No DB migrations needed.

**Tech Stack:** React + TypeScript (Vite), FastAPI (Python), SQLAlchemy, Tailwind CSS

---

## Task 1 — Approval sorting by urgency + CommandDashboard panel reorder (issue 1)

**Files:**
- Modify: `backend/app/services/constraints.py:221-244`
- Modify: `backend/app/routes/constraints.py:156-165`
- Modify: `frontend/src/pages/CommandDashboardPage.tsx:66-117`

Currently pending constraints are sorted by `created_at asc`. "Urgent" means the constraint starts soonest — those need approval before the soldier's start_date, so sort by `start_date asc`.

Additionally, the `CommandDashboardPage` panels are ordered with calendar and stats first. Actionable items (alerts, approvals, upcoming duties) should appear at the top so commanders see what needs their attention first.

- [ ] **Step 1: Change the sort order in `list_pending_approvals`**

In `backend/app/services/constraints.py`, find the query inside `list_pending_approvals` (around line 231) and change `.order_by(PersonalConstraint.created_at.asc())` to `.order_by(PersonalConstraint.start_date.asc())`:

```python
    return list(
        session.execute(
            select(PersonalConstraint)
            .where(
                PersonalConstraint.status == "pending",
                PersonalConstraint.soldier_id.in_(
                    select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
                ),
            )
            .order_by(PersonalConstraint.start_date.asc())
        )
        .scalars()
        .all()
    )
```

Also apply the same fix in the admin path in `backend/app/routes/constraints.py:156-165` (inside `pending_list`):
```python
        rows = list(
            session.execute(
                select(PersonalConstraint)
                .where(PersonalConstraint.status == "pending")
                .order_by(PersonalConstraint.start_date.asc())
            )
            .scalars()
            .all()
        )
```

### 1b — CommandDashboard panel reorder

- [ ] **Step 2: Reorder panels in `CommandDashboardPage`**

In `frontend/src/pages/CommandDashboardPage.tsx`, reorder the `panels` array so actionable items come first:

```typescript
  const panels: { id: string; title: string; content: React.ReactNode }[] = [
    {
      id: "alerts",
      title: t("command_dashboard.alerts"),
      content: <AlertsPanel data={alertsData} />,
    },
    {
      id: "approvals",
      title: t("command_dashboard.approvals"),
      content: <ApprovalsFeed data={approvalsData} onRefresh={refresh} />,
    },
    {
      id: "upcoming",
      title: t("command_dashboard.upcoming"),
      content: <UpcomingSnapshot data={upcomingData} />,
    },
    {
      id: "calendar",
      title: t("command_dashboard.calendar"),
      content: nodes.length > 0 ? <UnitCalendar nodeId={nodes[0]?.id || ""} /> : null,
    },
    {
      id: "soldiers",
      title: t("command_dashboard.soldiers"),
      content: (
        <div>
          <div className="mb-4">
            <HierarchyTree nodes={nodes} soldiers={soldierDTOs} isAdmin={false} onChanged={refresh} user={user} />
          </div>
        </div>
      ),
    },
    {
      id: "entries_exits",
      title: t("command_dashboard.entries_exits"),
      content: <EntriesExitsPanel soldiers={soldiers} onRefresh={refresh} />,
    },
    {
      id: "fairness_internal",
      title: t("command_dashboard.internal_fairness"),
      content: <InternalFairness data={fairnessInternal} />,
    },
    {
      id: "fairness_external",
      title: t("command_dashboard.external_fairness"),
      content: <ExternalFairness data={fairnessExternal} />,
    },
    {
      id: "potential",
      title: t("command_dashboard.potential"),
      content: <DutyPotentialPanel data={potentialData} />,
    },
  ];
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/constraints.py backend/app/routes/constraints.py \
        frontend/src/pages/CommandDashboardPage.tsx
git commit -m "fix: sort pending approvals by urgency + reorder CommandDashboard panels"
```

---

## Task 2 — Full-org tree endpoint + calendar visibility (issues 2 & 7)

**Files:**
- Modify: `backend/app/routes/hierarchy.py:144-164` — add `?all=true` param
- Modify: `backend/app/routes/calendar.py:173-191` — allow all authenticated users to view
- Modify: `frontend/src/api/hierarchy.ts` — add `fetchFullTree()`
- Modify: `frontend/src/pages/UnitCalendarPage.tsx` — use full tree
- Modify: `frontend/src/pages/TransparencyPage.tsx:307` — use full tree for unit filter
- Modify: `frontend/src/pages/CommandDashboardPage.tsx:48` — use full tree

### 2a — Backend: full-org tree option

- [ ] **Step 1: Add `all` query param to `get_tree`**

In `backend/app/routes/hierarchy.py`, change the `get_tree` function signature and body to support `?all=true`:

```python
@router.get("/tree", response_model=list[NodeOut])
def get_tree(
    all: bool = False,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NodeOut]:
    if all or user.role == "admin":
        nodes = session.execute(select(HierarchyNode)).scalars().all()
    elif user.role == "soldier":
        if user.hierarchy_node_id is None:
            return []
        node = session.get(HierarchyNode, user.hierarchy_node_id)
        return [_out(node, session)] if node else []
    else:
        roots = scope_root_ids(session, user)
        if not roots:
            return []
        nodes = [
            n
            for n in session.execute(select(HierarchyNode)).scalars().all()
            if any(r in n.path_ids for r in roots)
        ]
    return [_out(n, session) for n in nodes]
```

The `all=True` path allows any authenticated user to see the full org tree (read-only). This is safe — unit names are not sensitive.

### 2b — Backend: calendar shifts open to all authenticated users

- [ ] **Step 2: Remove scope restriction from `calendar_shifts`**

In `backend/app/routes/calendar.py`, change the authorization check to allow any logged-in user to view calendar shifts (it's read-only duty schedule data):

```python
@router.get("/shifts", response_model=CalendarShiftsResponse)
def calendar_shifts(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarShiftsResponse:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    # Calendar shifts are read-only schedule data visible to all authenticated users
    raw = get_calendar_shifts(session, node_id=node_id, date_from=date_from, date_to=date_to)
    shifts = [
        CalendarShiftOut(**s, swap_request_count=_swap_count_for_shift(session, s["id"]))
        for s in raw
    ]
    return CalendarShiftsResponse(shifts=shifts)
```

### 2c — Frontend: fetchFullTree helper

- [ ] **Step 3: Add `fetchFullTree` to `frontend/src/api/hierarchy.ts`**

```typescript
export async function fetchFullTree(): Promise<NodeDTO[]> {
  return (await api.get<NodeDTO[]>("/hierarchy/tree", { params: { all: true } })).data;
}
```

### 2d — Frontend: use full tree in UnitCalendarPage

- [ ] **Step 4: Update `frontend/src/pages/UnitCalendarPage.tsx`**

Change the import and the effect to use `fetchFullTree`:

```typescript
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
// ...
  useEffect(() => {
    void fetchFullTree().then((ns) => {
      const ordered = treeOrder(ns);
      setNodes(ordered);
      const preferred = user?.hierarchy_node_id
        ? ordered.find((n) => n.id === user.hierarchy_node_id)
        : null;
      setNodeId((preferred ?? ordered[0])?.id ?? "");
    });
  }, [user]);
```

### 2e — Frontend: use full tree in TransparencyPage unit filter

- [ ] **Step 5: Update `frontend/src/pages/TransparencyPage.tsx:307`**

Change:
```typescript
  useEffect(() => { void fetchTree().then(setTreeNodes); }, []);
```
To:
```typescript
  useEffect(() => { void fetchFullTree().then(setTreeNodes); }, []);
```

And add `fetchFullTree` to the import from `"../api/hierarchy"`.

### 2f — Frontend: use full tree in CommandDashboardPage

- [ ] **Step 6: Update `frontend/src/pages/CommandDashboardPage.tsx:48`**

In the `refresh` callback, replace `fetchTree()` with `fetchFullTree()` and update the import.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/hierarchy.py backend/app/routes/calendar.py \
        frontend/src/api/hierarchy.ts frontend/src/pages/UnitCalendarPage.tsx \
        frontend/src/pages/TransparencyPage.tsx frontend/src/pages/CommandDashboardPage.tsx
git commit -m "feat: full-org tree for calendar and transparency unit filter"
```

---

## Task 3 — Gimelim button scope enforcement (issue 3)

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx:197`

The backend (`_require_gimelim_permission`) already enforces that only duty managers and admins with the right scope can do gimelim (`Action.ASSIGNMENT_MANAGE` is not in `_COMMANDER_ACTIONS`). The problem is the button is shown to everyone, which is confusing and invites failed actions.

- [ ] **Step 1: Gate gimelim button to DM/admin only**

In `frontend/src/components/ShiftDetailPanel.tsx`, find the block around line 197:

```typescript
{gimelimEnabled && !a.is_reserve && (
  <button
    className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
    onClick={() => setGimelimTarget(a)}
  >
    גימלים 🏥
  </button>
)}
```

Change it to also check the user's role:

```typescript
{gimelimEnabled && !a.is_reserve && (user?.role === "duty_manager" || user?.role === "admin") && (
  <button
    className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
    onClick={() => setGimelimTarget(a)}
  >
    גימלים 🏥
  </button>
)}
```

You'll need to import `useAuth` (already available via context) if `user` is not already in scope. Look at the top of `ShiftDetailPanel.tsx` to see if `user` is already a prop or comes from context. If not, add:
```typescript
const { user } = useAuth();
```
near the top of the component.

- [ ] **Step 2: Verify**

Log in as a commander (role="commander"). Open a shift detail panel. Confirm the gimelim button is not visible. Log in as a duty_manager. Confirm the button is visible.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx
git commit -m "fix: hide gimelim button from commanders (only DM/admin can manage)"
```

---

## Task 4 — Wider tables on PC (issue 4)

**Files:**
- Modify: `frontend/src/pages/HakpazaPage.tsx:102`
- Modify: `frontend/src/components/FairnessComponentsCard.tsx` (if constrained)

The HakpazaPage has `max-w-2xl mx-auto` (max 672px) which is too narrow for the candidates table on desktop.

- [ ] **Step 1: Remove max-width constraint in HakpazaPage**

In `frontend/src/pages/HakpazaPage.tsx:102`, change:
```typescript
<div className="max-w-2xl mx-auto space-y-4 p-4" dir="rtl">
```
To:
```typescript
<div className="space-y-4 p-4" dir="rtl">
```

- [ ] **Step 2: Check other constrained pages**

Look at `frontend/src/pages/ApprovalsPage.tsx` and `frontend/src/pages/ShiftsPage.tsx` — if they have `max-w-*` constraints on their root `<section>`, remove them. The DataTable component should naturally fill available width.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/HakpazaPage.tsx
git commit -m "fix: remove max-width constraint on HakpazaPage for wider desktop layout"
```

---

## Task 5 — HakpazaPage soldier picker + explanation (issue 5)

**Files:**
- Modify: `frontend/src/pages/HakpazaPage.tsx`

The user wants to see their own soldiers (from their command scope) with upcoming duties listed, so they can pick who to replace — instead of only a search box. Also add a clear explanation of what הקפצה פיקודית does.

- [ ] **Step 1: Add state + data fetching for scoped soldier list**

At the top of `HakpazaPage`, add:
```typescript
import { SoldierDTO, listSoldiers } from "../api/soldiers";
// ...
const [scopedSoldiers, setScopedSoldiers] = useState<SoldierDTO[]>([]);
const [soldierSearch, setSoldierSearch] = useState("");
```

In a `useEffect`, load soldiers (the API already scopes by user's authority):
```typescript
useEffect(() => {
  listSoldiers().then(setScopedSoldiers).catch(() => {});
}, []);
```

- [ ] **Step 2: Add explanation header + redesign Step 1**

Replace the existing Step 1 block (the `SoldierSearchAutocomplete`) with:

```typescript
{/* Explanation */}
<div className="bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-4 text-sm space-y-2">
  <p className="font-semibold text-blue-800 dark:text-blue-200">מה זה הקפצה פיקודית?</p>
  <p className="text-blue-700 dark:text-blue-300">
    הקפצה פיקודית מאפשרת להחליף חייל בתורנות פעילה — למשל אם קיבל גימלים, נסיעה, או נסיבות חריגות.
    המערכת מחפשת את המחליף המתאים ביותר לפי ניקוד, ומציגה את הרשימה לבחירה.
    הבקשה עוברת לאישור מנהל תורניות לפני הפעלה.
  </p>
</div>

{/* Step 1: Select soldier */}
<div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 1 ? "opacity-60" : ""}`}>
  <h2 className="font-medium text-sm text-gray-500">שלב 1 — בחר חייל להקפיץ</h2>
  {step === 1 ? (
    <div className="space-y-3">
      {/* Quick search filter */}
      <input
        type="text"
        placeholder="חיפוש לפי שם..."
        value={soldierSearch}
        onChange={(e) => setSoldierSearch(e.target.value)}
        className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
        dir="rtl"
      />
      {/* Scoped soldier list */}
      <div className="max-h-60 overflow-y-auto border rounded dark:border-gray-700 divide-y dark:divide-gray-700">
        {scopedSoldiers
          .filter((s) => !soldierSearch || s.full_name.includes(soldierSearch))
          .map((s) => (
            <button
              key={s.id}
              type="button"
              className="w-full text-right px-3 py-2 text-sm hover:bg-indigo-50 dark:hover:bg-indigo-950 flex items-center justify-between gap-2"
              onClick={() => { void handleSoldierSelect(s); }}
            >
              <span className="font-medium">{s.full_name}</span>
              {s.rank && <span className="text-xs text-gray-400">{s.rank}</span>}
            </button>
          ))}
        {scopedSoldiers.filter((s) => !soldierSearch || s.full_name.includes(soldierSearch)).length === 0 && (
          <p className="text-sm text-gray-500 p-3">לא נמצאו חיילים</p>
        )}
      </div>
    </div>
  ) : (
    pulledSoldier && (
      <div className="flex items-center gap-2">
        <p className="text-sm font-medium">{pulledSoldier.full_name}</p>
        <button
          type="button"
          className="text-xs text-indigo-600 hover:underline"
          onClick={() => { setPulledSoldier(null); setStep(1); setAssignments([]); setSelectedAssignment(null); }}
        >
          שנה
        </button>
      </div>
    )
  )}
</div>
```

- [ ] **Step 3: Verify the flow works end to end**

Start dev stack. Open HakpazaPage. Confirm: explanation shows, soldier list shows (filtered to scope), click a soldier → loads their upcoming assignments → complete the 5-step flow normally.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/HakpazaPage.tsx
git commit -m "feat: add explanation + scoped soldier list picker in HakpazaPage"
```

---

## Task 6 — Larger pie chart in FairnessComponentsCard (issue 6)

**Files:**
- Modify: `frontend/src/components/FairnessComponentsCard.tsx:131-155`

The pie chart inside each fairness component card is 56×56px — too small on desktop.

- [ ] **Step 1: Increase pie size**

In `FairnessComponentsCard.tsx`, find the section around line 131:
```typescript
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
```

Change to 96×96 with proportionally larger radii:
```typescript
<div style={{ width: 96, height: 96 }}>
  <ResponsiveContainer width="100%" height="100%">
    <PieChart>
      <Pie
        data={dist}
        dataKey="soldiers"
        cx="50%"
        cy="50%"
        innerRadius={28}
        outerRadius={44}
        paddingAngle={2}
      >
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/FairnessComponentsCard.tsx
git commit -m "fix: increase FairnessComponentsCard pie chart size for readability on desktop"
```

---

## Self-review checklist

- [x] Issue 1 (approval urgency): handled in Task 1 — sort by `start_date.asc()`
- [x] Issue 2 (calendar beyond scope): handled in Task 2 — `fetchFullTree` + open calendar API
- [x] Issue 3 (gimelim on out-of-scope soldiers): handled in Task 3 — gate button by role
- [x] Issue 4 (tables too small): handled in Task 4 — remove `max-w-2xl`
- [x] Issue 5 (HakpazaPage soldier picker + explanation): handled in Task 5
- [x] Issue 6 (pie chart small): handled in Task 6 — increase size to 96×96
- [x] Issue 7 (transparency unit filter all units): handled in Task 2 step 5 — same `fetchFullTree`

No placeholder gaps found. Types used are consistent with existing codebase (`SoldierDTO`, `NodeDTO`, `fetchFullTree` returns `NodeDTO[]`).
