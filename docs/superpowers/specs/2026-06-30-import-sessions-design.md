# Import Sessions & Enhanced Preview
**Date:** 2026-06-30

---

## Overview

Upgrade the Excel import flow from a stateless 3-step wizard into a **persistent session system** with a rich review UI, inline resolution of unknown duty types and hierarchy nodes, per-row partial acceptance, and a historical session log.

---

## Data Model

### New table: `import_sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `status` | enum `import_session_status` | `draft / confirmed / cancelled / done` |
| `filename` | text | original uploaded filename |
| `raw_excel` | bytea | full uploaded xlsx file |
| `parsed_state` | JSONB | full `PreviewResult` (soldiers + assignments + templates rows) |
| `user_selections` | JSONB | per-row actions `{ "soldiers": { "2": "new" }, "assignments": { "3": "skip" }, ... }` |
| `created_links` | JSONB | `{ soldiers: [uuid], assignments: [uuid], shift_templates: [uuid] }` — filled on confirm |
| `created_by` | UUID FK → soldiers | |
| `created_at` | timestamptz | |
| `confirmed_at` | timestamptz | nullable |
| `cancelled_at` | timestamptz | nullable |

**Status transitions:**
- `draft` → `confirmed` (on confirm)
- `draft` → `cancelled` (on cancel)
- `confirmed` → `done` (on mark-done; hides from default list)

`done` and `cancelled` sessions are preserved in the DB forever. They are hidden from the default list view but visible with a toggle.

---

## Backend API

Router: `/import/sessions` (replaces old `/import/preview` and `/import/apply`; old endpoints stay for backwards compat but are deprecated).

| Endpoint | Description |
|---|---|
| `POST /import/sessions` | Upload xlsx → parse → create `draft` session → return `{ session_id, preview }` |
| `GET /import/sessions` | List sessions (summary, no bytea). Query param `?status=draft,confirmed` (default excludes done/cancelled). Admins see all users' sessions. |
| `GET /import/sessions/{id}` | Full session detail including `parsed_state` and `user_selections`. Used when resuming. |
| `POST /import/sessions/{id}/reparse` | Re-run parser against stored `raw_excel` → update `parsed_state` → return fresh preview. Called after creating a missing duty type or node inline. |
| `PATCH /import/sessions/{id}/selections` | Save current user selections to `user_selections`. Called on every selection change (debounced). |
| `POST /import/sessions/{id}/confirm` | Apply selected rows → write to DB → set `confirmed`, fill `created_links`. Per-row errors are recorded but do not roll back other rows. |
| `POST /import/sessions/{id}/cancel` | Set status `cancelled`. Only allowed on `draft`. |
| `POST /import/sessions/{id}/done` | Set status `done`. Only allowed on `confirmed`. |
| `GET /import/template` | Unchanged — download example xlsx. |

### Confirm behavior (partial acceptance)

- Rows with `action = "skip"` are skipped.
- Valid selected rows are applied in a single transaction per type (soldiers first, then assignments, then templates).
- If a row fails on DB write, it is recorded in `created_links` with `{ row, error }` and skipped; other rows in the same type continue.
- `created_links` stores UUIDs of every successfully created/updated object, keyed by type.
- Session transitions to `confirmed` regardless of per-row errors (there is no "roll back everything" — the user can fix the rest in the system directly).

---

## Frontend

### `/import` — Session list page

Table columns: filename, upload date, status chip, row summary (e.g. "12 חיילים / 5 שיבוצים / 3 תבניות"), actions.

- Default filter: draft + confirmed (excludes done/cancelled). Toggle "הצג הכל" to show all.
- Draft row actions: "המשך" (resume review), "בטל"
- Confirmed row actions: "צפה", "סמן כבוצע"
- Done/cancelled rows: "צפה" (read-only)
- "ייבוא חדש" button → upload step

### Upload step

- Same drag-and-drop / file picker as today.
- On file pick → `POST /import/sessions` → redirect to `/import/sessions/{id}`.

### Review step (`/import/sessions/{id}`)

Three tabs: **חיילים / שיבוצים / תבניות משמרות**

**Common to all tabs:**
- "בחר הכל" / "בטל הכל" checkbox at top (only affects non-error rows).
- Per-row include/skip toggle for every non-error row.
- Error rows: always excluded, shown with red chip + inline error text, no toggle.
- Confirmed/cancelled sessions: all controls disabled (read-only).

**Soldiers tab columns:** שם, מ"א, דרגה, מגדר, קצין, יחידה, תאריך גיוס, סטטוס, פעולה

- If `hierarchy_node_name` is not found in the system: the node name cell is colored red + two inline buttons:
  - "צור יחידה" → opens hierarchy node creation modal → on save, fires reparse → row updates
  - "שנה" → opens hierarchy node picker modal → on pick, fires reparse → row updates
- After reparse, the UI merges existing user selections onto the fresh preview (rows that were skip stay skip; newly valid rows default to their parsed action).

**Assignments tab columns:** מ"א, שם חייל, סוג תורנות, תאריך התחלה, תאריך סיום, מילואים, סטטוס, פעולה

- If `duty_type_name` not found: red chip + "צור סוג תורנות" button → opens `DutyTypeFormModal` → on save, fires reparse → row updates.

**Templates tab columns:** שם, סוג תורנות, ימים, נדרש ראשי, נדרש מילואים, סטטוס, פעולה

- Same duty type resolution as assignments tab.

**Duty types summary panel** (shown above the tabs if any unknown duty types exist):
- Lists all unique unknown duty type names found across all tabs.
- Each with a "צור" button. Creating one fires reparse and removes it from this panel.

**Selections auto-save:** debounced 500ms PATCH to `/import/sessions/{id}/selections` on every toggle change.

### Confirm step

- Summary card: X חיילים (Y חדשים / Z עדכונים) / W שיבוצים / V תבניות
- "אשר וייבא" → `POST /import/sessions/{id}/confirm`
- Loading state. On completion:
  - Success rows: green, with links to the created objects in the system (e.g. link to soldier profile, shift detail)
  - Error rows: red, with reason text
  - "חזור לרשימת ייבואים" button

---

## Alembic Migration

1. Create enum `import_session_status` with values `draft, confirmed, cancelled, done`.
2. Create table `import_sessions` as specified above.

---

## Testing

- Upload valid xlsx → session created with status `draft`, parsed_state populated.
- Resume draft session → review step loads with previous user_selections restored.
- Create missing duty type inline → reparse fires → affected rows flip from error to valid.
- Change hierarchy node inline → reparse → row updates.
- Confirm with mixed rows (some skip, some new, one error) → valid rows applied, error logged in created_links, session confirmed.
- Cancel draft session → status set to cancelled, no rows applied.
- Mark confirmed session as done → hidden from default list, still viewable.
- Confirmed session links → clicking link navigates to correct object in system.
- Admin can see all users' sessions; non-admin sees only own.
