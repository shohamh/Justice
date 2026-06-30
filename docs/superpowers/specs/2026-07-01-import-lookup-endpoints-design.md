# Import-support lookup endpoints + parser docs

## Problem

Excel import parsing (`backend/app/routes/import_excel.py`) currently has no way
to validate references — duty type names, hierarchy node names, soldier
personal numbers — against the live database while parsing. Humans and
agents writing/maintaining the parser also lack a single doc explaining the
expected sheet formats and how to use such validation data.

## Goals

- Three read-only endpoints a parser (or a human debugging an import) can call
  to look up valid duty types, hierarchy nodes, and soldiers.
- All three restricted to duty manager / admin (same population allowed to
  run the import itself).
- A markdown doc explaining the import pipeline's expected format and how to
  use these endpoints, written for both human and agent readers.

## Non-goals

- Changing how `/api/import/preview` or `/api/import/apply` parse or validate
  data — these are purely additive, read-only support endpoints.
- Pagination — org sizes here are small (hundreds to low thousands of
  soldiers), so all three endpoints return full result sets in one response.

## API design

New file: `backend/app/routes/import_lookup.py`, router prefix
`/api/import-lookup`, tag `import-lookup`. All endpoints depend on
`require_duty_manager_or_admin` (`backend/app/auth/deps.py`) — same
dependency `import_excel.py` already uses, so a token that can run the
import can also call these.

### `GET /api/import-lookup/duty-types`

Returns `list[DutyTypeOut]`. Reuses the existing `DutyTypeOut` Pydantic model
and `_dt_out` mapper already defined in `backend/app/routes/duty_config.py`
(import them rather than redefining) — full model fields, unfiltered,
includes inactive duty types so the parser can flag references to them.

### `GET /api/import-lookup/hierarchy`

Returns `list[NodeOut]`. Reuses the existing `NodeOut` Pydantic model and
`_out` mapper from `backend/app/routes/hierarchy.py`. Unlike
`GET /hierarchy/tree`, this endpoint does **not** apply role-based scoping —
it always returns every node, since a duty manager validating an import
needs visibility into the whole org regardless of their own DM scope.

### `GET /api/import-lookup/soldiers`

Query params (all optional, but at least one required):

- `personal_number: str | None` — exact match
- `name: str | None` — case-insensitive partial match (SQL `ILIKE
  '%value%'` on `full_name`)
- `hierarchy_node_id: uuid.UUID | None` — soldiers whose hierarchy node is
  the given node **or any descendant of it**

When multiple params are given, filters combine with AND. If none are given,
respond `400` with `detail="no_filter_provided"`. No matches → `200` with an
empty list (not 404), consistent with other list endpoints in this codebase.

Response model `SoldierLookupOut`:

```python
class SoldierLookupOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    rank: str | None
    hierarchy_node_id: uuid.UUID | None
    hierarchy_node_name: str | None
```

**Descendant resolution**: `HierarchyNode.path_ids` already stores each
node's full ancestor chain (used the same way in `hierarchy.py`'s
`get_tree`). To find all soldiers under `hierarchy_node_id` including
descendants:

1. Select all `HierarchyNode` rows where `id == hierarchy_node_id` OR
   `hierarchy_node_id == ANY(path_ids)` → candidate node id set.
2. Filter `Soldier.hierarchy_node_id.in_(candidate_node_ids)`.

This is a single query combining both steps via a join, not two round-trips.

## Error handling

- `403` via `require_duty_manager_or_admin` for unauthorized callers
  (unchanged dependency behavior).
- `400 no_filter_provided` for `/soldiers` called with zero filters.
- All other cases return `200` with full or empty lists — no 404s for
  "no results."

## Testing

New file `backend/tests/integration/test_import_lookup.py`. Covers:

- 401/403 for unauthenticated / non-DM-non-admin callers on all three
  endpoints.
- `/duty-types`: returns active and inactive types.
- `/hierarchy`: returns full tree regardless of caller's own DM scope.
- `/soldiers`: each filter individually, combined filters (AND), descendant
  inclusion (soldier two levels below the queried node is returned), no
  filters → 400, no matches → empty list.

The test-area auto-marker hook (`backend/pyproject.toml` markers list)
assigns areas by filename; `test_import_lookup.py` will need a matching
`marker_for_filename` entry (check `backend/tests/conftest.py` for the
mapping) — most likely `soldiers`, since that area's marker description
already covers "Excel import."

## Documentation

New file: `docs/excel-import-parser-guide.md` (top-level `docs/`, matching
the existing `docs/algorithm.md` convention — not under
`docs/superpowers/`, since this is permanent reference documentation, not a
planning artifact).

Contents:

1. **Overview** — what the import pipeline does (`POST /api/import/preview`
   → review → `POST /api/import/apply`), referencing
   `backend/app/routes/import_excel.py`.
2. **Expected sheet formats** — the `soldiers`, `assignments`, and
   `shift_templates` sheets and their columns, transcribed from the current
   implementation (personal_number, full_name, rank, gender, is_officer,
   hierarchy_node_name, enrolled_at, enlistment_date, phone, email for
   soldiers; personal_number, duty_type_name, start_date, end_date,
   is_reserve for assignments; name, duty_type_name, days_of_week,
   required_primary, required_reserve for templates). Date formats
   (dd.mm.yyyy or ISO).
3. **Validating data while parsing** — the three new lookup endpoints: auth
   requirement, request/response shape with example JSON, and guidance
   (e.g. "look up `hierarchy_node_name` from the sheet against
   `GET /api/import-lookup/hierarchy` before emitting a row referencing it").
4. Written so both a human engineer and a coding agent building/maintaining
   a parser can use it as a standalone reference.
