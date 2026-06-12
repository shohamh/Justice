# Reserve Days Rolling-Window Cap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a soldier from accumulating more than N reserve days in any rolling W-day window, with an admin toggle to disable take-free on reserves entirely.

**Architecture:** Add two helper functions to `reserves.py` (`count_reserve_days_in_window` / `check_reserve_cap`), then call them from `swaps.take_free` (hard block) and `gimelim.preview_gimelim` (warning). Three new `SystemSetting` keys control the feature.

**Tech Stack:** Python, SQLAlchemy, pytest. No migrations needed — settings are runtime `SystemSetting` rows, not schema changes.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `backend/app/services/reserves.py` |
| Modify | `backend/app/services/swaps.py` |
| Modify | `backend/app/services/gimelim.py` |
| Extend | `backend/tests/unit/test_reserves.py` |
| Extend | `backend/tests/unit/test_swaps.py` |
| Extend | `backend/tests/unit/test_gimelim_service.py` |

---

## Task 1: Cap utilities in `reserves.py`

**Files:**
- Modify: `backend/app/services/reserves.py`
- Test: `backend/tests/unit/test_reserves.py`

### Background

`reserves.py` already imports `DutyAssignment`, `Session`, and `date`. The cap helpers need `get_setting` / `SettingNotFound` from `app.services.settings_loader` (already used in the rest of the codebase). The sliding-window algorithm is identical to `_passes_density` in `gimelim.py` — iterate over every anchor date in the union of existing + candidate dates and count days in each W-day window.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_reserves.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, Soldier, SystemSetting
from app.services.reserves import check_reserve_cap


def _make_soldier(session, pn="cap01"):
    dt = DutyType(name=f"שמירה-{pn}", score_per_day=Decimal("1"))
    loc = DutyLocation(name=f"עמדה-{pn}")
    s = Soldier(
        personal_number=pn, full_name=pn, password_hash="x",
        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False,
    )
    session.add_all([dt, loc, s])
    session.flush()
    return s, dt, loc


def _reserve(session, soldier_id, dt_id, loc_id, start, end, status="published"):
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt_id, duty_location_id=loc_id,
        start_date=start, end_date=end, status=status, is_reserve=True,
    )
    session.add(a)
    session.flush()
    return a


def test_cap_passes_when_no_existing_reserves(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-none")
    passes, current, max_days = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 1), date(2026, 7, 7)
    )
    assert passes is True
    assert current == 7   # candidate days only
    assert max_days == 14


def test_cap_passes_exactly_at_limit(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-exact")
    # 7 existing reserve days, candidate adds 7 more = 14 total, which equals the cap
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 7))
    passes, current, _ = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 8), date(2026, 7, 14)
    )
    assert passes is True
    assert current == 14


def test_cap_fails_one_over_limit(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-over")
    # 8 existing days in same 30-day window, candidate adds 7 more = 15 > 14
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 8))
    passes, current, max_days = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 9), date(2026, 7, 15)
    )
    assert passes is False
    assert current == 15
    assert max_days == 14


def test_cap_respects_settings_override(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-setting")
    admin_session.add(SystemSetting(key="reserves.max_days_per_window", value=7))
    admin_session.flush()
    # 4 existing + 4 candidate = 8 > 7
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 4))
    passes, current, max_days = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 5), date(2026, 7, 8)
    )
    assert passes is False
    assert max_days == 7


def test_cap_ignores_primary_assignments(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-primary")
    # 14 PRIMARY days should not count toward the reserve cap
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 14),
        status="published", is_reserve=False,
    )
    admin_session.add(a)
    admin_session.flush()
    passes, current, _ = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 1), date(2026, 7, 7)
    )
    assert passes is True
    assert current == 7


def test_cap_counts_algorithm_draft_reserves(admin_session):
    s, dt, loc = _make_soldier(admin_session, "cap-draft")
    # algorithm_draft reserves should also count
    _reserve(admin_session, s.id, dt.id, loc.id, date(2026, 7, 1), date(2026, 7, 8), status="algorithm_draft")
    passes, _, _ = check_reserve_cap(
        admin_session, s.id, date(2026, 7, 9), date(2026, 7, 15)
    )
    assert passes is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && uv run pytest tests/unit/test_reserves.py::test_cap_passes_when_no_existing_reserves tests/unit/test_reserves.py::test_cap_fails_one_over_limit -v
