# Task 2 report: shared active-day calculation

## Scope delivered

- Added `effective_active_start(reference_date, unit_join_date)` and a shared interval helper used by both single-soldier and bulk active-day calculations.
- Active days now begin at the later configured reference date or unit join date, cap the calculation end at the earliest of today, discharge, and left dates, preserve the existing elapsed-day convention, and keep a minimum of one.
- Full-coverage exemption dates are clipped to the effective start through today before subtraction.
- Legacy databases without the setting preserve the prior per-soldier enrolled-at behavior until first-registration initialization creates the shared setting.
- Score projections are not changed: they persist duty and adjustment score totals, while active days are calculated dynamically by scoring read paths, so no cached active-day projection needs invalidation or rebuilding.

## Test-driven evidence

- RED: `py -3 -m pytest -q -n 0 app/services/tests/test_scoring_active_days.py` initially failed during collection because `effective_active_start` did not exist.
- RED: after the initial implementation, the bulk/single legacy-fallback regression failed because bulk calculation used the earliest soldier enrollment as a shared fallback; the expected later soldier result was 3 and the actual result was 10.
- GREEN: `py -3 -m pytest -q -n 0 app/services/tests/test_scoring_active_days.py tests/unit/test_scoring_service.py app/services/tests/test_score_projection.py` passed: `36 passed` (27.1s).
- Static checks: `py -3 -m ruff check app/services/tests/test_scoring_active_days.py` and `git diff --check` passed.

## Self-review

- The configured-reference path is shared by `active_days()` and `_bulk_active_days()` through `_active_day_interval()`; test coverage also compares bulk and single results for absent-setting legacy compatibility.
- Exemption clipping intentionally ends at today, not an earlier discharge/left cap, matching the supplied formula.
- Existing duty scores and exemption records are read only and not rewritten.

## Focused files

- `backend/app/services/scoring.py`
- `backend/app/services/tests/test_scoring_active_days.py`

## Concern

- The focused pytest run emits one existing Starlette `multipart` pending-deprecation warning. Running Ruff over the whole pre-existing `scoring.py` still reports unrelated legacy diagnostics; the new test file passes Ruff cleanly.

## Final status

- Status: DONE
- Commit: `feat: calculate active days from unit-aware reference date`
