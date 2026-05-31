# Shift-Based Unit Calendar & Reserve Dismissal UI — Design

**Date:** 2026-05-31
**Status:** Draft

---

## 1. Purpose

The Unit Calendar currently shows individual soldier assignments as FullCalendar events.
This spec redesigns it to show **shifts** as events, with all assignees (primary + reserve)
listed inside each event. Clicking a shift opens a detail panel where the Duty Manager can
dismiss primaries with a visual day-range picker, auto-call-up the linked reserve, and
relink to a different reserve if needed.

---

## 2. Backend: New endpoint `GET /api/calendar/shifts`

### 2.1 Route

```
GET /calendar/shifts?node_id=<uuid>&date_from=<date>&date_to=<date>
```

Auth: `HIERARCHY_READ` on the target node (same as existing `/calendar/unit`).

### 2.2 Response model

```python
class CalendarShiftAssignee(BaseModel):
    soldier_id: uuid.UUID
    soldier_name: str
    hierarchy_label: str | None          # "parent / leaf"
    is_reserve: bool
    # Primary-only fields:
    dismissals: list[DismissalRecord]
    reserve_assignment_id: uuid.UUID | None
    reserve_hierarchy_distance: int | None
    # Reserve-only fields:
    called_up_from: date | None
    called_up_to: date | None
    primary_assignment_ids: list[uuid.UUID]

class CalendarShiftOut(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_type_color: str
    duty_location_name: str
    start_date: date
    end_date: date
    required_count: int
    assigned_count: int
    fill_status: str
    reserve_count: int
    assignees: list[CalendarShiftAssignee]

class CalendarShiftResponse(BaseModel):
    shifts: list[CalendarShiftOut]
```

### 2.3 Service logic

1. Resolve hierarchy subtree from `node_id` (same as existing `/calendar/unit`)
2. Collect soldier IDs in that subtree
3. Query all `DutyShift` overlapping `[date_from, date_to]` where the duty type's
   soldiers have at least one assignment under the subtree
4. For each shift, load `DutyAssignment` rows with `duty_shift_id = shift.id` AND
   `soldier_id IN (subtree soldier ids)` AND `status IN ('published', 'algorithm_draft')`
5. Join `DutyReserveLink` + `DutyDismissal` in bulk for all returned assignment IDs
6. Group by shift; build assignee lists split by `is_reserve`

### 2.4 Edge cases

- Shift with no assignees under this node → excluded from response (no event to show)
- Shift where all assignees under node are reserves only → shown, reserve badge on event
- Deleted assignments (cancelled) → filtered by status, not included

---

## 3. Backend: Reserve relink endpoint

### 3.1 Route

```
PUT /shifts/{shift_id}/duty-assignments/{primary_id}/reserve-link
Body: { reserve_assignment_id: uuid.UUID }
```

Auth: `ASSIGNMENT_MANAGE`.

### 3.2 Service logic

1. Load existing `DutyReserveLink` for this primary; delete if exists
2. Load the reserve `DutyAssignment` to get its soldier ID
3. Compute `hierarchy_distance` between primary's soldier node and reserve's soldier node
4. Create new `DutyReserveLink(reserve_assignment_id, primary_assignment_id, hierarchy_distance)`
5. Audit trail: `action="reserve.relink"`

### 3.3 Edge cases

- Primary already has dismissals against old reserve → dismissals stay on the primary
  (they record that the primary is released, not which reserve covers). The new reserve
  should be called-up separately.
- Reserve not found or not `is_reserve` → 400 error

---

## 4. Frontend: UnitCalendar event display

### 4.1 Data loading

- Replace `getUnitCalendar()` call with `getCalendarShifts(nodeId, from, to)` from new API
- Remove `fetchTree()` import for leaf labels (backend returns `hierarchy_label` directly)

### 4.2 FullCalendar events

One event per `CalendarShiftOut`. `eventContent` renders:

```
┌─────────────────────┐
│ שמירה — מוצב 7       │  ← duty_type_name — location
│ 3 חיילים | 2 רזרבות   │  ← counts scoped to current node
└─────────────────────┘
```

