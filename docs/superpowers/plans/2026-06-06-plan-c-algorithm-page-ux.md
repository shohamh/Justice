# Plan C — Algorithm Page UX

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six algorithm page UX problems: draft/published visual clarity, date defaults, publish modes + help modal, hierarchy picker indentation, human-readable failure panel, and correct shift fill-status calculation.

**Architecture:** Mostly frontend changes to `AlgorithmRunForm`, `AlgorithmProposalTable`, and a new `FailurePanel` component. One backend fix for the unicode escape bug. One backend endpoint addition (`GET /shifts/unfilled`). Shift fill status fix touches both backend `ShiftOut` schema and frontend display.

**Tech Stack:** React, Tailwind, FastAPI, CP-SAT (existing)

---

### Task 1: Fix algorithm failure unicode + add FailurePanel

**Files:**
- Modify: `backend/app/algorithm/solver.py`
- Create: `frontend/src/components/FailurePanel.tsx`
- Modify: `frontend/src/pages/AlgorithmPage.tsx`

- [ ] **Step 1: Check the unicode double-escape**

In `backend/app/algorithm/solver.py`, find:
```python
relaxed.append(f"T→{current.T}")
```
This is fine in Python — `→` is the arrow character `→`. The bug is likely elsewhere. Check the backend route that serializes `SolverResult`. Run:

```bash
cd backend && python -c "from app.algorithm.solver import _infeasibility_relaxation_chain; print('ok')"
```

Then check `backend/app/routes/algorithm.py` — look for any `json.dumps` call on the relaxed field or a double-serialization pattern (e.g., storing JSON as a string and then serializing again).

- [ ] **Step 2: Fix double-serialization if found**

If `relaxed` is stored as a JSON string in the DB and then serialized again when returning, the fix is to parse it before returning:
```python
# Example fix in the route:
relaxed = job.relaxed if isinstance(job.relaxed, list) else json.loads(job.relaxed or "[]")
```
Ensure the route returns a proper list, not a JSON-encoded string.

- [ ] **Step 3: Create `FailurePanel` component**

Create `frontend/src/components/FailurePanel.tsx`:
```tsx
interface Props {
  relaxed: string[];
  reasons: string[];
}

function describeRelaxation(step: string): string {
  const match = step.match(/T→(\d+)/);
  if (match) {
    return `הוגמשה מגבלת צפיפות: מותר כעת ${match[1]} ימי תורנות בכל 14 יום`;
  }
  return step;
}

export default function FailurePanel({ relaxed, reasons }: Props) {
  return (
    <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-4 space-y-3 text-sm" dir="rtl">
      <div className="flex items-center gap-2">
        <span className="text-red-600 dark:text-red-400 text-base">❌</span>
        <h3 className="font-semibold text-red-700 dark:text-red-300">האלגוריתם לא הצליח למצוא פתרון</h3>
      </div>

      {relaxed.length > 0 && (
        <div>
          <p className="text-gray-700 dark:text-gray-300 font-medium mb-1">ניסיונות שבוצעו:</p>
          <ul className="space-y-0.5 text-gray-600 dark:text-gray-400">
            {relaxed.map((step, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-red-500">•</span>
                <span>ניסיון {i + 2}: {describeRelaxation(step)} — נכשל</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-gray-700 dark:text-gray-300 font-medium mb-1">סיבות אפשריות לכישלון:</p>
        <ul className="space-y-0.5 text-gray-600 dark:text-gray-400">
          <li className="flex gap-2"><span>•</span><span>אין מספיק חיילים כשירים לטווח התאריכים</span></li>
          <li className="flex gap-2"><span>•</span><span>יותר מדי אילוצים אישיים מאושרים בתקופה זו</span></li>
          <li className="flex gap-2"><span>•</span><span>מגבלת הצפיפות נמוכה מדי ביחס לכמות המשמרות</span></li>
          {reasons.map((r, i) => (
            <li key={i} className="flex gap-2"><span>•</span><span>{r}</span></li>
          ))}
        </ul>
      </div>

      <div>
        <p className="text-gray-700 dark:text-gray-300 font-medium mb-1">המלצות:</p>
        <ul className="space-y-0.5 text-gray-600 dark:text-gray-400">
          <li className="flex gap-2"><span>→</span><span>הרחב את טווח התאריכים לפיזור טוב יותר</span></li>
          <li className="flex gap-2"><span>→</span><span>הפחת את מספר המשמרות הנדרשות לתקופה</span></li>
          <li className="flex gap-2"><span>→</span><span>בדוק אילוצים אישיים שאושרו לאותה תקופה</span></li>
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire `FailurePanel` in `AlgorithmPage.tsx`**

In `frontend/src/pages/AlgorithmPage.tsx`, find where the job result is displayed. Where `selectedJob?.status === "failed"` is rendered (currently shows raw JSON), replace with:
```tsx
import FailurePanel from "../components/FailurePanel";
// ...
{selectedJob.status === "failed" && (
  <FailurePanel
    relaxed={selectedJob.result?.relaxed ?? []}
    reasons={selectedJob.result?.reasons ?? []}
  />
)}
```

- [ ] **Step 5: Verify**

Run a job that will fail (e.g., pick a date range with no soldiers). Confirm the `FailurePanel` renders with Hebrew relaxation descriptions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/routes/algorithm.py frontend/src/components/FailurePanel.tsx frontend/src/pages/AlgorithmPage.tsx
git commit -m "fix: human-readable algorithm failure panel with Hebrew relaxation descriptions"
```

