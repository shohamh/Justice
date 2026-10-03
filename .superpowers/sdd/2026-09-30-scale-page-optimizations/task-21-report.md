# Task 21: Compact transparency projection readiness

## Implementation

- Global transparency now queries distinct projected quarter dates for the exact active soldier population. It no longer materializes every persisted `(soldier_id, quarter_start)` pair in Python.
- Readiness accepts the active soldier IDs separately from explicit bucket keys. SQL bucket-health checks and dirty/divergent marker repair still cover every active soldier; quarter freshness and quarter-total checks use the compact union of score and effort quarters. Required soldier totals still cover the same population.
- The request-local readiness token records soldier and quarter scopes. The effort read rechecks the narrowed effort quarters and full active population, retaining the READ COMMITTED protection for a dirty marker committed between reads.
- Explicit canonical diagnostics still enumerate and compare individual buckets when requested. Other callers of key-based readiness keep their prior behavior. No API, pagination, or caching changes were made.

## Regression evidence

- RED: `python -m pytest -q -n 0 --tb=short tests/unit/test_score_projection_read_repair.py::test_transparency_readiness_uses_compact_quarters_for_full_active_population` failed at the old `_projection_data_keys_for_soldiers` call with `global transparency must not enumerate soldier-quarter pairs`.
- GREEN: the same PostgreSQL-backed test passed after implementation. It includes active and departed soldiers, distinct score and effort quarters, a stale bucket, and a dirty marker. It checks both readiness scopes, marker/bucket repair, and equality with canonical transparency output.
- Focused suite: `python -m pytest -q -n 0 --tb=short tests/unit/test_score_projection_read_repair.py tests/unit/test_projected_effort_sql.py tests/unit/test_scoring_service.py` passed: 35 tests.
- `git diff --check` passed. Focused Ruff checks on the changed test files passed. A broader Ruff invocation over `scoring.py` reports existing findings on lines outside this change; no new Ruff finding is introduced by this slice.

Page latency remains unmeasured. The profiling database/browser route was blocked before launch, so this task makes no page reprofile or latency claim.
