# Task 8 follow-up report: defer secondary page reads

Date: 2026-10-02

## Changes

- Approvals now fetches the full hierarchy only on the enrollment and transfers tabs. Direct links still enable the query, and transfer labels retain the existing ID fallback.
- Swaps now fetches the visible hierarchy only on the Board tab, including direct ?tab=board navigation.
- Planning Export now fetches transparency rows and the full hierarchy only when transparency or sub-units is selected. Configuration-only exports skip both.
- Export stays disabled and guarded until both selected-sheet payloads finish successfully. A localized error alert retries the failed payload, and users can export after a successful retry.
- Added tests for default and relevant tabs, direct routes, configuration-only export, pending/error guards, retries, full transparency row ordering, and sub-unit aggregates.

## Verification

- RED: the focused run before implementation had 7 failures and 50 passes across 3 files. Failures showed the eager default-tab reads, missing Export guard and retry UI, and an export fixture that was corrected to match the endpoint's flat tree response.
- GREEN: npm test -- src/pages/ApprovalsPage.test.tsx src/pages/SwapsPage.test.tsx src/pages/planning/ExportPage.test.tsx - 3 files, 57 tests passed.
- npx eslint src/pages/ApprovalsPage.tsx src/pages/ApprovalsPage.test.tsx src/pages/SwapsPage.tsx src/pages/SwapsPage.test.tsx src/pages/planning/ExportPage.tsx src/pages/planning/ExportPage.test.tsx - passed.
- git diff --check - passed; Git printed only line-ending normalization notices.

No browser scale profiling was run in this slice.