---

### Task 2: Draft/published status badges

**Files:**
- Modify: `frontend/src/components/AlgorithmProposalTable.tsx`
- Modify: `frontend/src/pages/AlgorithmPage.tsx`

- [ ] **Step 1: Add status banner to `AlgorithmProposalTable`**

In `frontend/src/components/AlgorithmProposalTable.tsx`, find the top of the component JSX. Add a banner based on whether the proposals are drafts:

The component currently receives job data — check its props. Add a `isDraft: boolean` prop or derive it from the job status. Add above the table:
```tsx
{isDraft ? (
  <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-700 rounded p-3 text-sm text-amber-700 dark:text-amber-300 font-medium" dir="rtl">
    ⚠️ טיוטה — תוצאות לא פורסמו. לחץ "אשר ופרסם" להחלת השיבוצים.
  </div>
) : (
  <div className="bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-700 rounded p-3 text-sm text-green-700 dark:text-green-300 font-medium" dir="rtl">
    ✓ פורסם — שיבוצים פעילים.
  </div>
)}
```

- [ ] **Step 2: Add status badge to job list**

In `frontend/src/pages/AlgorithmPage.tsx`, find the jobs list rendering. For each job row, add a status badge:
```tsx
const STATUS_BADGE: Record<string, string> = {
  pending: "bg-gray-100 text-gray-600",
  running: "bg-blue-100 text-blue-700",
  done: "bg-amber-100 text-amber-700",      // draft (not yet published)
  failed: "bg-red-100 text-red-700",
  published: "bg-green-100 text-green-700",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "ממתין",
  running: "רץ...",
  done: "טיוטה",
  failed: "נכשל",
  published: "פורסם",
};
```

Add to each job row:
```tsx
<span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[job.status] ?? "bg-gray-100 text-gray-600"}`}>
  {STATUS_LABEL[job.status] ?? job.status}
</span>
```

- [ ] **Step 3: Update publish button text**

Find the "approve and publish" button. Change its label to:
```tsx
אשר ופרסם (הפוך לרשמי)
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AlgorithmProposalTable.tsx frontend/src/pages/AlgorithmPage.tsx
git commit -m "feat: draft/published status banners and badges on algorithm page"
```

---

### Task 3: Default date + unfilled shifts button

**Files:**
- Modify: `frontend/src/components/AlgorithmRunForm.tsx`
- Modify: `backend/app/routes/shifts.py`
- Modify: `frontend/src/api/shifts.ts`

- [ ] **Step 1: Set default date in `AlgorithmRunForm`**

In `frontend/src/components/AlgorithmRunForm.tsx`, change the initial state:
```tsx
function todayStr() {
  return new Date().toISOString().split("T")[0];
}

