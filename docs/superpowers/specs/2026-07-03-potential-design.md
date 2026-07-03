# Potential-Based Duty Responsibility — Design

## Summary

Introduce a "potential" concept: for each hierarchy sub-unit, count how many
soldiers are eligible for at least one active duty type. This number drives
proportional responsibility splits when creating shifts (a sub-unit with more
eligible soldiers takes a proportionally larger share of a shift's slots),
and is manually auditable/adjustable via documented modifiers. Also adds a
new exemption category — פטור פיקודי (commander exemption) — which relieves
an individual soldier's duty burden without reducing their unit's potential
(so the burden concentrates on fewer soldiers within that unit).

## Goals

- Duty managers and commanders ranked רסן+ can see potential per sub-unit,
  for a chosen reference date (past, present, or future).
- Potential calculation is fully auditable: who is counted, who isn't, and why.
- Manual modifiers to potential require a documented reason and are themselves
  audited (who, when, why, what delta).
- New shifts auto-compute a proportional per-sub-unit quota split based on
  potential, editable by the duty manager before saving.
- New פטור פיקודי exemption category: single-step grant by רסן+ commanders
  or duty managers, or by a commander of a hierarchy node at level מדור or
  above (even if personally below רסן). Affects duty assignment eligibility
  but not potential.
- פטור רשמי (regular exemptions) move to a mandatory sequential dual-approval
  flow: commander (any rank, in scope) → duty manager (scoped to מרכז+).
  Replaces and removes the old `exemptions_require_rasn` global setting.
- Export the potential table to Excel for offline analysis/graphing.
- Document both new concepts in the help modal.

## Non-goals

- No caching/materialization of potential — always computed live against
  current data as of the reference date (see Approach A below).
- No automatic re-computation of quotas or assignments on a schedule —
  recompute is a manual, explicit action.
- Potential is not computed per-duty-type; it's binary per soldier ("eligible
  for at least one active duty type or not").

## Data Model

### `ExemptionType.is_commander_exemption: bool` (new column, default `False`)

Flags a type as פטור פיקודי:
- Grantable single-step (no `ExemptionRequest` approval cycle) by: rank
  רסן+, OR a commander of any hierarchy node at level מדור or higher
  (closer to root) — checked via `HierarchyLevelType.rank` ordering — OR
  a duty manager.
- Active exemptions of this type do **not** remove duty types from a
  soldier's eligible set for potential purposes (they still count toward
  potential), but **do** apply normally for actual duty assignment
  eligibility (the algorithm still won't assign them to duty types they're
  exempted from).

### `Soldier.next_rank_date: date | None` (new column)

When set and `next_rank_date <= reference_date`, potential/eligibility
calculations use the soldier's *next* rank instead of their current one.
Next rank is derived (not stored) by finding the soldier's current rank in
`ENLISTED_RANKS` or `OFFICER_RANKS` (whichever list contains it) and taking
the following entry; soldiers already at the top of their track keep their
current rank.

### `PotentialModifier` (new table)

```
id                uuid pk
hierarchy_node_id uuid fk -> hierarchy_nodes (RESTRICT)
delta             int (signed; can be negative or positive)
reason            text NOT NULL
start_date        date NOT NULL
end_date          date NULL
created_by        uuid fk -> soldiers (SET NULL)
created_at        timestamptz
```

Applies to the exact node named — not auto-inherited to descendants. Rollup
to ancestors happens at calculation time (see below), so a modifier deep in
the tree still surfaces in a top-level total.

### `ExemptionRequest` — dual approval

`status` transitions become: `pending_commander` → `pending_duty_manager` →
`approved`, with `rejected` reachable from either pending state. New column
`commander_approved_by: uuid | None` records the step-1 approver (existing
`decided_by` becomes the step-2/final DM approver, consistent with current
`SoldierExemption.granted_by` semantics).

The old `exemptions_require_rasn` setting and its associated rank check in
`exemption_requests.py` are deleted; the DM-scope-level check (מרכז+)
structurally replaces it.

### `DutyShiftNodeQuota` — no schema change

Auto-split quotas reuse the existing table and `set_shift_quotas` service
function as-is. The algorithm's proposed split (before any manual edit) is
recorded as an audit entry (`shift.potential_split_suggested`) rather than a
new column — combined with the existing `shift.set_node_quotas` audit
(before/after on save), this gives a full "algorithm proposed X, human saved
Y" trail without schema duplication.

## Potential Calculation

New `backend/app/services/potential.py`, pure function:

```python
def compute_potential(session, node_id, reference_date) -> PotentialResult
```

Algorithm:

1. Load all soldiers whose `path_ids` contains `node_id`, filtered to those
   still enlisted (not discharged) as of `reference_date`.
2. Resolve each soldier's rank as of `reference_date`: if
   `next_rank_date <= reference_date`, use the derived next rank (see above).
3. For each soldier, compute their eligible-duty-type set: start from all
   active duty types in the system, filter by rank requirements
   (`DutyTypeRequirements.allowed_ranks`) — **ignoring mitvahim/alal timing
   entirely** (always treated as satisfied for potential purposes) — then
   remove any duty type covered by an active **regular** (non-commander)
   `SoldierExemption` as of `reference_date` (via `is_global` or
   `ExemptionDutyTypeMap`). Active commander exemptions (`is_commander_exemption
   = True`) and personal constraints are **never** applied at this step.
4. A soldier counts toward potential iff their resulting eligible-duty-type
   set is non-empty.
5. Sum counts of directly-attached + descendant soldiers for `node_id`.
6. Apply all active `PotentialModifier` rows anywhere in the subtree
   (`start_date <= reference_date <= end_date or end_date is null`) as a
   signed sum on top of the raw count.
