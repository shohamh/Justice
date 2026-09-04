# Task 3A report: gimelim, reserve dismissal, and duty-problem browser contract

## Scope

Locked the existing dismissal UI contract and the commander-facing shift problem display. The backend taxonomy work already present in the worktree was kept and connected to the panel; no new authorization model was introduced.

## Changes

- Added stable selectors for opening a primary assignment dismissal, switching dismissal modes, selecting a covering reserve, saving a normal replacement, and the gimelim preview/commit sequence.
- Added focused component coverage that drives the existing gimelim preview then commit, chooses a different covering reserve and verifies the submitted reallocation payload, and opens the nested dismissal modal through its stable shift-assignment action.
- Added distinct commander-facing badges for duty exemption, גימלים, inability to attend, and Hakpaza Pikudit, plus visible replacement history for called-up reserves.

## Verification

- RED: the new selector tests failed before the production hooks existed.
- `npx vitest run src/components/DismissalModal.test.tsx --maxWorkers=1 --no-file-parallelism` — 1 file, 5 tests passed.
- `npx vitest run src/components/ShiftDetailPanel.test.tsx -t "dismissal action selector" --maxWorkers=1 --no-file-parallelism` — 1 selected test passed; 18 unrelated tests skipped.
- `npm run typecheck` — passed.
- `git diff --check` — passed before staging.
- After the problem-panel implementation, the focused pair passed with 24 tests and `npm run typecheck` plus `npm run lint` passed.

## Worktree note

The replacement reviewer could not start because the platform reported that the subagent usage limit had been reached. The controller therefore completed the narrowly scoped missing panel implementation and verified it locally; a separate subagent review remains unavailable for this checkpoint.
