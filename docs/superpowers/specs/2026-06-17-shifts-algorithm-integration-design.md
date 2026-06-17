# Spec: Integrate Algorithm into Shifts Page

**Date:** 2026-06-17  
**Status:** Approved

## Goal

Consolidate the Algorithm and Shifts experiences into a single `/planning/shifts` page.  
Remove the separate `/planning/assignment` page entirely.

---

## Page Layout (`ShiftsManagementPage`)

Three stacked sections, top to bottom:

```
┌──────────────────────────────────────────────┐
│ ▼ תבניות                    [collapsible]    │
│   ShiftTemplatesContent (unchanged)          │
└──────────────────────────────────────────────┘
┌──────────────────────────────────────────────┐
│ ▼ ריצות אלגוריתם            [collapsible]    │
│   AlgorithmContent (job list + detail)       │
│   Auto-opens when a job is submitted         │
└──────────────────────────────────────────────┘
┌──────────────────────────────────────────────┐
│  לוח משמרות                  [always visible] │
│  [date filters]  [שיבוץ אוטומטי button]      │
│                                              │
│  ┌── AlgorithmInlinePanel ──────────────┐    │
│  │  X משמרות נבחרות                    │    │
│  │  [טיוטה | פרסום ישיר]  [?]          │    │
│  │  ▸ הגדרות מתקדמות                   │    │
│  │  ▸ הגבלת תת-עץ                     │    │
│  │  [הרץ שיבוץ אוטומטי]               │    │
│  └──────────────────────────────────────┘    │
│  (expands/collapses on button click)         │
│                                              │
│  ┌── DataTable ─────────────────────────┐    │
│  │ ☐ | סוג | מיקום | תחילה | סיום ...  │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  BulkDeletePanel (unchanged, at bottom)      │
└──────────────────────────────────────────────┘
```

---

## New Component: `AlgorithmInlinePanel`

**File:** `frontend/src/components/AlgorithmInlinePanel.tsx`

**Props:**
```ts
interface Props {
  selectedShiftIds: string[];
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
  onClose: () => void;
}
```

**Content (no shift picker — shifts are selected via the DataTable):**
- Selected count badge: *"X משמרות נבחרות"* (live, updates as user checks rows)
- Mode toggle: טיוטה / פרסום ישיר + `?` help modal button
- Collapsible solver settings (collapsed by default, same fields as AlgorithmRunForm)
- SubHierarchySelector (`<details>` element, same as AlgorithmRunForm)
- Error message (if submission fails)
- "הרץ שיבוץ אוטומטי" button — disabled when `selectedShiftIds.length === 0`
- Calls `submitJob({ shift_ids: selectedShiftIds, mode, settings })` on click, then `onJobSubmitted(resp.id)`

Extracted from `AlgorithmRunForm` — same logic, minus the date/shift-picker UI.

---

## Changes to `ShiftsContent`

**File:** `frontend/src/pages/ShiftsPage.tsx`

New props:
```ts
interface ShiftsContentProps {
  onJobSubmitted?: (jobId: string) => void;
}
```

New state:
- `selectedShiftIds: string[]` — which shifts have checkboxes checked
- `showAlgorithmPanel: boolean` — whether AlgorithmInlinePanel is expanded

Changes:
1. **"שיבוץ אוטומטי" button** — added to the section header row, right side, blue/prominent. Toggles `showAlgorithmPanel`.
2. **AlgorithmInlinePanel** — renders between the filter row and the DataTable when `showAlgorithmPanel` is true. On job submitted: calls `onJobSubmitted`, closes the panel, clears selected shift IDs.
3. **Checkbox column** — first column in the DataTable. Header cell contains a "select all" checkbox that checks/unchecks all rows currently visible after filtering. Each row's cell is a checkbox bound to `selectedShiftIds`.
4. `dutyTypes` is already loaded in `ShiftsContent` — passed straight to `AlgorithmInlinePanel`.

---

## Changes to `AlgorithmContent`

**File:** `frontend/src/pages/AlgorithmPage.tsx`

New prop:
```ts
interface AlgorithmContentProps {
  initialJobId?: string;
}
```

Behavior: if `initialJobId` is provided and differs from the current `selectedJobId`, set it. Use a `useEffect` on `initialJobId`.

No other changes. The "New Run" button in the job list panel is left in place (it opens the existing slide-in drawer — harmless, and useful for re-runs with overrides).

---

## Changes to `ShiftsManagementPage`

**File:** `frontend/src/pages/planning/ShiftsManagementPage.tsx`

New state:
- `runsOpen: boolean` — controls the "ריצות אלגוריתם" collapsible (starts closed)
- `latestJobId: string | null` — most recently submitted job

Sections rendered (top to bottom):
1. Templates collapsible — unchanged
2. Algorithm runs collapsible:
   - Header: "ריצות אלגוריתם" + chevron
   - Body: `<AlgorithmContent initialJobId={latestJobId} />`
   - `runsOpen` controls visibility
3. `<ShiftsContent onJobSubmitted={handleJobSubmitted} />`

`handleJobSubmitted(jobId)`:
```ts
setLatestJobId(jobId);
setRunsOpen(true);   // auto-open runs section
```

---

## Removing the Assignment Page

1. **`App.tsx`**: Remove the `/planning/assignment` route. Change existing redirects:
   - `/duty-management` → `/planning/shifts`
   - `/algorithm` → `/planning/shifts`
2. **`UnifiedNav.tsx`**: Remove the "שיבוץ" nav item (the one linking to `/planning/assignment`).
3. **`AssignmentPage.tsx`**: Delete the file.
4. **Note**: `DutyManagementContent` (manual drag-and-drop assignment tab) is removed with this page and has no replacement. This is intentional.

---

## What is NOT changed

- `AlgorithmRunForm` — kept as-is for the re-run drawer inside `AlgorithmContent`
- `AlgorithmJobTabs`, `AlgorithmJobTabs` sub-components — unchanged
- `BulkDeletePanel` — unchanged, stays at the bottom of the shifts section
- `/planning/shifts` URL — unchanged
- Backend — no changes required

---

## Testing Checklist

- [ ] Checkboxes in shifts DataTable select/deselect rows; header checkbox selects all filtered rows
- [ ] "שיבוץ אוטומטי" button toggles the inline panel
- [ ] Run button disabled when 0 shifts selected; shows correct count
- [ ] Submitting a job closes the panel, opens "ריצות אלגוריתם" section, auto-selects the new job
- [ ] Algorithm runs section polls and updates in real time
- [ ] `/planning/assignment` redirects to `/planning/shifts`
- [ ] "שיבוץ" nav item is gone
- [ ] Re-run from within the job detail still works (opens existing drawer)
