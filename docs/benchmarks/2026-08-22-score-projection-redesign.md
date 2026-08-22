# Score projection redesign — performance audit 2026-08-22

Branch: `scoring-projection-task2` (commits `11fbbb0e`…`9552306f`)
Scope: `backend/app/services/score_projection.py`, `scoring.py`,
`score_projection_reconciliation.py`, `commander_dashboard.py`,
`sql_arrays.py`, `score_projection_revalidation_worker.py`.

## What score projections are

Every transparency / fairness / commander-dashboard read needs each soldier's
duty scores. Computing them canonically means expanding every published duty
assignment day-by-day in Python (`_effective_duty_day_rows`), applying
overrides, dismissals and reserve multipliers per day. At deployment scale
(10k soldiers / 500k assignments) that is minutes of Python per request.

The projection feature pre-computes that math into two tables:

| Table | Grain | Contents |
| --- | --- | --- |
| `soldier_quarter_score_projection` | soldier × quarter × duty type (+ one aggregate row) | day counts, weighted days, duty/adjustment scores **and** `source_fingerprint` JSONB |
| `soldier_score_projection` | soldier | cumulative totals |
| `score_projection_quarter_total` | quarter | unit-wide denominators for effort/fairness math |
| `score_projection_dirty_buckets` | bucket marker | writer invariant bookkeeping |

Writes rebuild affected buckets synchronously; reads serve from the tables
after verifying they are trustworthy.

## The old (simpler) design, and why it failed

The first implementation was conceptually simple:

1. **Backfill**: walk every (soldier, quarter) touched by an assignment,
   recompute the bucket, write partition rows.
2. **Quarter totals**: after each bucket rebuild, recompute the *entire
   quarter* by re-projecting every soldier from canonical source
   (`project_all_buckets`).
3. **Read validation**: before serving, prove every touched bucket is
   trustworthy by loading all partition rows *including their JSONB
   fingerprints* and re-checking each row against its own fingerprint in
   Python.
4. **Trust model**: nothing is trusted; every read re-proves everything.

Measured against a 10k-soldier / 500k-assignment dataset:

| Symptom | Evidence |
| --- | --- |
| Backfill was quadratic | 200-soldier smoke: 283.9s / **280,886 queries** (≈570 queries per bucket). At target scale it could not complete. Root cause: step 2 re-projected O(active soldiers in quarter) buckets per rebuilt bucket. |
| Reads permanently fell back to legacy | Reads require a total row for every calendar quarter back to `fairness.reset_date` (default: 2 years ago). Backfill only wrote quarters *with assignments*, so empty history quarters had no total → `_ensure_projection_ready` always failed → every projected read silently served legacy. Existing tests missed this because their fixture pins a recent reset date. |
| Read validation cost was O(all fingerprints) | Full-scale transparency read issued **20,582 queries** (~2 per soldier) and shipped every fingerprint blob to Python. |
| Fairness crashed at scale | `fairness_components` pulled exempted-duty-types through `load_soldier_inputs`, expanding all 500k assignments and blowing psycopg's 65,535-parameter limit. |
| Repair poisoned itself | Read-time repair rebuilt buckets without refreshing the quarter total, so the very next validation failed and forced fallback anyway. |

## What changed

### Phase 1 — make projections correct and linearly buildable

- Quarter totals are derived from persisted partition rows (the same rows the
  read validator recomputes from), never from canonical re-projection.
- Backfill refreshes each distinct quarter once per batch, not once per bucket.
- Backfill completion writes zero-valued totals for empty effort-history
  quarters, so reads can serve datasets whose reset date predates first
  activity.
- Any repair refreshes the quarter totals it invalidates.
- `fairness_components` resolves exempted duty-type ids directly from
  exemption/eligibility tables instead of the full canonical expansion.

### Phase 2 — remove the per-read hotspots

- Soldier-total verification: two set-based reads + server-side JSONB
  aggregate, rebuilding only genuinely stale soldiers (was ~2 point queries
  per soldier).
- Assignment→quarter key derivation runs as SQL (`generate_series`) instead of
  shipping every published assignment into Python loops.
- Giant `IN (...)` lists replaced by single array parameters
  (`app/services/sql_arrays.py`).

### Phase 3 — A/B trust redesign (this change)

The remaining cost was structural: proving every bucket on every read required
reading the fingerprint heap. The guarantee and the cost were redesigned
together.

**New read-path contract** — reads verify *structure only*:

| Check | Old read path | New read path |
| --- | --- | --- |
| Bucket completeness / versions | full-row fetch | index-only scan via covering index `ix_sqsp_soldier_quarter_cover` |
| Fingerprint self-consistency proof | Python over all rows, every read | **removed from reads**; runs hourly in the revalidation worker |
| Dirty/divergent markers → targeted rebuild | yes | yes (unchanged) |
| Quarter-total numeric divergence | recomputed every read | trusted; existence + version checked, missing/stale totals self-heal |
| Soldier totals numeric divergence | recomputed every read | trusted unless missing/stale or marker-implicated |

