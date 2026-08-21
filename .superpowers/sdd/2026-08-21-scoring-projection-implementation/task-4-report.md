# Task 4 report: Move transparency and fairness reads to shared projection data

## Status

Implemented.

## Summary

- Added projected read helpers in `backend/app/services/scoring.py` for:
  - transparency rows,
  - fairness effort inputs without calling `transparency_rows`,
  - single-soldier score breakdown,
  - single-soldier effort breakdown.
- Kept legacy calculation paths as explicit fallbacks when required projection buckets cannot be proven usable after a synchronous rebuild attempt.
- Added synchronous read-time rebuild for missing/incomplete/dirty/divergent required soldier-quarter buckets.
- Preserved response keys, sorting by `effort_score`, active-day and exemption redaction behavior, normalization, effort quarter boundaries, and score-adjustment preview behavior.
- Added `backend/app/services/tests/test_projected_scoring_reads.py` covering projected/legacy differential output, no normal duty-day expansion, fairness independence from `transparency_rows`, in-memory preview adjustments, and missing-bucket rebuild.

## TDD evidence

Initial RED command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py -q
```

Initial output summary:

```text
FFFF [100%]
FAILED ... missing bucket not rebuilt
FAILED ... normal projected scoring read expanded duty days
FAILED ... fairness must not call transparency_rows
FAILED ... normal projected scoring read expanded duty days
```

Focused GREEN command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py -q
```

Focused output:

```text
.... [100%]
```

## Verification

Focused projection/scoring route regression:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py app\services\tests\test_score_projection.py app\services\tests\test_score_projection_persistence.py app\services\tests\test_score_projection_freshness.py app\routes\tests\test_scoring_routes.py app\services\tests\test_scoring_dismissal.py -q
```

Output:

```text
............................... [100%]
```

Existing effort/scoring/fairness/API regression:

```powershell
python -m pytest tests\test_effort_score.py tests\unit\test_scoring_service.py tests\unit\test_fairness_components.py tests\integration\test_scoring_api.py -q
```

Output:

```text
............................................................... [100%]
```

Final combined verification:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py app\services\tests\test_score_projection.py app\services\tests\test_score_projection_persistence.py app\services\tests\test_score_projection_freshness.py app\routes\tests\test_scoring_routes.py app\services\tests\test_scoring_dismissal.py tests\test_effort_score.py tests\unit\test_scoring_service.py tests\unit\test_fairness_components.py tests\integration\test_scoring_api.py -q
```

Output:

```text
........................................................................ [ 76%]
......................                                                   [100%]
```

`git diff --check` exit code 0. It emitted only Git's existing Windows line-ending warning for touched Python files.

## Concerns

- I did not run the full backend suite.
- Current fallback logging is diagnostic-only; it does not surface a response flag, preserving the existing API contract.
