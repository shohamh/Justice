# SDD ledger — plan: docs/superpowers/plans/2026-08-29-native-dialogs.md

## Pre-flight scan

| Scope | Relationship checked | Result / ruling |
|---|---|---|
| Task 1 ↔ Task 2 | Task 1 produces shared ConfirmDialog, MessageDialog, InputDialog; Task 2 consumes them | Compatible. Task 2 must import shared components and not duplicate modal behavior. |
| Task 1 ↔ Task 3 | Task 1 produces shared dialog callbacks; Task 3 consumes them for range and shift handlers | Compatible. Existing range reason dialog remains domain-specific. |
| Task 1 ↔ Task 4 | Task 1 produces confirmation/message/input interfaces; Task 4 consumes all three | Compatible. Sequential duty prompts require local state transitions. |
| Task 1 ↔ Task 5 | Task 5 verifies no native calls and shared tests | Compatible. Function names containing confirm/alert/prompt require manual review. |
| Task 2 ↔ Task 3 | Both may touch shared UI conventions but have disjoint runtime files | No file conflict; both use the Task 1 interfaces. |
| Task 2 ↔ Task 4 | Both may touch i18n and representative tests | No runtime file conflict; translation keys must remain unique and descriptive. |
| Task 3 ↔ Task 4 | Both may touch existing dialog compatibility and i18n | No required shared implementation; keep each domain migration in its listed files. |
| Task 1 self-consistency | Shared interfaces, tests, implementation, and translations | Consistent; tests target public callbacks and visible behavior. |
| Task 2 self-consistency | Hierarchy/soldier files and tests | Consistent; existing dirty HierarchyTree changes must be preserved. |
| Task 3 self-consistency | Ranges/shifts files and tests | Consistent; native prompt reasons use InputDialog. |
| Task 4 self-consistency | Remaining domains, created tests, and test command | Consistent after adding missing test-file creation steps. |
| Task 5 self-consistency | Runtime search and full verification | Search is portable; manually review non-browser function names. |

## Rulings

Ruling: keep the existing uncommitted `HierarchyTree.tsx` and
`HierarchyTree.test.tsx` changes in place and require Task 2 to merge around
them — because they are pre-existing user work — cost if wrong: dialog changes
could be harder to review or the existing hierarchy work could be overwritten.

Ruling: treat `alert` as a one-button MessageDialog and `prompt` as an
InputDialog, rather than forcing both into ConfirmDialog — because the user
explicitly requested slightly different modal behavior and existing callers
depend on input/cancel semantics — cost if wrong: some flows may need a second
iteration for wording or validation.

Task 1: complete (commits 13a2c71d..24aefacf, review clean after fix round 1)

Task 2: minor (deferred): pre-existing unused `EllipsisVertical` import in
dirty `HierarchyTree.tsx` blocks a clean lint run until the unrelated WIP is
resolved.

Task 2: complete (commits 24aefacf..8153c234, review clean after fix rounds 1-2)

Task 3: complete (commits 8153c234..ab5d27ce, review clean)

Task 4: complete (commits 5308a5f7..0d66b61e). Fixed three pre-existing test
i18n-mock bugs discovered during verification (ShiftTemplatesPage.test.tsx,
AlgorithmProposalTable.test.tsx, UpcomingSnapshot.test.tsx all mocked `t`
without object-form/interpolation support, masking real component behavior
behind literal keys) — see task-4-report.md. Left the unrelated in-progress
hierarchy-transfer-reason work (backend + HierarchyTree.tsx/UnifiedNav.tsx/
ApprovalsPage.tsx/ConfirmDialog.tsx `children` prop) uncommitted, including
its portion of he.json, per the brief.

Task 5: complete (commit b4303a60). Runtime inventory found one native
`window.confirm` outside the plan's file lists (`ErrorsContent.tsx`, admin
error-log clear action) and fixed it the same way; full suite (154 files,
1110 tests), lint, and `git diff --check` all clean — see task-5-report.md.

Plan: complete.
