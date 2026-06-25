# RBAC Capability Model Fix

## Problem

`Soldier.role` is a single string (`soldier` | `commander` | `duty_manager` | `admin`). Several code
paths treat it as the sole source of truth for authorization. But a soldier can simultaneously:

- command one hierarchy node (`HierarchyNode.commander_id == soldier.id`), and
- be a duty manager of other nodes (`DutyManagerScope.duty_manager_id == soldier.id`).

Today, whichever of `set_commander()` or `assign_dm_scope()` runs last silently overwrites
`Soldier.role`, which breaks the other capability's permission checks (e.g. a commander who is also
made a duty manager loses `DM_SCOPE_MANAGE`, since that's only granted to `role == "commander"`).

This is a prerequisite for the upcoming hierarchy-page duty-manager-assignment feature, which will
make dual-capability soldiers far more common.

## Goal

Stop deriving authorization decisions from `Soldier.role` for the commander/duty_manager
distinction. Derive them from the actual underlying data instead. `role` becomes a **read-only,
recomputed display label** — never a target of direct mutation by any API request, and never
consulted for permission decisions except the `admin` check.

`is_commander` / `is_duty_manager` are **derived, read-only** facts, computed from
`HierarchyNode.commander_id` and `DutyManagerScope` rows respectively. There is no endpoint or modal
that sets them directly — they only change as a side effect of `set_commander()` (hierarchy page,
existing) and `assign_dm_scope()` / `remove_dm_scope()` (duty-manager feature, sub-project #2,
existing service functions).

## Backend changes

### `app/auth/authz.py`

- Add two helpers:
  ```python
  def is_commander(session: Session, soldier_id: uuid.UUID) -> bool: ...
  def is_duty_manager(session: Session, soldier_id: uuid.UUID) -> bool: ...
  ```
  Each a cheap `EXISTS`-style query (`select(...).limit(1)` + `.first() is not None`).

- Fix `scope_root_ids()`: currently only unions `DutyManagerScope` nodes
  `if user.role == "duty_manager"`. Remove that guard — always union them. Commander nodes are
  already unioned unconditionally.

- Rewrite `can()` to stop switching on `user.role` for the commander/duty_manager branches. New shape:
  ```python
  def can(user, action, *, target_node, roots, is_commander, is_duty_manager) -> bool:
      if user.role == "admin":
          return True
      allowed = False
      if is_duty_manager:
          if action in _DM_GLOBAL_ACTIONS:
              return True
          if action in _DM_ACTIONS and _node_in_scope(target_node, roots):
              allowed = True
      if is_commander:
          if action == Action.DM_SCOPE_MANAGE:
              if user.rank in RANKS_RASAN_AND_ABOVE and _node_in_scope(target_node, roots):
                  allowed = True
          elif action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots):
              allowed = True
      return allowed
  ```
  A dual-capability soldier gets the union of both action sets, each correctly scoped.

- `authorize(session, user, action, *, target_node)` computes `is_commander`/`is_duty_manager`
  internally before calling `can()`. Its signature does not change, so none of its ~10 existing call
  sites in routes need to change.

- `can_see_private()`: replace `viewer.role in ("duty_manager", "commander")` with
  `is_commander(session, viewer.id) or is_duty_manager(session, viewer.id)`.

### Other backend call sites that bypass `can()`/`authorize()`

These check `user.role` directly and must switch to the new helpers:

- `routes/hakpaza.py`: `_COMMANDER_ROLES = {"commander", "duty_manager", "admin"}` and
  `_APPROVER_ROLES = {"duty_manager", "admin"}` membership tests become
  `user.role == "admin" or is_commander(...) or is_duty_manager(...)` and
  `user.role == "admin" or is_duty_manager(...)` respectively (matching current semantics, just
  capability-driven).
- `routes/algorithm.py` line ~356: `is_dm = user.role in ("duty_manager", "admin")` becomes
  `is_dm = user.role == "admin" or is_duty_manager(session, user.id)`.
- `routes/soldiers.py` line ~433: `include_drafts and user.role not in ("duty_manager", "admin")`
  becomes the negation of the same capability check.
