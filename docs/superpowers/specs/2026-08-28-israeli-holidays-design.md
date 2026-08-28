# Israeli Holidays in the Calendar — Design

## Summary

Surface Israeli holidays throughout the scheduling UI:
- Personal-constraint requests and their commander/duty-manager approvals show which holidays a requested date range crosses.
- Duty shift detail modals (admin and soldier-facing) show which holidays a shift crosses.
- The unit calendar shades holiday day cells with a distinct background.
- The shared date-input component gains an in-app calendar-grid popup (replacing the native OS date picker), with optional holiday shading for constraint/exemption date fields.

All holiday information is informational — it never blocks submission or approval. On approval screens it is flagged with an amber badge to prompt closer review, per the maintainer's decision.

## Background

The backend already exposes `GET /calendar/holidays?year=` (`backend/app/routes/calendar_holidays.py`), backed by the `holidays` PyPI package's IL calendar (`hol.country_holidays("IL", years=year)`), returning `[{date, name}]` for the full civil+religious IL holiday set. A typed frontend client exists (`frontend/src/api/calendarHolidays.ts`, `listHolidays(year)`) but is not consumed anywhere. This feature wires that existing data source into the UI and adds the crossing-detection logic needed to relate it to constraint/shift date ranges.

The full IL holiday set (unfiltered) is used as-is — no curation to a "major holidays" subset.

## Data model note: inclusive vs. exclusive date ranges

This is the trickiest invariant in the codebase and must be respected by any shared crossing-detection helper:

- `PersonalConstraint.start_date` / `end_date` (`backend/app/db/models.py:670-689`) are **both inclusive**.
- `DutyShift.start_date` / `end_date` (`backend/app/db/models.py:434-472`) has an **exclusive** `end_date` (the first day NOT worked).

The crossing helper must take an explicit inclusive/exclusive-end flag (mirroring the existing split between `lastDutyDay`/`toExclusiveEndDate` in `frontend/src/utils/formatDate.ts`), or expose two call-sites, so callers cannot accidentally mix the two.

## Backend changes

### New shared helper

Add `backend/app/services/holidays.py` (name indicative) with a function such as:

```python
def holidays_in_range(start: date, end: date, *, end_inclusive: bool) -> list[HolidayHit]
```

`HolidayHit` is `{date: date, name: str}`. Implementation calls into the same `holidays` package data already used by `calendar_holidays.py` (extract that into a shared lookup so both the route and this helper stay in sync), spanning however many calendar years the range touches (a request crossing a year boundary must still work).

### Schema changes

- `ConstraintOut` (`backend/app/routes/constraints.py`) gains `crossed_holidays: list[HolidayHit]`, computed via the helper with `end_inclusive=True`. Populated on submit response, the pending-approvals list, and constraint detail reads.
- The duty shift read schema (wherever shifts are serialized for `ShiftDetailPanel`/`DutyDetailModal` consumption) gains the same field, computed with `end_inclusive=False`.

No new DB columns — this is computed at read time, not stored, since the holiday calendar itself doesn't change per-request.

## Frontend changes

### 1. Personal constraints — submit (`MyRequestsPage.tsx`)

When the submit response's `crossed_holidays` is non-empty, show an amber inline note under the date fields listing the holiday names (new i18n string, interpolated list). Purely informational, never blocks the already-submitted request (this is post-submit feedback, not a pre-submit gate).

### 2. Personal constraints — approval (`ApprovalsPage.tsx`)

Constraint cards (`ApprovalsPage.tsx:567-576`, alongside the existing `DaysBadge`) render an amber badge listing crossed holiday names when `crossed_holidays` is non-empty. Same visual family as the existing warning/info badges (`ShiftDetailPanel.tsx` badge pattern) but amber, to read as "worth a closer look" without implying an error. Approve/reject remain fully functional regardless.

### 3. Duty shift modals

Both `ShiftDetailPanel.tsx` and `DutyDetailModal.tsx` render the same amber crossed-holiday badge/list when the shift's `crossed_holidays` is non-empty, using the badge conventions already established there (`data-testid`, `title`/`aria-label` via i18n).

### 4. Calendar day-cell shading (`UnitCalendar.tsx`)

- Fetch holidays for the visible year(s) via `listHolidays` (existing client, finally consumed) — fetch both the current and adjacent years if the visible range can span a year boundary (e.g. December/January views).
- Add FullCalendar's `dayCellClassNames` prop to tint holiday day cells with a distinct background (soft violet/lavender — chosen to be visually distinct from the existing red/blue/amber event badges so the two signals don't blend).
- `UnitCalendar` is shared by `HomePage.tsx`, `UnitCalendarPage.tsx`, and `CommandDashboardPage.tsx`, so all three get this automatically.

### 5. Replace `DateInput`'s native popup with an in-app grid

- `DateInput.tsx` currently pairs a custom text field with a hidden native `<input type="date">` used only to trigger the OS date-picker popup (`DateInput.tsx:246-255`). Replace that popup with an in-app calendar grid built on the already-installed-but-unused `react-calendar` package.
- This changes the popup UI for all current call sites of `DateInput` (constraint/exemption dates, birthdates, shift/template dates, settings, registration, etc. — 23 files at time of writing). The text-field-typing behavior and value contract of `DateInput` are unchanged; only the picker popup itself changes.
- Add a new optional prop `showHolidays?: boolean` (default `false`) that shades holiday days in the grid the same way `UnitCalendar` does. Only `MyRequestsPage.tsx` (constraint + exemption date fields) and `ExemptionsPanel.tsx` pass `true`. All other call sites keep the plain (unshaded) grid.
- This is the largest-blast-radius change in this design — it touches the shared date-input primitive used across the app — but was chosen deliberately for one consistent picker experience over keeping two different date-input UIs.

### i18n

Add a new scoped namespace (e.g. `holidays.crossed_note`, `holidays.badge_label`, `holidays.calendar_legend`) rather than nesting under an existing key. Grep `frontend/src/i18n/he.json` for any pre-existing `holidays` key before adding, given the known duplicate-key hazard in that file (see `unit_calendar` precedent — same key appears at top level as both a plain string and nested object under different parents).

## Testing

**Backend:**
- Unit tests for `holidays_in_range`: inclusive vs. exclusive end-date edge cases, ranges spanning a year boundary, ranges with zero/one/multiple holidays.
- Route/service tests asserting `crossed_holidays` appears correctly on constraint submit/list/detail responses and on duty shift read responses.

**Frontend:**
- `DateInput.test.tsx`: rewritten/extended to cover the new `react-calendar`-based grid popup (open/select/close behavior) in place of the native-input assertions it likely has today, plus a case for `showHolidays`.
- New or extended tests: `ApprovalsPage` renders the amber holiday badge for a constraint with `crossed_holidays`; `ShiftDetailPanel` and `DutyDetailModal` do the same for shifts; `UnitCalendar` applies the holiday day-cell class for known holiday dates.

## Out of scope

- No change to which holidays are included (full unfiltered IL set from the `holidays` package).
- No blocking/validation behavior tied to holidays anywhere.
- No new persisted data — holidays are computed at read time from the existing package, not stored per-request.