Why this is sound: the write path marks a bucket dirty *before* rebuilding it
and clears the marker *after*. A clean marker table therefore implies every
stored bucket matches what its writer computed. What markers do not catch —
out-of-band edits, interrupted writes that die between mark and clear — is now
the job of the periodic worker.

**Revalidation worker** (`score_projection_revalidation_worker.py`, hourly):
keyset-walks all buckets using a persisted cursor in
`score_projection_state.revalidated_after_*`, proves one bounded batch
(2,000 buckets) per tick inside PostgreSQL (JSONB shredded server-side, only
violations returned), rebuilds violations from canonical rows, wraps around
when the table is exhausted. Unmarked corruption is caught within ~an hour
instead of being paid on every request.

**Covering index** (`a2b3c4d5e6f7`): `(soldier_id, quarter_start) INCLUDE
(duty_type_id, projection_version)` — verified via `EXPLAIN` that the
completeness check is an Index Only Scan.

## Measured results

Full scale: 10k soldiers, 500k assignments, 200 teams.

| Metric | Before audit | After phase 1+2 | After A/B redesign |
| --- | ---: | ---: | ---: |
| Backfill (500k assignments) | un runnable (quadratic) | ~40 min, linear | ~40 min, linear |
| Backfill smoke query count (200 soldiers) | 280,886 | 6,031 | 6,031 |
| Transparency read queries | 20,582 | ~125 | **124** |
| Fairness read queries | crashed (65,535-param limit) | ~70 | **69** |
| Dashboard read queries | 39 (with full-JSONB fetches) | 58 | **58** |
| Single-assignment write refresh | 0.66–2.4s | stable | ~6s incl. probe insert |

Correctness: full fast suite green; legacy-vs-projected output equality
asserted across scenarios; new tests cover empty-history-quarter coverage,
marker-based repair, and worker detection of unmarked corruption.

Wall-time caveat: the scratch Docker volume used for benchmarking showed 5×
throughput swings between runs (identical query measured 3s ↔ 27s), so wall
times below ~2 minutes are not comparable across sessions. Query counts and
query plans are the reliable measures; both are structural and hold anywhere.
Re-run `backend/tests/performance/score_projection_benchmark.py` against a
production-like environment before making capacity decisions.

## Maintainability notes

- `score_projection._metadata_violation_clause()` mirrors the Python
  `_projection_row_matches_fingerprint_metadata` in `scoring.py`; they must be
  kept semantically identical. Both are documented as mirrors.
- The read-path trust model is now explicit: writers maintain correctness,
  readers check structure cheaply, the worker audits deeply. If a future write
  path mutates projection rows, it MUST go through
  `rebuild_projection_bucket` / `refresh_projection_for_change` (which mark
  dirty) or the invariant breaks silently.
- `sql_arrays.uuid_any` should be preferred over `.in_(...)` whenever the id
  set can exceed a few thousand entries.

## Remaining optimization opportunities (post-audit scan)

Ranked by expected impact; all verified against current code.

1. **Request-path full expansions of `load_soldier_inputs`** — the same defect
   class as the fairness crash, still live on two user-facing paths:
   `app/routes/shifts.py` (shift candidate/preview flows) and
   `app/services/hakpaza.py` (reserve pull). Each call expands every published
   assignment day-by-day in Python. At deployment scale these endpoints will
   take minutes per request and can exceed the psycopg 65,535-parameter limit.
   Fix: scope inputs to the shift/pull cohort instead of the whole force, or
   serve from projections once fresh.

2. **Set-based backfill** — backfill is now linear but still ~12 point queries
   × ~500k buckets ≈ 40 min. A single SQL pass (assignments joined through
   overrides/dismissals, grouped by soldier×quarter×type with
   `generate_series` day expansion server-side) could plausibly cut this to
   minutes. Highest-leverage change for cold starts and version migrations.

3. **SQL-native `_effective_duty_day_rows`** — the day-by-day Python expansion
   still powers non-projection paths: `duty_score_by_soldier` feeds the CP-SAT
   solver (`algorithm_bridge.load_soldier_inputs`) so every algorithm job pays
   it, plus `gimelim.py` scoring and the legacy fallbacks. A SQL rewrite would
   benefit solver runs even before projections are trusted there.

4. **`scoring.cumulative_score(soldier_id)`** — computes scores for *every*
   soldier in the database to return one (`duty_score_by_soldier(...).get(...)`).
   Any caller that runs per-soldier turns into O(all soldiers) work.

5. **Dead code** — `_projection_data_quarters_for_soldiers` (scoring.py) and
   `_projection_rows_by_key` (both scoring.py and score_projection.py) have no
   remaining callers after this redesign. Deletable.

6. **Dashboard query consolidation** — `summary_cards` issues ~17 sequential
   queries each carrying the full soldier-id array. Functionally fine after the
   array-param conversion, but 3–4 CTE-shaped queries would cut round trips
   further if dashboard latency still matters after re-benchmarking.
