# Writing an Excel import parser

This guide explains the import pipeline's expected spreadsheet format and the
API endpoints available to validate data while building or maintaining an
import parser. It's written for both human engineers and coding agents.

## Pipeline overview

Import is a two-step flow, implemented in `backend/app/routes/import_excel.py`:

1. `POST /api/import/preview` — upload an `.xlsx` file. The server parses it
   and returns a preview of what would be created/updated, without writing
   anything to the database.
2. `POST /api/import/apply` — submit the (optionally edited) preview payload
   to actually commit the changes.

Both endpoints require a duty manager or admin token
(`require_duty_manager_or_admin` in `backend/app/auth/deps.py`).

## Expected sheet formats

The workbook may contain up to three sheets, each optional: `soldiers`,
`assignments`, `shift_templates`.

### `soldiers` sheet columns

`personal_number`, `full_name`, `rank`, `gender`, `is_officer`,
`hierarchy_node_name`, `enrolled_at`, `enlistment_date`, `unit_join_date`, `phone`, `email`

- `personal_number` is the unique key: if it matches an existing soldier,
  the row becomes an update; otherwise it's a new soldier.
- `hierarchy_node_name` must match a node in the current hierarchy tree —
  validate it against `GET /api/import-lookup/hierarchy` before generating
  rows that reference it (see below).
- `enrolled_at` and `enlistment_date` are dates, parsed by `_parse_date` in
  `backend/app/routes/import_excel.py`: both `dd.mm.yyyy` and ISO
  `yyyy-mm-dd` are accepted.
- `unit_join_date` is optional for legacy rows and must be between enlistment
  and enrollment when supplied. Changing it for an active existing soldier is
  not applied directly by import; submit the change through the unit-entry
  approval workflow.

### `assignments` sheet columns

`personal_number`, `duty_type_name`, `start_date`, `end_date`, `is_reserve`

- `personal_number` must reference a soldier — new or already existing.
- `duty_type_name` must match an existing duty type — validate against
  `GET /api/import-lookup/duty-types`.
- `start_date` and `end_date` are dates, parsed by `_parse_date` in
  `backend/app/routes/import_excel.py`: both `dd.mm.yyyy` and ISO
  `yyyy-mm-dd` are accepted.

### `shift_templates` sheet columns

`name`, `duty_type_name`, `days_of_week`, `required_primary`, `required_reserve`

- `duty_type_name` must match an existing duty type, same as above.
- `days_of_week` is a comma-separated list.

## Validating data while parsing

Three read-only endpoints exist specifically to support parser development
and debugging, defined in `backend/app/routes/import_lookup.py`. All three
require a duty manager or admin token (`require_duty_manager_or_admin`) —
the same auth level needed to run the import itself.

### `GET /api/import-lookup/duty-types`

Returns every duty type (active and inactive) with full fields (see
`DutyTypeOut` in `backend/app/routes/duty_config.py`). Use this to confirm a
`duty_type_name` from a sheet is real before emitting a row that references
it — an unrecognized name should be flagged as a parse error rather than
silently sent to `/api/import/apply`.

```
GET /api/import-lookup/duty-types
Authorization: Bearer <token>

200 OK
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "משמר לילה",
    "score_per_day": "1.50",
    "description": null,
    "active": true,
    "requirements": {},
    "reserve_ratio": "0.000",
    "reserve_minimum": 0,
    "contact_name": "רב\"ט כהן",
    "contact_phone": "050-1234567",
    "start_time": "20:00:00",
    "end_time": "06:00:00",
    "instructions": "הצטיידות במקלע בשער הראשי",
    "is_external": false,
    "eligible_node_ids": ["8f14e45f-ceea-467e-bd5d-1e0c5f0e8f9c"]
  }
]
```

### `GET /api/import-lookup/hierarchy`

Returns every hierarchy node, regardless of the caller's own duty-manager
scope (see `NodeOut` in `backend/app/routes/hierarchy.py`). Use this to
resolve a `hierarchy_node_name` from the sheet to a node `id`, and to
confirm the name isn't ambiguous (names are not guaranteed globally
unique — check `parent_id`/`path_ids` if a sheet's name matches more than
one node).

```
GET /api/import-lookup/hierarchy
Authorization: Bearer <token>

200 OK
[
  {
    "id": "8f14e45f-ceea-467e-bd5d-1e0c5f0e8f9c",
    "level": "unit",
    "name": "יחידה 1",
    "parent_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "commander_id": null,
    "commander_name": null,
    "path_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6", "8f14e45f-ceea-467e-bd5d-1e0c5f0e8f9c"],
    "duty_managers": [
      {
        "scope_id": "8f14e45f-ceea-467e-bd5d-1e0c5f0e8f9c",
        "soldier_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
        "name": "רב\"ט לוי"
      }
    ],
    "dm_manageable": false
  }
]
```

### `GET /api/import-lookup/soldiers`

Look up soldiers by `personal_number` (exact), `name` (case-insensitive
partial match), and/or `hierarchy_node_id` (includes all descendant nodes,
not just direct members). At least one filter is required — a request with
none returns `400 no_filter_provided`. Filters combine with AND. No matches
returns `200` with an empty list.

```
GET /api/import-lookup/soldiers?personal_number=1234567
Authorization: Bearer <token>

200 OK
[
  {
    "id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
    "personal_number": "1234567",
    "full_name": "ישראל ישראלי",
    "rank": "רב\"ט",
    "hierarchy_node_id": "8f14e45f-ceea-467e-bd5d-1e0c5f0e8f9c",
    "hierarchy_node_name": "יחידה 1"
  }
]
```

Typical use: before treating a sheet row as a "new soldier," check whether
`personal_number` already exists via this endpoint — this mirrors what
`/api/import/preview` itself does internally, and is useful for a parser
that wants to pre-flag likely duplicates (e.g. same name, different
personal number) before the row ever reaches the import endpoints.
