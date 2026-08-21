# Backend test-suite performance baseline — 2026-08-21

## Environment

- Worktree: `C:\Users\Shoham\.paseo\worktrees\1n26l98r\adoring-cougar`
- Baseline commit: `005bb477871a79f21a20a4becc97c11c9a4475f2`
- Python: 3.13.3
- pytest: 9.0.3
- Platform: Windows PowerShell on Windows
- Measurement method: `Measure-Command`; each command had a 300-second execution cap.
- Recovery measurement: bounded collection-only marker slices, run after the Task 1
  classification helper was added. These validate selection counts without starting
  containers or executing the full suite.

## Commands and observed results

| Command | Result | Wall-clock duration | Pass/skip counts |
| --- | --- | --- | --- |
| `Measure-Command { pytest -q }` | **Timed out** at the 300-second cap; no completed result. | Timeout reported after 304.029 seconds of wrapper wall time. | Not available: pytest did not complete. |
| `Measure-Command { pytest --slow -q }` | **Timed out** at the 300-second cap; no completed result. | Timeout reported after 304.057 seconds of wrapper wall time. | Not available: pytest did not complete. |
| `Measure-Command { pytest -m algorithm -q -n 0 }` | Exit code 0, but the captured double-quiet output omitted the summary; this is an **incomplete result record**, not a count-complete baseline. | 98.804 seconds. | Not captured; pass/skip counts are unavailable. |
| `Measure-Command { pytest -m "not algorithm" -q -n 0 }` | **Incomplete**: stopped at the user's request before completion. | No completed duration recorded. | Not available: pytest did not complete. |

## Bounded classification-slice recovery measurement

| Command | Result | Wall-clock duration | Pass/skip counts | Selected/deselected counts |
| --- | --- | --- | --- | --- |
| `python -m pytest -m pure --collect-only -v -n 0 -o addopts=''` | Exit code 0. | 5.206 seconds. | 0 passed / 0 skipped (collection only). | 212 selected / 1,991 deselected (2,203 collected). |
| `python -m pytest -m database --collect-only -v -n 0 -o addopts=''` | Exit code 0. | 4.519 seconds. | 0 passed / 0 skipped (collection only). | 1,298 selected / 905 deselected (2,203 collected). |
| `python -m pytest -m http --collect-only -v -n 0 -o addopts=''` | Exit code 0. | 5.016 seconds. | 0 passed / 0 skipped (collection only). | 685 selected / 1,518 deselected (2,203 collected). |

The recovery run intentionally did not execute `pytest -q` or `pytest --slow -q`:
both were already shown above to exceed the 300-second cap. It also did not rerun
the incomplete `not algorithm` execution. The three selected counts sum to 2,195,
not 2,203: the eight `slow` items are deselected before layer markers are applied.
That arithmetic confirms every non-slow collected item has exactly one explicit
test-layer marker.

This baseline is intentionally incomplete: the long measurements were stopped or timed out before later performance refactors could run. Do not compare later timings to missing pass/skip counts as though they were successful runs.
