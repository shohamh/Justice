# Hierarchy Level Types — Design Spec

**Date:** 2026-06-23  
**Feature:** DB-backed, reorderable hierarchy level types with inline DnD management in the edit dialog

---

## Background

Hierarchy nodes carry a `level` field (e.g. `branch`, `group`) used to enforce parent-child ordering: a child must have a strictly lower rank than its parent. Currently the level list and ordering are hardcoded in both backend (`LEVEL_ORDER` in `services/hierarchy.py`) and frontend (`LEVEL_ORDER` constants in several components). Admins have no way to add new types or rename existing ones.

Additionally, the "ערוך" button on a node currently only allows renaming — there is no way to change a node's level after creation.

---

## Goals

1. Store level types in the database with an explicit rank ordering
2. Allow admins and duty managers to add new types, rename them, and reorder them via a drag-and-drop UI
3. Allow any user with HIERARCHY_MANAGE permission to change a node's level when editing it
4. Keep strict ordering enforcement: a node's level rank must be strictly greater than its parent's rank
5. Prevent a reorder from being saved if it would create violations in the existing tree

---

## Data Model

### New table: `hierarchy_level_types`

| column | type | constraints |
|--------|------|-------------|
| `id` | `UUID` | PK, default `gen_random_uuid()` |
| `key` | `VARCHAR(50)` | UNIQUE NOT NULL — internal slug (e.g. `"branch"`) |
| `label` | `VARCHAR(200)` | NOT NULL — Hebrew display name (e.g. `"ענף"`) |
| `rank` | `INTEGER` | UNIQUE NOT NULL — ordering; lower rank = higher in hierarchy |

Seeded via Alembic with the 7 existing types:

| key | label | rank |
|-----|-------|------|
| `corps` | `אגף` | 1 |
| `division` | `מערך` | 2 |
| `unit` | `יחידה` | 3 |
| `department` | `מרכז` | 4 |
| `branch` | `ענף` | 5 |
| `group` | `מדור` | 6 |
| `team` | `צוות` | 7 |

The `HierarchyNode.level` column remains a plain `VARCHAR` — no FK to `hierarchy_level_types`. This keeps the DB simple and avoids cascade issues. Enforcement is done in the service layer.

---

## API

All endpoints are under `/hierarchy/level-types`.

### `GET /hierarchy/level-types`
- Auth: any authenticated user
- Returns: list of `LevelTypeOut` ordered by `rank` ascending
- Used by frontend to populate dropdowns and the DnD list

```json
[
  { "id": "...", "key": "branch", "label": "ענף", "rank": 5 },
  ...
]
```

### `POST /hierarchy/level-types`
- Auth: admin or duty_manager
- Body: `{ "key": string, "label": string }`
- Creates a new type with `rank = max(existing ranks) + 1` (appended at bottom)
- Returns: `LevelTypeOut`
- 409 if `key` already exists

### `PUT /hierarchy/level-types/reorder`
- Auth: admin or duty_manager
- Body: `{ "ordered_ids": [uuid, uuid, ...] }` — full ordered list of all type IDs
- Assigns ranks 1, 2, 3, ... to types in the given order
- **Before saving:** validates every existing `(parent_node, child_node)` pair in the tree against the new ranks. If `child_new_rank <= parent_new_rank` for any pair, returns:
  ```json
  HTTP 409
  {
    "detail": "reorder_would_violate_tree",
    "violations": [
      { "parent": "פוקוס (מדור)", "child": "אלומות (ענף)" },
      ...
    ]
  }
  ```
- On success: commits new ranks, returns updated list

### `DELETE /hierarchy/level-types/{id}`
- Auth: admin or duty_manager
- 409 if any `HierarchyNode.level == type.key`
- 204 on success

### `PATCH /hierarchy/nodes/{id}` (existing endpoint — extended)
- Add `level: str | None` to `UpdateNodeRequest`; remove the hard regex pattern from `CreateNodeRequest` (which currently only allows the 6 fixed keys) and replace with a runtime DB lookup that validates the key exists in `hierarchy_level_types`
- When `level` is provided: look up its rank, validate `rank > parent.rank` and `rank < min(children ranks)`
- 400 with `detail: "invalid_level_for_position"` if the level would violate the tree at this node's location

---

## Backend Service Changes

### `services/hierarchy.py`

