# Design: Cancel All Assignments From Today — שיבוץ ידני Page

**Date:** 2026-06-06  
**Status:** Approved

## Summary

Add two "nuclear option" buttons to the שיבוץ ידני (DutyManagementPage) that allow a duty manager to wipe all pending draft assignments and/or all published assignments from today onward in a single action. The draft button shows a live count and expandable list on page load so the user knows what will be deleted before acting.

## Backend Changes

### `backend/app/routes/algorithm.py`

#### 1. `POST /algorithm/reset-published`
- Change `days_ahead: int = Query(ge=1)` → `ge=0`
- Change filter from `DutyAssignment.start_date > cutoff` → `>= cutoff`
- Result: calling with `days_ahead=0` cancels all published assignments with `start_date >= today`

#### 2. `POST /algorithm/reset-drafts`
- Same two changes as above
- Result: calling with `days_ahead=0` rejects all algorithm_draft assignments with `start_date >= today`

#### 3. New: `GET /algorithm/drafts-preview`
- Auth: requires `ALGORITHM_RUN` permission
- No query params
- Query: all `DutyAssignment` rows where `status == "algorithm_draft"` and `start_date >= date.today()`
- Joins soldier `full_name` (via `Soldier`) and duty type `name` (via `DutyType`)
- Response:
  ```json
  {
    "count": 12,
    "items": [
      {
        "assignment_id": "uuid",
        "soldier_name": "string",
        "duty_type_name": "string",
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD"
      }
    ]
  }
  ```

## Frontend Changes

### `frontend/src/api/algorithm.ts`
- Add `getDraftsPreview()` → `GET /algorithm/drafts-preview`
- The existing `resetPublished(days)` and `resetDrafts(days)` work unchanged with `days=0`

### `frontend/src/pages/DutyManagementPage.tsx`
- On mount: call `getDraftsPreview()`, store `{ count, items }` in component state
- Add a new section below the score adjustment form, separated by `border-t`

#### Drafts section
- Label: "טיוטות שיבוץ מהיום ואילך"
- Amber badge: `{count} שיבוצים` (or "אין טיוטות" if count=0)
- Clicking the badge toggles an inline list showing each draft as: `{soldier_name} · {duty_type_name} · {start_date}`
- Button: "מחק טיוטות" — amber/red, disabled when count=0
- On click: `window.confirm` with count in message → calls `resetDrafts(0)` → shows result message → re-fetches preview

#### Published section
- Label: "שיבוצים פורסמים מהיום ואילך"
- Button: "מחק שיבוצים פורסמים" — red
- On click: `window.confirm` → calls `resetPublished(0)` → shows result message → re-fetches draft preview

### `frontend/src/i18n/he.json`
New keys under `duty_management`:
```json
"bulk_cancel_section_title": "ביטול שיבוצים",
"drafts_from_today_label": "טיוטות שיבוץ מהיום ואילך",
"drafts_badge": "{{count}} שיבוצים",
"drafts_badge_none": "אין טיוטות",
"drafts_toggle_show": "הצג פירוט",
"drafts_toggle_hide": "הסתר פירוט",
"cancel_drafts_btn": "מחק טיוטות",
"cancel_drafts_confirm": "למחוק {{count}} טיוטות שיבוץ מהיום ואילך?",
"cancel_drafts_result": "בוטלו {{count}} טיוטות",
"cancel_drafts_none": "לא נמצאו טיוטות לביטול",
"published_from_today_label": "שיבוצים פורסמים מהיום ואילך",
"cancel_published_btn": "מחק שיבוצים פורסמים",
"cancel_published_confirm": "לבטל את כל השיבוצים הפורסמים מהיום ואילך?",
"cancel_published_result": "בוטלו {{count}} שיבוצים פורסמים",
"cancel_published_none": "לא נמצאו שיבוצים פורסמים לביטול"
```

## Authorization
Both actions require the `ALGORITHM_RUN` permission (same as the existing reset endpoints). The page is already only accessible to `duty_manager` / `admin` roles.

## Error Handling
- Network/API errors show `t("errors.generic")` inline below the relevant button
- Both result messages auto-clear after 5 seconds (or on next action)

## Out of Scope
- No pagination on the drafts-preview list (expected to be small; if large, a scrollable container handles it)
- No undo — both actions are irreversible; the confirm dialog is the only guard