7. Result: `{node_id, raw_eligible_count, modifiers: [...], final_potential,
   as_of: reference_date}`.

This same function/result backs the table view, the audit drill-down (per
node: full soldier roster with eligible/excluded + reason, and modifier
list), and the shift auto-split algorithm.

No caching — recomputed on every request. At this org's scale (hundreds of
soldiers), this is fast and avoids invalidation bugs that would undermine
trust in an audited fairness number.

## Shift Auto-Quota Split

On shift create/edit (`required_count` or eligible scope changes):

1. Resolve the shift's eligible root node (from `eligible_node_ids`, or base
   root if unrestricted).
2. Compute potential for each **direct child** of that root, using the
   shift's start date as the reference date (the largest sub-hierarchies
   split first; the main assignment algorithm handles fair distribution
   within each sub-hierarchy).
3. Split `required_count` proportionally by potential ratio using
   largest-remainder rounding, so slot counts always sum exactly to
   `required_count`.
4. Auto-populate `DutyShiftNodeQuota` via the existing `set_shift_quotas`,
   pre-filled and editable in the UI (not silently applied) — the DM reviews
   and can override before saving.
5. Write a `shift.potential_split_suggested` audit entry with the computed
   split, before any manual edits.
6. The shift's "responsible" node (display-only) is the lowest common
   ancestor of all quota'd node paths, computed live from `path_ids` — not
   stored.
7. **Recompute quotas** action on existing shifts: re-runs the split using
   *current* data (today, not the shift's original creation date), useful
   for shifts scheduled far in advance where potential has since drifted.
   Never auto-saves; re-populates the editable table and writes a fresh
   suggestion audit entry.
8. **Re-run assignment algorithm** action: reuses the existing
   `ALGORITHM_RUN` flow, scoped to the shift's unassigned/reassignable
   duties — offered alongside recompute-quotas but triggered independently.

## Exemption Flows

### פטור רשמי (regular) — sequential dual approval

- Step 1: any commander with `Action.CONSTRAINT_APPROVE` in scope (unchanged
  rule — any rank) approves/rejects. `pending_commander` →
  `pending_duty_manager` or `rejected`.
- Step 2: a duty manager whose `DutyManagerScope` includes a node at
  hierarchy level מרכז or higher (closer to root) in the target soldier's
  path. `pending_duty_manager` → `approved` or `rejected`.
- UI: status-stage indicator across both steps.

### פטור פיקודי (commander) — single-step grant

- New direct-grant endpoint/action `Action.EXEMPTION_COMMANDER_GRANT`,
  gated by: rank רסן+ OR commanding a node at level מדור or above OR duty
  manager. Only exemption types with `is_commander_exemption = True` are
  selectable. Creates a `SoldierExemption` directly — no `ExemptionRequest`
  cycle.
- UI: simple form (soldier, exemption type, reason, dates) restricted to
  users who pass the above gate.

## Permissions

New `Action` constants in `authz.py`:
- `POTENTIAL_READ` — duty managers (any scope) + commanders ranked רסן+ (own
  scope only).
- `POTENTIAL_MODIFIER_MANAGE` — same gate as `POTENTIAL_READ`.
- `EXEMPTION_COMMANDER_GRANT` — gated per the פטור פיקודי rule above,
  distinct from existing `Action.EXEMPTION_GRANT`.

Dual-approval for פטור רשמי reuses `Action.CONSTRAINT_APPROVE` for step 1
(unchanged); step 2 needs a new scope-level check (DM scoped to מרכז+),
implemented alongside the existing `can()`/action-set pattern rather than a
new authorization mechanism.

## Frontend

- New route `/planning/potential`, added to `planningItems` in
  `UnifiedNav.tsx`. Table of the whole unit (tree or flat-with-indent,
  matching `TeamHierarchyPage` conventions): node name, raw eligible count,
  modifiers total, final potential, as-of date. Reference-date picker
  (default today).
- Row click → drill-down: soldier roster (eligible/excluded + reason) and
  modifier list (reason/creator/dates).
- "Export to Excel" button → new backend endpoint streaming `.xlsx` snapshot
  of the current table at the selected reference date.
- Modifier CRUD UI (reason required, optional end date), gated to
  `POTENTIAL_MODIFIER_MANAGE`.
- `CommandDashboardPage` (דף מפקד): new panel showing potential for the
  commander's own subunit(s), reusing the drill-down component, scoped via
  `scope_root_ids`.
- `ShiftsManagementPage`: quota table pre-filled from auto-split, with
  "Recompute quotas" and "Re-run assignment algorithm" actions on existing
  shifts.
- Exemption request screens: status-stage indicator for the two-step flow;
  separate simple form surface for direct פטור פיקודי grants.

## Help Modal

Two new entries added to the existing icon/title/desc card pattern in
`HelpModal.tsx`:
1. **פוטנציאל** — what it counts, how it's excluded/included (regular
   exemptions reduce it; commander exemptions and constraints and
   mitvahim/alal timing do not), how it drives shift responsibility splits,
   how to audit it.
2. **פטור פיקודי** — who can grant it, that it relieves the individual
   without reducing unit potential (so remaining soldiers absorb more
   burden), explicit guidance to use sparingly and only in special cases.

## Open Questions / Follow-ups for Implementation Planning

- Exact Excel export library/pattern to mirror from `import_excel.py`.
- Whether `PotentialModifier` audit trail needs its own dedicated view or
  reuses the existing generic audit log viewer.
- Test coverage plan: potential calculation edge cases (reference dates
  crossing rank/discharge transitions, modifier date-range boundaries,
  empty-eligible-set edge cases) belongs in `backend/app/services/tests/`
  following existing conventions.