Remove the hardcoded `LEVEL_ORDER` list and `_validate_child_level` helper.

Add a helper `_get_level_rank(session, level_key) -> int | None` that queries `HierarchyLevelType` for the rank of a given key.

Update `create_node`:
- Instead of `_validate_child_level(parent.level, level)`, fetch both ranks and check `child_rank > parent_rank`
- No longer restrict root nodes to a specific level key

Update `move_node`:
- Instead of `_validate_child_level(parent.level, node.level)`, fetch both ranks and check `node_rank > parent_rank`
- Remove the restriction on moving non-`corps` nodes to root

Add `reorder_level_types(session, ordered_ids, actor_id)`:
- Simulates new ranks, runs the tree violation check, raises `HierarchyError` if any violation found
- Commits new ranks and writes an audit entry

Add `create_level_type(session, key, label, actor_id)` and `delete_level_type(session, id, actor_id)`.

### Revert my earlier removal

During this session I removed the level validation from `move_node` and `create_node` as a hotfix. The implementation plan should reinstate validation using DB ranks, so those checks come back correctly.

---

## Frontend Changes

### New file: `api/levelTypes.ts`

Typed fetch wrappers for all 4 level-type endpoints. Exports:
- `listLevelTypes(): Promise<LevelTypeOut[]>`
- `createLevelType(key, label): Promise<LevelTypeOut>`
- `reorderLevelTypes(orderedIds: string[]): Promise<LevelTypeOut[]>`
- `deleteLevelType(id: string): Promise<void>`

### `RenameNodeDialog` → `EditNodeDialog`

Rename the component file and component name. Props stay the same plus `currentLevel: string` and `isAdmin: boolean`.

New layout:
1. **Name field** — unchanged
2. **Level dropdown** — fetches types from API; only shows types valid for the node's position (rank > parent's rank AND rank < min children's rank); selecting a different level calls `PATCH /hierarchy/nodes/{id}` with the new level on save
3. **Level type manager** (admin/DM only) — shown below the dropdown, a collapsible section titled "ניהול סוגי דרגות". Contains:
   - The DnD sortable list (using `@dnd-kit/sortable`)
   - Each row: drag handle icon + rank badge + label + delete button (✕, only if no nodes use this type)
   - Add-new-type row at the bottom: text input + "הוסף" button
   - Reorder is saved when the user clicks a "שמור סדר" button that appears when the list has been modified; if the reorder would violate the tree, show the violation list inline (no toast, inline error within the manager section)

### `AddChildNodeDialog` and `AddRootNodeDialog`

Replace the hardcoded `LEVEL_ORDER` constant with `useLevelTypes()` — a simple hook that calls `listLevelTypes()` on mount. The filtering logic (only show levels valid for the parent) uses ranks from the fetched data instead of array index arithmetic.

### `HierarchyTree.tsx`

Remove the local `LEVEL_ORDER` constant. The `canHaveChildrenFn` check (whether a node can have children added) should be replaced with: "can it have children" = its rank is not the maximum rank among all types — fetched from the same `useLevelTypes()` hook passed down as a prop or via context.

### `LEVEL_COLORS` in `HierarchyTree.tsx`

Currently keyed by English level key (`branch`, `group`, etc.). Since custom types won't have a corresponding color, fallback to a default color for unknown keys. The existing 6 keys keep their current colors.

---

## Enforcement Summary

| action | check |
|--------|-------|
| Create node under parent | `child_level.rank > parent_level.rank` |
| Move node to new parent | `node_level.rank > new_parent_level.rank` |
| Change node's level | `new_rank > parent_rank` AND `new_rank < min(children ranks)` |
| Reorder level types | no existing `(parent, child)` pair violates the new rank ordering |
| Delete level type | no existing node carries this level key |

---

## Migration

One Alembic migration:
1. Create `hierarchy_level_types` table
2. Insert the 7 seed rows
3. No changes to `hierarchy_nodes` — `level` stays a plain varchar

---

## Testing

- Unit tests for `reorder_level_types` covering: happy path, violation detection, partial ID list rejection
- Unit tests for updated `move_node` / `create_node` using DB-rank enforcement
- Integration test: reorder that causes violation returns 409 with violation list
- Frontend: update existing `HierarchyTree` tests that reference `LEVEL_ORDER` or level strings directly
