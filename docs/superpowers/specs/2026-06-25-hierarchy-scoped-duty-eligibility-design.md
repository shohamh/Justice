# Hierarchy-Scoped Duty Eligibility

## Problem

There is currently no way to restrict a duty type to a specific part of the org chart. A DM
cannot say "only ענף פוקוס may be assigned to this duty" — every soldier is a candidate for every
duty type, system-wide.

A scoping mechanism already exists, but only at the `DutyShift` level
(`eligible_node_ids: list[UUID] | None`), and it has two problems:

1. **No cascade.** It must be set manually on every individual shift; there's no way to set a
   default at the duty-type or template level so newly created shifts inherit it.
2. **Exact-node match, not subtree match.** [`solver.py:175-177`](../../../backend/app/algorithm/solver.py)
   and [`routes/shifts.py:278`](../../../backend/app/routes/shifts.py) only match a soldier whose
   `hierarchy_node_id` is *exactly* one of the listed nodes. A soldier in a sub-team under the
   scoped node does not match, even though the existing frontend UI for this
   (`AlgorithmRunForm`'s "restrict to subtree" picker) implies subtree semantics. This is a latent
   bug independent of the new feature.

## Goal

- Let a DM set eligibility scope (one or more hierarchy nodes) on a `DutyType`, a `ShiftTemplate`,
  or an individual `DutyShift`.
- Scope cascades by copy-down at creation time: shift inherits from template (if generated from
  one) or duty type (if standalone); template inherits from duty type. Each level is editable
  after creation as an independent override — later changes to a parent do not retroactively
  affect already-created children.
- Fix the existing matching logic to be subtree-aware everywhere it's used, and exclude
  unassigned soldiers from scoped duties.

## Non-goals

- No new RBAC action or capability. Duty type / template / shift management remains gated by the
  existing `require_duty_manager_or_admin` dependency / `Action.SHIFT_MANAGE`, unscoped to
  hierarchy nodes — same as today.
- No retroactive re-scoping of existing shifts when a duty type's or template's scope changes.

## Data model

Add the same field already on `DutyShift` to the two other levels:

- `DutyType.eligible_node_ids: list[UUID] | None` (new column, JSONB or ARRAY(UUID) to match
  `DutyShift.eligible_node_ids`'s existing column type)
- `ShiftTemplate.eligible_node_ids: list[UUID] | None` (new column, same type)

`None` continues to mean "unrestricted" at every level.

### Cascade (copy-down at creation)

- **Creating a `ShiftTemplate`:** if the form doesn't override it, `eligible_node_ids` defaults to
  the chosen `DutyType.eligible_node_ids` at the moment of creation. Stored as a plain copy —
  editable afterward, independent of the duty type from then on.
- **Generating a `DutyShift` from a `ShiftTemplate`:** `eligible_node_ids` copies from the
  template's value at generation time.
- **Creating a standalone `DutyShift`** (no template): `eligible_node_ids` copies from the chosen
  `DutyType.eligible_node_ids` at creation time.
- In all cases the destination field can be edited/cleared afterward as a one-off override; this
  has no effect on the source.

## Eligibility matching (subtree-aware, fixed everywhere)

Today's check effectively is:

```python
if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
    if s.hierarchy_node_id not in d.eligible_node_ids:
        continue
```

New behavior:

- A soldier matches a scope if **any node in `eligible_node_ids` appears in the soldier's
  ancestry** (i.e. `scope_node_id in soldier.path_ids`, mirroring the ancestry check already used
  in `app/auth/authz.py`'s `_node_in_scope`), or the soldier's own `hierarchy_node_id` is itself
  one of the scoped nodes (a node is in its own subtree).
- **Unassigned soldiers** (`hierarchy_node_id is None`) are now excluded from any duty/shift that
  has a non-null `eligible_node_ids` — this flips today's bypass behavior, which silently treated
  unassigned soldiers as eligible for everything.

This single matching change ripples through every consumer of `eligible_node_ids`, with no change
to their call sites' control flow:

- `app/algorithm/solver.py` (`_eligible_pairs`)
- `app/algorithm/model.py` (`build_model`'s pre-filter)
- `app/routes/shifts.py` (candidate-listing endpoint, line ~278)
- `AlgorithmRunForm` / `AlgorithmInlinePanel`'s ad-hoc "restrict to subtree" picker — gets correct
  subtree semantics for free since it shares the same matching code.

`SoldierInput` (in `app/algorithm/types.py`) currently carries `hierarchy_node_id` but not
`path_ids`. It needs `path_ids: list[UUID]` added so the solver can do the ancestry check without
extra DB round-trips per soldier.

## API changes

- `DutyType` create/update request schemas (`app/routes/duty_config.py`) gain
  `eligible_node_ids: list[UUID] | None`.
- `ShiftTemplate` create/update request schemas (`app/routes/shift_templates.py`) gain
  `eligible_node_ids: list[UUID] | None`, with create-time default-from-duty-type behavior
  implemented in the service layer (not the route), so the cascade logic is testable independent
  of the HTTP layer.
- `DutyShift` create path (manual creation and template-generation) implements the same
  default-from-parent behavior in the service layer. The existing `UpdateShiftRequest.eligible_node_ids`
  field (already present) is unchanged — it remains the override mechanism.
- Candidate-listing endpoint (`routes/shifts.py`) and `app/services/shifts.py` use the new
  subtree-aware matching helper instead of the inline `not in` check.

## Frontend

Reuse the existing `SubHierarchySelector` tree-checkbox component (currently only wired into
`AlgorithmRunForm`/`AlgorithmInlinePanel`) in three more places:

- `DutyTypeFormModal` — new collapsible "eligible units" section.
- `ShiftTemplateFormModal` — same, pre-populated from the chosen duty type's scope when the modal
  opens in create mode (editable before saving).
- `ShiftFormModal` (and/or the shift edit-assignments flow) — same, pre-populated from the
  template's or duty type's scope when generating/creating, editable afterward as an override.

No new pages or routes. No RBAC/permission UI changes — the section is visible/editable to
whoever can already manage that duty type, template, or shift.

## Testing

- Backend: unit tests for the new subtree-matching helper (node itself matches, descendant
  matches, unrelated node doesn't, unassigned soldier excluded when scope is set, no scope means
  everyone matches).
- Backend: service-layer tests for cascade copy-down (template defaults from duty type unless
  overridden; shift defaults from template or duty type unless overridden; later parent changes
  don't affect already-created children).
- Backend: existing algorithm/solver tests that exercise `eligible_node_ids` should be checked —
  some may currently assert exact-match behavior and need updating to reflect subtree semantics.
- Frontend: `SubHierarchySelector` already has coverage from its algorithm-run usage; add minimal
  tests confirming the three modals pre-populate and submit the field correctly.
