# Unit Calendar Design

- **Date:** 2026-05-29
- **Status:** Approved

## Overview

Replace the existing text-table `UnitCalendarPage` with a full-featured visual calendar showing all duty assignments across a selected hierarchy subtree. Multi-day duties span across days visually; single-day duties appear as event chips. A detail table below provides drill-down on click.

## Backend Changes

### Enriched `/api/calendar/unit` response

Add `duty_type_name`, `duty_location_name`, and `duty_type_color` to `CalAssignment` so the frontend can render events without extra lookups.

**File:** `backend/app/routes/calendar.py`

```python
class CalAssignment(BaseModel):
    assignment_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str          # NEW
    duty_type_color: str         # NEW — hex color from deterministic hash
    duty_location_id: uuid.UUID
    duty_location_name: str      # NEW
    start_date: date
    end_date: date
```

Color derivation: backend generates a hex color string. Hash the duty_type_id → HSL hue, fixed saturation/lightness (e.g., `hsl(${hash % 360}, 70%, 50%)` → convert to hex `#XXXXXX`). The frontend uses this as `backgroundColor` in FullCalendar event objects.

The `unit_calendar` endpoint already loads `HierarchyNode` and `Soldier` — add a join to `DutyType` and `DutyLocation` to resolve names.

## Frontend Changes

### Dependency

Add `@fullcalendar/react`, `@fullcalendar/daygrid`, `@fullcalendar/interaction` (FullCalendar v6).

### Component: `frontend/src/components/UnitCalendar.tsx`

New component encapsulating FullCalendar + detail table.

**Props:**
- `nodeId: string` — selected hierarchy node
- `locale?: 'he' | 'en'`

**Internal state:**
- `rows: CalRow[]` — fetched data
- `selectedDate: string | null` — clicked day (YYYY-MM-DD)
- `selectedEvent: CalAssignment | null` — clicked event
- `dutyTypeFilter: string | null` — filtered duty type id
- `loading: boolean`
- `error: string | null`

**Data flow:**

1. On mount / `nodeId` change / `datesSet` callback (fired by FullCalendar when the visible date range changes): fetch `GET /api/calendar/unit?node_id={nodeId}&date_from={monthStart}&date_to={monthEnd}`
2. Map response to FullCalendar events:
   - `{ id: assignment_id, title: duty_type_name, start: start_date, end: end_date + 1 day, backgroundColor: duty_type_color, extendedProps: { soldier_name, duty_type_id, duty_location_name, soldier_id, assignment_id } }`
3. Render FullCalendar `dayGridMonth` view with:
   - `dateClick` → set `selectedDate`, clear `selectedEvent`, populate detail table
   - `eventClick` → set `selectedEvent`, clear `selectedDate` filter, populate detail table
   - Custom `dayCellDidMount` for RTL styling if needed
4. Detail table below calendar:
   - **Default:** hint text "לחץ על יום או תורנות לפרטים"
   - **Day mode:** filter already-fetched `rows` client-side for duties active on `selectedDate` → table with soldier, duty type, location; optionally filtered by `dutyTypeFilter`
   - **Event mode:** show that single duty's soldier details + assignment info
   - Sorting: alphabetical by soldier name
5. Duty type filter: clicking a duty type chip in a day cell sets/clears `dutyTypeFilter`; clicking the chip again clears the filter

### Page: `frontend/src/pages/UnitCalendarPage.tsx`

Refactored to use `UnitCalendar` component:
- Hierarchy fetch + dropdown (existing)
- Renders `<UnitCalendar nodeId={selectedNodeId} />`
- Remove existing table rendering

### i18n: `frontend/src/i18n/he.json`

Add keys under `unit_calendar`:
- `detail_table` — "פירוט תורנויות"
- `click_hint` — "לחץ על יום או תורנות לפרטים"
- `week_summary` — "שבוע {{week}}: {{count}} תורנויות"
- `status` — "סטטוס"
- `soldier_info` — "פרטי חייל"
- `personal_number` — "מספר אישי"
- `duty_type_filter` — "סינון לפי סוג תורנות"
- `loading` — "טוען..."
- `error` — "שגיאה בטעינת היומן"

### Routing

No routing changes — `UnitCalendarPage` is already registered in `App.tsx` at the `/unit-calendar` route.

## Testing

### E2E (Playwright)

Update `frontend/tests/e2e/seed_views.spec.ts` to cover the new calendar:
- Navigate to `/unit-calendar`
- Select hierarchy node from dropdown
- Verify FullCalendar renders (check for `.fc-dayGridMonth-view`)
- Click a day → verify detail table appears with duty rows
- Verify multi-day duties render as events in calendar
- Click an event → verify single-event detail
- Verify hierarchy node change refetches data

### Manual verification

- Calendar renders with correct Hebrew day names
- Event colors vary by duty type
- Multi-day duties span across day cells
- Single-day duties render as chips within the day cell
- Detail table populates correctly on click
- Filter by duty type works
- Month navigation refetches data
- Loading/error states display correctly
