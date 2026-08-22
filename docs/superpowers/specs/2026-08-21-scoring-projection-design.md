# Scoring Projection for Correct, Current Performance

Date: 2026-08-21

## Goal

Make transparency, fairness components, effort breakdowns, and dashboard score
reads fast at 10,000-user scale without changing the current scoring semantics
or serving stale data after a successful mutation.

## Invariants

- Existing canonical assignment, override, dismissal, exemption, adjustment,
  soldier, and hierarchy tables remain authoritative.
- The optimized result preserves current all-time score semantics, reserve and
  call-up multipliers, dismissal handling, effective-soldier overrides,
  exemption-covered active days, quarter boundaries, and normalization rules.
- A committed scoring-affecting write is visible to subsequent scoring reads.
- Missing, incomplete, or divergent projection data never silently replaces a
  correct canonical result.
- Every projection bucket is rebuildable from canonical data.

## Architecture

Add a rebuildable scoring read model with small, independently replaceable
aggregates:

1. `soldier_score_projection`: per soldier totals such as effective score,
   effective duty days, shift count, and projection version.
2. `soldier_quarter_score_projection`: per soldier, quarter, and duty type
   effective weighted days and score, plus adjustment contributions.
3. Unit/quarter aggregate rows for the values used by effort and normalization.
4. A dirty/outbox table containing affected soldiers, quarters, units, and a
   transaction/version marker.

The exact schema should follow the current scoring functions after a detailed
bucket-by-bucket inventory. The projection must store raw inputs needed to
reconstruct displayed values, rather than only storing final formatted rows.

## Write path

Every scoring-affecting application-service write updates the affected
projection buckets synchronously in the same database transaction. This
includes assignment publish/cancel, overrides, dismissals, reserve call-up
changes, score adjustments, exemptions, hierarchy transfers, and imports.

The updater identifies affected soldiers, quarters, duty types, and old/new
hierarchy units, then recomputes those buckets from canonical rows and replaces
them transactionally. It does not rely solely on inverse `+delta` arithmetic,
because overrides, dismissals, and effective-soldier changes can rewrite the
meaning of historical rows.

The dirty/outbox record is committed with the write. A reconciliation worker
rebuilds dirty buckets, compares them with canonical recomputation, repairs
drift, and records discrepancies. This is a safety net and repair mechanism,
not the primary freshness mechanism.

## Read path

Transparency, fairness components, effort breakdowns, and dashboard score
summaries read the projection model and shared aggregate helpers. Fairness must
not call the complete transparency computation as a prerequisite.

Before serving a projected result, the read path verifies that the required
projection version is complete. If a bucket is missing, behind, or marked
divergent, it synchronously rebuilds only the affected bucket from canonical
data and then serves the result. The legacy calculation remains available as a
fallback during rollout and as a diagnostic comparator.

## Rollout

1. Add projection tables, indexes, rebuild functions, and version metadata.
2. Backfill all historical data while reads continue using the legacy path.
3. Run dual-read comparisons in tests and controlled production logging.
4. Enable projected reads only for complete, matching buckets.
5. Keep the canonical fallback and drift reconciliation until sustained
   agreement is established.
6. Remove the fallback only in a later, separately reviewed change.

Backfill and rebuild commands must be resumable, idempotent, and partitioned
by soldier/quarter so they do not require a single long transaction.

## Correctness verification

Add differential tests comparing legacy and projected results for:

- ordinary multi-day assignments;
- reserve and called-up assignments;
- dismissals and day overrides;
- effective-soldier replacements;
- score adjustments;
- temporary and permanent exemptions;
- future assignments and quarter boundaries;
- hierarchy transfers between units.

Add integration coverage for every scoring-affecting mutation path. Each test
must assert that the projection is current immediately after commit. Add a
reconciliation test that intentionally corrupts a projection bucket and
verifies repair from canonical data.

## Performance acceptance criteria

Against the existing 10,000-soldier/500,000-assignment dataset:

- transparency and fairness reads must not hydrate or iterate all historical
  assignment rows in Python;
- the normal read path must be sub-second or low-single-digit seconds,
  measured separately for database time and Python processing;
- projected reads must issue a bounded number of queries independent of
  historical assignment count;
- a single-soldier mutation must recompute only its affected buckets, with
  measured write latency recorded separately from read latency.
