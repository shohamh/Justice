# Duty Day Calculation — Design

## Problem

A duty's "number of days" is used for two different purposes that should not share one formula:

1. **Window/rolling-cap calculation** (rest constraints, no-double-booking, T-cap/R-cap in the CP-SAT algorithm) cares about which **calendar dates** are occupied.
2. **Effort score** cares about **wall-clock duration**, rounded up to whole days.

Today both purposes use the same formula — `(end_date - start_date).days` — because no duty record stores a time-of-day at all. `ShiftTemplate.start_time`/`end_time` and `DutyType.start_time`/`end_time` exist in the schema but are purely cosmetic: `generate_shifts()` never copies them onto the `DutyShift` it creates, and `DutyShift`/`DutyAssignment` have no time columns to receive them. So the two formulas coincide today only because there is no data that could make them diverge — a duty from Monday 14:00 to the following Monday 14:00 cannot currently be represented as anything other than a whole-day span, even though it should score as 7 days of effort while touching 8 calendar dates for window purposes.

## Scope

Full fix: thread real `start_time`/`end_time` through `DutyShift` and `DutyAssignment` (not just a formula tweak), so the data model can actually represent a duty that doesn't start/end at midnight, and the two calculations can correctly diverge.

## Core date/time model

`end_date` keeps its current exclusive meaning (the calendar date immediately after the last day touched) — this is unchanged, pure date arithmetic, and already correct for window purposes:

```
calendar_days_touched = (end_date - start_date).days
```

This is exactly what `_duty_dates()` (`backend/app/algorithm/model.py:30-36`) and `expand_dates()` (`backend/app/services/shift_templates.py`) already compute. **No change needed for window/rolling-cap logic** — it already operates on calendar dates touched, which is correct.

Add two new fields, `start_time` and `end_time` (HH:MM strings, same format as `ShiftTemplate`):
- `start_time` is the clock time on `start_date` when the duty begins.
- `end_time` is the clock time on `end_date - 1 day` (the *last* calendar day touched — not `end_date` itself, which is never touched) when the duty ends.

New helper, `score_days(start_date, end_date, start_time, end_time) -> int`, used wherever effort score needs a day-count:

```python
calendar_days_touched = (end_date - start_date).days
elapsed_hours = (calendar_days_touched - 1) * 24 + (end_time_minutes - start_time_minutes) / 60
score_days = ceil(elapsed_hours / 24)
```

Worked examples:
- 8am–5pm, single day (`calendar_days_touched = 1`): `elapsed = 0*24 + 9 = 9h → ceil(9/24) = 1`. Matches today's behavior.
- Monday 14:00 → following Monday 14:00 (`duration_days = 8`, `calendar_days_touched = 8`): `elapsed = 7*24 + 0 = 168h → ceil(168/24) = 7`. Scores as 7 days; touches 8 calendar dates for window purposes.
- Default full-day template (`start_time="00:00"`, `end_time="23:59"`, `calendar_days_touched = N`): `elapsed = (N-1)*24 + 23.983h`, `ceil(elapsed/24) = N`. Reproduces today's exact day-count (the ~1-minute slack from `23:59` vs. true midnight never changes the `ceil` result for any whole-day duration).

## Validation

When `duration_days == 1` (single calendar day touched), `end_time` must be strictly greater than `start_time` — a same-day duty cannot wrap past midnight; an overnight duty needs `duration_days >= 2` instead. When `duration_days > 1`, no ordering constraint between `start_time` and `end_time` is required, since they refer to different calendar days. This extends `_validate()` in `backend/app/services/shift_templates.py:55-77`, which today only checks `start_time`/`end_time` for HH:MM format, not relative ordering.

## Data flow

- `ShiftTemplate.start_time`/`end_time` (already exists) → copied onto the `DutyShift` at generation time in `generate_shifts()` (`backend/app/services/shift_templates.py`), which currently drops them entirely.
- `DutyShift.start_time`/`end_time` → copied onto `DutyAssignment` at assignment-creation time, at the 3 call sites that have access to the source shift:
  - `backend/app/services/algorithm_bridge.py:593` (publishing algorithm results) — via the shift looked up through `block_to_shift_map`.
  - `backend/app/services/gimelim.py:597` (reserve promotion) — via `future_shift`, already loaded.
  - `backend/app/services/assignments.py:99` (manual assignment creation) — via the `DutyShift` the caller already has (e.g. `backend/app/routes/shifts.py:373`).
- The 2 call sites without shift access fall back to the default full-day values `start_time="00:00"`, `end_time="23:59"` (today's effective behavior, since these paths already only ever produce whole-day-equivalent assignments):
  - `backend/app/routes/hakpaza.py:205` (forced call-up replacement, splits an existing assignment by date only).
  - `backend/app/routes/import_excel.py:390` (bulk Excel import, dates only, no shift association).
- `DutyBlock` (`backend/app/algorithm/types.py:31-40`) gains `start_time`/`end_time`, sourced from the `DutyShift` when blocks are built in `algorithm_bridge.py`, so the solver's in-run scoring can use the corrected formula.
- Manual (non-template) shift creation — `CreateShiftRequest`/`create_shift()` (`backend/app/routes/shifts.py:39-46`, `backend/app/services/shifts.py:94-105`), currently date-only — gains optional `start_time`/`end_time` fields defaulting to `"00:00"`/`"23:59"`.

## Score formula call sites

Three places currently compute `(end_date - start_date).days` for scoring purposes and must switch to `score_days(...)`:

1. `backend/app/algorithm/model.py::_block_score` (lines 24-27) — uses `DutyBlock.start_time`/`end_time`.
2. `backend/app/services/algorithm_bridge.py:373-375` (duty-block scoring sum) — same.
3. `backend/app/services/scoring.py::effective_duty_days()` (lines 41-95) and its consumer `backend/app/services/effort_score.py` (lines 227-237).

For (3), the per-calendar-day expansion is **preserved as-is** — `effective_duty_days()` still emits one `(date, soldier_id, duty_type_id, multiplier)` tuple per calendar day touched, which is what feeds quarter-boundary splitting and any duty-history timeline display that relies on "which days was this soldier on duty." What changes is the per-day score contribution: instead of a flat `score_per_day` per touched day, each touched day contributes:

```
score_per_day * score_days / calendar_days_touched
```

This keeps the total across all touched days exactly `score_per_day * score_days` (the corrected total), while preserving today's behavior of proportionally splitting a duty's score across quarters when it straddles a quarter boundary — just scaled down from the old (overcounted) total to the corrected one.

## Migrations

Two new migrations, adding nullable `start_time`/`end_time` `Text` columns (same type as `ShiftTemplate`'s) to `duty_shifts` and `duty_assignments`, with existing rows backfilled to `"00:00"`/`"23:59"` so historical effort-score totals for already-published assignments do not change (since `score_days` for a default-windowed historical record reproduces `calendar_days_touched` exactly, per the worked example above).

## Out of scope

- No change to `end_date` semantics, `_duty_dates()`, `expand_dates()`, or any rolling-window (T-cap/R-cap) constraint — these already correctly operate on calendar dates touched.
- No change to `DutyType.start_time`/`end_time` (display-only, unrelated to this calculation).
- No retroactive recalculation of already-finalized historical quarterly scores beyond the backfill default (which is designed to leave them unchanged).
