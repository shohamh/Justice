# Import Fuzzy Name Mapping

**Date:** 2026-07-02

## Problem

When the Excel import parser cannot match a duty type name or hierarchy node name to a DB record, the row is marked as "error". The user's only options were to create a new record or (for nodes) rename the existing DB node. There was no way to say "this Excel name actually refers to that existing record."

## Goal

Replace the "שנה" / bare red-name UX with an inline searchable combobox showing the closest-matching existing DB records. Picking one maps the Excel name to that record for the session and triggers a reparse so the row immediately resolves.

---

## Data Model

Name mappings are stored inside the existing `user_selections` JSON column under the key `_name_mappings`:

```json
{
  "_name_mappings": {
    "duty_type":      { "<excel name>": "<uuid>" },
    "hierarchy_node": { "<excel name>": "<uuid>" }
  },
  "soldiers":      { "3": "skip" },
  "duty_shifts":   {},
  "shift_templates": {}
}
```

Keying by name (not row number) means one mapping entry covers every row that shares that unresolved name, with no extra storage.

---

## Backend

### `reparse_session`

Pass the current `user_selections` (read from `import_session.user_selections`) to `_resolve_and_score`.

### `_resolve_and_score`

Accept a `name_mappings` dict (defaulting to `{}`) and pass the relevant sub-dicts to each resolver:

```python
nm = (selections or {}).get("_name_mappings", {})
duty_type_map   = nm.get("duty_type", {})
node_map        = nm.get("hierarchy_node", {})
```

### `_resolve_soldiers`

Before `nodes_by_name.get(name)`, check:

```python
mapped_id = node_map.get(row.hierarchy_node_name)
node = session.get(HierarchyNode, uuid.UUID(mapped_id)) if mapped_id else nodes_by_name.get(row.hierarchy_node_name)
```

### `_resolve_duty_shifts`

Apply `duty_type_map` for `row.duty_type_name` and `node_map` for each `q.node_name` in node quotas.

### `_resolve_shift_templates`

Apply `duty_type_map` for `row.duty_type_name`.

No new endpoints. Mapping is saved via existing `PATCH /{session_id}/selections`, reparse via existing `POST /{session_id}/reparse`.

---

## Frontend

### Data fetching

On `ImportSessionReviewPage` mount, fetch in parallel:
- `GET /import-lookup/duty-types` → `allDutyTypes`
- `GET /import-lookup/hierarchy` → `allNodes`

### Fuzzy matching

Install `fuse.js`. For each unresolved name, when the combobox opens, initialize a `Fuse` instance over the candidate list (keyed on `name`) and sort results by score.

### `FuzzyPickerCombobox` component

Props: `unresolvedName`, `candidates: { id, name }[]`, `onPick(id: string): void`, `disabled: boolean`

Behaviour:
- Renders inline (no modal).
- Input is pre-filled with `unresolvedName` as the search query, so the closest matches appear immediately on open.
- Typing re-filters in real time via Fuse.
- Shows up to ~8 results in a dropdown list.
- Picking an item calls `onPick(id)`.

### "Apply to all" prompt

After `onPick` fires:
1. Count rows across the current tab that share the same unresolved name.
2. If count > 1, show an inline banner below the combobox:
   > *"יש עוד N שורות עם השם '…'. להחיל על כולן?"*  [כן] [לא, רק שורה זו]
3. Since the mapping is keyed by name, "כן" is the default and requires no extra work — one entry in `_name_mappings` already covers all rows. "לא" is not supported by the data model (one name → one ID), so the prompt is informational: it tells the user the mapping will cover all matching rows and asks them to confirm or cancel.

### Save flow

```
update local selections: selections["_name_mappings"]["duty_type"|"hierarchy_node"][name] = id
→ PATCH /selections (debounced 500ms, same as existing action saves)
→ POST /reparse
→ setDetail(result), setSelections(result.user_selections)
```

### Removed UX

The "שנה" button (which renamed the DB node) is removed. The combobox replaces it. The "צור" / "צור סוג תורנות" / "צור יחידה" buttons remain alongside the combobox.

---

## Error handling

- If a mapped UUID no longer exists at reparse time (record deleted between sessions), the resolver falls back to name lookup and the row returns to "error" state — same behaviour as before.
- Fuse.js runs entirely client-side; no extra API calls on keystroke.

---

## Out of scope

- Persisting mappings across sessions (each import session is independent).
- Fuzzy matching for `duty_location_name` (locations are not currently user-resolvable).
- Soldiers fuzzy matching by name (soldiers are identified by personal number, not name).
