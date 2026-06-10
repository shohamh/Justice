# Reserve Days Rolling-Window Cap

**Date:** 2026-06-10  
**Status:** Approved

## Problem

A soldier can call `POST /swaps/take-free` on every reserve assignment in a
7-day שמירה block, accumulating 7 standby-reserve days that score at only
0.2× per day. The algorithm's density constraint counts those dates as
"occupied", so the soldier can't be assigned primaries during that window —
yet their score barely moves. The result: a low-score soldier gets locked out
of primary duties for weeks while still appearing under-served to the
scheduler.

## Solution

Enforce a hard cap: no soldier may hold more than **N reserve days in any
rolling W-day window** (default N=14, W=30). Both numbers are stored in
`SystemSetting` so commanders can adjust them without a deploy.

---

## Architecture

### 1. Settings

| Key | Default | Meaning |
|-----|---------|---------|
| `reserves.allow_take_free` | `true` | Whether soldiers may use take-free on reserve assignments |
| `reserves.max_days_per_window` | `14` | Max reserve days in any rolling window |
| `reserves.window_days` | `30` | Rolling window length in days |

Read using the existing `get_setting` / `SettingNotFound` fallback pattern
already used for `algorithm.T`, `algorithm.W`, `eligibility.mitvahim_months`,
etc.

### 2. Cap utility — `reserves.py`

```python
def count_reserve_days_in_window(
    session: Session,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> int:
    """
    Peak reserve-day count across all rolling W-day windows that overlap
    [start_date, end_date], including the candidate range itself.
    Uses the same sliding-window logic as _passes_density in gimelim.py.
    Counts is_reserve=True assignments with status "published" or
    "algorithm_draft".
    """
```

```python
def check_reserve_cap(
    session: Session,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> tuple[bool, int, int]:
    """
    Returns (passes, current_peak_days, max_allowed).
    passes=True means adding [start_date, end_date] stays within the cap.
    """
```

Both helpers load `reserves.max_days_per_window` and `reserves.window_days`
from settings (defaulting to 14 and 30).

### 3. Enforcement in `swaps.take_free`

After the existing `assignment_not_found` / `cannot_take_own_duty` /
`not_published` / `already_pending` guards, add:

```python
if assignment.is_reserve:
    # Toggle: admin can disable take-free on reserve assignments entirely
    try:
        allow = bool(get_setting(session, "reserves.allow_take_free"))
    except SettingNotFound:
        allow = True
    if not allow:
        raise SwapError("reserve_take_free_disabled")

    passes, current, max_days = check_reserve_cap(
        session, covering_soldier_id,
        assignment.start_date, assignment.end_date,
    )
    if not passes:
        raise SwapError(f"reserve_cap_exceeded:{current}/{max_days}")
```

**Hard block** — the swap request is never created. The 400 response
`detail` field carries one of:
- `reserve_take_free_disabled` — feature is turned off entirely
- `reserve_cap_exceeded:X/Y` — soldier is over cap

Frontend Hebrew messages:
> *"לא ניתן לקחת תורנות רזרבה — קחת רזרבה חופשית מושבת במערכת."*
> *"לא ניתן לקחת תורנות רזרבה זו — ניצלת כבר X מתוך Y ימי רזרבה בחלון של Z ימים."*

### 4. Warning in `preview_gimelim`

After `reserve_b` is loaded, before the preview token is stored:

```python
passes, current, max_days = check_reserve_cap(
    session, reserve_b.soldier_id,
    primary_a.start_date, primary_a.end_date,
)
if not passes:
    warnings.append(f"reserve_cap_exceeded:{current}/{max_days}")
```

**Warning only, not a block** — the preview proceeds and the token is
issued. The commander sees the warning on the confirmation screen and may
choose to override. `commit_gimelim` does not re-check (commander-initiated
action, already reviewed).

The frontend parses `reserve_cap_exceeded:X/Y` from `warnings` and displays:

> *"חייל הרזרבה ניצל כבר X מתוך Y ימי רזרבה בחלון של Z ימים — שקול לשנות
> רזרבה."*

---

## Out of Scope

- **Algorithm solver** — reserve assignments created by the CP-SAT solver
  are `algorithm_draft` and require commander review before publishing.
  That human gate is sufficient for now. Adding a solver-level reserve
  density constraint is a future enhancement.
- **`commit_gimelim` hard block** — gimelim commit is commander-initiated;
  the preview warning is the appropriate gate.

---

## Testing

### Unit tests (`test_reserve_cap.py` or extend existing unit suite)

- `check_reserve_cap` returns `(True, ...)` when soldier has no existing
  reserves.
- Returns `(False, current, max)` when the candidate range pushes any
  rolling window over the cap.
- Edge: existing days exactly at cap → passes; one day over → fails.
- Settings override: `reserves.max_days_per_window=7` lowers the cap
  correctly.

### Integration tests (extend existing swap / scoring integration suite)

- `POST /swaps/take-free` on a reserve assignment returns 400
  `reserve_take_free_disabled` when `reserves.allow_take_free=false`.
- Returns 400 `reserve_cap_exceeded:X/Y` when soldier is at cap.
- Succeeds when soldier is under cap and feature is enabled.
- `preview_gimelim` includes `reserve_cap_exceeded` in `warnings` when B
  is over cap but still returns HTTP 200 with a valid token.
