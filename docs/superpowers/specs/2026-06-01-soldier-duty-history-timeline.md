# Soldier Duty History Timeline

**Date:** 2026-06-01
**Status:** Draft.
**Depends on:** existing soldier modal, assignments, exemptions, constraints, reserves infra.

## Goal

Add a "duty history" tab to the soldier modal showing a unified, filterable, timeline-sorted view of everything that has happened to a soldier: assignments (active & cancelled), reserve call-ups, dismissals, exemption requests, and personal constraint requests.

---

## 1. Backend: New aggregated endpoint

### 1.1 New route

```
GET /soldiers/{soldier_id}/duty-history
```

Response: `list[TimelineEventOut]`

### 1.2 Schema

```python
class TimelineEventOut(BaseModel):
    id: uuid.UUID
    event_type: str          # "assignment" | "cancellation" | "dismissal" | "call_up"
                             # | "exemption_request" | "personal_constraint"
    date: str                # ISO date — primary sort date
    end_date: str | None
    title: str               # human-readable, e.g. "תורנות שמירה במחנה 80"
    description: str | None  # extra detail (reason, notes, etc.)
    status: str | None       # "active" | "cancelled" | "pending" | "approved" | "rejected"
    metadata: dict           # keys: duty_type_name, location_name, reason,
                             #       exemption_type_name, decision_note,
                             #       created_by_name, duty_assignment_id
```

### 1.3 Data sources queried & merged

| Source | event_type | date field | status |
|---|---|---|---|
| `DutyAssignment` (all statuses) | `"assignment"` (if status != cancelled) / `"cancellation"` (if cancelled) | `start_date` | `status` |
| `DutyDismissal` → join through `DutyAssignment` | `"dismissal"` | `dismissed_from` | — |
| `DutyAssignment` where `called_up_from` is set | `"call_up"` | `called_up_from` | — |
| `ExemptionRequest` for this soldier | `"exemption_request"` | `start_date` | `status` |
| `PersonalConstraint` for this soldier | `"personal_constraint"` | `start_date` | `status` |

**Sorting:** descending by `date`, then `created_at` for same-date items.

### 1.4 Authorization

Same pattern as existing soldier-read endpoints: if the viewing user is not the soldier themselves, require `Action.SOLDIER_READ` authorization against the soldier's hierarchy node.

### 1.5 L10n

All `title` fields are assembled server-side in Hebrew from DB names (duty_type.name, duty_location.name, exemption_type.name). The frontend uses `t()` only for filter chip labels, status labels, and section headings.

Title templates (using metadata values):
- assignment: `"{duty_type_name} ב{location_name}"`
- cancellation: `"בוטלה: {duty_type_name} ב{location_name}"`
- call_up: `"הוקפץ לרזרבה: {duty_type_name}"`
- dismissal: `"שוחרר מתורנות {duty_type_name}"`
- exemption_request: `"בקשת פטור: {exemption_type_name}"`
- personal_constraint: `"בקשה אישית"` (reason goes in description)

---

## 2. Frontend: New duty history tab

### 2.1 Tab addition

Add `"duty_history"` to the `TABS` array in `UnifiedSoldierModal.tsx`.

### 2.2 New component: `DutyHistoryPanel`

Fetches `GET /soldiers/{id}/duty-history` on mount and when the tab becomes active.

**Filter chips** (horizontal bar below the tab selector):
- All (default)
- Assignments (type `"assignment"`)
- Cancellations (type `"cancellation"`)
- Call-ups (type `"call_up"`)
- Dismissals (type `"dismissal"`)
- Exemption Requests (type `"exemption_request"`)
- Personal Constraints (type `"personal_constraint"`)

**Timeline rendering:**
- Vertical timeline with left-border color per event type and a dot indicator
- Each card shows: date range (or single date), title, status badge with color coding
- Clicking/expanding a card shows description/reason details
- Pending items (constraints, exemption requests) show approve/reject buttons inline (same pattern as existing constraints tab)

**Empty state:** "No duty history events found" message.

### 2.3 Status badge colors

| status | color |
|---|---|
| active / approved | green |
| pending | yellow |
| cancelled / rejected | red |
| (no status) | gray |

### 2.4 i18n keys to add

```
duty_history.title          — "היסטוריית תורנויות"
duty_history.filter_all     — "הכל"
duty_history.filter_assignments  — "תורנויות"
duty_history.filter_cancellations — "ביטולים"
duty_history.filter_call_ups     — "הקפצות"
duty_history.filter_dismissals   — "שחרורים"
duty_history.filter_exemption_requests — "בקשות פטור"
duty_history.filter_constraints   — "בקשות אישיות"
duty_history.empty           — "אין אירועים להצגה"
duty_history.event_assignment     — "תורנות"
duty_history.event_cancellation   — "ביטול תורנות"
duty_history.event_call_up        — "הקפצת רזרבה"
duty_history.event_dismissal      — "שחרור מתורנות"
duty_history.event_exemption_request — "בקשת פטור"
duty_history.event_constraint     — "בקשה אישית"
```

### 2.5 Approve/reject for pending items

Already exists for constraints in the modal; extend the same pattern to exemption requests shown in duty history. Inline buttons appear only for admin/duty_manager/commander roles when the item has `status: "pending"`.

---

## 3. No new DB migrations

All data already exists in the database. The new endpoint is purely a query/aggregation layer.

---

## 4. Testing

- **Backend:** Unit test for the new service function; integration test for the new endpoint (valid data, empty result, authorization).
- **Frontend:** E2E test opening soldier modal, clicking duty history tab, verifying events appear and filters work.
