# Task 1 Report — Scoring projection bucket contract

## Status

Completed Task 1 only.

## Changed files

- `backend/app/services/score_projection.py`
- `backend/app/services/tests/test_score_projection.py`
- `backend/app/services/scoring.py`
- `.superpowers/sdd/2026-08-21-scoring-projection-implementation/task-1-report.md`

## Design decisions

1. Added a new pure rebuild helper module at `backend/app/services/score_projection.py`.
   - Introduced `ProjectionBucket`.
   - Added `project_soldier_bucket(session, soldier_id, quarter_start_value)`.
   - Added `project_all_buckets(session, soldier_ids=None, quarter_starts=None)`.

2. Kept scoring semantics canonical by extracting a shared internal seam in `backend/app/services/scoring.py`.
   - Added `_effective_duty_day_rows(...)` so projection logic reuses the same day-level reserve / called-up / dismissal / override behavior instead of forking the rules.
   - Rewired `_duty_stats_by_soldier(...)` to use the same helper.

3. Made `project_soldier_bucket(...)` bounded to the requested soldier and quarter.
   - Candidate assignments are limited to:
     - published assignments owned by the soldier and overlapping the quarter, and
     - published assignments with in-quarter `DutyDayOverride` rows that make the soldier effective on a day in that quarter.
   - Manual adjustments are limited to the requested soldier and quarter datetime window.

4. Made `source_fingerprint` structured and deterministic rather than hashed.
   - Includes the canonical identifiers and values that actually feed the bucket:
     - duty row assignment IDs, dates, effective soldier IDs, weighted multipliers, and derived day scores
     - adjustment IDs, deltas, and timestamps
   - This should make Task 2 persistence/drift inspection easier.

5. Covered the requested scoring cases in a single differential scenario:
   - ordinary multi-day assignment
   - reserve standby/call-up multipliers
   - dismissal
   - effective-soldier day override
   - manual adjustments
   - quarter boundary split
   - full-coverage exemption

6. Full-coverage exemptions are intentionally a no-op for Task 1 bucket fields.
   - The new bucket contract stores duty score, adjustment score, shift count, and fingerprint only.
   - The test still proves an active full-coverage exemption exists and that the bucket remains aligned with canonical scoring outputs.

## Tests run

### Red phase

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py
```

Output:

```text
ERROR collecting app/services/tests/test_score_projection.py
ModuleNotFoundError: No module named 'app.services.score_projection'
```

### Focused Task 1 verification

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py
```

Output:

```text
..                                                                       [100%]
============================== warnings summary ===============================
... PendingDeprecationWarning: Please use `import python_multipart` instead.
```

### Existing scoring / effort verification

Command:

```powershell
pytest -q -n 0 tests/unit/test_scoring_service.py tests/unit/test_scoring_reserve.py app/services/tests/test_scoring_dismissal.py tests/test_effort_score.py
```

Output:

```text
....................................................                     [100%]
============================== warnings summary ===============================
... PendingDeprecationWarning: Please use `import python_multipart` instead.
```

## Concerns

1. `source_fingerprint` is currently an in-memory structured dict with UUID/date/Decimal values, not yet a persisted shape. Task 2 should decide whether to persist this as JSONB directly or normalize/serialize it first.

2. `project_all_buckets(...)` returns the explicit cross-product when both `soldier_ids` and `quarter_starts` are supplied, including zero-value buckets if a requested pair has no sources. That is helpful for deterministic rebuild/delete semantics, but Task 2 should confirm this matches the persistence replacement strategy.

3. The test runs emit a pre-existing Starlette `python_multipart` PendingDeprecationWarning. It did not affect Task 1 behavior.

4. I preserved unrelated dirty/untracked workspace state and did not reset or stash anything.

## Fix round 1 — reviewer findings

### Findings addressed

1. Expanded `source_fingerprint` so duty rows now carry:
   - `override_id`, `override_date`, `override_effective_soldier_id`, `override_reason`
   - `dismissal_id`, `dismissed_from`, `dismissed_to`, `dismissal_reason`
   - supporting canonical values such as `assignment_soldier_id`, `day_weight`, `multiplier`, and `multiplier_source`
   - plus deduplicated top-level `overrides` and `dismissals` lists

2. Removed the remaining scoring-semantics fork:
   - `effective_duty_days(...)` now delegates to the shared `_effective_duty_day_rows(...)` seam
   - projection and existing scoring helpers therefore consume the same canonical day expansion

3. Strengthened the full-coverage exemption coverage:
   - added an assertion that projected cumulative score matches canonical cumulative score
   - added an explicit active-days assertion showing the exemption reduces the normalization input used by projected reads

### Additional red phase

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py
```

Output:

```text
FF..
KeyError: 'override_id'
```

### Fix-round focused verification

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py
```

Output:

```text
....                                                                     [100%]
============================== warnings summary ===============================
... PendingDeprecationWarning: Please use `import python_multipart` instead.
```

### Fix-round covering verification

Command:

```powershell
pytest -q -n 0 app/services/tests/test_score_projection.py tests/unit/test_scoring_service.py tests/unit/test_scoring_reserve.py app/services/tests/test_scoring_dismissal.py tests/test_effort_score.py
```

Output:

```text
........................................................                 [100%]
============================== warnings summary ===============================
... PendingDeprecationWarning: Please use `import python_multipart` instead.
```
