# Calendar 3-Day View + Min Column Width Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "3 days" view option and a minimum per-day-column width (with horizontal scroll) to the two FullCalendar-based calendars in the app (`UnitCalendar.tsx`, `DutyCalendarWidget.tsx`), so the grid stays readable at narrow widths.

**Architecture:** A shared pure helper computes `{ minWidthPx, dayCount }` for a given FullCalendar view type (`dayGridMonth` / `timeGridWeek` / `timeGridThreeDay`). Both calendar components register a custom `timeGridThreeDay` view (duration 3 days), track the active view type in state via their existing `datesSet` callback, and apply the helper's `minWidthPx` as an inline style on a wrapper `div` around `<FullCalendar>` that sits inside an `overflow-x: auto` container.

**Tech Stack:** React, TypeScript, `@fullcalendar/react` + `@fullcalendar/timegrid`, Tailwind CSS, vitest.

## Global Constraints

- Per-day-column min width: **130px**.
- Fixed time-axis gutter allowance added to the min width for time-grid views: **60px**.
- Time-grid views affected: `timeGridWeek` (7 columns), `timeGridThreeDay` (3 columns, new).
- `dayGridMonth` is unaffected (helper returns `undefined` — no min-width constraint).
- New 3-day view button label (Hebrew): `"3 ימים"`.
- `UnitCalendar.tsx` button label comes from i18n key `unit_calendar.view_3day` in `frontend/src/i18n/he.json`.
- `DutyCalendarWidget.tsx` has no i18n plumbing for calendar button text today; give its new view a hardcoded Hebrew `text: "3 ימים"`, consistent with that file having no `buttonText` override at all currently.
- No changes to event data, fetching logic, month view, `ShiftDetailPanel`, or filter chips.

---

### Task 1: Shared min-width helper + unit tests

**Files:**
- Create: `frontend/src/utils/calendarViewWidth.ts`
- Test: `frontend/src/utils/calendarViewWidth.test.ts`

