# Calendar: 3-day view + min day-column width

## Problem

The FullCalendar week view (`timeGridWeek`) in `UnitCalendar.tsx` (unit page) and
`DutyCalendarWidget.tsx` (dashboard widget) squeezes 7 day columns into
whatever width the container has. On narrow containers this makes event
content (duty type, location, soldier/reserve counts) unreadable.

## Design

Applies identically to both `frontend/src/components/UnitCalendar.tsx` and
`frontend/src/components/dashboard/DutyCalendarWidget.tsx`.

### 1. New 3-day view

Register a custom FullCalendar view `timeGridThreeDay` with
`duration: { days: 3 }`, added to `views`. Add it to `headerToolbar`'s right
group alongside the existing `dayGridMonth,timeGridWeek`:
`dayGridMonth,timeGridWeek,timeGridThreeDay`.

Button label: `"3 ימים"`.
- `UnitCalendar.tsx` already threads button labels through i18n
  (`unit_calendar.view_month`, `unit_calendar.view_week`) — add
  `unit_calendar.view_3day: "3 ימים"` to `he.json` and wire it the same way.
- `DutyCalendarWidget.tsx` has no i18n plumbing for its calendar today
  (labels come from FullCalendar's `heLocale` defaults); give the new view a
  hardcoded Hebrew `text` label the same way `heLocale` would, consistent
  with how that widget currently has no custom `buttonText` at all.

Switching views/navigating already triggers FullCalendar's normal
range-change flow, which `UnitCalendar.tsx` handles via `datesSet` → refetch.
No API changes needed — a 3-day range is just a narrower `date_from`/`date_to`.

### 2. Min width per day column

Only time-grid views (`timeGridWeek`, `timeGridThreeDay`) get a minimum
column width; `dayGridMonth` is left as-is (not part of this complaint, and
month cells already wrap fine).

- Wrap the `<FullCalendar>` element in a container with `overflow-x: auto`.
- Track the current view via the existing `datesSet` callback (both files
  already have one, or gain one) — read `arg.view.type` and the view's
  column count (`arg.view.currentStart`/`currentEnd` span, or simpler:
  hardcode 7 for `timeGridWeek` and 3 for `timeGridThreeDay` since those are
  the only two time-grid views registered).
- Store `{ minWidthPx }` in component state: `numColumns * 130 + 60` (130px
  per day column, 60px fixed allowance for the time-axis gutter) for
  time-grid views, `undefined` (no constraint) for month view.
- Apply that as an inline `style={{ minWidth }}` on the wrapper div holding
  `<FullCalendar>`. The outer `overflow-x: auto` container stays full-width;
  when `minWidth` exceeds the container's actual width, the grid scrolls
  horizontally and the header toolbar (title/nav/view buttons), which lives
  outside the scrolling div, stays fully visible and unscrolled.

130px per column is chosen so the existing two-line event content (title row
+ counts row) fits without truncation for typical duty-type name lengths
seen in this app; easy to tune later as a single constant.

### Non-goals

- No changes to event data, fetching, or the month view.
- No changes to `ShiftDetailPanel` or filter chips.
- Not adding a day view (`timeGridDay`) — only 3-day, per request.
