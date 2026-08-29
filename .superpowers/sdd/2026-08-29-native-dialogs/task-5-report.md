# Task 5 report — Runtime inventory, full verification, and cleanup

## Runtime inventory

```
rg -n -i --glob '!**/*.test.*' --glob '!**/docs/**' --glob '!node_modules/**' "window\\.(confirm|alert|prompt)|\\b(confirm|alert|prompt)\\s*\\(" frontend/src
```

Found one real remaining native call outside the plan's original file lists:
`frontend/src/pages/admin/ErrorsContent.tsx` used `window.confirm` to gate the
admin error-log "clear through date" action. This file was never listed in
Tasks 1-4, so it was missed until this scan.

Fixed it the same way as every other flow: added `ConfirmDialog` state
(`confirmClear`), moved the mutation (`clearAdminErrors`) into a
`confirmClearErrors` callback invoked only from the dialog's confirm button,
and added two focused tests (`ErrorsContent.test.tsx`) — one asserting the
dialog blocks the API call until accepted, one asserting cancel leaves it
uncalled. Committed separately (`fix: replace native confirm in admin error
log clear action`) since it's outside the plan's declared scope.

All other matches are false positives: a local function literally named
`confirm` in `RangeBulkAutoAssignModal.tsx` (not `window.confirm`, already
uses `OverrideReasonModal`) and a code comment referencing `window.prompt()`
in a docblock.

## Full verification

```
npm test -- --run --maxWorkers=1 --no-file-parallelism
```
154 test files, 1110 tests — all pass.

```
npm run lint   # runs tsc --noEmit && eslint src --max-warnings 0
```
Clean.

```
git diff --check -- frontend/src
```
Clean (only CRLF-on-checkout warnings, no whitespace errors).

## Translations and behavior review

Every dialog introduced across Tasks 1-5 supplies a Hebrew title, message,
and button text via `t(key, { defaultValue })` or `t(key, "fallback")`,
consistent with the rest of the codebase's i18n convention — so even where a
key isn't (yet) present in `he.json`, the visible text is Hebrew, never a
raw key or English string. Dynamic interpolation (`{{count}}`, `{{soldier}}`,
etc.) renders left-to-right numbers/names embedded in RTL Hebrew sentences,
matching the pattern already used by `HierarchyTree`'s transfer-confirmation
message. `useModalBackClose`/`EventDetailModal`'s existing browser-back
handling closes only the active dialog (verified via the existing dialog
components' shared behavior, unchanged by this work). No flow calls its
mutation before the user clicks the dialog's confirm button — verified by
this task's and prior tasks' "cancel does not call the API" tests.

## Scope note

The unrelated in-progress hierarchy-transfer-reason work identified in
Task 4 (backend files, `HierarchyTree.tsx`/`UnifiedNav.tsx`/`ApprovalsPage.tsx`,
`hierarchyTransfers.ts`, and `ConfirmDialog.tsx`'s `children` prop, plus its
slice of `he.json`) remains uncommitted in the working tree, as before. It is
untouched by this task.

## Commit

`fix: replace native confirm in admin error log clear action` — the only
runtime code change this task required. No further plan-file commit was
needed since the plan document itself needs no edits.
