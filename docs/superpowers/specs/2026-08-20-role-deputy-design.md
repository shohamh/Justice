# Commander / duty-officer deputies (ממלא מקום)

## Problem

A commander or duty-officer (אחראי תורנויות) sometimes needs someone to
temporarily act with their authority — e.g. while away. Today the only way
to grant that is a permanent reassignment (change who commands a node, or
add/remove a `DutyManagerScope` row), which has no time bound and requires
explicitly reverting it afterward. The user wants a first-class, time-limited
"deputy" concept: define one or more deputies, each with a start and end
date, who gain the same permissions as the commander/duty-officer for the
duration of their window — with zero ongoing maintenance (no reverting
required; the grant just expires).

## Data model

New table `role_deputies`:

| column | type | notes |
|---|---|---|
| `id` | uuid pk | |
| `principal_id` | uuid, FK soldiers | the commander/duty-officer being deputized for |
| `deputy_id` | uuid, FK soldiers | the soldier acting as deputy |
| `role` | enum(`commander`, `duty_manager`) | which capability of the principal's is being deputized |
| `start_date` | date, not null | |
| `end_date` | date, not null | no open-ended deputies |
| `created_by` | uuid, FK soldiers, nullable | who set it up (self or admin) |
| `created_at` | timestamptz | |

Constraints:
- `end_date >= start_date`.
- Unique on `(principal_id, deputy_id, role)` — no duplicate identical grants. Multiple *different* deputies per principal are allowed; a soldier may be a deputy for multiple principals simultaneously.
- No recursion: a deputy cannot themselves name a sub-deputy — creation is rejected if `deputy_id` is currently (today) an active deputy for anyone, for the relevant `role`. (Being a deputy for `commander` doesn't block also being named a deputy for `duty_manager`, or vice versa — the recursion check is per-role.)
- At creation time, `principal_id` must actually hold the named `role` right now (`is_commander`/`is_duty_manager`) — a deputy grant references a *capability*, not a *node*, so if the principal later stops commanding that node (or starts commanding a different one), the deputy's effective scope moves with them automatically (this is a feature, not a bug: "act as X" should track whatever X's current scope is).

"Active" means `start_date <= today <= end_date`, evaluated live at read time — no scheduled activation/deactivation job, matching how `is_commander`/`is_duty_manager` are already computed live per-request.

## Authorization — consolidate, then extend

`HierarchyNode.commander_id` and `DutyManagerScope` are currently queried
directly and inline in about ten places, not always through the two central
lookup functions (`is_commander`/`scope_root_ids` in `app/auth/authz.py`).
Making a deputy's access genuinely match the principal's everywhere requires
first eliminating that duplication:

1. Add two new shared functions in `app/auth/authz.py`:
   - `commanded_node_ids(session, soldier_id) -> set[uuid.UUID]` — nodes this soldier commands directly, **plus** the commanded nodes of every principal for whom this soldier is an active `commander`-role deputy today.
   - `dm_scope_node_ids(session, soldier_id) -> set[uuid.UUID]` — this soldier's own `DutyManagerScope` nodes, **plus** the DM-scope nodes of every principal for whom this soldier is an active `duty_manager`-role deputy today.
2. Refactor `is_commander`, `is_duty_manager`, `scope_root_ids`, and `can_view_medical_document` in `authz.py` to call these two functions instead of inlining `select(...).where(commander_id == ...)` / `where(duty_manager_id == ...)`.
3. Refactor the other files that currently inline the same queries to call the shared functions too:
   - `app/services/authority.py` — `rank_advancement_edit_authorized`, `range_attendance_edit_authorized`, `commander_can_grant_commander_exemption`, `duty_manager_exemption_immediate_apply_authorized`, `has_any_exemption_immediate_apply_scope`, `commander_delete_soldier_authorized`, `has_any_commander_delete_scope`, `_commanded_nodes`, `_dm_scope_nodes`, `can_view_soldier_scope`, `has_any_visibility`.
   - `app/routes/commander_dashboard.py` — `_commander_node`.
   - `app/routes/exemption_requests.py` — the DM-scope lookup used for exemption approval-stage authorization.
   - `app/routes/range_qualification_visibility.py` — `_resolve_roots`.
   - `app/services/hierarchy_transfers.py` — `list_pending_for_approver`.

