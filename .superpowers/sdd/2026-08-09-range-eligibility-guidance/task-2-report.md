# Task 2 report - shared explanations and sortable hierarchy table

## Commit

`04d405ef feat: explain range eligibility in sortable table`

## Changed committed files

- `frontend/src/api/ineligibleSoldiers.ts`
- `frontend/src/components/ranges/IneligibleSoldiersTable.tsx`
- `frontend/src/components/ranges/IneligibleSoldiersTable.test.tsx`
- `frontend/src/i18n/he.json`
- `frontend/src/utils/rangeEligibilityExplanation.ts`
- `frontend/src/utils/rangeEligibilityExplanation.test.ts`

## TDD evidence

- RED: `npm test -- src/utils/rangeEligibilityExplanation.test.ts` failed because the formatter module did not exist.
- GREEN: the formatter test passed after the minimal shared formatter and per-duty API type were added.
- RED: the table test failed for the expected missing date formatting, shared planned/uncovered explanations, and non-sortable qualification/future-context headers.
- GREEN: the formatter and table tests passed after the table consumed the per-duty facts and supplied sort values for all required columns.

## Tests and checks

- `npm test -- src/utils/rangeEligibilityExplanation.test.ts src/components/ranges/IneligibleSoldiersTable.test.tsx src/pages/RangesPage.test.tsx` - 40 passed.
- `npm run lint` - passed.
- `npm run typecheck` - passed.
- `git diff --check` - passed before commit.

## Concerns

- The focused RangesPage test emits pre-existing react-i18next setup and React Router future-flag warnings; all tests passed.

## Fix round 1

### Changed files

- `frontend/src/components/ranges/IneligibleSoldiersTable.tsx`
- `frontend/src/components/ranges/IneligibleSoldiersTable.test.tsx`
- `.superpowers/sdd/2026-08-09-range-eligibility-guidance/task-2-report.md`

### RED/GREEN evidence

- RED: before production changes, `npm test -- src/components/ranges/IneligibleSoldiersTable.test.tsx` failed the new commander-use regression because the component did not expose the commander audience contract. The hierarchy test was then corrected to select hierarchy rows only, rather than nested expanded-table rows.
- GREEN: after the clarified minimal typed `audience?: "planning" | "commander"` contract was added, the commander regression rendered the same expandable, read-only hierarchy table and the hierarchy header assertion verified the concrete ascending unit order `מחלקה 1`, `פיקוד עליון`, `פלוגה א` while the expanded company remained visible.

### Tests and checks

- `npm test -- src/utils/rangeEligibilityExplanation.test.ts src/components/ranges/IneligibleSoldiersTable.test.tsx src/pages/RangesPage.test.tsx` - 41 passed.
- `npm run lint` - passed.
- `npm run typecheck` - passed.
- `git diff --check` - passed.

### Concerns

- The focused `RangesPage` test continues to emit the pre-existing react-i18next setup and React Router future-flag warnings; no tests failed.
