# Plan C — Algorithm Page UX
**Date:** 2026-06-06  
**Issues:** #17, #18, #19, #20, #22, #23

---

## Overview

The algorithm page has several UX problems: draft/published distinction is invisible, default date is wrong, modes are poorly named, the hierarchy picker is unsorted, failure messages are garbled/unhelpful, and the shift fill status is miscalculated. This plan fixes all six.

---

## 1. Draft vs published distinction (#17)

**Current state:** `AlgorithmProposalTable` shows results without clearly indicating whether they are a draft (not yet published) or published.

**Design:**
- Add a sticky status banner at the top of `AlgorithmProposalTable`:
  - If `status === "algorithm_draft"`: amber banner — **"טיוטה — תוצאות לא פורסמו. לחץ 'אשר ופרסם' להחלת השיבוצים."**
  - If published: green banner — **"פורסם — שיבוצים פעילים."**
- In the jobs list, each row shows a status badge: `טיוטה` (amber), `פורסם` (green), `נכשל` (red), `בהרצה` (blue spinner).
- The "approve and publish" button text is changed to **"אשר ופרסם (הפוך לרשמי)"** to make the action consequence explicit.

---

## 2. Default date + unfilled shifts (#18)

**Current state:** `AlgorithmRunForm` date pickers have no default. No way to see unfilled shifts without running the algorithm.

**Design:**
- `start_date` defaults to today's date on mount.
- `end_date` defaults to today + 30 days.
- Add a secondary action button: **"הצג משמרות ללא שיבוץ"** — visible alongside the Run button, calls `GET /shifts/unfilled` (new endpoint, returns shifts with fewer than required primary assignments in a given date range).
- If the date range fields are empty, the "Run" button is disabled with tooltip "יש לבחור טווח תאריכים".

**New backend endpoint:** `GET /shifts/unfilled?date_from=&date_to=` — returns shift IDs and dates where `assigned_primary < required`.

---

## 3. Mode rename + direct publish + help modal (#19)

**Current state:** Only "מצב צל" (shadow mode) exists, poorly named.

**Design — two modes:**

| Mode | Hebrew name | Behavior |
|------|-------------|----------|
| Draft mode | **מצב טיוטה** | Algorithm result saved as `algorithm_draft` status; commander reviews and approves before publish. |
| Direct publish | **מצב פרסום ישיר** | Algorithm result immediately published as active assignments. No review step. |

- Toggle rendered as two radio buttons or a segmented control.
- A **`?` help button** next to the toggle opens a modal explaining both modes in plain Hebrew, including when to use each and what "publish" means for soldiers.
- Default mode: טיוטה (safer).

---

## 4. SubHierarchy picker — sorted + indented (#20)

**Current state:** `SubHierarchySelector` lists hierarchy nodes in database insertion order with no indentation.

**Design:**
- `SubHierarchySelector` receives the full tree (`NodeDTO[]`).
- Renders a `<select>` whose options are DFS-ordered, with ` ` (non-breaking space) padding multiplied by depth:
  ```
  ── יחידה ראשית
  ──── ענף א
  ────── מדור 1
  ────── מדור 2
  ──── ענף ב
  ```
- Uses the same `sortNodesByTree` utility defined in Plan B.
- Selection value is still the node UUID.

---

## 5. Algorithm failure explanation (#22)

**Two bugs to fix:**

**A — Garbled unicode:** The solver produces `f"T→{n}"` which creates a proper `→` character. The frontend receives it double-escaped as the literal string `→`. Fix: ensure the JSON response is not double-serialized on the backend (`json.dumps` called on an already-serialized string). Verify in `algorithm_bridge.py` / `algorithm` route.

**B — Human-readable failure panel:** Replace the raw JSON dump with a `FailurePanel` component:

```
┌─────────────────────────────────────────────────┐
│ ❌ האלגוריתם לא הצליח למצוא פתרון               │
│                                                   │
│ ניסיונות שבוצעו:                                  │
│  • ניסיון 1: מגבלת צפיפות T=7 ב-14 יום — נכשל   │
│  • ניסיון 2: הוגמשה ל-T=8 — נכשל                 │
│  • ניסיון 3: הוגמשה ל-T=9 — נכשל                 │
│                                                   │
│ סיבות אפשריות לכישלון:                            │
│  • אין מספיק חיילים כשירים לטווח התאריכים         │
│  • יותר מדי אילוצים אישיים מאושרים                │
│  • מגבלת הצפיפות נמוכה מדי ביחס לכמות המשמרות    │
│                                                   │
│ המלצות:                                           │
│  • הרחב את טווח התאריכים                          │
│  • הפחת את מספר המשמרות הנדרשות                   │
│  • בדוק אילוצים שאושרו לאותה תקופה               │
└─────────────────────────────────────────────────┘
```

Relaxation string mapping (backend sends these keys, frontend renders Hebrew):
- `T→N` → "הוגמשה מגבלת צפיפות: מותר כעת N ימי תורנות בכל 14 יום"

---

## 6. Shift full status bug (#23)

**Current state:** A shift shows as "מלא" when `assigned_count (primary + reserve) >= required`. This is wrong — reserve slots serve a different purpose than primary.

**Design:**
- Shift status display separates primary and reserve:
  - Primary: `X / Y מלא` where Y = `required_primary`
  - Reserve: `X / Y רזרבה` where Y = `required_reserve`
- A shift is marked "מלא" (green) only when primary slots are at or above `required_primary`.
- Reserve slots show a separate status indicator.
- Fix in: `DutyManagementPage.tsx`, `ShiftsPage.tsx`, and any backend aggregation query that feeds the "filled" count.
- Backend `GET /shifts` response should include separate `assigned_primary_count` and `assigned_reserve_count` fields.

---

## Data / API changes

| Change | Type |
|--------|------|
| `GET /shifts/unfilled?date_from&date_to` | New endpoint |
| `GET /shifts` response: add `assigned_primary_count`, `assigned_reserve_count` | Extend existing |
| `SolverResult.relaxed` unicode fix | Bug fix |

---

## Testing

- Jobs list shows amber "טיוטה" / green "פורסם" badges correctly.
- Algorithm run form defaults start to today.
- "הצג משמרות ללא שיבוץ" lists unfilled shifts without running algorithm.
- Two mode options are visible; direct publish skips the proposal review.
- Help modal explains both modes.
- SubHierarchy select shows indented, tree-ordered options.
- Failed job shows `FailurePanel` with Hebrew relaxation steps and suggestions.
- Shift with 2/3 primary + 1 reserve does not show as "מלא".