```

Expected: `ImportError` or `AttributeError` — `check_reserve_cap` not yet defined.

- [ ] **Step 3: Add imports to `reserves.py`**

At the top of `backend/app/services/reserves.py`, add these imports (keep existing ones):

```python
from datetime import date, timedelta

from app.services.settings_loader import SettingNotFound, get_setting
```

`date` and `timedelta` may already be imported — only add what's missing.

- [ ] **Step 4: Add the two helpers to `reserves.py`**

Append at the end of `backend/app/services/reserves.py`:

```python
def count_reserve_days_in_window(
    session: Session,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> int:
    """Peak reserve-day count in any W-day window that overlaps [start_date, end_date].

    Includes the candidate range itself alongside existing published/draft reserves.
    Uses the same sliding-window logic as _passes_density in gimelim.py.
    """
    try:
        W = int(get_setting(session, "reserves.window_days"))
    except SettingNotFound:
        W = 30

    existing = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.is_reserve.is_(True),
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalars().all()

    # Build the full set of dates: existing reserves + candidate
    all_dates: set[date] = set()
    for a in existing:
        d = a.start_date
        while d <= a.end_date:
            all_dates.add(d)
            d += timedelta(days=1)
    d = start_date
    while d <= end_date:
        all_dates.add(d)
        d += timedelta(days=1)

    if not all_dates:
        return 0

    sorted_dates = sorted(all_dates)
    peak = 0
    for anchor in sorted_dates:
        window_end = anchor + timedelta(days=W - 1)
        count = sum(1 for x in sorted_dates if anchor <= x <= window_end)
        if count > peak:
            peak = count
    return peak


def check_reserve_cap(
    session: Session,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> tuple[bool, int, int]:
    """Return (passes, current_peak_days, max_allowed).

    passes=True means adding [start_date, end_date] stays within the cap.
    """
    try:
        max_days = int(get_setting(session, "reserves.max_days_per_window"))
    except SettingNotFound:
        max_days = 14

    peak = count_reserve_days_in_window(session, soldier_id, start_date, end_date)
    return peak <= max_days, peak, max_days
```

- [ ] **Step 5: Run all reserve cap tests**

```
cd backend && uv run pytest tests/unit/test_reserves.py -v -k "cap"
```

Expected: all 6 cap tests PASS.

- [ ] **Step 6: Run full unit test suite to check for regressions**

```
cd backend && uv run pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add backend/app/services/reserves.py backend/tests/unit/test_reserves.py
git commit -m "feat: add check_reserve_cap utility with rolling-window logic"
```

---

## Task 2: Enforce cap + toggle in `swaps.take_free`

**Files:**
- Modify: `backend/app/services/swaps.py`
- Test: `backend/tests/unit/test_swaps.py`

### Background

`swaps.py` already imports `SettingNotFound` and `get_setting`. The `take_free` function is at line ~288. The check goes after the existing `already_pending` guard. We need to import `check_reserve_cap` from `reserves`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_swaps.py`:

```python
from app.db.models import SystemSetting
from app.services.reserves import check_reserve_cap  # just for setup
from decimal import Decimal


def _reserve_assignment(session, soldier_id, dt_id, loc_id, start, end, status="published"):
    from app.db.models import DutyAssignment
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt_id, duty_location_id=loc_id,
        start_date=start, end_date=end, status=status, is_reserve=True,
    )
    session.add(a)
    session.flush()
    return a


def _seed_with_reserve(session):
    from app.db.models import DutyAssignment, DutyLocation, DutyType, Soldier
    dt = DutyType(name="שמירה-res-swap", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-res-swap")
    owner = Soldier(personal_number="rswap-owner", full_name="Owner", password_hash="x",
                    role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    taker = Soldier(personal_number="rswap-taker", full_name="Taker", password_hash="x",
                    role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, owner, taker])
    session.flush()
    reserve_a = DutyAssignment(
        soldier_id=owner.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 7),
        status="published", is_reserve=True,
    )
    session.add(reserve_a)
    session.flush()
    return owner, taker, reserve_a, dt, loc


def test_take_free_reserve_blocked_when_feature_disabled(admin_session):
    owner, taker, reserve_a, _, _ = _seed_with_reserve(admin_session)
    admin_session.add(SystemSetting(key="reserves.allow_take_free", value=False))
    admin_session.flush()
    try:
        svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "reserve_take_free_disabled"


def test_take_free_reserve_blocked_when_cap_exceeded(admin_session):
    owner, taker, reserve_a, dt, loc = _seed_with_reserve(admin_session)
    # Give taker 14 existing reserve days in the same window (Aug 1-30)
    _reserve_assignment(admin_session, taker.id, dt.id, loc.id, date(2026, 8, 10), date(2026, 8, 23))
    try:
        svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("reserve_cap_exceeded:")


def test_take_free_reserve_succeeds_under_cap(admin_session):
    owner, taker, reserve_a, _, _ = _seed_with_reserve(admin_session)
    # No existing reserves for taker → under cap
    result = svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
    assert result.status in ("open", "applied")


def test_take_free_primary_unaffected_by_reserve_setting(admin_session):
    # Disabling allow_take_free must NOT block take-free on primary assignments
    a, b, assignment = _seed(admin_session)  # _seed from existing test file creates a primary
    admin_session.add(SystemSetting(key="reserves.allow_take_free", value=False))
    admin_session.flush()
    # Should succeed — primary assignment, not reserve
    result = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && uv run pytest tests/unit/test_swaps.py::test_take_free_reserve_blocked_when_feature_disabled tests/unit/test_swaps.py::test_take_free_reserve_blocked_when_cap_exceeded -v
```

Expected: FAIL — no reserve check exists yet.

- [ ] **Step 3: Add import to `swaps.py`**

In `backend/app/services/swaps.py`, add to the import block:

```python
from app.services.reserves import check_reserve_cap
```

- [ ] **Step 4: Add the check to `take_free` in `swaps.py`**

In `take_free`, after the `already_pending` guard (after `if existing is not None: raise SwapError("already_pending")`), add:

```python
    if assignment.is_reserve:
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

- [ ] **Step 5: Run all swap tests**

```
cd backend && uv run pytest tests/unit/test_swaps.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full unit suite**

```
cd backend && uv run pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add backend/app/services/swaps.py backend/tests/unit/test_swaps.py
git commit -m "feat: block take-free on reserves when disabled or cap exceeded"
```

---

## Task 3: Cap warning in `preview_gimelim`

**Files:**
- Modify: `backend/app/services/gimelim.py`
- Test: `backend/tests/unit/test_gimelim_service.py`

### Background

`gimelim.py` already imports `get_setting` / `SettingNotFound`. `preview_gimelim` builds a `warnings: list[str]` and currently adds `"no_future_slot_found"` when no future slot exists. We add a second possible warning: `"reserve_cap_exceeded:{current}/{max_days}"` for soldier B. The preview is **not blocked** — warnings are informational.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_gimelim_service.py`:

```python


def _make_full_gimelim_scene(session):
    """Returns (dt, loc, soldier_a, soldier_b, shift, primary, reserve)."""
    from app.db.models import DutyAssignment, DutyLocation, DutyReserveLink, DutyShift, DutyType, HierarchyNode, Soldier
    node = HierarchyNode(name="unit-cap")
    session.add(node)
    session.flush()

    dt = DutyType(name="שמירה-cap", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-cap")
    soldier_a = _make_soldier(session, "gcap-a", "A-cap", node_id=node.id)
    soldier_b = _make_soldier(session, "gcap-b", "B-cap", node_id=node.id)
    session.add_all([dt, loc])
    session.flush()

    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 7), required_count=1,
    )
    session.add(shift)
    session.flush()

    primary = DutyAssignment(
        soldier_id=soldier_a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 7),
        status="published", is_reserve=False, duty_shift_id=shift.id,
    )
    reserve = DutyAssignment(
        soldier_id=soldier_b.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 7),
        status="published", is_reserve=True, duty_shift_id=shift.id,
    )
    session.add_all([primary, reserve])
    session.flush()

    link = DutyReserveLink(primary_assignment_id=primary.id, reserve_assignment_id=reserve.id)
    session.add(link)
    session.flush()
    return dt, loc, soldier_a, soldier_b, shift, primary, reserve


