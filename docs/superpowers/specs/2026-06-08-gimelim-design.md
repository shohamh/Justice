# גימלים (Medical Leave) — Design Spec
**Date:** 2026-06-08  
**Status:** Approved  

---

## Overview

Gimelim (גימלים) is a medical-leave flow that prevents soldiers from faking illness to escape duty. When a primary soldier is released on medical grounds, their reserve covers the current shift **and** the system automatically rolls the medical-leave soldier into the next eligible future duty of the same type — replacing a chosen primary who is demoted to reserve. This makes gaming the system self-defeating: taking gimelim guarantees you come back sooner.

The feature is gated behind a system setting (`gimalim.enabled`, on by default) and uses a two-step preview → commit flow so commanders see the full impact before confirming.

---

## System Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `gimalim.enabled` | boolean | true | Master toggle. When off, the גימלים button is hidden everywhere. |
| `gimalim.default_rest_days` | number | 7 | Minimum rest days between end of current shift and start of reassigned future shift. Overridable per-action in the form. |
| `gimalim.reserve_fate` | `"keep"` / `"release"` | `"keep"` | What happens to B (the called-up reserve) after covering the current shift. `"keep"` = B remains as a general reserve on the shift. `"release"` = B's reserve assignment is deleted after call-up. |

These appear in `SystemSettingsPage.tsx` under a new **"גימלים"** group.

---

## Data Model

No new tables are needed. One new column on an existing table:

### `duty_dismissals.is_gimelim` (boolean, default false)
Flags that a dismissal was triggered by medical leave. Used for reporting, audit filtering, and to distinguish gimelim dismissals from regular dismissals in the UI.

All other data (dismissal records, reserve call-up, future assignment demotion/promotion) is handled by existing models: `duty_dismissals`, `duty_assignments`, `duty_reserve_link`.

---

## API — Two New Endpoints

### `POST /shifts/{shift_id}/gimelim/preview`

**Auth:** Admin or commander in scope of the primary soldier.  
**Purpose:** Dry-run. Computes the full gimelim proposal without writing anything. Returns a time-limited preview token.

**Request body:**
```json
{
  "primary_assignment_id": "uuid",
  "rest_days": 7,
  "reason": "optional free text (admin-only, not shared with other soldiers)"
}
```

**Response — `GimelimPreview`:**
```json
{
  "preview_token": "uuid",        // expires in 5 minutes
  "preview_token_expires_at": "ISO datetime",
  "current_shift": {
    "shift_id": "uuid",
    "duty_type_name": "שמירה",
    "start_date": "2026-06-10",
    "end_date": "2026-06-12"
  },
  "soldier_a": { "id": "uuid", "name": "...", "rank": "..." },
  "reserve_called_up": {           // soldier B
    "assignment_id": "uuid",
    "soldier": { "id": "uuid", "name": "..." }
  },
  "future_assignment": {           // null if no eligible slot found
    "shift": {
      "shift_id": "uuid",
      "duty_type_name": "שמירה",
      "start_date": "2026-06-18",
      "end_date": "2026-06-20",
      "duty_location_name": "..."
    },
    "soldier_demoted": {           // soldier C
      "assignment_id": "uuid",
      "soldier": { "id": "uuid", "name": "..." },
      "hierarchy_distance": 2,
      "score_per_day": "3.50"
    },
    "c_existing_reserve": {        // soldier D — stays as general reserve
      "assignment_id": "uuid",
      "soldier": { "id": "uuid", "name": "..." }
    }
  },
  "warnings": [
    // e.g. "no_future_slot_found", "density_borderline", "eligibility_marginal"
  ]
}
```

### `POST /shifts/{shift_id}/gimelim/commit`

**Auth:** Same as preview.  
**Purpose:** Atomic transaction that executes everything.

**Request body:**
```json
{
  "preview_token": "uuid"
}
```

**Response:**
```json
{
  "dismissal_id": "uuid",
  "call_up_assignment_id": "uuid",
  "future_primary_assignment_id": "uuid | null",
  "future_demoted_assignment_id": "uuid | null",
  "notifications_queued": 3
}
```

If the preview token has expired or the relevant assignments have changed since preview, the endpoint returns `409 Conflict` with a message asking the commander to re-preview.

