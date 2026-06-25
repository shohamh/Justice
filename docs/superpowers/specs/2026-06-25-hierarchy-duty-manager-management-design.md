# Hierarchy-Page Duty-Manager Management

## Problem

Today the hierarchy page (`TeamHierarchyPage` / `HierarchyTree`) lets an admin assign a single
commander per node ("קביעת מפקד") but has no UI for assigning duty managers, even though the
backend already fully supports it: `DutyManagerScope` (a soldier can be DM of multiple nodes, a
node can have multiple DMs), `services/dm_scope.py::assign_dm_scope`/`remove_dm_scope`, and
`routes/dm_scope.py`'s `POST`/`DELETE /duty-manager-scope` (both already authorize via
`Action.DM_SCOPE_MANAGE`, which restricts to admins or commanders ranked רס״ן and above whose
scope covers the target node).

This is sub-project #2, building on the now-completed RBAC capability-model fix
(`docs/superpowers/specs/2026-06-25-rbac-capability-model-design.md`), which made `is_commander`/
`is_duty_manager` independently derived from real data — necessary here because a commander who is
made a duty manager elsewhere must keep both capabilities.

## Goal

Add two modals to the hierarchy page:

1. **קביעת אחראי תורנויות** — assign/remove duty managers for one hierarchy node.
2. **אחריות אחראי תורנויות** — view/edit one duty manager's full portfolio of nodes.

Both are gated so only admins, and commanders (rank רס״ן+) whose own scope covers the relevant
node(s), can edit. Like `is_commander`/`is_duty_manager`, a soldier's DM status is never set
directly — only as a side effect of these two modals calling the existing `assign_dm_scope`/
`remove_dm_scope` service functions.

## Backend changes

### `NodeOut` (`backend/app/routes/hierarchy.py`)

Add two fields, both computed in `_out()`:

```python
class DutyManagerEntryOut(BaseModel):
    scope_id: uuid.UUID
    soldier_id: uuid.UUID
    name: str


class NodeOut(BaseModel):
    ...
    duty_managers: list[DutyManagerEntryOut] = []
    dm_manageable: bool = False
```

- `duty_managers`: every `DutyManagerScope` row for this node, joined to `Soldier.full_name`. Lets
  the tree render DM names the same way it already renders `commander_name`, and gives the
  modal-1 UI the `scope_id` it needs to call `DELETE /duty-manager-scope/{id}`.
- `dm_manageable`: `can(user, Action.DM_SCOPE_MANAGE, target_node=n, roots=scope_root_ids(session, user), is_commander=is_commander(session, user.id), is_duty_manager=is_duty_manager(session, user.id))`. Computing this server-side means the frontend never re-implements the rank/scope rule — it just reads a boolean per node.

`_out()` already takes `_session: Session | None` (used today only for `commander_name`); both new
fields are computed there too, using the already-authenticated `user` available in each route
handler (passed through as a new required parameter to `_out()`, since unlike `commander_name`
this is viewer-specific, not absolute).

### `GET /duty-manager-scope` (`backend/app/routes/dm_scope.py`)

Today: `user.role != "admin" and user.id != soldier_id` → 403 (admin or self only). This blocks a
commander from viewing/managing a DM's portfolio for nodes within their own scope — needed for
modal 2's commander entry point (soldier-table row).

New rule: build the result set from all `DutyManagerScope` rows for `soldier_id`, then:
- if `user.role == "admin"` or `user.id == soldier_id`: return all of them (existing behavior, now also explicitly allowing self-view).
- otherwise: filter to entries whose node is in `scope_root_ids(session, user)`'s subtree (using
  the same `_node_in_scope` helper `authz.py` already exports), returning an empty list rather than
  403 if none match. A commander who manages nothing of this DM's portfolio sees an empty list, not
  an error — consistent with "show what you can manage," not "tell me you have no access."

`POST`/`DELETE /duty-manager-scope` are unchanged — they already authorize per-node correctly.

## Frontend changes

