# Reserve Days Count on Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Issue #24 — Show the current soldier's reserve-day count for the current month on the homepage, alongside the existing stat cards.

**Architecture:**
- `EffectiveDuty` (from `GET /assignments/effective`) currently lacks `is_reserve`. Add it to the backend response and frontend type.
- In `HomePage`, compute current-month reserve days from the already-fetched `duties` array using the new field.
- Add a new `StatCard` showing reserve days this month (and maybe year-to-date as a sub-label).

**Tech Stack:** FastAPI (Python), React, TypeScript

---

## File Map

| File | Change |
|------|--------|
| `backend/app/routes/assignments.py` | Add `is_reserve` to the effective-duties response schema |
| `frontend/src/api/assignments.ts` | Add `is_reserve` to `EffectiveDuty` interface |
| `frontend/src/pages/HomePage.tsx` | Compute and display monthly reserve days |

---

### Task 1: Add is_reserve to EffectiveDuty backend response

**Files:**
- Modify: `backend/app/routes/assignments.py`

- [ ] **Step 1: Find the EffectiveDutyOut schema**

Open `backend/app/routes/assignments.py`. Search for the Pydantic model that backs `GET /assignments/effective`. It likely looks like:

```python
class EffectiveDutyOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    shift_id: uuid.UUID | None = None
```

Add `is_reserve`:
```python
class EffectiveDutyOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    shift_id: uuid.UUID | None = None
    is_reserve: bool = False
```

- [ ] **Step 2: Include is_reserve when building the response**

Find where `EffectiveDutyOut` objects are constructed (in the route handler or a helper function). Ensure `is_reserve=assignment.is_reserve` is included. For example, if the code is:

```python
EffectiveDutyOut(
    assignment_id=a.id,
    soldier_id=a.soldier_id,
    duty_type_id=a.duty_type_id,
    duty_location_id=a.duty_location_id,
    start_date=a.start_date,
    end_date=a.end_date,
    shift_id=a.duty_shift_id,
)
```

Change to:
```python
EffectiveDutyOut(
    assignment_id=a.id,
    soldier_id=a.soldier_id,
    duty_type_id=a.duty_type_id,
    duty_location_id=a.duty_location_id,
    start_date=a.start_date,
    end_date=a.end_date,
    shift_id=a.duty_shift_id,
    is_reserve=a.is_reserve,
)
```

- [ ] **Step 3: Restart backend and verify**

```bash
curl -s "http://localhost:8000/api/assignments/effective?soldier_id=<your-id>" | python -m json.tool | grep is_reserve
```
Each effective duty should have `"is_reserve": true` or `"is_reserve": false`.

- [ ] **Step 4: Commit backend**

```bash
git add backend/app/routes/assignments.py
git commit -m "feat: include is_reserve in effective-duties response"
```

---

### Task 2: Update frontend EffectiveDuty type

**Files:**
- Modify: `frontend/src/api/assignments.ts`

- [ ] **Step 1: Add is_reserve to EffectiveDuty**

In `frontend/src/api/assignments.ts`, find:
```typescript
export interface EffectiveDuty {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  shift_id?: string | null;
}
```
Add `is_reserve`:
```typescript
export interface EffectiveDuty {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  shift_id?: string | null;
  is_reserve: boolean;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/assignments.ts
git commit -m "feat: add is_reserve to EffectiveDuty interface"
```

---

### Task 3: Compute and display monthly reserve days on HomePage

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1: Compute current-month reserve days**

In `frontend/src/pages/HomePage.tsx`, add a new `useMemo` after the existing `pastDays` memo:

```typescript
  const currentMonthStart = useMemo(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
  }, []);

  const currentMonthEnd = useMemo(() => {
    const d = new Date();
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    return last.toISOString().split("T")[0];
  }, []);

  const monthReserveDays = useMemo(() => {
    return duties
      .filter(
        (d) =>
          d.is_reserve &&
          d.start_date <= currentMonthEnd &&
          d.end_date >= currentMonthStart
      )
      .reduce((sum, d) => {
        // Clamp to current month
        const start = d.start_date < currentMonthStart ? currentMonthStart : d.start_date;
        const end = d.end_date > currentMonthEnd ? currentMonthEnd : d.end_date;
        const [sy, sm, sd] = start.split("-").map(Number);
        const [ey, em, ed] = end.split("-").map(Number);
        return sum + (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000 + 1;
      }, 0);
  }, [duties, currentMonthStart, currentMonthEnd]);

  const yearReserveDays = useMemo(() => {
    const yearStart = `${new Date().getFullYear()}-01-01`;
    const yearEnd = `${new Date().getFullYear()}-12-31`;
    return duties
      .filter(
        (d) =>
          d.is_reserve &&
          d.start_date <= yearEnd &&
          d.end_date >= yearStart
      )
      .reduce((sum, d) => {
        const start = d.start_date < yearStart ? yearStart : d.start_date;
        const end = d.end_date > yearEnd ? yearEnd : d.end_date;
        const [sy, sm, sd] = start.split("-").map(Number);
        const [ey, em, ed] = end.split("-").map(Number);
        return sum + (Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd)) / 86400000 + 1;
      }, 0);
  }, [duties]);
```

- [ ] **Step 2: Add a reserve-days StatCard**

Find the existing stats grid (the `grid grid-cols-2 sm:grid-cols-4` section, around line 229):
```tsx
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="תורנויות שירתתי" ... />
          <StatCard label="ימי תורנות" ... />
          <StatCard label="ניקוד מנורמל" ... />
          <StatCard label="דירוג ביחידה" ... />
        </div>
```

Add a 5th card below the grid (or change to a new row). To keep layout clean, put it as a separate single-card row directly before the grid:

```tsx
        {/* Reserve days this month */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-500 dark:text-gray-400">ימי רזרבה החודש</p>
            <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">{monthReserveDays}</p>
            <p className="text-xs text-gray-400 mt-0.5">סה"כ השנה: {yearReserveDays}</p>
          </div>
          <div className="text-3xl opacity-20">🛡</div>
        </div>
```

Place this block just before the `<div className="grid grid-cols-2 sm:grid-cols-4 gap-3">` section.

- [ ] **Step 3: Remove the emoji if it causes issues**

The shield emoji `🛡` is a visual hint. If linting or team style rules disallow emojis in TSX, remove the `<div className="text-3xl opacity-20">🛡</div>` line.

- [ ] **Step 4: Verify**

Open the homepage. A "ימי רזרבה החודש" card should appear showing the current month's reserve day count and a year-to-date figure below it. If you have no reserve assignments it will show 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/HomePage.tsx
git commit -m "feat: show monthly reserve days on homepage"
```
