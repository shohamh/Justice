# Task 8: Swaps board hierarchy filter

## Change

- Removed the board tab's eager visible-tree query. The node filter trigger is available immediately on the board, including direct links.
- Mounted the existing authorization-scoped, paged `SubHierarchySelector` only when the filter popover opens. Roots load on open; child branches load on expansion.
- Kept explicit selected node IDs in `BoardFilters.nodeIds`, the board query, the badge, and clear behavior. Added an optional selector prompt so Swaps shows its filter label while algorithm consumers retain their default.

## Evidence

- RED: new SwapsPage hierarchy regressions failed 3/3 before the implementation (8 other tests passed).
- Focused: `npx vitest run src/pages/SwapsPage.test.tsx src/components/SubHierarchySelector.test.tsx --reporter=dot` passed, 16/16.
- Changed-file ESLint passed with zero warnings.
- `git diff --check` passed.
- `npm run typecheck` failed on 17 existing errors in unchanged files: hierarchy, scoring, and soldiers API modules; AssignCommanderDialog, CursorPagedTable, HierarchyTree, LazyHierarchyTree, TeamHierarchyPage, and TransparencyPage. No error named a changed file.
- One full `npm test` run was stopped after about 2.5 minutes without a summary. Partial output included failures in ImportSessionReviewPage and ShiftFormModal (`useAuth` outside AuthProvider), HomePage and MyDutiesPage malformed-response assertions, and other fixture errors. Final counts are unavailable because the run was interrupted.

## Self-review

- The popover callback mounts the selector only while open. Its existing scope-aware root and branch query keys remain intact.
- Selection toggles one ID at a time; the page passes that array unchanged to the board API. Clearing resets the controlled value and query filters.
- The panel uses RTL, existing native checkbox/list semantics, expand controls, and loading/retry states. No backend or browser-auth/DB work was performed.