- `routes/soldiers.py` lines ~403, ~428 (`!= "soldier"` / "is plain soldier" checks): these test "is
  this user elevated at all," which the recomputed `role` label still answers correctly (a
  dual-capability soldier's label is never `"soldier"`). Verify with a test case during
  implementation; no helper-based rewrite needed unless the test reveals otherwise.

### Role-label recompute

Add `recompute_role(session: Session, soldier: Soldier) -> None` (in `services/dm_scope.py`, the
existing home of role-mutation logic) implementing the priority rule:

```python
def recompute_role(session, soldier):
    if soldier.role == "admin":
        return
    if is_commander(session, soldier.id):
        soldier.role = "commander"
    elif is_duty_manager(session, soldier.id):
        soldier.role = "duty_manager"
    else:
        soldier.role = "soldier"
```

Call sites:

- `services/hierarchy.py::set_commander()`: call for the newly-assigned commander, **and** for
  whoever was previously commanding that node if displaced (they may now fall back to
  `duty_manager` or `soldier` instead of staying stuck on `commander`).
- `services/dm_scope.py::assign_dm_scope()` / `remove_dm_scope()`: replace their current ad-hoc
  `soldier.role = ...` mutations with calls to `recompute_role()`.

`recompute_role` is internal plumbing only — never exposed as something a request body can set.

## Frontend changes

- `Me` (`frontend/src/api/auth.ts`) and `SoldierDTO` gain two server-computed, read-only fields:
  `is_commander: boolean`, `is_duty_manager: boolean`. No request type gains these fields — they are
  response-only.
- Replace `role === "commander"` / `role === "duty_manager"` *permission* gates with these booleans:
  - `components/UnifiedNav.tsx` (`canApprove`, `canPlan`)
  - `pages/ProfilePage.tsx` (notification-scope section gate)
  - `components/UnifiedSoldierModal.tsx` (`isDutyManager`, `isCommander`, `canManage`, `canViewAll`)
  - `pages/HomePage.tsx` (`canApprove`)
  - `components/ShiftDetailPanel.tsx` (`canGimelim`)
  - `pages/TeamHierarchyPage.tsx` (`canManageLevelTypes`)
- Pure display spots (role badge text in soldier tables/dropdowns, e.g. `AssignCommanderDialog.tsx`,
  `t(\`role.${s.role}\`)` cells) keep reading `role` unchanged — they're labels, not gates.

## Data model

No new tables or columns. `Soldier.role` keeps its current column; only its write semantics change
(recomputed, never directly settable to `commander`/`duty_manager` by request bodies — it already
isn't, since no route accepts `role` as input today).

## Edge cases

- A soldier who commands node A and is later also made DM of node B: must retain `DM_SCOPE_MANAGE`
  over A (commander capability) and `_DM_ACTIONS`/`_DM_GLOBAL_ACTIONS` over B (duty-manager
  capability) simultaneously. Their `role` label displays `"commander"` (priority), but this no
  longer affects what they can actually do.
- A commander is displaced from node A (someone else is set as commander there) while having no DM
  scopes: `recompute_role` must drop them to `"soldier"`, not leave them stuck at `"commander"`.
- A duty manager's last `DutyManagerScope` row is removed while they also command a node: must end
  up labeled `"commander"` (already roughly how `remove_dm_scope` works today, but now routed through
  the shared `recompute_role` for consistency).
- Admins are never touched by `recompute_role`, regardless of commander/DM data.

## Testing

- Backend (`pytest -m auth`): dual-role fixture (soldier commands node A, is DM of node B) exercising
  `DM_SCOPE_MANAGE` on A and `_DM_ACTIONS`/global DM actions on B simultaneously; commander-displacement
  recompute; DM-scope-removal recompute when also a commander; hakpaza approver/initiator checks and
  algorithm-explanation redaction for the dual-role fixture.
- Frontend (`npm test`): nav/tab/profile-gate components re-tested with `is_commander`/`is_duty_manager`
  props/fixtures instead of role strings, including a dual-role fixture.
