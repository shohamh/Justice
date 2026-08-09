# Final fix C — UI report

## Scope delivered

1. `UnitCalendar` now invalidates the eligibility-count request generation and clears the warning badge when `nodeId` or `soldierId` changes. A response belonging to the previous scope can no longer update the current calendar.
2. Removed the obsolete `../api/shifts` eligibility-count mock and its mock-call assertion from `UnifiedNav.test.tsx`. The remaining test asserts the visible navigation result.
3. Made the hierarchy sort regression test explicitly commander-scoped and asserted the fixture's hierarchy order before clicking the unit header, then the sorted order after the click.

## Changed files

- `frontend/src/components/UnitCalendar.tsx`
- `frontend/src/components/UnitCalendar.test.tsx`
- `frontend/src/components/UnifiedNav.test.tsx`
- `frontend/src/components/ranges/IneligibleSoldiersTable.test.tsx`
- `.superpowers/sdd/2026-08-09-range-eligibility-guidance/final-fix-ui-report.md`

## TDD evidence

### RED

Command:

```powershell
cd frontend
npm test -- src/components/UnitCalendar.test.tsx src/components/UnifiedNav.test.tsx src/components/ranges/IneligibleSoldiersTable.test.tsx
```

Result: failed as expected. The two new UnitCalendar tests showed that a scope change left the loaded badge (`4`) visible and allowed a pending old-scope response (`7`) to render. The same run initially exposed four leftover assertions coupled to the obsolete UnifiedNav mock; those assertions were removed with the mock as test hygiene.

### GREEN

Command:

```powershell
cd frontend
npm test -- src/components/UnitCalendar.test.tsx src/components/UnifiedNav.test.tsx src/components/ranges/IneligibleSoldiersTable.test.tsx
```

Result: passed — 3 files, 48 tests.

## Validation commands and results

| Command | Result |
| --- | --- |
| `Get-Content -Raw AGENTS.md` and the final-fix brief | Read project rules and complete scoped requirements. |
| `git status --short`, `git branch --show-current`, and targeted `rg`/file inspection | Confirmed branch `feature/range-eligibility-guidance`, identified unrelated existing WIP, and inspected the relevant UI/tests. |
| Focused `npm test -- ...` (RED) | Exit 1 for the two expected missing scope-change behaviors; see TDD evidence. |
| Focused `npm test -- ...` (GREEN) | Exit 0 — 48/48 tests passed. |
| `npm run lint` | Exit 0. |
| `npm run typecheck` | Exit 0. |
| `git diff --check` | Exit 0. |
| `git diff` and `git status --short` scope review | Confirmed only the five files above are staged for this fix; unrelated backend/frontend WIP remains uncommitted. |

## Commit

`git commit -m "fix: prevent stale calendar warning counts"` on `feature/range-eligibility-guidance`.

## Concerns

- The focused UnifiedNav test run passes but continues to print pre-existing React `act(...)` and jsdom network warnings from unrelated async effects. They are not introduced by this change and do not affect the exit status.
- Existing unrelated WIP is present in backend calendar/ineligible tests and a frontend range-eligibility utility test; it is intentionally excluded from this commit.
