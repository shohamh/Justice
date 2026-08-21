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

## Fix round 1 report

### Status

Implemented.

### Findings addressed

- `_ensure_projection_ready` now proves required persisted bucket rows against canonical `project_soldier_bucket` summaries, rebuilds mismatches synchronously, and falls back to legacy if proof or rebuild fails.
- Transparency now validates `SoldierScoreProjection` for every active soldier whose totals are read; missing/stale totals are rebuilt from projection rows before use, and a remaining missing total forces legacy fallback instead of a zero default.
- Effort, fairness, transparency, and single-soldier effort breakdown readiness now includes every effort-window quarter total, including denominator-only quarters with no visible/requested soldier bucket key.
- Missing/divergent denominator quarter totals synchronously enumerate canonical quarter buckets, rebuild all needed bucket rows, and re-check canonical quarter totals before projected computation.
- Added scoped non-admin exemption-redaction differential coverage for projected transparency.

### TDD evidence

Fix-round RED command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py -q
```

Fix-round RED output summary:

```text
..F....F                                                                 [100%]
FAILED app/services/tests/test_projected_scoring_reads.py::test_transparency_rebuilds_divergent_projection_bucket_before_projected_read
FAILED app/services/tests/test_projected_scoring_reads.py::test_effort_breakdown_rebuilds_denominator_only_quarter_total
```

Focused GREEN command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py -q
```

Focused GREEN output:

```text
........                                                                 [100%]
```

### Verification

Final focused Task 4 regression command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py app\services\tests\test_score_projection.py app\services\tests\test_score_projection_persistence.py app\services\tests\test_score_projection_freshness.py app\routes\tests\test_scoring_routes.py app\services\tests\test_scoring_dismissal.py tests\test_effort_score.py tests\unit\test_scoring_service.py tests\unit\test_fairness_components.py tests\integration\test_scoring_api.py -q
```

Final focused Task 4 regression output:

```text
........................................................................ [ 73%]
..........................                                               [100%]
```

Diff hygiene:

```powershell
git diff --check
```

Output:

```text
warning: in the working copy of 'backend/app/services/scoring.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/services/tests/test_projected_scoring_reads.py', LF will be replaced by CRLF the next time Git touches it
```

Exit code: 0.

### Concerns

- I reran the requested 94 focused tests plus the 4 new fix-round readiness/differential tests (98 total). I did not run the full backend suite.
- The stricter projected-read proof intentionally performs bounded canonical checks for required read keys/quarters; this avoids silently serving stale projection data, with legacy fallback if proof cannot be established.

## Fix round 2 report

### Status

Implemented.

### Findings addressed

- Removed canonical per-bucket and per-quarter expansion from the normal projected-read readiness path.
- Normal `_ensure_projection_ready` now uses persisted projection metadata only: projection state completeness/current version, row presence/version, dirty/divergent bucket rows, persisted fingerprint self-consistency, and row-summed soldier/quarter totals.
- Read-time bucket rebuilds now refresh only the affected soldier-quarter bucket and skip broad `project_all_buckets` quarter-total refresh; required quarter totals are repaired by summing persisted projection rows.
- Kept canonical bucket/quarter comparison helpers available behind explicit `canonical_diagnostic_check=True`; normal transparency/fairness/breakdown reads do not enable it.
- Updated no-expansion tests to monkeypatch the actual `score_projection` seam and added scale/no-history-expansion coverage.
- Unprovable persisted metadata now falls back to the legacy canonical path with diagnostics instead of performing canonical expansion as a readiness check.

### TDD evidence

Fix-round RED command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py -q
```

Fix-round RED output summary:

```text
F..F...F.                                                                [100%]
FAILED app/services/tests/test_projected_scoring_reads.py::test_effort_breakdown_matches_legacy_from_projection_and_keeps_preview_in_memory
FAILED app/services/tests/test_projected_scoring_reads.py::test_transparency_rebuilds_missing_soldier_total_before_projected_read
FAILED app/services/tests/test_projected_scoring_reads.py::test_effort_breakdown_rebuilds_denominator_only_quarter_total_from_projection_rows
```

Focused GREEN command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py -q
```

Focused GREEN output:

```text
.........                                                                [100%]
```

### Verification

Final focused Task 4 regression command:

```powershell
python -m pytest app\services\tests\test_projected_scoring_reads.py app\services\tests\test_score_projection.py app\services\tests\test_score_projection_persistence.py app\services\tests\test_score_projection_freshness.py app\routes\tests\test_scoring_routes.py app\services\tests\test_scoring_dismissal.py tests\test_effort_score.py tests\unit\test_scoring_service.py tests\unit\test_fairness_components.py tests\integration\test_scoring_api.py -q
```

Final focused Task 4 regression output:

```text
........................................................................ [ 72%]
...........................                                              [100%]
```

Diff hygiene:

```powershell
git diff --check
```

Output:

```text
warning: in the working copy of 'backend/app/services/score_projection.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/services/scoring.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/services/tests/test_projected_scoring_reads.py', LF will be replaced by CRLF the next time Git touches it
```

Exit code: 0.

### Concerns

- I reran the focused Task 4 suite plus the new scale/no-history-expansion test (99 total). I did not run the full backend suite.
- The round-1 canonical-readiness concern is superseded by this fix: canonical comparison remains available only through explicit diagnostic mode, not normal reads.
