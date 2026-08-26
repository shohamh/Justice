# Task 3 report

## Changed files

- `frontend/src/components/ranges/RangeFormModal.tsx`
  - Replaced the native dark-mode range-type select with the shared styled `Combobox`.
  - Added the required items: `laser` / `מטווח לייזר`, `live` / `מטווח חי`, and `alal` / `אל"ל`.
  - Preserved the controlled `RangeType` value and submission payload.
- `frontend/src/components/ranges/RangeFormModal.test.tsx`
  - Added a focused regression for the selected Hebrew label and all three readable list options.
- `.superpowers/sdd/2026-08-15-bug-report-feedback-follow-up/task-3-report.md`
  - Added this report.

## RED

Command:

```powershell
npx vitest run src/components/ranges/RangeFormModal.test.tsx -t "range type"
```

Result before implementation: failed as expected. The new regression expected `מטווח לייזר`, while the native select exposed the raw value `laser`.

## GREEN and final verification

Focused GREEN command:

```powershell
npx vitest run src/components/ranges/RangeFormModal.test.tsx -t "range type"
```

Result: 1 passed, 7 skipped.

Final command:

```powershell
npx vitest run src/components/ranges/RangeFormModal.test.tsx src/components/Combobox.test.tsx
npm run typecheck
```

Result: 2 test files passed, 25 tests passed; `tsc --noEmit` passed.

Additional verification: `git diff --check` passed.

## Commit

Commit message: `fix: show readable range type choices`

Commit hash: `4a96139ccc76b454d22f3944ae8041d8fc919dfe`

## Concerns

- No functional concerns identified.
- The pre-existing untracked file `docs/superpowers/plans/2026-08-15-bug-report-feedback-follow-up.md` was preserved and excluded from the Task 3 commit.

## Fix round 1

Reviewer finding: the modal duplicated range labels in a local untyped options array. Fixed by adding the typed `RANGE_TYPE_OPTIONS` list beside `RANGE_TYPE_LABELS` in `frontend/src/utils/rangeLabels.ts` and consuming it from `RangeFormModal.tsx`. The shared `Combobox`, exact IDs, Hebrew labels, and Task 2 active-location selector behavior remain unchanged.

Commands and output:

```powershell
npx vitest run src/components/ranges/RangeFormModal.test.tsx src/components/Combobox.test.tsx
```

Result: 2 test files passed, 25 tests passed.

```powershell
npm run typecheck
```

Result: `tsc --noEmit` passed.

```powershell
git diff --check
```

Result: passed.

The initial attempt to narrow `RANGE_TYPE_LABELS` to `Record<RangeType, string>` caused five unrelated existing call sites to reject arbitrary-string/empty-string indexing, so the compatibility type was retained while the shared options list remains explicitly typed.