def test_preview_gimelim_warns_when_reserve_over_cap(admin_session):
    dt, loc, soldier_a, soldier_b, shift, primary, reserve = _make_full_gimelim_scene(admin_session)

    # Saturate B's window: give them 14 existing reserve days in the same 30-day window
    extra = DutyAssignment(
        soldier_id=soldier_b.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 8), end_date=date(2026, 9, 21),
        status="published", is_reserve=True, duty_shift_id=shift.id,
    )
    admin_session.add(extra)
    admin_session.flush()

    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=0,
        reason="חופשה",
        actor_id=soldier_a.id,
    )
    cap_warnings = [w for w in preview.warnings if w.startswith("reserve_cap_exceeded:")]
    assert len(cap_warnings) == 1


def test_preview_gimelim_no_warning_when_reserve_under_cap(admin_session):
    dt, loc, soldier_a, soldier_b, shift, primary, reserve = _make_full_gimelim_scene(admin_session)
    preview = preview_gimelim(
        admin_session,
        shift_id=shift.id,
        primary_assignment_id=primary.id,
        rest_days=0,
        reason="חופשה",
        actor_id=soldier_a.id,
    )
    cap_warnings = [w for w in preview.warnings if w.startswith("reserve_cap_exceeded:")]
    assert len(cap_warnings) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && uv run pytest tests/unit/test_gimelim_service.py::test_preview_gimelim_warns_when_reserve_over_cap -v