- `backgroundColor` / `borderColor` = `duty_type_color`
- Reserves badge in different shade (`bg-purple-100` ring) when reserve_count > 0

### 4.3 Click handling

`handleEventClick` sets `selectedShift` state to the full `CalendarShiftOut` object,
opening the detail panel overlay. The old bottom detail table (`[data-testid="calendar-detail"]`)
and the manual shift-ID input are removed.

### 4.4 Filter chips

Stay unchanged — duty type filter applied client-side over shifts.

---

## 5. Frontend: ShiftDetailPanel (replaces ShiftReservePanel)

### 5.1 Layout (modal overlay)

```
┌──────────────────────────────────────┐
│ ✕  שמירה — מוצב 7    1/6–3/6         │  ← header
├──────────────────────────────────────┤
│  חיילים ראשיים (3)                   │
│                                      │
│  יוסי כהן  ──  דני לוי (ר)  [שחרור]  │
│  [משוחרר 2/6–3/6]                    │  ← if has dismissal
│  ─────────────────────────           │
│  רון ישראלי  ──  דני לוי (ר)  [שחרור]  │
│                                      │
├──────────────────────────────────────┤
│  רזרבות (2)                          │
│                                      │
│  דני לוי (הוקפץ: 2/6–3/6)           │
│    ← מכסה: יוסי כהן, רון ישראלי      │
│  ─────────────────────────           │
│  מיכאל אברהם (המתנה)                 │
│    ← מכסה: —                         │
└──────────────────────────────────────┘
```

- Soldier name links to the linked reserve/primary by name (not UUID)
- "שחרור" button on each primary → opens DismissalModal
- **Relink** UX: when a primary has no linked reserve, or the user wants to change,
  a dropdown selects from the shift's reserves and calls the relink endpoint

### 5.2 Data source

The panel loads its data from the calendar endpoint response (already in memory when
the user clicks an event). No additional API call needed — the `CalendarShiftOut.assignees`
list contains all primary + reserve data, dismissals, links, and soldier names.

When the user dismisses a primary and the panel needs to refresh after the action,
it calls the calendar endpoint again for that shift's date range.

---

## 6. Frontend: DismissalModal

### 6.1 Trigger

"שחרור" button on a primary row in ShiftDetailPanel.

### 6.2 Layout

```
┌──────────────────────────────────────┐
│  שחרור — יוסי כהן                     │
│  תורנות: 1/6–6/6                     │
│                                      │
│  ┌──────[===███▓▓▓▓▓▓▓▓▓███===]──────┐ │
│  │  1/6   2/6   3/6   4/6   5/6   6/6 │ │
│  │            ╰── 2/6 – 4/6 ──╯       │ │
│  └────────────────────────────────────┘ │
│         [from: 2/6]    [to: 4/6]       │
│                                      │
│  רזרבה מכסה: [דני לוי ▼]             │  ← dropdown, auto-selected
│                                      │
│  סיבה: [___________________________] │
│                                      │
│           [ביטול]    [אשר שחרור]       │
└──────────────────────────────────────┘
```

### 6.3 Range slider

Custom component `DismissalRangeSlider`:

- Horizontal track representing the primary's full assignment span (`start_date` → `end_date`)
- Two draggable handles (from = left, to = right)
- Days outside the assignment range are grey/non-interactive
- Handle positions map to discrete dates (one step = one day)
- Selected range between handles is highlighted (amber fill)
- Live labels below: `from: YYYY-MM-DD` / `to: YYYY-MM-DD`

**Implementation approach:** Two `<input type="range">` elements overlaid on a single
CSS track. The left handle drives `from_date` (min = start_date, max = to_date), the right
handle drives `to_date` (min = from_date, max = end_date). Styling uses CSS custom properties
to position the fill between handles. Both handle values update each other's constraints via
`useState` + `onChange`.

### 6.4 Reserve selector

`<select>` dropdown listing all reserves for this shift. Auto-selected to the one
currently linked via `reserve_assignment_id`. If none linked (unlikely), first reserve.

