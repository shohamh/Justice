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

## Fix round 1

- Password reset confirmation remains open and disables repeat confirmation while its request is pending. A rejected reset now shows the translated generic error in `MessageDialog`.
- Constraint rejection now awaits its request, disables repeat confirmation while pending, and shows a translated `MessageDialog` error without treating cancellation as an empty submission.
- Added focused regression tests for success-pending and rejection-error paths.

Verification:

- `npx vitest run src/pages/TeamHierarchyPage.test.tsx src/components/UnifiedSoldierModal.test.tsx src/components/ConfirmDialog.test.tsx src/components/InputDialog.test.tsx` — 39 passed.
- `npm run typecheck` — passed.
- `npm run lint` — passed.
- `git diff --check` — passed.
