# Task 7 report: format range eligibility warning details

## Changed files

- `frontend/src/utils/rangeEligibilityExplanation.ts`
- `frontend/src/utils/rangeEligibilityExplanation.test.ts`
- `frontend/src/components/ShiftDetailPanel.tsx`
- `frontend/src/components/ShiftDetailPanel.test.tsx`

The uncovered-duty explanation now separates the duty requirement from the
last-qualification or never-qualified clause with a newline. The detail-panel
popover uses `whitespace-pre-line`, while calendar badges retain their native
`title` fallback from the same readable explanation. Task 6's duty-requirement
panel, eligibility semantics, and permission gate were not changed.

## RED

Command run from `frontend`:

```powershell
npx vitest run src/utils/rangeEligibilityExplanation.test.ts src/components/ShiftDetailPanel.test.tsx
```

Output: 2 files failed; 4 tests failed and 23 passed. The three utility tests
received a space where the new expected newline preceded `אין מטווחים בתוקף`
or the known last-qualification line. The panel test failed because the tooltip
lacked `whitespace-pre-line`.

## GREEN and final verification

Focused GREEN command:

```powershell
npx vitest run src/utils/rangeEligibilityExplanation.test.ts src/components/ShiftDetailPanel.test.tsx
```

Output: 2 files passed; 27 tests passed.

Final commands run from `frontend`:

```powershell
npx vitest run src/utils/rangeEligibilityExplanation.test.ts src/components/ShiftDetailPanel.test.tsx src/components/UnitCalendar.test.tsx
npm run typecheck
```

Output: 3 files passed; 34 tests passed. `tsc --noEmit` passed.

## Commit

`944b2b61cfdd246f1b507098de372b328dfb73f7` — `fix: format range eligibility warning details`

## Concerns

The passing focused suites emit pre-existing React `act(...)` warnings from
`ShiftDetailPanel` tests and jsdom `AggregateError` network warnings from
`UnitCalendar` tests. No Task 7 scope was broadened to address them.
