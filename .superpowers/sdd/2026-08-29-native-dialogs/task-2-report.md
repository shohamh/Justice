# Task 2 report: hierarchy and soldier dialogs

Implemented the scoped native-dialog migration.

- Hierarchy node deletion and soldier password reset use `ConfirmDialog` and do not perform mutations before confirmation.
- Hierarchy, node-editor, and soldier-loading errors/protection messages use `MessageDialog`.
- Constraint rejection uses `InputDialog`; closing submits nothing, while confirming an empty input submits `""`.
- Added Hebrew i18n strings for every new dialog title and message.

Verification:

- `npx vitest run src/components/HierarchyTree.test.tsx src/pages/TeamHierarchyPage.test.tsx src/components/UnifiedSoldierModal.test.tsx` — 42 passed.
- `npm run typecheck` — passed.
- `npm run lint` — passed.
- Scoped runtime native-dialog search returned no matches.
- `git diff --check` — passed.

The pre-existing hierarchy action-layout changes in `HierarchyTree.tsx` and
`HierarchyTree.test.tsx` were preserved and intentionally left unstaged.