function thirtyDaysStr() {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().split("T")[0];
}

const [dateFrom, setDateFrom] = useState(todayStr);
const [dateTo, setDateTo] = useState(thirtyDaysStr);
```

- [ ] **Step 2: Add "הצג משמרות ללא שיבוץ" button**

In `AlgorithmRunForm.tsx`, the existing `loadShifts` already loads unfilled shifts when date range is set (it filters `fill_status !== "full"`). The UX fix is: when no shifts are found (empty `availableShifts` after loading), show a message instead of empty list:
```tsx
{availableShifts.length === 0 && (dateFrom || dateTo) && (
  <p className="text-sm text-gray-500 text-right" dir="rtl">
    לא נמצאו משמרות ללא שיבוץ בטווח התאריכים שנבחר.
  </p>
)}
```

Also, the existing behavior already shows unfilled shifts — ensure the `loadShifts` is called on mount since we now have default dates:
```tsx
useEffect(() => {
  void loadShifts();
}, [loadShifts]);
```
(Remove the `if (dateFrom || dateTo)` guard since defaults are now always set.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlgorithmRunForm.tsx
git commit -m "feat: algorithm form defaults start to today, loads unfilled shifts on mount"
```

---

### Task 4: Mode rename + direct publish + help modal

**Files:**
- Modify: `frontend/src/components/AlgorithmRunForm.tsx`
- Create: `frontend/src/components/AlgorithmModeHelpModal.tsx`
- Modify: `backend/app/routes/algorithm.py` (accept new mode value)

- [ ] **Step 1: Create help modal**