Deliberately **out of scope** (not scope/authorization checks, so deputies
don't change them):
- `app/routes/me.py` and `app/routes/soldiers.py`'s "who is my direct
  commander" display logic — a deputy shouldn't appear as anyone's org-chart
  commander, only their *permissions* extend.
- `app/services/hierarchy.py`'s commander-reassignment mutation and
  `app/services/dm_scope.py`'s scope-assignment mutation — these *write*
  `commander_id`/`DutyManagerScope`, unrelated to deputy read-time checks.
- `SwapManagerApproval.commander_id` — a historical field on approval
  records (who approved), not a scope check. A deputy acting on an approval
  records their own `id` as approver, not the principal's.
- `CommanderNotificationScope` — a commander's personal notification-depth
  subscription (see `ProfilePage`'s existing "commander scopes" UI), a
  different concept from authorization scope. Handled separately below.

## Notifications

`cascade_to_commanders` and `notify_duty_managers_in_scope` /
`notify_duty_managers_of_request` (all in `app/services/notifications.py`)
get extended the same way, computed live at send time:

- `cascade_to_commanders`: after resolving the set of commander ids from
  `CommanderNotificationScope` rows covering the soldier's node path, also
  include any soldier who is currently an active `commander`-role deputy for
  one of those commanders.
- `notify_duty_managers_in_scope` / `notify_duty_managers_of_request`: after
  resolving the set of duty-manager ids from `DutyManagerScope`, also include
  any soldier who is currently an active `duty_manager`-role deputy for one
  of those duty managers.

No changes to `CommanderNotificationScope` itself — a deputy inherits the
principal's *existing* subscription rows for the duration of the window,
rather than needing their own.

## Assignment — self-service and admin

New routes:
- `POST /soldiers/{principal_id}/deputies` — create a deputy grant.
- `GET /soldiers/{principal_id}/deputies` — list a principal's deputies (past, active, future).
- `DELETE /deputies/{id}` — revoke early.

Authorized via: the principal themselves (only if they currently hold the
named role) or an admin. Not the principal's own commander/duty-manager
chain — deliberately narrow to match "self-service or admin" from the
requirements.

One shared `DeputiesPanel` React component, rendered in two places:
- `ProfilePage` — self-service, visible only when the logged-in user
  currently `is_commander` or `is_duty_manager`.
- `UnifiedSoldierModal` — the existing admin-edits-a-soldier surface, so an
  admin can manage deputies for someone else. Visible only to admins, and
  only when the target soldier currently holds a deputizable role.

Each panel: form to add a deputy (soldier picker, role — auto-derived if the
principal only holds one of the two roles, otherwise a choice — start date,
end date), and a list of existing grants (active/future/expired, each with a
revoke button for non-expired ones).

## Visibility

A deputy should understand why they suddenly have extra permissions:
- A banner on `HomePage`, shown only while at least one of the logged-in
  user's deputy grants is currently active: "פועל/ת כממלא/ת מקום עבור
  \<principal name\> (\<role\>) עד \<end_date\>."
- The deputy list itself, visible in the principal's `DeputiesPanel`.

## Out of scope for this pass

- No approval workflow for creating a deputy grant (self/admin action is
  immediate, matching how commander/DM assignment already works elsewhere).
- No email/Telegram-specific deputy notification copy — deputies receive the
  same notification types through the same channels the principal would,
  using existing notification preference infrastructure.
- No UI badge on the hierarchy tree marking a node's active deputies (only
  the homepage banner and the profile panel surface this).
