# Task 8 Swaps node clear follow-up

The previous `HierarchyNodeFilter` included an in-popover clear action that reset selected node IDs only. The paged Swaps filter lacked that action. Added a conditional clear button inside the Swaps node popover that sets `nodeIds` to `undefined` while preserving the other board filters. `SubHierarchySelector` behavior for other consumers is unchanged.

Regression evidence: a new SwapsPage test selected a node with eligibility filtering active and failed RED because the in-popover clear button was absent. After the fix, the focused SwapsPage and SubHierarchySelector run passed 17/17. Changed-file ESLint and `git diff --check` passed. The full frontend suite and typecheck were not rerun for this follow-up; their earlier limitations are recorded in the original slice report.