**Interfaces:**
- Produces: `calendarViewMinWidth(viewType: string): number | undefined` — exported function. Returns `undefined` for `"dayGridMonth"` (and any unrecognized view type), and a pixel number for `"timeGridWeek"` / `"timeGridThreeDay"`.
- Produces: `CALENDAR_VIEW_DAY_COUNTS: Record<string, number>` — exported const map `{ timeGridWeek: 7, timeGridThreeDay: 3 }`, used by Task 2/3 to know how many columns each time-grid view has (not required by the helper's own logic, but kept alongside it so both components reference one source of truth instead of re-hardcoding 7/3).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/utils/calendarViewWidth.test.ts
import { describe, expect, it } from "vitest";
import { calendarViewMinWidth, CALENDAR_VIEW_DAY_COUNTS } from "./calendarViewWidth";

describe("calendarViewMinWidth", () => {
  it("returns undefined for month view (no min-width constraint)", () => {
    expect(calendarViewMinWidth("dayGridMonth")).toBeUndefined();
  });

  it("returns undefined for an unrecognized view type", () => {
    expect(calendarViewMinWidth("listWeek")).toBeUndefined();
  });

  it("computes 7 columns * 130px + 60px gutter for the week view", () => {
    expect(calendarViewMinWidth("timeGridWeek")).toBe(970);
  });

  it("computes 3 columns * 130px + 60px gutter for the 3-day view", () => {
    expect(calendarViewMinWidth("timeGridThreeDay")).toBe(450);
  });
});

describe("CALENDAR_VIEW_DAY_COUNTS", () => {
  it("has 7 days for the week view and 3 for the 3-day view", () => {
    expect(CALENDAR_VIEW_DAY_COUNTS.timeGridWeek).toBe(7);
    expect(CALENDAR_VIEW_DAY_COUNTS.timeGridThreeDay).toBe(3);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/utils/calendarViewWidth.test.ts`
Expected: FAIL — `Cannot find module './calendarViewWidth'` (file doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/src/utils/calendarViewWidth.ts
const DAY_COLUMN_MIN_PX = 130;
const TIME_AXIS_GUTTER_PX = 60;

export const CALENDAR_VIEW_DAY_COUNTS: Record<string, number> = {
  timeGridWeek: 7,
  timeGridThreeDay: 3,
};

export function calendarViewMinWidth(viewType: string): number | undefined {
  const dayCount = CALENDAR_VIEW_DAY_COUNTS[viewType];
  if (!dayCount) return undefined;
  return dayCount * DAY_COLUMN_MIN_PX + TIME_AXIS_GUTTER_PX;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/utils/calendarViewWidth.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/calendarViewWidth.ts frontend/src/utils/calendarViewWidth.test.ts
git commit -m "feat: add calendar view min-width helper"
```

---

### Task 2: Wire 3-day view + min-width scroll into UnitCalendar

**Files:**
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Modify: `frontend/src/i18n/he.json:335` (insert new key after `view_week`)

**Interfaces:**
- Consumes: `calendarViewMinWidth` from `frontend/src/utils/calendarViewWidth.ts` (Task 1).
- Consumes: existing `handleDatesSet(arg: DatesSetArg)` in this file (`UnitCalendar.tsx:52`) — extend it, don't replace its signature.

- [ ] **Step 1: Add the i18n key**

In `frontend/src/i18n/he.json`, right after line 335 (`"view_week": "שבוע",`), add:

```json
    "view_3day": "3 ימים",
```

So the block reads:

```json
  "unit_calendar": {
    "title": "יומן יחידה",
    "today": "היום",
    "view_month": "חודש",
    "view_week": "שבוע",
    "view_3day": "3 ימים",
    "soldier": "חייל",
```

- [ ] **Step 2: Add view-type state and extend `handleDatesSet`**

In `frontend/src/components/UnitCalendar.tsx`, add the import (alongside the existing imports at the top):

```typescript
import { calendarViewMinWidth } from "../utils/calendarViewWidth";
```

Add state near the other `useState` calls (after `dutyTypeFilter`, around line 24):

```typescript
  const [activeViewType, setActiveViewType] = useState("dayGridMonth");
```

Extend `handleDatesSet` (currently at `UnitCalendar.tsx:52-59`) to also record the view type:

```typescript
  function handleDatesSet(arg: DatesSetArg) {
    setActiveViewType(arg.view.type);
    const from = arg.start.toISOString().slice(0, 10);
    const to = arg.end.toISOString().slice(0, 10);
    const prev = dateRangeRef.current;
    if (prev && prev.from === from && prev.to === to) return;
    dateRangeRef.current = { from, to };
    fetchData(from, to);
  }
```

- [ ] **Step 3: Register the `timeGridThreeDay` view and add it to the toolbar**

In the `<FullCalendar>` JSX (currently `UnitCalendar.tsx:146-189`), make these edits:

Change `headerToolbar`:
```typescript
          headerToolbar={{ left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,timeGridThreeDay" }}
```

Change `buttonText`:
```typescript
          buttonText={{
            today: t("unit_calendar.today") || "היום",
            month: t("unit_calendar.view_month") || "חודש",
            week: t("unit_calendar.view_week") || "שבוע",
            timeGridThreeDay: t("unit_calendar.view_3day") || "3 ימים",
          }}
```

Change `views`:
```typescript
          views={{
            dayGridMonth: { displayEventTime: false },
            timeGridWeek: { displayEventTime: true },
            timeGridThreeDay: { type: "timeGrid", duration: { days: 3 }, displayEventTime: true },
          }}
```

- [ ] **Step 4: Wrap the calendar in a scrollable min-width container**

Replace the outer calendar wrapper div (currently `UnitCalendar.tsx:145`, `<div data-testid="fullcalendar" className="text-sm">`) so the scroll container and the width-constrained inner div are separate:

```typescript
      <div className="overflow-x-auto">
        <div
          data-testid="fullcalendar"
          className="text-sm"
          style={{ minWidth: calendarViewMinWidth(activeViewType) }}
        >
          <FullCalendar
            ...
          />
        </div>
      </div>
```

(Keep everything inside `<FullCalendar ... />` exactly as it was — only the two wrapping `div`s and the closing tags change.)

- [ ] **Step 5: Typecheck and lint**

Run (from `frontend/`): `npm run typecheck && npm run lint`
Expected: both pass with no errors/warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/UnitCalendar.tsx frontend/src/i18n/he.json
git commit -m "feat: add 3-day view and min column width to unit calendar"
```

---

### Task 3: Wire 3-day view + min-width scroll into DutyCalendarWidget

**Files:**
- Modify: `frontend/src/components/dashboard/DutyCalendarWidget.tsx`

**Interfaces:**
- Consumes: `calendarViewMinWidth` from `frontend/src/utils/calendarViewWidth.ts` (Task 1).

- [ ] **Step 1: Add imports and view-type state**

In `frontend/src/components/dashboard/DutyCalendarWidget.tsx`, add to the imports:

```typescript
import { calendarViewMinWidth } from "../../utils/calendarViewWidth";
```

`DatesSetArg` isn't imported in this file today — add it:

```typescript
import type { DatesSetArg } from "@fullcalendar/core";
```

Add state near the existing `const [holidays, setHolidays] = useState<Holiday[]>([]);` (line 17):

```typescript
  const [activeViewType, setActiveViewType] = useState("dayGridMonth");
```

- [ ] **Step 2: Add a `datesSet` handler**

Add this function above the `return` statement (this file has no existing `datesSet` handler, unlike `UnitCalendar.tsx`):

```typescript
  function handleDatesSet(arg: DatesSetArg) {
    setActiveViewType(arg.view.type);
  }
```

- [ ] **Step 3: Register the `timeGridThreeDay` view and add it to the toolbar**

In the `<FullCalendar>` JSX (currently `DutyCalendarWidget.tsx:74-97`):

Change `headerToolbar`:
```typescript
        headerToolbar={{ start: "prev,next", center: "title", end: "dayGridMonth,timeGridWeek,timeGridThreeDay" }}
```

Add `datesSet` prop (this file has no `datesSet` prop today — add it near `headerToolbar`):
```typescript
        datesSet={handleDatesSet}
```

Change `views`:
```typescript
        views={{
          dayGridMonth: { displayEventTime: false },
          timeGridWeek: { displayEventTime: true },
          timeGridThreeDay: { type: "timeGrid", duration: { days: 3 }, displayEventTime: true, buttonText: "3 ימים" },
        }}
```

(`buttonText` set per-view here, since this file has no top-level `buttonText` prop to extend.)

- [ ] **Step 4: Wrap the calendar in a scrollable min-width container**

The `<FullCalendar>` currently sits directly inside the `<section>` (`DutyCalendarWidget.tsx:74`). Wrap it:

```typescript
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">היומן שלי</h2>
      <div className="overflow-x-auto">
        <div style={{ minWidth: calendarViewMinWidth(activeViewType) }}>
          <FullCalendar
            ...
          />
        </div>
      </div>
    </section>
```

(Keep everything inside `<FullCalendar ... />` exactly as it was — only the two wrapping `div`s and the closing tags change.)

- [ ] **Step 5: Typecheck and lint**

Run (from `frontend/`): `npm run typecheck && npm run lint`
Expected: both pass with no errors/warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/DutyCalendarWidget.tsx
git commit -m "feat: add 3-day view and min column width to dashboard duty widget"
```

---

### Task 4: Manual browser verification

**Files:** none (verification only, no code changes expected)

- [ ] **Step 1: Start the dev stack**

Run: `.\dev.ps1` from the repo root (per `CLAUDE.md`), wait for `[frontend]` to report the Vite server is up on `http://localhost:5173`.

- [ ] **Step 2: Verify UnitCalendar**

Navigate to a unit page containing the calendar. Confirm:
- Toolbar shows three view buttons: month / week / "3 ימים".
- Clicking "3 ימים" shows a 3-day grid and fetches data for that 3-day range (check network tab or that shifts render correctly for the visible days).
- Resize the browser/container narrow (e.g. via `preview_resize` to a narrow width) while in week or 3-day view: the day columns keep their width and a horizontal scrollbar appears instead of the columns shrinking unreadably.
- Switch to month view: no horizontal scrollbar appears, month grid still fills the container as before.

- [ ] **Step 3: Verify DutyCalendarWidget**

Navigate to the dashboard page showing "היומן שלי". Repeat the same checks: 3-day button present and working, narrow-width scroll behavior on week/3-day, month view unaffected.

- [ ] **Step 4: Run the frontend unit test suite**

Run (from `frontend/`): `npm test`
Expected: all tests pass, including the new `calendarViewWidth.test.ts` from Task 1.
