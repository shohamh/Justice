# Plan F — Excel Import Mechanism
**Date:** 2026-06-06  
**Issue:** #16

---

## Overview

A three-step import wizard that lets commanders import soldiers, historical duty assignments, and shift templates from Excel. The user uploads a file, reviews a parsed preview, and confirms what to apply.

---

## Location

New page: **"ייבוא מ-Excel"** under the תכנון (Planning) section. Route: `/import`.

---

## Excel file format

A single `.xlsx` file with up to three sheets:

### Sheet 1: `soldiers`
| Column | Required | Notes |
|--------|----------|-------|
| `personal_number` | Yes | Unique identifier |
| `full_name` | Yes | |
| `rank` | No | Free text |
| `gender` | No | `m` / `f` |
| `is_officer` | No | `true` / `false` |
| `hierarchy_node_name` | No | Matched by name to existing nodes |
| `enrolled_at` | No | `dd.mm.yyyy` — when they joined the unit |
| `enlistment_date` | No | `dd.mm.yyyy` — actual IDF enlistment |
| `phone` | No | |
| `email` | No | |

### Sheet 2: `assignments`
| Column | Required | Notes |
|--------|----------|-------|
| `personal_number` | Yes | Must match an existing or imported soldier |
| `duty_type_name` | Yes | Matched by name to existing duty types |
| `start_date` | Yes | `dd.mm.yyyy` |
| `end_date` | Yes | `dd.mm.yyyy` |
| `is_reserve` | No | `true` / `false`, default `false` |

### Sheet 3: `shift_templates`
| Column | Required | Notes |
|--------|----------|-------|
| `name` | Yes | Template name |
| `duty_type_name` | Yes | |
| `days_of_week` | Yes | Comma-separated: `0,1,2,3,4,5,6` (0=Sun) |
| `required_primary` | Yes | Integer |
| `required_reserve` | No | Integer, default 0 |

---

## Backend

### `POST /import/preview`
- Accepts: multipart file upload (`.xlsx`).
- Parses all three sheets using `openpyxl`.
- Returns a `PreviewResult` JSON object:
  ```json
  {
    "soldiers": [
      {
        "row": 2,
        "action": "new" | "update" | "error",
        "data": { ...parsed fields },
        "conflict": { ...existing record if action=update },
        "errors": ["field X is invalid"]
      }
    ],
    "assignments": [ ... ],
    "shift_templates": [ ... ]
  }
  ```
- Does NOT write to the database.
- Resolves `hierarchy_node_name` → UUID (null + warning if not found).
- Resolves `duty_type_name` → UUID (null + error if not found).

### `POST /import/apply`
- Accepts: `ApplyRequest`:
  ```json
  {
    "soldiers": [{ "row": 2, "action": "new" | "update" | "skip", "data": { ... } }],
    "assignments": [ ... ],
    "shift_templates": [ ... ]
  }
  ```
- Applies all rows with `action != "skip"` in a single transaction.
- Returns a summary: `{ created: N, updated: N, skipped: N, errors: [...] }`.
- On any error in the transaction, rolls back everything and returns the error details.

---

## Frontend — 3-step wizard

### Step 1: Upload
- Drag-and-drop or file picker for `.xlsx`.
- "הורד תבנית לדוגמה" (download example template) link.
- On upload: POST to `/import/preview`, show loading spinner.
- On error (wrong format, unreadable file): show inline error message.

### Step 2: Review
Three tabs: **חיילים / שיבוצים / תבניות משמרות**.

Each tab shows a table with:
- Row number from Excel.
- All parsed fields.
- Status chip:
  - `חדש` (green) — will be created.
  - `עדכון` (blue) — will update existing record; shows diff of changed fields.
  - `שגיאה` (red) — cannot be imported; shows error text. Row is non-selectable.
  - `דלג` (gray) — user chose to skip.
- For **update** rows: a per-row dropdown to choose `עדכן` or `דלג`.
- Global: "בחר הכל" / "בטל הכל" checkboxes per tab.
- Rows with errors are always excluded (cannot be selected).

### Step 3: Confirm
- Summary table: `X חיילים חדשים / Y עדכונים / Z שיבוצים / W תבניות`.
- "אשר וייבא" button → POST to `/import/apply`.
- Loading state during apply.
- On success: green success banner with counts; "חזור לתכנון" button.
- On partial failure: show which rows failed with reasons; offer "נסה שוב" for failed rows only.

---

## Example template

A downloadable `.xlsx` template (`GET /import/template`) with one example row per sheet and header row with Hebrew comments in a second header row (row 1 = field names in English for parsing, row 2 = Hebrew labels for humans).

---

## Data / API changes

| Change | Type |
|--------|------|
| `POST /import/preview` | New endpoint |
| `POST /import/apply` | New endpoint |
| `GET /import/template` | New endpoint |
| New route `/import` in frontend router | New page |

---

## Testing

- Upload file with all three sheets → preview shows correct actions per row.
- Duplicate soldier personal number → shows as "עדכון" with diff, not error.
- Unknown `duty_type_name` → error row, excluded from apply.
- User skips a "חדש" soldier row → not created on apply.
- Apply creates/updates correct records; skipped rows are untouched.
- Partial failure rolls back entire transaction; error details shown.
- Template download contains valid example data.
