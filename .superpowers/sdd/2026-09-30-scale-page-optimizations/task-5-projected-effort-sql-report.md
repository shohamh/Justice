# Task 5 projected effort SQL aggregate

## Change

- `_try_projected_effort_data` retains the global reset-override fallback, quarter-alignment fallback, request-local effort keys, and the second readiness check for the prevalidated active-soldier scope. If readiness fails, it returns `None` so the existing transparency caller uses the legacy path.
- The projected effort read now groups quarter projection scores in PostgreSQL and returns one `(soldier_id, numerator, denominator)` row per active soldier. Python performs the final `effort_score`, `C_over_D`, and integer `effort_offset` calculation. The SQL fraction uses the same soldier activation date and tracked quarter endpoints as the prior helper. Quarter score fields and totals are already stored at six decimal places, preserving `_q6` inputs.
- The old `_projection_burden_share_inputs` remains available as the reference for direct PostgreSQL parity tests, but the projected transparency path no longer invokes it or materializes per-soldier/per-quarter score maps.

## Verification

- RED: `backend/.venv/Scripts/python.exe -m pytest tests/unit/test_projected_effort_sql.py -q -n 0` failed at `quarter_maps_are_forbidden` because `_try_projected_effort_data` called `_projection_burden_share_inputs`.
- GREEN: the same file passed 4/4. It compares the SQL result to the previous Python map plus `_compute_effort_data` using real PostgreSQL projection rows across three quarters, a May 15 join, a zero-total quarter, a persisted adjustment row, equal histories, and an empty history. It also checks reset overrides, incomplete projections, and the second prevalidated readiness check.
- Focused suite: `backend/.venv/Scripts/python.exe -m pytest tests/unit/test_projected_effort_sql.py tests/unit/test_score_projection_read_repair.py tests/unit/test_scoring_service.py tests/test_effort_score.py tests/integration/test_scoring_api.py -q -n 0 -k 'not breakdown_contributions_reconstruct_scores' --tb=short` passed. The read-repair and transparency/service/API tests are included.
- The same focused command without `-k` had one failure: `tests/test_effort_score.py::test_breakdown_contributions_reconstruct_scores`. It also failed alone with `backend/.venv/Scripts/python.exe -m pytest tests/test_effort_score.py::test_breakdown_contributions_reconstruct_scores -q -n 0 --tb=short`. Its fixture inserts a `ScoreAdjustment` with default `created_at` (current date, 2026-10-02), then expects an adjustment in Q3 2026. The assertion got only `{'duty'}` for Q3. This breakdown path and fixture are outside this diff; the date-sensitive test needs its adjustment timestamp pinned to Q3.
- Changed-file Ruff: `ruff check app/services/scoring.py tests/unit/test_projected_effort_sql.py` reports four existing findings in untouched `scoring.py` lines (`B023` at 208, `SIM103` at 1605, `SIM108` at 2160 and 2294). `ruff check ... --ignore B023,SIM103,SIM108` passes. The new test file passes Ruff without ignores. `git diff --check` passes.

## Self-review and limits

- The SQL query returns a single aggregate per soldier and keeps zero-score soldiers in the result. It still scans or joins a population-wide soldier and quarter scope in PostgreSQL; global normalization, sorting, and summaries also remain O(population). No page-size performance claim is made.
- The existing initial projection readiness check, narrowed second check, dirty/divergent handling, and legacy fallback remain in place. No cache, index, migration, API, filter, sort, summary, or frontend behavior changed.
- This slice did not run the final browser scale profile.
