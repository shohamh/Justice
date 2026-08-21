# Task 4 report: split normal and slow solver coverage

## Scope completed

Marked only `backend/tests/unit/test_tiebreak_e2e.py::test_range_mode_improves_average_spread_across_scenarios` with `@pytest.mark.slow`.

Committed as `12520801 test: mark tiebreak statistical sweep slow`.

That test is the broad statistical sweep: 20 randomized scenario pairs, each
solving both `off` and `range` modes with the existing 15-second batch and
10-second tiebreak budgets. It remains unchanged and is now excluded from a
normal run by the existing `--slow` collection hook.

No production solver code, solver settings, test budgets, or fairness E2E
coverage changed. In particular, the already-slow cases in
`tests/unit/test_fairness_e2e.py` were left unchanged.

## Normal-suite regression coverage

No additional regression was needed. The same file already contains the small,
deterministic end-to-end test
`test_range_mode_recovers_known_achievable_split`. It proves the aggregate
claim's canonical production contract: with a calibrated 72-duty case,
`tiebreak_mode="range"` assigns the four tied soldiers exactly `[16, 16, 16,
16]`. The existing parameterized correctness tests also retain coverage,
eligibility, and density-cap invariants under range mode.

Adding another aggregate test would duplicate that existing deterministic
contract without replacing the statistical sweep.

## Collection evidence

Before the marker, normal collection of `tests/unit/test_tiebreak_e2e.py`
reported 6 tests.

After the marker:

```text
python -m pytest tests\\unit\\test_tiebreak_e2e.py --collect-only -q -n 0
tests/unit/test_tiebreak_e2e.py: 5

python -m pytest tests\\unit\\test_tiebreak_e2e.py --slow --collect-only -q -n 0
tests/unit/test_tiebreak_e2e.py: 6
```

The existing collection hook in `tests/conftest.py` deselects tests carrying
the `slow` marker unless `--slow` is supplied, so a new collection test was not
required. These focused collection checks prove normal exclusion and explicit
slow inclusion for this test.

## Focused execution

```text
python -m pytest tests\\unit\\test_tiebreak_e2e.py -q -n 0
..... [100%]
5 passed
```

This executed only the normal deterministic tiebreak tests. The large
randomized sweep was not executed, as required. Pytest emitted one pre-existing
third-party `starlette.formparsers` `PendingDeprecationWarning` about
`python_multipart`; it did not affect the result.

## Concerns

None in the changed scope. The worktree contained unrelated dirty soldier-modal
files before this task; they were not modified or staged.

## Fix round 1: reviewer follow-up (2026-08-22)

### Documentation and scope

- Updated `backend/pyproject.toml` and the `--slow` option help in
  `backend/tests/conftest.py`: the marker now describes both scale scenarios
  and multi-scenario statistical fairness sweeps. It no longer claims exactly
  eight large-scale cases or a fixed combined duration.
- Per the controller ruling, no reusable phase-timing helper was added. That
  work belongs to Task 5; no production solver code changed here.

### Required solver commands

The commands were run from `backend` with explicit hard bounds, using
`python -m pytest` to invoke the installed pytest module.

1. `python -m pytest -m algorithm -q -n 0 --durations=50`
   - Hard bound: 300 seconds.
   - Completed in 51.2 seconds with exit code 1 (no timeout).
   - The captured run reached 88% after three skips, then reported 20 setup
     errors in `app/services/tests/test_algorithm_bridge.py`.
   - Each error is caused by the pre-existing session fixture failure
     `fixture '_database_runtime' not found` at
     `tests/conftest.py:363`; no solver assertion failure was reported.

2. `python -m pytest -m algorithm --slow -q -n 0 --durations=50`
   - Hard bound configured: 720 seconds.
   - The command was manually terminated at the user's instruction after the
     harness had observed 255 seconds of execution; it did not reach the hard
     bound.
   - No pytest progress or final summary was emitted before termination, so no
     completed-test count is available. This is an interrupted partial result,
     not a passing slow-suite result.

### Recovery note

Algorithm timing exposed pre-existing `_database_runtime` fixture setup errors;
the slow run was interrupted at 255 seconds and has no passing result.