```

Expected: FAIL — no cap check in `preview_gimelim` yet.

- [ ] **Step 3: Add import to `gimelim.py`**

In `backend/app/services/gimelim.py`, add to the imports from `app.services.reserves`:

```python
from app.services.reserves import ReserveError, call_up_reserve, check_reserve_cap, dismiss_primary
```

(Replace the existing `from app.services.reserves import ReserveError, call_up_reserve, dismiss_primary` line.)

- [ ] **Step 4: Add cap warning to `preview_gimelim`**

In `preview_gimelim`, after `reserve_b` is loaded (after `if reserve_b is None: raise GimelimError("reserve_not_found")`), add:

```python
    cap_passes, cap_current, cap_max = check_reserve_cap(
        session, reserve_b.soldier_id,
        primary_a.start_date, primary_a.end_date,
    )
    if not cap_passes:
        warnings.append(f"reserve_cap_exceeded:{cap_current}/{cap_max}")
```

Note: add the cap check right after `warnings: list[str] = []` and before `future_result = _find_future_slot(...)` — both are adjacent lines in the function.

- [ ] **Step 5: Run gimelim tests**

```
cd backend && uv run pytest tests/unit/test_gimelim_service.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full unit suite**

```
cd backend && uv run pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add backend/app/services/gimelim.py backend/tests/unit/test_gimelim_service.py
git commit -m "feat: warn in gimelim preview when reserve soldier exceeds cap"
```

---

## Task 4: Final integration smoke-test

**Files:**
- Test: `backend/tests/unit/` (no new files — just run the full suite)

- [ ] **Step 1: Run the complete test suite**

```
cd backend && uv run pytest -q
```

Expected: all tests pass, no regressions.

- [ ] **Step 2: Verify the three setting keys work end-to-end via the settings API**

Start the dev stack (`.\dev.ps1 -NoBot`) and run:

```powershell
# Set the toggle off
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/system-settings" `
  -Headers @{ Authorization = "Bearer <admin_token>" } `
  -ContentType "application/json" `
  -Body '{"key":"reserves.allow_take_free","value":false}'

# Attempt take-free on a reserve assignment — expect 400 reserve_take_free_disabled
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/swaps/take-free" `
  -Headers @{ Authorization = "Bearer <soldier_token>" } `
  -ContentType "application/json" `
  -Body '{"duty_assignment_id":"<reserve_assignment_uuid>"}'
```

Expected response: `{"detail": "reserve_take_free_disabled"}` with HTTP 400.

- [ ] **Step 3: Final commit (if any fixups were needed)**

```
git add -p
git commit -m "fix: reserve cap integration smoke-test fixups"
```

Only commit if step 2 revealed a real bug. Otherwise skip this step.
