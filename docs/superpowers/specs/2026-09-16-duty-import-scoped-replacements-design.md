# Duty import, scoped replacements, and modal layering

## Status

Approved direction, pending implementation review.

## Goals

This change covers the following related workflows:

1. Keep the existing system-level range-qualification option, expose its effective value when starting an algorithm run, and let each run override it.
2. Make nested modals render in the order they were opened. A modal opened later must be above an earlier modal, regardless of which component owns it.
3. Restrict a duty manager to replacing assignments and replacement candidates inside that manager's scope. The API is authoritative and the GUI must hide unavailable actions.
4. Change the algorithm-results action from “reject” to “replace”. Open the assignments modal for the same shift, support a scoped manual replacement, and offer the best eligible replacement using scores that include current draft assignments.
5. Make Excel assignments with a valid duty type/location/date create a duty shift when no matching shift exists. Duty type selection in the review UI must remain available until the assignment actually has a resolved type.

## Design decisions

### Excel assignments

The import parser continues to parse assignment rows independently of duty-shift rows. During session resolution, an assignment gets a `resolved_duty_type_id` as soon as its type is resolved, even if no existing shift matches it. This separates “type is unresolved” from “shift needs to be generated”.

When all fields needed to identify a shift are valid but no existing or imported shift matches, the assignment is marked as a new assignment with a stable generated-shift key and a warning that the shift will be created on confirmation. Rows with the same type, location, dates, and times share one key. The generated shift is created only if at least one associated assignment remains selected, so skipped rows do not leave orphan shifts.

The confirmation transaction creates each required generated shift before its assignments and maps the stable key to the new shift ID. Generated shifts use the assignment time range, with the existing import defaults of `00:00` and `23:59` when times are absent. Primary and reserve counts are derived from the selected associated assignments. A generated shift is still subject to the same validation and audit behavior as a regular imported shift.

The review page displays the duty-type combobox when `resolved_duty_type_id` is absent, not merely when the whole assignment row has an error. Selecting a type therefore remains visible while the shift-matching warning is being resolved.

### Range-qualification settings

The existing system key `weapon_qualification.enforce_eligibility` remains the source of the default. The algorithm-defaults response includes the effective system value. The run form initializes its checkbox from that response and sends the value explicitly; the backend continues to resolve an omitted value from the system setting for compatibility with existing clients.

### Modal stack

Add one application-level modal stack allocator. Each participating modal registers when it opens and receives a monotonically increasing layer number. Closing releases the registration; reopening obtains a new highest layer. The rendered z-index is derived from that layer, with a shared base above ordinary page content and below intentional in-modal controls such as dropdowns.

The duty-detail modal, shift/event detail modal, and unified soldier modal all use the allocator. This makes the soldier modal opened from a shift modal appear above the shift modal while preserving the same rule for other modal combinations. The stack is based on opening order, not nesting depth or a hard-coded “child modal” z-index.

### Scoped replacements

The backend remains the source of truth. For a non-admin duty manager:

- Candidate queries return only soldiers in that manager's scope.
- Assignment replacement validates both the assignment's current soldier and the replacement soldier against that scope.
- Existing assignment-management endpoints retain their current authorization checks and gain the same per-soldier scope enforcement where they mutate an individual assignment.
- Calendar assignee data includes a capability flag calculated by the backend so the GUI does not offer replacement controls for out-of-scope people.

Administrators retain unrestricted behavior. Scope filtering is applied to replacement candidates, not to unrelated read-only shift data.

Use one atomic replacement endpoint for both ordinary shift editing and algorithm-result replacement. It receives the shift, assignment, and replacement soldier, validates the shift/assignment relationship, scope, eligibility, duplicate constraints, and capacity as appropriate, then updates the existing assignment. This preserves the assignment identity and its draft/published state, avoids a remove-then-add race, and records the old and new soldier in the existing audit mechanism.

### Algorithm-result replacement

The proposal table passes the selected proposal's shift and assignment to the assignments modal and labels the action “replace”. The modal uses the atomic replacement endpoint when a target assignment is supplied.

Replacement candidates include a draft-aware burden score for this workflow. The score counts the current active draft assignments together with published assignments and excludes the assignment being replaced. The backend applies the same eligibility and scope filters before scoring. The modal offers an automatic choice that selects the lowest-scoring eligible candidate; the user can then accept that choice or select another candidate from the displayed scoped list.

After replacement, the proposal data is refreshed so the soldier, score, and status shown in the results reflect the updated draft assignment.

## Verification plan

Add focused regression coverage for:

- assignment type resolution with no matching shift, generated-key reuse, confirmation-created shift, and no orphan shift when rows are skipped;
- algorithm defaults inheriting the system range setting and explicit per-run overrides;
- modal layers increasing by opening order and increasing again after reopen;
- scoped candidate filtering and server rejection of out-of-scope target/replacement soldiers;
- GUI hiding out-of-scope replacement actions and rendering the new “replace” flow;
- draft-aware candidate ordering and automatic replacement selection.

Run the focused backend and frontend tests first, then the normal backend suite, frontend tests, lint, typecheck, and build where the worktree dependencies permit. Report any dependency/setup limitation separately from test failures.