### Modal 1 — `AssignDutyManagersDialog.tsx` (new, modeled on `AssignCommanderDialog.tsx`)

Props: `node: NodeDTO` (now carrying `duty_managers`/`dm_manageable`), `onClose`, `onAssigned`.

- Lists current `node.duty_managers` with a name and a ✕ button per entry (calls
  `DELETE /duty-manager-scope/{scope_id}`, then `onAssigned()` to refetch).
- Below the list, the same Fuse.js soldier-search box pattern as `AssignCommanderDialog` — picking
  a soldier calls `POST /duty-manager-scope` with `{ soldier_id, node_id: node.id }`, then
  `onAssigned()`. The list stays open after each add/remove so multiple changes can be made in one
  sitting (no auto-close).
- Any soldier in the org can be picked (consistent with how `AssignCommanderDialog` doesn't
  pre-filter by node) — the backend rejects out-of-scope assignments via `authorize()`.

### Modal 2 — `DutyManagerPortfolioDialog.tsx` (new)

Props: `soldierId: string`, `soldierName: string`, `onClose`, `onChanged`.

- On open, calls `GET /duty-manager-scope?soldier_id=...` (now scope-filtered per the backend
  change above) and renders each entry's node name (resolved from the already-loaded `nodes` array
  passed in as a prop) with a ✕ to remove.
- A `Combobox` (reusing the existing component already used for the soldier-onboarding form) lists
  nodes to add a new one — filtered to `nodes.filter(n => n.dm_manageable)`, so the picker never
  offers a node the current viewer can't actually assign.
- Add calls `POST /duty-manager-scope` with the chosen node id; remove calls `DELETE`. Both
  re-fetch the list afterward.

### `HierarchyTree.tsx` integration

- Each node row gains a green "קביעת אחראי תורנויות" button next to "קביעת מפקד", visible when
  `node.dm_manageable` (not gated by the existing `isAdmin` prop — this is the one action commanders
  can also perform, unlike add-child/rename/delete/assign-commander which stay admin-only,
  consistent with current backend `HIERARCHY_MANAGE` semantics being admin-exclusive).
- Each node row renders `node.duty_managers` as a comma-separated list of clickable names (similar
  styling to the existing `commander_name` span), each opening `DutyManagerPortfolioDialog` for that
  soldier.

### Soldier table (`TeamHierarchyPage.tsx`)

- One new action link per row, "ניהול אחריות תורנויות", visible to admin or any commander (since
  the modal itself filters to what that viewer can edit) — opens `DutyManagerPortfolioDialog` for
  that row's soldier.

## Data flow / error handling

- All mutations (`POST`/`DELETE /duty-manager-scope`) are re-authorized server-side regardless of
  what the frontend shows — `dm_manageable` and the portfolio's node filtering are UX conveniences,
  not the security boundary.
- A 400 from `POST /duty-manager-scope` (e.g. soldier/node not found) surfaces as a generic
  `alert(t("errors.generic"))`, matching the existing pattern in `HierarchyTree.tsx`'s
  `handleDelete`/`handleQuickAdd`.
- Removing a DM's last scope entry triggers `recompute_role` (existing behavior from sub-project
  #1) — the UI doesn't need to special-case this; the next `fetchTree()`/soldier-list refresh will
  reflect the updated `role` label automatically.

## Testing

- Backend: `pytest -m hierarchy` — new tests for `NodeOut.duty_managers`/`dm_manageable` reflecting
  real data and viewer-specific scope; `GET /duty-manager-scope` scope-filtering for a commander
  (sees only in-scope entries, not all of a DM's portfolio); confirm `POST`/`DELETE` behavior is
  unchanged (existing tests in `test_dm_scope_routes.py` should keep passing).
- Frontend: `npm test` — new tests for `AssignDutyManagersDialog` (add/remove flow) and
  `DutyManagerPortfolioDialog` (add/remove flow, node-list filtering to `dm_manageable`); a
  `HierarchyTree.test` (if one doesn't exist, a new one) for the new button's visibility gating on
  `dm_manageable` and the DM-name click target.