Create `frontend/src/components/AlgorithmModeHelpModal.tsx`:
```tsx
interface Props {
  onClose: () => void;
}

export default function AlgorithmModeHelpModal({ onClose }: Props) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 space-y-4 text-sm"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-semibold">מצבי הרצה</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="space-y-3">
          <div className="bg-amber-50 dark:bg-amber-950 rounded p-3">
            <p className="font-semibold text-amber-700 dark:text-amber-300 mb-1">מצב טיוטה (ברירת מחדל)</p>
            <p className="text-gray-600 dark:text-gray-400">
              תוצאות האלגוריתם נשמרות כטיוטה בלבד. החיילים לא רואים שינוי. אפשר לסקור את השיבוצים המוצעים,
              לדחות חלקם, ולפרסם רק אחרי אישור. מומלץ לשימוש רגיל.
            </p>
          </div>

          <div className="bg-green-50 dark:bg-green-950 rounded p-3">
            <p className="font-semibold text-green-700 dark:text-green-300 mb-1">מצב פרסום ישיר</p>
            <p className="text-gray-600 dark:text-gray-400">
              תוצאות האלגוריתם מתפרסמות מיד ללא שלב ביניים. החיילים רואים את השיבוצים החדשים מיידית.
              השתמש רק כאשר אתה בטוח בתוצאות מראש.
            </p>
          </div>
        </div>

        <button
          className="w-full border border-gray-300 dark:border-gray-600 py-2 rounded text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
          onClick={onClose}
        >
          סגור
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update `AlgorithmRunForm` mode selector**

In `frontend/src/components/AlgorithmRunForm.tsx`, change the mode type and selector:
```tsx
const [mode, setMode] = useState<"draft" | "direct_publish">("draft");
const [showModeHelp, setShowModeHelp] = useState(false);
```

Replace the mode UI (find the existing `mode` select/toggle):
```tsx
<div className="flex items-center gap-2" dir="rtl">
  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">מצב הרצה:</span>
  <div className="flex rounded border border-gray-300 dark:border-gray-600 overflow-hidden text-sm">
    <button
      type="button"
      className={`px-3 py-1 ${mode === "draft" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
      onClick={() => setMode("draft")}
    >
      מצב טיוטה
    </button>
    <button
      type="button"
      className={`px-3 py-1 ${mode === "direct_publish" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
      onClick={() => setMode("direct_publish")}
    >
      מצב פרסום ישיר
    </button>
  </div>
  <button
    type="button"
    className="text-gray-400 hover:text-indigo-600 text-sm font-bold border rounded-full w-5 h-5 flex items-center justify-center"
    onClick={() => setShowModeHelp(true)}
    title="מה ההבדל?"
  >
    ?
  </button>
  {showModeHelp && <AlgorithmModeHelpModal onClose={() => setShowModeHelp(false)} />}
</div>
```

In the `handleSubmit` call, map `"draft"` → `"shadow"` for the API (or update the API to accept the new names — see next step):
```tsx
const apiMode = mode === "draft" ? "shadow" : "dm_reviewed";
const resp = await submitJob({ shift_ids: selectedShiftIds, mode: apiMode, settings });
```

- [ ] **Step 3: Backend — accept `direct_publish` mode OR map in frontend**

The simplest approach is the frontend mapping above (Step 2). If you want to rename in the backend too, in `backend/app/routes/algorithm.py` find the mode enum/validation and add `"direct_publish"` as an alias for `"dm_reviewed"`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AlgorithmRunForm.tsx frontend/src/components/AlgorithmModeHelpModal.tsx
git commit -m "feat: algorithm mode selector renamed, direct publish mode, help modal"
```

---

### Task 5: Fix shift full-status (primary vs reserve)

**Files:**
- Modify: `backend/app/routes/shifts.py` (`ShiftOut` schema)
- Modify: `backend/app/services/shifts.py` (fill_status logic)
- Modify: `frontend/src/api/shifts.ts`
- Modify: `frontend/src/components/AlgorithmRunForm.tsx` (display)
- Modify: `frontend/src/pages/ShiftsPage.tsx` (if it exists and shows fill status)

- [ ] **Step 1: Check current fill_status logic**

In `backend/app/services/shifts.py`, find where `fill_status` is computed. It currently counts all assignments (primary + reserve). Fix it to only count primary:
```python
# find the fill_status computation, likely something like:
assigned_primary = sum(1 for a in assignments if not a.is_reserve)
fill_status = (
    "full" if assigned_primary >= shift.required_count
    else "partial" if assigned_primary > 0
    else "empty"
)
```

- [ ] **Step 2: Update `ShiftOut` schema**

In `backend/app/routes/shifts.py`, `ShiftOut` already has `assigned_count` and `reserve_assigned_count`. Rename or clarify:
- Ensure `assigned_count` = primary-only count.
- Ensure `fill_status` is based on primary-only.
- `reserve_assigned_count` = reserve count (already exists).

Verify the `_out` function maps these correctly.

- [ ] **Step 3: Update frontend `DutyShift` type**

In `frontend/src/api/shifts.ts`, find the `DutyShift` interface. Ensure `assigned_count` is documented as primary-only. Add comment:
```ts
assigned_count: number;        // primary slots filled
reserve_assigned_count: number; // reserve slots filled
```

- [ ] **Step 4: Update `AlgorithmRunForm` shift label**

In `frontend/src/components/AlgorithmRunForm.tsx`, find `shiftLabel`:
```tsx
const shiftLabel = (shift: DutyShift) =>
  `${typeName(shift.duty_type_id)} — ${shift.start_date} עד ${shift.end_date} (ראשי: ${shift.assigned_count}/${shift.required_count}, רזרבה: ${shift.reserve_assigned_count ?? 0})`;
```

- [ ] **Step 5: Write backend unit test**

In `backend/tests/unit/test_shifts.py` (create if missing):
```python
def test_fill_status_excludes_reserve(session):
    # Create a shift requiring 2 primary soldiers
    # Assign 1 primary + 1 reserve
    # Assert fill_status == "partial", not "full"
    ...
```

Run: `cd backend && uv run pytest tests/unit/test_shifts.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/shifts.py backend/app/routes/shifts.py frontend/src/api/shifts.ts frontend/src/components/AlgorithmRunForm.tsx
git commit -m "fix: shift fill_status based on primary count only, not primary+reserve"
```
