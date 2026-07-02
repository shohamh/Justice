# Import Fuzzy Name Mapping

**Date:** 2026-07-02

## Problem

When the Excel import parser cannot match a duty type name or hierarchy node name to a DB record, the row is marked as "error". The user's only options were to create a new record or (for nodes) rename the existing DB node. There was no way to say "this Excel name actually refers to that existing record."

## Goal

Replace the bare red-name UX with an inline searchable combobox showing the closest-matching existing DB records. Picking one persists a mapping in `user_selections` and triggers a reparse so the row immediately resolves.

Two levels of mapping are supported:

- **Name mappings** — one entry covers every row that shares the same unresolved Excel name.
- **Row overrides** — per-row entries that take precedence over name mappings (applied first during reparse).

This lets the user say "all rows named X map to record Y" globally, and still override individual rows differently.

---

## Data Model

All mapping data lives inside the existing `user_selections` JSON column under `_name_mappings`:

```json
{
  "_name_mappings": {
    "duty_type": {
      "by_name": {
        "<excel name>": "<uuid>"
      },
      "by_row": {
        "duty_shifts:<row>":     "<uuid>",
        "shift_templates:<row>": "<uuid>"
      }
    },
    "hierarchy_node": {
      "by_name": {
        "<excel name>": "<uuid>"
      },
      "by_row": {
        "soldiers:<row>":              "<uuid>",
        "duty_shifts:<row>:<node_name>": "<uuid>"
      }
    }
  },
  "soldiers":       { "3": "skip" },
  "duty_shifts":    {},
  "shift_templates": {}
}
```

**Row key format:**
- Duty type on a shift row: `"duty_shifts:5"`, `"shift_templates:3"`
- Hierarchy node on a soldier row: `"soldiers:2"`
- Hierarchy node inside a node quota (within a shift row): `"duty_shifts:5:<node_name>"` — the node name disambiguates which quota within that row.

**Resolution order during reparse (highest priority first):**
1. `by_row` override for this specific row (and quota slot if applicable)
2. `by_name` mapping for this Excel name
3. Regular DB name lookup

---

## Backend

### `reparse_session`

Pass `import_session.user_selections` into `_resolve_and_score`.

### `_resolve_and_score`

Extract the mapping sub-dicts and pass them to each resolver:

```python
nm            = (selections or {}).get("_name_mappings", {})
dt_by_name    = nm.get("duty_type", {}).get("by_name", {})
dt_by_row     = nm.get("duty_type", {}).get("by_row", {})
node_by_name  = nm.get("hierarchy_node", {}).get("by_name", {})
node_by_row   = nm.get("hierarchy_node", {}).get("by_row", {})
```

### `_resolve_soldiers`

Resolution for `hierarchy_node_name`:

```python
row_key    = f"soldiers:{row.source_row}"
mapped_id  = node_by_row.get(row_key) or node_by_name.get(row.hierarchy_node_name)
node       = session.get(HierarchyNode, uuid.UUID(mapped_id)) if mapped_id else nodes_by_name.get(row.hierarchy_node_name)
```

### `_resolve_duty_shifts`

Duty type resolution:

```python
row_key   = f"duty_shifts:{row.source_row}"
mapped_id = dt_by_row.get(row_key) or dt_by_name.get(row.duty_type_name)
duty_type = session.get(DutyType, uuid.UUID(mapped_id)) if mapped_id else duty_types_by_name.get(row.duty_type_name)
```

Node quota resolution (per quota slot):

```python
quota_key = f"duty_shifts:{row.source_row}:{q.node_name}"
mapped_id = node_by_row.get(quota_key) or node_by_name.get(q.node_name)
node      = session.get(HierarchyNode, uuid.UUID(mapped_id)) if mapped_id else nodes_by_name.get(q.node_name)
```

### `_resolve_shift_templates`

```python
row_key   = f"shift_templates:{row.source_row}"
mapped_id = dt_by_row.get(row_key) or dt_by_name.get(row.duty_type_name)
duty_type = session.get(DutyType, uuid.UUID(mapped_id)) if mapped_id else duty_types_by_name.get(row.duty_type_name)
```

No new endpoints. Mapping saved via existing `PATCH /{session_id}/selections`, reparse via `POST /{session_id}/reparse`.

---

## Frontend

### Data fetching

On `ImportSessionReviewPage` mount, fetch in parallel:
- `GET /import-lookup/duty-types` → `allDutyTypes`
- `GET /import-lookup/hierarchy` → `allNodes`

### Fuzzy matching

Install `fuse.js`. For each combobox, initialize a `Fuse` instance over the candidate list (keyed on `name`) so results are sorted by similarity to the unresolved name.

### `FuzzyPickerCombobox` component

Props: `unresolvedName`, `candidates: { id, name }[]`, `onPick(id: string): void`, `disabled: boolean`

- Renders inline (no modal).
- Input pre-filled with `unresolvedName` so closest matches appear immediately.
- Typing re-filters via Fuse in real time.
- Shows up to 8 results.
- Calling `onPick(id)` triggers the save flow below.

### "Apply to all" prompt

After `onPick` fires:
1. Count rows in the current tab (and same entity type) that share the same unresolved name.
2. If count > 1, show an inline banner:
   > *"יש עוד N שורות עם השם '…'."*
   > **[החל על כולן]** &nbsp; **[רק שורה זו]** &nbsp; **[ביטול]**

- **החל על כולן** → write to `by_name` (covers all rows with that name automatically).
- **רק שורה זו** → write to `by_row` for this specific row key only.
- **ביטול** → discard pick, no save.

If count === 1, skip the prompt and go straight to `by_row` write (since there is no ambiguity).

### Save flow

```
build updated selections with new mapping entry
→ PATCH /selections  (debounced 500ms)
→ POST  /reparse
→ setDetail(result), setSelections(result.user_selections ?? {})
```

### Removed UX

The "שנה" button (which renamed the DB node) is removed. The combobox replaces it. "צור" / "צור סוג תורנות" / "צור יחידה" buttons remain alongside.

---

## Error handling

- If a mapped UUID no longer exists at reparse time, the resolver falls back to name lookup; if that also fails, the row returns to "error" state — same as baseline behaviour.
- Fuse.js runs client-side; no extra API calls on keystroke.

---

## Out of scope

- Fuzzy matching for `duty_location_name` (not user-resolvable today).
- Soldiers matched by name (identified by personal number).
- Cross-session persistence of mappings (each import session is independent).