### 6.5 Submit flow

On "אשר שחרור", the frontend calls a single backend endpoint:

`POST /shifts/{shift_id}/dismissals`
Body:
```json
{
  "primary_assignment_id": "uuid",
  "from_date": "2026-06-02",
  "to_date": "2026-06-04",
  "covering_reserve_assignment_id": "uuid",
  "reason": "optional"
}
```

The backend does all of the following in one transaction:

1. **Dismiss** the primary — create `DutyDismissal` record
2. **Call up** the covering reserve — set `called_up_from` / `called_up_to`
3. **Relink** the dismissed primary's link to the covering reserve (if changed)
4. **Reallocate orphaned primaries** — find any OTHER primaries on this shift that were linked to the called-up reserve. For each such orphaned primary whose assignment overlaps the call-up date range, find the closest available reserve (by hierarchy distance) and relink them. Available = reserve on the same shift, not the one being called up, and not themselves called up during the overlapping period.

Response:
```json
{
  "dismissal_id": "uuid",
  "covering_reserve": { "assignment_id": "uuid", "called_up_from": "...", "called_up_to": "..." },
  "reallocations": [
    { "primary_assignment_id": "uuid",
      "old_reserve_assignment_id": "uuid",
      "new_reserve_assignment_id": "uuid",
      "hierarchy_distance": 2 }
  ]
}
```

The UI shows a loading spinner during the flow. On completion, the panel refreshes.

### 6.6 Reallocation logic

When a reserve R1 is called up for dates D1–D4 (because the linked primary P1 was dismissed for those dates):

1. Find all `DutyReserveLink` rows where `reserve_assignment_id = R1.id`
2. For each such link (pointing to primary Px), check if Px's assignment overlaps D1–D4
3. For each overlapping primary Px:
   a. Collect all reserve assignments on the same shift that are **available**:
      - Not R1 (already called up)
      - Not themselves called up during the overlapping period
   b. Compute hierarchy distance from Px's soldier node to each available reserve's soldier node
   c. Pick the closest reserve (minimum distance); link Px to that reserve
4. Log each reallocation in the response for UI display

If no available reserve exists for an orphaned primary, a warning is returned (the primary has no reserve coverage for those days).

### 6.7 Edge cases

- Primary already has overlapping dismissal → 400 from server
- Reserve is already called-up for different dates → server replaces range, OK
- Called-up reserve has no other linked primaries → no reallocations needed
- No available reserve for an orphaned primary → warning, primary has no reserve coverage
- User dismisses entire shift (from=D1, to=Dn) → full dismissal

---

## 7. Frontend: File changes

| File | Change |
|---|---|
| `src/api/calendar.ts` | Add `getCalendarShifts()`, types `CalendarShiftOut`, `CalendarShiftAssignee` |
| `src/api/reserves.ts` | Add `relinkReserve()` call |
| `src/components/UnitCalendar.tsx` | Rewrite to shift-based events, remove old detail section + shift-ID input |
| `src/components/ShiftReservePanel.tsx` | Replace with richer `ShiftDetailPanel` |
| `src/components/ShiftDetailPanel.tsx` | New file (was ShiftReservePanel, enhanced) |
| `src/components/DismissalModal.tsx` | New file — range slider + reserve selector |
| `src/i18n/he.json` | Add keys for new UI strings |

---

## 8. Testing

### 8.1 Backend

- `test_calendar_shifts_endpoint`: verify response shape, hierarchy filtering
- `test_calendar_shifts_no_assignees`: shift with no soldiers under node omitted
- `test_relink_reserve`: verify old link deleted, new link created with correct distance
- `test_relink_not_a_reserve`: 400 on non-reserve assignment

### 8.2 Frontend

- UnitCalendar renders shift events correctly with counts
- Clicking shift event opens ShiftDetailPanel
- Dismissal range slider initializes to full assignment span
- Submit flow calls single dismiss+reallocate endpoint
- Error state when dismiss fails (overlapping)