---

## Algorithm — Future Slot Search

### Inputs
- Soldier A's `soldier_id`, `duty_type_id`
- `earliest_eligible_date` = `current_shift.end_date + rest_days`
- All existing published/algorithm_draft assignments (for density check)
- Hierarchy tree (for distance calculation)

### Step 1 — Find candidate future shifts
```sql
SELECT shifts WHERE
  duty_type_id = current_shift.duty_type_id
  AND start_date >= earliest_eligible_date
  AND status IN ('published', 'algorithm_draft')
ORDER BY start_date ASC
```

### Step 2 — For each candidate shift, find eligible C
For each primary assignment in the candidate shift:

1. **Eligibility check:** Soldier A must pass the duty_type's requirements (gender, rank, mitvahim, alal, bahad1, service_type) for the candidate shift's dates.
2. **Density check:** Adding A to this shift must not exceed T duty-days in any rolling W-day window (using existing `ExistingAssignment` logic, treating the current shift as already complete).
3. **Hierarchy distance:** Compute `_hierarchy_distance(A_node, C_node, hier_parent)`.
4. **Tiebreaker:** Among C candidates with equal hierarchy distance, prefer the one with the highest `score_per_day` (they've earned the most — they can afford to wait as reserve).

Return the first shift where a valid C is found, along with the selected C.

### Step 3 — Result
- If found: return full preview including future shift, C, and D (C's existing reserve, who stays as general reserve).
- If not found: return `future_assignment: null` + warning `"no_future_slot_found"`. The commit will still execute the dismissal + call-up.

### Preview Token Race Condition Protection
The token is stored in-process (or Redis if available) with 5-minute TTL. On commit, the service re-reads the assignment IDs that appeared in the preview and verifies their `status` and `soldier_id` are unchanged. If any differ, returns `409 Conflict`.

---

## Backend Service — `app/services/gimelim.py`

New module, separate from `reserves.py`. Contains:

- `preview_gimelim(session, *, shift_id, primary_assignment_id, rest_days, actor_id) -> GimelimPreview`
- `commit_gimelim(session, *, shift_id, preview_token, actor_id) -> GimelimCommitResult`
- `_find_future_slot(session, *, soldier_a, duty_type_id, earliest_date, hier_maps) -> FutureSlotResult | None`
- `_select_best_c(primaries, soldier_a_node, hier_parent) -> DutyAssignment | None`

The commit function calls, in order within a single DB transaction:
1. `dismiss_primary()` from `reserves.py` (with `is_gimelim=True`)
2. `call_up_reserve()` from `reserves.py`
3. Demote C: update C's `DutyAssignment` to `is_reserve=True`, create new `DutyReserveLink` (C → A's new primary slot)
4. Promote A: create a new `DutyAssignment` for A on the future shift as primary
5. Handle D: D's `DutyReserveLink` stays pointing to C's old primary slot; since C is now reserve, D becomes a "floating" general reserve on that shift
6. Apply `gimalim.reserve_fate` setting to B
7. Write 4 audit entries
8. Enqueue notifications

---

## Frontend

### `ShiftDetailPanel.tsx` — Button Addition
Alongside the existing amber "שחרור" button, add a red **"גימלים 🏥"** button per primary:

```tsx
{isGimelimEnabled && !isCalledUp && isAdminOrCommanderInScope && (
  <button
    className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
    onClick={() => setGimelimTarget(a)}
  >
    גימלים 🏥
  </button>
)}
```

Visibility conditions:
- `gimalim.enabled` system setting is true (fetched with other settings)
- User is admin or commander in scope of the soldier
- Assignee is a primary (not already a called-up reserve)
- Assignee has no active dismissal

### `GimelimModal.tsx` — New Component

**Step 1 — Form:**
- Rest days input (number, default from system setting)
- Optional reason textarea (shown only to admins, never forwarded to other soldiers)
- "חשב הצעה ⟶" button → calls preview endpoint → shows spinner → Step 2

**Step 2 — Preview & Confirm:**
Displays structured summary:
- Current shift section: A dismissed, B called up
- Future shift section (or warning if null): C demoted, A enters as primary, D stays as reserve
- Any warnings highlighted in amber
- Token expiry countdown (5 min timer shown as subtle text)
- "⟵ חזור לעריכה" (back to Step 1) and "אשר ובצע ✓" buttons

On confirm → calls commit endpoint → on success shows success toast + closes modal + invalidates `calendarShifts` query.

On `409 Conflict` → shows message "הנתונים השתנו מאז החישוב — יש לחשב מחדש" and resets to Step 1.

### `SystemSettingsPage.tsx` — New Group

```tsx
{
  label: "גימלים",
  settings: [
    { key: "gimalim.enabled", label: "גלגול תורנויות בגימלים", type: "boolean", defaultValue: true,
      description: "כשמופעל, שחרור גימלים מגלגל את החייל לתורנות העתידית הבאה מתאימה" },
    { key: "gimalim.default_rest_days", label: "ימי מנוחה ברירת מחדל", type: "number", defaultValue: 7,
      description: "מספר ימים מינימלי בין סוף התורנות הנוכחית לתחילת השיבוץ מחדש" },
    { key: "gimalim.reserve_fate", label: "גורל רזרבת הגימלים", type: "select",
      options: [{ value: "keep", label: "שמור כרזרבה כללית" }, { value: "release", label: "שחרר מהתורנות" }],
      defaultValue: "keep",
      description: "מה קורה לרזרבה שהוקפצה לכיסוי אחרי שהכיסוי הסתיים" },
  ]
}
```

(The `"select"` type will require a small extension to the settings renderer.)

### `HelpModal.tsx` — New Tab

Tab **"🏥 גימלים"** added to `TABS` array, visible only when `gimalim.enabled = true`. Content:

- Short explanation of the social problem (soldiers faking illness) and how rolling solves it
- Step-by-step flow diagram using the existing `FlowStep` + `Arrow` components:
  1. חייל מדווח גימלים
  2. הרזרבה מוקפצת לכיסוי
  3. המערכת מוצאת את התורנות העתידית הקרובה
  4. הראשוני הקרוב היררכית ממומר לרזרבה
  5. חייל הגימלים נכנס כראשוני בתורנות העתידית
- Note on privacy: reason never shared with other soldiers
- Note on what happens if no future slot is found

---

## Notifications

All notifications routed through existing `NotificationType` + `TelegramOutbox` infrastructure.

| Recipient | Message |
|---|---|
| B (reserve called up) | "הוקפצת לכיסוי תורנות [סוג] בתאריכים [X–Y] בשל גימלים" |
| C (demoted to reserve) | "הועברת לרזרבה בתורנות [סוג] בתאריך [Z] — חייל שוחרר גימלים ומשובץ במקומך" |
| A (gimelim soldier) | "שוחררת גימלים מתורנות [X]. שובצת מחדש כראשוני לתורנות [סוג] בתאריך [Z]" (only if future slot found) |

**Privacy rule:** C and B's messages never mention A's name or reason. Only "בשל גימלים" — no identifying medical detail.

---

## Audit Trail

Four audit entries written atomically within the commit transaction:

| Action | Entity |
|---|---|
| `gimelim.dismiss` | `duty_dismissal` — includes `is_gimelim: true` in after |
| `gimelim.call_up` | `duty_assignment` (B) |
| `gimelim.demote_to_reserve` | `duty_assignment` (C) — before: primary, after: reserve |
| `gimelim.reassign` | `duty_assignment` (A's new future assignment) |

If no future slot found: only `gimelim.dismiss` + `gimelim.call_up` are written, with `context: { "future_slot": "not_found" }`.

Reason field is stored in `duty_dismissals.reason` — visible to admins only, never surfaced in soldier-facing notifications or public views.

---

## Permissions

| Action | Required role |
|---|---|
| Preview + commit | Admin OR commander whose scope includes soldier A |
| View gimelim tab in help modal | Any authenticated user (when feature enabled) |
| View gimelim settings | Admin only |

Scope check reuses the existing `dm_scope` service.

---

## Out of Scope

- Gimelim history / reporting page (future slice)
- Bulk gimelim (multiple soldiers at once)
- Soldier self-reporting gimelim (commanders/admins only)
- Gimelim on reserve assignments (only primary soldiers can take gimelim)
