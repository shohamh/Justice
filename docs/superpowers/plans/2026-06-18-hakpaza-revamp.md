# Hakpaza Page Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Issue #43 — In הקפצה פיקודית: (1) show only soldiers in the commander's subtree (the backend already scopes this via `listSoldiers`), (2) sort soldiers by their nearest upcoming assigned shift with shift type and date shown, (3) restrict the blue explanation box text to extraordinary operational/personal circumstances only (remove גימלים mention).

**Architecture:**
- The backend's `GET /soldiers` already applies `scope_root_ids`, so commanders only receive their own subtree — no backend change needed for scoping.
- Sorting by next shift: after loading soldiers, fetch all upcoming assignments for the scoped soldiers in a single `Promise.all`. Each assignment includes `duty_type_id` and `start_date`. Load duty-type names in parallel. Sort soldiers by earliest `start_date` among their assignments; soldiers with no upcoming shift sort last.
- Display: show the nearest shift's type name + date beneath each soldier's name in the Step 1 list.
- Description: replace the existing blue info box text; remove גימלים, only mention נסיבות חריגות מבצעיות או אישיות.

**Tech Stack:** React, TypeScript

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/pages/HakpazaPage.tsx` | Fetch shift data per soldier, sort list, update description |

---

### Task 1: Update description text

**Files:**
- Modify: `frontend/src/pages/HakpazaPage.tsx`

- [ ] **Step 1: Replace the explanation box text**

In `frontend/src/pages/HakpazaPage.tsx`, find:
```tsx
        <div className="bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-4 text-sm space-y-2" dir="rtl">
          <p className="font-semibold text-blue-800 dark:text-blue-200">מה זה הקפצה פיקודית?</p>
          <p className="text-blue-700 dark:text-blue-300">
            הקפצה פיקודית מאפשרת להחליף חייל בתורנות פעילה — למשל אם קיבל גימלים, נסיעה, או נסיבות חריגות.
            המערכת מחפשת את המחליף המתאים ביותר לפי ניקוד, ומציגה את הרשימה לבחירה.
            הבקשה עוברת לאישור מנהל תורניות לפני הפעלה.
          </p>
        </div>
```
Replace with:
```tsx
        <div className="bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-4 text-sm space-y-2" dir="rtl">
          <p className="font-semibold text-blue-800 dark:text-blue-200">מה זה הקפצה פיקודית?</p>
          <p className="text-blue-700 dark:text-blue-300">
            הקפצה פיקודית מיועדת לנסיבות חריגות מבצעיות או אישיות בלבד.
            המערכת מחפשת את המחליף המתאים ביותר לפי ניקוד, ומציגה את הרשימה לבחירה.
            הבקשה עוברת לאישור מנהל תורניות לפני הפעלה.
          </p>
        </div>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/HakpazaPage.tsx
git commit -m "fix: update hakpaza description to reflect extraordinary circumstances only"
```

---

### Task 2: Fetch upcoming shifts per soldier and sort the list

**Files:**
- Modify: `frontend/src/pages/HakpazaPage.tsx`

- [ ] **Step 1: Add state for next-shift data**

In `frontend/src/pages/HakpazaPage.tsx`, add imports at the top:
```typescript
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import { formatDate } from "../utils/formatDate";
```

Add two new state variables after the existing state declarations:
```typescript
  const [nextShiftBySoldier, setNextShiftBySoldier] = useState<Record<string, { date: string; typeName: string } | null>>({});
  const [shiftsLoading, setShiftsLoading] = useState(false);
```

- [ ] **Step 2: Load duty-type names and next shifts after soldiers load**

Currently, `listSoldiers()` is called in `useEffect` and sets `scopedSoldiers`. Add a second effect that fires after `scopedSoldiers` changes to fetch each soldier's upcoming assignments:

```typescript
  useEffect(() => {
    if (scopedSoldiers.length === 0) return;
    setShiftsLoading(true);
    const todayStr = new Date().toISOString().split("T")[0];

    Promise.all([
      listDutyTypes().catch(() => [] as DutyType[]),
      Promise.all(
        scopedSoldiers.map((s) =>
          listAssignments(s.id, { date_from: todayStr })
            .then((asgns) => ({
              soldierId: s.id,
              upcoming: asgns
                .filter((a) => a.status === "published")
                .sort((a, b) => a.start_date.localeCompare(b.start_date)),
            }))
            .catch(() => ({ soldierId: s.id, upcoming: [] }))
        )
      ),
    ]).then(([dts, results]) => {
      const typeNameById = Object.fromEntries((dts as DutyType[]).map((d) => [d.id, d.name]));
      const map: Record<string, { date: string; typeName: string } | null> = {};
      for (const { soldierId, upcoming } of results) {
        if (upcoming.length > 0) {
          const first = upcoming[0];
          map[soldierId] = {
            date: first.start_date,
            typeName: typeNameById[first.duty_type_id] ?? "תורנות",
          };
        } else {
          map[soldierId] = null;
        }
      }
      setNextShiftBySoldier(map);
      setShiftsLoading(false);
    });
  }, [scopedSoldiers]);
```

- [ ] **Step 3: Sort soldiers by next shift date in the Step 1 list**

Find the soldier list rendering (inside the Step 1 card, the `.map((s) => ...)` on `scopedSoldiers`):
```tsx
                {scopedSoldiers
                  .filter((s) => !soldierSearch || s.full_name.includes(soldierSearch))
                  .map((s) => (
```
Add a sort before the filter:
```tsx
                {[...scopedSoldiers]
                  .sort((a, b) => {
                    const na = nextShiftBySoldier[a.id];
                    const nb = nextShiftBySoldier[b.id];
                    if (na && nb) return na.date.localeCompare(nb.date);
                    if (na) return -1;
                    if (nb) return 1;
                    return a.full_name.localeCompare(b.full_name);
                  })
                  .filter((s) => !soldierSearch || s.full_name.includes(soldierSearch))
                  .map((s) => (
```

- [ ] **Step 4: Show next-shift info in each list item**

In the same `.map((s) => ...)` block, the current button body is:
```tsx
                      <span className="font-medium">{s.full_name}</span>
                      {s.rank && <span className="text-xs text-gray-400">{s.rank}</span>}
```
Replace with:
```tsx
                      <div className="text-right">
                        <span className="font-medium">{s.full_name}</span>
                        {s.rank && <span className="text-xs text-gray-400 mr-1">{s.rank}</span>}
                        {nextShiftBySoldier[s.id] ? (
                          <p className="text-xs text-indigo-600 dark:text-indigo-300 mt-0.5">
                            {nextShiftBySoldier[s.id]!.typeName} — {formatDate(nextShiftBySoldier[s.id]!.date)}
                          </p>
                        ) : (
                          <p className="text-xs text-gray-400 mt-0.5">אין תורנות קרובה</p>
                        )}
                      </div>
```

- [ ] **Step 5: Show loading state while shift data loads**

Below the search input and before the soldier list div, add a small indicator:
```tsx
              {shiftsLoading && (
                <p className="text-xs text-gray-400 px-3 py-1">טוען תורנויות...</p>
              )}
```

- [ ] **Step 6: Verify**

Open הקפצה פיקודית as a commander. The soldier list should:
- Show only soldiers in your subtree (existing behavior)
- Sort by nearest upcoming shift (soonest first)
- Display shift type + date under each name
- Show "אין תורנות קרובה" for soldiers with no upcoming assignments

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/HakpazaPage.tsx
git commit -m "feat: sort hakpaza soldiers by upcoming shift, show shift type and date"
```
