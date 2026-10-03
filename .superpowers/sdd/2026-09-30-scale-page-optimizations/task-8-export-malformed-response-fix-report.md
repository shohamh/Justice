# Task 8 Export malformed-response fix

Date: 2026-10-02

## Changes

- Added export-specific transparency and full-tree readers that reject malformed collection payloads while accepting valid empty arrays.
- Kept the shared getTransparency and fetchFullTree readers lenient for their existing callers; their compatibility tests still pass.
- Planning Export now uses the strict readers. Its existing disabled, alert, and retry behavior handles either malformed response.
- Set Export query freshness to zero so cached empty results from lenient shared readers are revalidated before export. Added coverage for stale cached results.

## Verification

- RED: npm test -- src/api/scoring.test.ts src/api/hierarchy.test.ts - 2 failed and 19 passed because the strict export readers were missing.
- GREEN: npm test -- src/api/scoring.test.ts src/api/hierarchy.test.ts src/pages/planning/ExportPage.test.tsx - 3 files, 36 tests passed.
- Changed-file ESLint and git diff --check passed.

The inherited plan document modification was left untouched. No scale profiling was run.
