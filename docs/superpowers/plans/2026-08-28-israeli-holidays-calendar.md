# Israeli Holidays in the Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Israeli holidays in the calendar and duty/constraint UIs — a badge listing crossed holiday names on constraint requests/approvals and duty shift modals, and a distinct day-cell background on the calendar — using the holiday data source that already exists but is unused.

**Architecture:** A shared backend helper computes which holidays a date range crosses (respecting the codebase's existing inclusive/exclusive end-date split between constraints and shifts), exposed as a new `crossed_holidays` field on the existing constraint and shift read schemas. The frontend renders that field with a new shared `HolidayBadge` component (styled like the existing warning/info badge pattern, but amber) in three places, and separately fetches the existing `/calendar/holidays` list to shade calendar day cells and a new in-app date-picker grid that replaces `DateInput`'s native popup.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy (backend), React + TypeScript + `@fullcalendar/react` + `react-calendar` (already an unused dependency) + `react-i18next` (frontend), pytest / vitest.

**Spec:** [docs/superpowers/specs/2026-08-28-israeli-holidays-design.md](../specs/2026-08-28-israeli-holidays-design.md)

## Global Constraints

- Holiday data is the full, unfiltered IL calendar from the `holidays` PyPI package (no curation to "major holidays").
- All holiday information is informational only — it never blocks constraint submission or approval, or any shift operation.
- `PersonalConstraint.start_date`/`end_date` are **inclusive** on both ends. `DutyShift`/`CalendarShiftOut` `start_date`/`end_date` has an **exclusive** `end_date`. Any crossing computation must respect this per call site — never share one call across both without the explicit flag.
- No new persisted data — holidays are computed at read time from the `holidays` package, not stored per-request.
- New i18n strings go under a new `holidays` top-level namespace in `frontend/src/i18n/he.json` — grep for `"holidays"` before adding (this repo has had silent duplicate-key collisions on other namespaces).
- All new/changed backend routes are prefixed `/api` at test-call time per this repo's existing convention (`client.post("/api/me/constraints", ...)`).

---

## Task 1: Backend shared holiday-crossing helper

**Files:**
- Create: `backend/app/services/holidays.py`
- Modify: `backend/app/routes/calendar_holidays.py` (reuse the new shared year-lookup instead of calling `hol.country_holidays` directly)
- Test: `backend/app/services/tests/test_holidays.py`

**Interfaces:**
- Produces: `HolidayHit` (Pydantic model, fields `date: date`, `name: str`) and `holidays_in_range(start: date, end: date, *, end_inclusive: bool) -> list[HolidayHit]`, both importable from `app.services.holidays`. Tasks 2 and 3 consume these.

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_holidays.py
from __future__ import annotations

from datetime import date

from app.services.holidays import HolidayHit, holidays_in_range


def test_inclusive_range_includes_holiday_on_end_date():
    # Rosh Hashana 5787 starts the evening of 2026-09-11; the `holidays`
    # package marks 2026-09-12 as "Rosh Hashana".
    hits = holidays_in_range(date(2026, 9, 12), date(2026, 9, 12), end_inclusive=True)
    assert hits == [HolidayHit(date=date(2026, 9, 12), name="Rosh Hashanah")]


def test_exclusive_range_excludes_holiday_on_end_date():
    # Same date, but as an exclusive shift end_date the holiday on that date
    # is NOT covered (the shift's last worked day is the day before).
    hits = holidays_in_range(date(2026, 9, 11), date(2026, 9, 12), end_inclusive=False)
    assert hits == []


def test_exclusive_range_includes_holiday_the_day_before_end_date():
    hits = holidays_in_range(date(2026, 9, 12), date(2026, 9, 13), end_inclusive=False)
    assert hits == [HolidayHit(date=date(2026, 9, 12), name="Rosh Hashanah")]


def test_range_spanning_year_boundary():
    # Independence Day (Yom HaAtzmaut) 5786 falls on 2026-04-22; also check a
    # range that crosses from one Gregorian year into the next still works.
    hits = holidays_in_range(date(2025, 12, 30), date(2026, 1, 2), end_inclusive=True)
    assert hits == [HolidayHit(date=date(2026, 1, 1), name="New Year's Day")]


def test_range_with_no_holidays_returns_empty_list():
    hits = holidays_in_range(date(2026, 6, 1), date(2026, 6, 5), end_inclusive=True)
    assert hits == []


def test_end_before_start_after_exclusive_adjustment_returns_empty_list():
    # A same-day exclusive-end shift (start_date == end_date) covers zero
    # days — must not raise or invert the range.
    hits = holidays_in_range(date(2026, 6, 1), date(2026, 6, 1), end_inclusive=False)
    assert hits == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/app/services/tests/test_holidays.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.holidays'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/holidays.py
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import holidays as hol
from pydantic import BaseModel


class HolidayHit(BaseModel):
    date: date
    name: str


@lru_cache(maxsize=64)
def holidays_for_year(year: int) -> dict[date, str]:
    """IL holiday calendar for one Gregorian year, cached (the `holidays`
    package rebuilds its internal table on every call otherwise, which is
    wasteful when many shifts/constraints in the same request need it)."""
    return dict(hol.country_holidays("IL", years=year))


def holidays_in_range(start: date, end: date, *, end_inclusive: bool) -> list[HolidayHit]:
    """Holidays touching [start, last_day], where last_day is `end` itself
    when end_inclusive, or the day before `end` otherwise (DutyShift/
    CalendarShiftOut end_date is exclusive — the first day NOT covered)."""
    last_day = end if end_inclusive else end - timedelta(days=1)
    if last_day < start:
        return []
    merged: dict[date, str] = {}
    for year in range(start.year, last_day.year + 1):
        merged.update(holidays_for_year(year))
    return [
        HolidayHit(date=d, name=name)
        for d, name in sorted(merged.items())
        if start <= d <= last_day
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/app/services/tests/test_holidays.py -v`
Expected: PASS (6 tests). If the `holidays` package's English name for Rosh Hashanah/New Year's Day differs from what's asserted, run `python -c "import holidays; print(sorted(holidays.country_holidays('IL', years=2026).items()))"` and update the assertions to match the installed package version's exact strings — the behavior under test (inclusive/exclusive/year-boundary/empty) is what matters, not the exact English label.

- [ ] **Step 5: Refactor `calendar_holidays.py` to reuse the cached lookup**

```python
# backend/app/routes/calendar_holidays.py — replace the full file
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.services.holidays import holidays_for_year

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/holidays")
def list_holidays(
    year: int = Query(ge=1900, le=2100),
    _user: Soldier = Depends(require_password_changed),
) -> list[dict]:
    il = holidays_for_year(year)
    return [{"date": str(d), "name": name} for d, name in sorted(il.items())]
```

- [ ] **Step 6: Run the full backend test suite for regressions**

Run: `pytest -q`
Expected: PASS, no new failures (this step only refactored an internal call, the route's response shape is unchanged).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/holidays.py backend/app/services/tests/test_holidays.py backend/app/routes/calendar_holidays.py
git commit -m "feat: add shared IL holiday-crossing helper"
```

---

## Task 2: `crossed_holidays` on personal constraints

**Files:**
- Modify: `backend/app/routes/constraints.py` (`ConstraintOut` class at line 55, `_out()` helper at line 110)
- Test: `backend/tests/integration/test_constraints_api.py`

**Interfaces:**
- Consumes: `HolidayHit`, `holidays_in_range` from `app.services.holidays` (Task 1).
- Produces: `ConstraintOut.crossed_holidays: list[HolidayHit]`, populated on every constraint read (submit response, `/me/constraints`, `/constraints/pending`, detail reads) since they all funnel through `_out()`.

- [ ] **Step 1: Write the failing test**

```python
# Add to backend/tests/integration/test_constraints_api.py
def test_submit_response_includes_crossed_holidays(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500020")
    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            # 2026-09-12 is Rosh Hashanah in the IL holiday calendar.
            "start_date": "2026-09-10",
            "end_date": "2026-09-14",
            "reason": "חופשה",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["crossed_holidays"] == [{"date": "2026-09-12", "name": body["crossed_holidays"][0]["name"]}]


def test_submit_response_has_empty_crossed_holidays_when_no_holiday_in_range(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500021")
    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={"start_date": "2026-06-01", "end_date": "2026-06-05", "reason": "חופשה"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["crossed_holidays"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_constraints_api.py -v -k crossed_holidays`
Expected: FAIL with a `KeyError`/`pydantic.ValidationError`-shaped failure — `crossed_holidays` missing from the response body (the first assertion's `body["crossed_holidays"]` raises `KeyError`).

- [ ] **Step 3: Implement**

In `backend/app/routes/constraints.py`, add the import near the top (alongside the existing imports):

```python
from app.services.holidays import HolidayHit, holidays_in_range
```

Add the field to `ConstraintOut` (after `commander_approved_by: PersonRefOut | None = None` at line 75):

```python
    commander_approved_by: PersonRefOut | None = None
    crossed_holidays: list[HolidayHit] = []
```

Update `_out()` to populate it (add before the `return ConstraintOut(` statement, and add the kwarg into the constructor call):

```python
def _out(
    session: Session,
    c: PersonalConstraint,
    soldier_name: str = "",
    node_name: str | None = None,
    include_reason: bool = True,
    nearest_commander: NearestApproverOut | None = None,
    nearest_duty_manager: NearestApproverOut | None = None,
    can_approve: bool = True,
    can_cancel: bool = False,
    audit_times: dict[uuid.UUID, datetime] | None = None,
) -> ConstraintOut:
    crossed_holidays = holidays_in_range(c.start_date, c.end_date, end_inclusive=True)
    return ConstraintOut(
        id=c.id,
        soldier_id=c.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        start_date=c.start_date,
        end_date=c.end_date,
        reason=c.reason if include_reason else None,
        status=c.status,
        decided_by=person_ref(session, c.decided_by),
        decided_at=c.decided_at,
        decision_note=c.decision_note,
        created_at=c.created_at,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
        can_approve=can_approve,
        can_cancel=can_cancel,
        requested_at=c.created_at,
        updated_at=latest_activity(c.created_at, c.decided_at, (audit_times or {}).get(c.id)),
        waiting_on=resolve_waiting_on(session, soldier_id=c.soldier_id, status=c.status),
        commander_approved_by=person_ref(session, c.commander_approved_by),
        crossed_holidays=crossed_holidays,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/integration/test_constraints_api.py -v`
Expected: PASS, including the two new tests and all pre-existing ones in that file (adding a field with a default doesn't break existing assertions that don't check for it).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/constraints.py backend/tests/integration/test_constraints_api.py
git commit -m "feat: add crossed_holidays to personal constraint responses"
```

---

## Task 3: `crossed_holidays` on duty shift calendar responses

**Files:**
- Modify: `backend/app/routes/calendar.py` (`CalendarShiftOut` class at line 83, `get_shift_detail` at line 173, `calendar_shifts` list endpoint at line 253)
- Test: Create `backend/tests/integration/test_calendar_api.py` (confirmed no `test_calendar*.py` exists yet in `backend/tests/integration/`).

**Interfaces:**
- Consumes: `HolidayHit`, `holidays_in_range` from `app.services.holidays` (Task 1).
- Produces: `CalendarShiftOut.crossed_holidays: list[HolidayHit]`, populated on both `/calendar/shifts/{shift_id}` and `/calendar/shifts` (list) responses.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/integration/test_calendar_api.py (create if it doesn't exist;
# add imports as needed to match this repo's fixture conventions, e.g.:)
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.duty_config import create_duty_type
from app.services.shifts import create_shift
from tests.helpers import auth_headers, create_node, create_soldier
from decimal import Decimal
from app.db.models import DutyLocation


def _make_duty_type_and_location(session, name_suffix: str):
    dt = create_duty_type(session, name=f"dt_cal_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_cal_{name_suffix}")
    session.add(loc)
    session.flush()
    return dt, loc


def test_shift_detail_includes_crossed_holidays(client: TestClient, admin_session: Session):
    dt, loc = _make_duty_type_and_location(admin_session, "1")
    # end_date is EXCLUSIVE: this shift covers 2026-09-11 only, the day
    # before Rosh Hashanah (2026-09-12) — so it should cross zero holidays.
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 11), end_date=date(2026, 9, 12),
    )
    admin_session.commit()
    s = create_soldier(admin_session, personal_number="7500030")
    r = client.get(f"/api/calendar/shifts/{shift.id}", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    assert r.json()["crossed_holidays"] == []


def test_shift_detail_includes_crossed_holidays_when_shift_covers_holiday(client: TestClient, admin_session: Session):
    dt, loc = _make_duty_type_and_location(admin_session, "2")
    # Covers 2026-09-11 through 2026-09-12 inclusive (end_date exclusive of 09-13).
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 11), end_date=date(2026, 9, 13),
    )
    admin_session.commit()
    s = create_soldier(admin_session, personal_number="7500031")
    r = client.get(f"/api/calendar/shifts/{shift.id}", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    dates = [h["date"] for h in r.json()["crossed_holidays"]]
    assert dates == ["2026-09-12"]


def test_calendar_shift_list_includes_crossed_holidays(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="division", name="div_cal1")
    dt, loc = _make_duty_type_and_location(admin_session, "3")
    create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 11), end_date=date(2026, 9, 13),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    s = create_soldier(admin_session, personal_number="7500032", hierarchy_node_id=node.id)
    r = client.get(
        "/api/calendar/shifts",
        params={"node_id": str(node.id), "date_from": "2026-09-01", "date_to": "2026-09-30"},
        headers=auth_headers(s),
    )
    assert r.status_code == 200, r.text
    shifts = r.json()["shifts"]
    assert len(shifts) == 1
    assert [h["date"] for h in shifts[0]["crossed_holidays"]] == ["2026-09-12"]
```

If `create_shift` doesn't accept an `eligible_node_ids` kwarg, or the calendar list route needs different query params, check `backend/app/services/shifts.py::create_shift`'s actual signature and an existing passing test in `backend/app/services/tests/test_calendar_shifts.py` or `backend/tests/integration/` that calls `/api/calendar/shifts` with `node_id`, and match its exact setup instead.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest backend/tests/integration/test_calendar_api.py -v`
Expected: FAIL — `crossed_holidays` missing from response bodies.

- [ ] **Step 4: Implement**

In `backend/app/routes/calendar.py`, add the import near the top:

```python
from app.services.holidays import HolidayHit, holidays_in_range
```

Add the field to `CalendarShiftOut` (after `swap_request_count: int = 0`):

```python
class CalendarShiftOut(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_type_color: str
    required_range_type: str | None = None
    duty_location_name: str
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    start_at: datetime
    end_at: datetime
    required_count: int
    assigned_count: int
    fill_status: str
    reserve_count: int
    assignees: list[CalendarShiftAssignee]
    swap_request_count: int = 0
    crossed_holidays: list[HolidayHit] = []
```

Update `get_shift_detail` (single-shift endpoint):

```python
@router.get("/shifts/{shift_id}", response_model=CalendarShiftOut)
def get_shift_detail(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarShiftOut:
    raw = get_single_shift(session, shift_id=shift_id)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    swap_count = _swap_counts_for_shifts(session, [shift_id]).get(shift_id, 0)
    crossed_holidays = holidays_in_range(raw["start_date"], raw["end_date"], end_inclusive=False)
    shift = CalendarShiftOut(**raw, swap_request_count=swap_count, crossed_holidays=crossed_holidays)
    roots = scope_root_ids(session, user)
    _redact_shift_reasons(shift, user, roots)
    return shift
```

Update the list endpoint's loop (find the function containing `raw = get_calendar_shifts(` around line 272 — read the ~15 lines above it first to get its exact `def` name and signature before editing):

```python
    swap_counts = _swap_counts_for_shifts(session, [s["id"] for s in raw])
    shifts = []
    for s in raw:
        crossed_holidays = holidays_in_range(s["start_date"], s["end_date"], end_inclusive=False)
        shift = CalendarShiftOut(
            **s,
            swap_request_count=swap_counts.get(s["id"], 0),
            crossed_holidays=crossed_holidays,
        )
        _redact_shift_reasons(shift, user, roots)
        shifts.append(shift)
    return CalendarShiftsResponse(shifts=shifts)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/integration/test_calendar_api.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full backend test suite for regressions**

Run: `pytest -q`
Expected: PASS, no new failures.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/calendar.py backend/tests/integration/test_calendar_api.py
git commit -m "feat: add crossed_holidays to calendar shift responses"
```

---

## Task 4: Frontend API types + shared `HolidayBadge` component

**Files:**
- Modify: `frontend/src/api/constraints.ts` (add field to `PersonalConstraint`)
- Modify: `frontend/src/api/calendar.ts` (add field to `CalendarShift`)
- Create: `frontend/src/components/HolidayBadge.tsx`
- Test: `frontend/src/components/HolidayBadge.test.tsx`
- Modify: `frontend/src/i18n/he.json` (new `holidays` namespace)

**Interfaces:**
- Produces: `HolidayBadge({ holidays }: { holidays: { date: string; name: string }[] })` — a React component. Renders `null` when `holidays` is empty. Renders an amber pill with `data-testid="holiday-badge"` and a click-to-open popover listing each holiday's formatted date and name when non-empty. Tasks 5, 6, and 7 consume this component and the `crossed_holidays` field on `PersonalConstraint`/`CalendarShift`.

- [ ] **Step 1: Grep for i18n key collisions before adding**

Run: `Select-String -Path frontend/src/i18n/he.json -Pattern '"holidays"'` (or `grep -n '"holidays"' frontend/src/i18n/he.json` in bash)
Expected: no matches (confirmed already during design research — re-check here since the file may have changed).

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/HolidayBadge.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import HolidayBadge from "./HolidayBadge";

describe("HolidayBadge", () => {
  it("renders nothing when there are no crossed holidays", () => {
    const { container } = render(<HolidayBadge holidays={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a badge and opens a popover listing holiday names on click", () => {
    render(<HolidayBadge holidays={[{ date: "2026-09-12", name: "Rosh Hashanah" }]} />);
    const badge = screen.getByTestId("holiday-badge");
    expect(badge).toBeInTheDocument();
    expect(screen.queryByText("Rosh Hashanah")).not.toBeInTheDocument();

    fireEvent.click(badge);
    expect(screen.getByText("Rosh Hashanah")).toBeInTheDocument();
  });

  it("lists every crossed holiday when there are multiple", () => {
    render(
      <HolidayBadge
        holidays={[
          { date: "2026-09-12", name: "Rosh Hashanah" },
          { date: "2026-09-13", name: "Rosh Hashanah II" },
        ]}
      />
    );
    fireEvent.click(screen.getByTestId("holiday-badge"));
    expect(screen.getByText("Rosh Hashanah")).toBeInTheDocument();
    expect(screen.getByText("Rosh Hashanah II")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- HolidayBadge` (from `frontend/`)
Expected: FAIL — `Cannot find module './HolidayBadge'`.

- [ ] **Step 4: Implement the component**

```tsx
// frontend/src/components/HolidayBadge.tsx
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { formatDate } from "../utils/formatDate";

export interface HolidayHit {
  date: string;
  name: string;
}

export default function HolidayBadge({ holidays }: { holidays: HolidayHit[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({});
  const btnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const POPOVER_WIDTH = 224;
  const MARGIN = 8;

  useLayoutEffect(() => {
    if (!open) return;
    function reposition() {
      const btn = btnRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      const left = Math.min(
        Math.max(rect.left, MARGIN),
        window.innerWidth - POPOVER_WIDTH - MARGIN
      );
      setPopoverStyle({ position: "fixed", top: rect.bottom + 4, left });
    }
    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (
        btnRef.current && !btnRef.current.contains(e.target as Node) &&
        popoverRef.current && !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  if (holidays.length === 0) return null;

  const label = t("holidays.badge_label", { count: holidays.length });

  return (
    <span className="relative inline-block">
      <button
        ref={btnRef}
        type="button"
        aria-label={label}
        title={label}
        data-testid="holiday-badge"
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className="inline-flex items-center gap-0.5 rounded bg-amber-100 px-1.5 py-0.5 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
      >
        📅 <span className="text-[10px] leading-4">{holidays.length}</span>
      </button>
      {open && (
        <div
          ref={popoverRef}
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
          style={popoverStyle}
          className="z-[70] w-56 max-w-[calc(100vw-1rem)] rounded border border-gray-200 bg-white p-2 text-xs text-gray-700 shadow-lg dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
        >
          <p className="font-semibold mb-1">{t("holidays.calendar_legend")}</p>
          <ul className="space-y-0.5">
            {holidays.map((h) => (
              <li key={h.date}>{formatDate(h.date)} — {h.name}</li>
            ))}
          </ul>
        </div>
      )}
    </span>
  );
}
```

- [ ] **Step 5: Add i18n strings**

Add a new top-level key to `frontend/src/i18n/he.json` (place alongside other top-level namespaces, e.g. near `unit_calendar`):

```json
"holidays": {
  "badge_label": "חוצה חג ({{count}})",
  "calendar_legend": "חגים בטווח:",
  "crossed_note": "טווח הבקשה חוצה חג/ים: {{names}}"
},
```

- [ ] **Step 6: Extend the API types**

`frontend/src/api/constraints.ts` — add to the `PersonalConstraint` interface (after `can_cancel?: boolean;`):

```ts
  can_cancel?: boolean;
  crossed_holidays: { date: string; name: string }[];
```

`frontend/src/api/calendar.ts` — add to the `CalendarShift` interface (after `swap_request_count?: number;`):

```ts
  swap_request_count?: number;
  crossed_holidays: { date: string; name: string }[];
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `npm test -- HolidayBadge`
Expected: PASS (3 tests).

Then run the full frontend suite and typecheck to catch any other place constructing a `PersonalConstraint`/`CalendarShift` object literal that now needs the new required field (e.g. test fixtures/mocks):

Run: `npm run typecheck`
Expected: any errors here point to test fixture files building `PersonalConstraint`/`CalendarShift` literals — add `crossed_holidays: []` to each one flagged.

Run: `npm test`
Expected: PASS, no new failures.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/HolidayBadge.tsx frontend/src/components/HolidayBadge.test.tsx frontend/src/api/constraints.ts frontend/src/api/calendar.ts frontend/src/i18n/he.json
git commit -m "feat: add HolidayBadge component and crossed_holidays API types"
```

---

## Task 5: Holiday badge in duty shift modals

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`
- Modify: `frontend/src/components/dashboard/DutyDetailModal.tsx`
- Test: extend or create `frontend/src/components/ShiftDetailPanel.test.tsx` and `frontend/src/components/dashboard/DutyDetailModal.test.tsx` (check whether these already exist first; if so add cases to them, matching their existing render/mock setup).

**Interfaces:**
- Consumes: `HolidayBadge` from `./HolidayBadge` (Task 4), `CalendarShift.crossed_holidays` (Task 4).

- [ ] **Step 1: Check for existing test files and their mocking conventions**

Run: `Get-ChildItem frontend/src/components -Filter "ShiftDetailPanel.test.tsx"` and `Get-ChildItem frontend/src/components/dashboard -Filter "DutyDetailModal.test.tsx"`. Read whichever exist to match their existing `vi.mock(...)` setup for `../api/calendar` / `../../api/calendar` before writing new test cases, since both modals fetch shift data through that module.

- [ ] **Step 2: Write the failing tests**

If `ShiftDetailPanel.test.tsx` exists, add:

```tsx
it("shows a holiday badge when the shift crosses a holiday", () => {
  const shift = {
    /* ...spread whatever minimal CalendarShift fixture the existing tests in
       this file already use... */
    crossed_holidays: [{ date: "2026-09-12", name: "Rosh Hashanah" }],
  };
  render(<ShiftDetailPanel shift={shift} onClose={() => {}} onRefreshNeeded={() => {}} />);
  expect(screen.getByTestId("holiday-badge")).toBeInTheDocument();
});

it("shows no holiday badge when the shift crosses no holiday", () => {
  const shift = { /* ...same base fixture... */ crossed_holidays: [] };
  render(<ShiftDetailPanel shift={shift} onClose={() => {}} onRefreshNeeded={() => {}} />);
  expect(screen.queryByTestId("holiday-badge")).not.toBeInTheDocument();
});
```

If the file doesn't exist yet, create it modeled on how `DutyDetailModal` or another modal test in this repo mocks `getShift`/`listSwapsForAssignment`/`listEffectiveDuties` — read one such existing modal test file first (e.g. search `frontend/src/components/**/*.test.tsx` for `vi.mock("../api/shifts"`) and copy its mock shape before writing assertions, since `ShiftDetailPanel` fetches several related resources on mount.

Add the equivalent pair of cases to `DutyDetailModal.test.tsx`, following that file's existing `duty`/`typeNames`/`locationNames` prop fixture and its `getCalendarShift` mock.

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm test -- ShiftDetailPanel DutyDetailModal`
Expected: FAIL — no `holiday-badge` testid rendered yet.

- [ ] **Step 4: Implement**

In `frontend/src/components/ShiftDetailPanel.tsx`, add the import near the top (with the other local imports):

```tsx
import HolidayBadge from "./HolidayBadge";
```

Render it next to the header's date range. Find the JSX where `formatDutyRange(...)` is rendered for the shift's header date line (search for `formatDutyRange(shift.start_date, shift.end_date)` in this file) and add the badge immediately after that text, inside the same flex row, e.g.:

```tsx
<span>{formatDutyRange(shift.start_date, shift.end_date)}</span>
<HolidayBadge holidays={shift.crossed_holidays} />
```

In `frontend/src/components/dashboard/DutyDetailModal.tsx`, add the import:

```tsx
import HolidayBadge from "../HolidayBadge";
```

Render it next to the existing date-range line (`DutyDetailModal.tsx:94-97`):

```tsx
<p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5 flex items-center gap-1 flex-wrap">
  {formatDutyRange(duty.start_date, duty.end_date)}
  {time && <span className="mr-2 text-xs">· {time}</span>}
  {shift && <HolidayBadge holidays={shift.crossed_holidays} />}
</p>
```

(`DutyDetailModal` only has `shift.crossed_holidays` once its own `getCalendarShift` fetch resolves — `duty` itself, an `EffectiveDuty`, doesn't carry this field — so gate on `shift` being loaded, matching how the rest of this component already treats `shift` as optional.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- ShiftDetailPanel DutyDetailModal`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx frontend/src/components/dashboard/DutyDetailModal.tsx frontend/src/components/ShiftDetailPanel.test.tsx frontend/src/components/dashboard/DutyDetailModal.test.tsx
git commit -m "feat: show crossed-holiday badge in duty shift modals"
```

---

## Task 6: Holiday badge + day-cell shading in `UnitCalendar`

**Files:**
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Test: check for `frontend/src/components/UnitCalendar.test.tsx`; add cases there (create if it doesn't exist, following the `vi.mock("../api/calendar", ...)` pattern any sibling calendar test already uses — search for an existing test mocking `getCalendarShifts`).

**Interfaces:**
- Consumes: `HolidayBadge` (Task 4, used inline as a badge inside the event chip — actually: this task renders a plain inline amber badge matching the event-chip style directly, since `HolidayBadge`'s popover positioning assumes a normal document flow the FullCalendar event cell doesn't reliably provide; see Step 4), `listHolidays` from `../api/calendarHolidays` (already existing, previously unused).

- [ ] **Step 1: Write the failing tests**

```tsx
// Add to frontend/src/components/UnitCalendar.test.tsx (create if absent)
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import UnitCalendar from "./UnitCalendar";

vi.mock("../api/calendarHolidays", () => ({
  listHolidays: vi.fn().mockResolvedValue([{ date: "2026-09-12", name: "Rosh Hashanah" }]),
}));

// ...mock ../api/calendar's getCalendarShifts, ../api/ranges, ../api/dutyConfig,
// and ../hooks/usePublicSettings the same way an existing UnitCalendar-adjacent
// test in this repo does — grep for other tests importing UnitCalendar first
// (e.g. from a page test) to copy the exact mock shapes FullCalendar needs to
// render without throwing, before adding the two assertions below.

it("applies a holiday day-cell class to a known holiday date", async () => {
  render(<UnitCalendar nodeId="node-1" />);
  await waitFor(() => {
    const cell = document.querySelector('[data-date="2026-09-12"]');
    expect(cell?.className).toMatch(/holiday-day-cell/);
  });
});

it("shows a holiday badge on a shift event that crosses a holiday", async () => {
  // extend the getCalendarShifts mock above with a shift whose
  // crossed_holidays is non-empty, matching this file's existing shift fixture
  render(<UnitCalendar nodeId="node-1" />);
  await waitFor(() => {
    expect(screen.getByTestId(/shift-holiday-badge-/)).toBeInTheDocument();
  });
});
```

Since `UnitCalendar` has several existing dependencies to mock (shifts, ranges, duty types, public settings), find whichever existing test in this repo already renders it successfully (search `frontend/src/**/*.test.tsx` for `import UnitCalendar` or a page test that renders a page embedding it) and copy its exact mock setup verbatim before adding these two new cases — do not guess the mock shapes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- UnitCalendar`
Expected: FAIL — no `holiday-day-cell` class, no `shift-holiday-badge-*` testid yet.

- [ ] **Step 3: Add holiday fetching**

In `frontend/src/components/UnitCalendar.tsx`, add the import (with the other API imports near line 12-15):

```tsx
import { listHolidays } from "../api/calendarHolidays";
```

Add state for the holiday map (near the other `useState` declarations around line 69-82):

```tsx
const [holidaysByDate, setHolidaysByDate] = useState<Map<string, string>>(new Map());
const fetchedHolidayYearsRef = useRef<Set<number>>(new Set());
```

Extend `handleDatesSet` (line 134-142) to also fetch any not-yet-fetched years spanned by the newly visible range:

```tsx
function handleDatesSet(arg: DatesSetArg) {
  setActiveViewType(arg.view.type);
  const from = arg.start.toISOString().slice(0, 10);
  const to = arg.end.toISOString().slice(0, 10);
  const prev = dateRangeRef.current;
  if (prev && prev.from === from && prev.to === to) return;
  dateRangeRef.current = { from, to };
  fetchData(from, to);

  const fromYear = arg.start.getFullYear();
  const toYear = arg.end.getFullYear();
  const yearsToFetch: number[] = [];
  for (let y = fromYear; y <= toYear; y++) {
    if (!fetchedHolidayYearsRef.current.has(y)) yearsToFetch.push(y);
  }
  if (yearsToFetch.length === 0) return;
  yearsToFetch.forEach((y) => fetchedHolidayYearsRef.current.add(y));
  Promise.all(yearsToFetch.map((y) => listHolidays(y)))
    .then((results) => {
      setHolidaysByDate((prevMap) => {
        const next = new Map(prevMap);
        results.flat().forEach((h) => next.set(h.date, h.name));
        return next;
      });
    })
    .catch(() => {
      // Holiday shading is purely informational — a failed fetch just means
      // no shading this time, not an error state for the whole calendar.
      yearsToFetch.forEach((y) => fetchedHolidayYearsRef.current.delete(y));
    });
}
```

- [ ] **Step 4: Add `dayCellClassNames` and the event-chip badge**

Add the `dayCellClassNames` prop to the `<FullCalendar>` element (alongside `datesSet={handleDatesSet}` around line 263):

```tsx
dayCellClassNames={(arg) => {
  const iso = arg.date.toISOString().slice(0, 10);
  return holidaysByDate.has(iso) ? ["holiday-day-cell"] : [];
}}
```

Add the CSS rule to `frontend/src/styles/globals.css` (append at the end):

```css
.holiday-day-cell {
  background-color: rgb(237 233 254 / 0.6); /* violet-100 @ 60% */
}
:is([data-theme="dark"], .dark) .holiday-day-cell {
  background-color: rgb(76 29 149 / 0.25); /* violet-900 @ 25% */
}
```

Inside `eventContent` (the shift-chip branch starting at line 302, `const shift = shifts.find(...)`), add a badge next to the existing warning/info badges. Insert it right after the info-badge block (after the `)}` that closes the `plannedCoverageAssignee?.range_eligibility?.covered_by_range_date &&` block, before the `swapCount > 0 &&` block):

```tsx
{shift.crossed_holidays.length > 0 && (
  <span
    data-testid={`shift-holiday-badge-${shift.id}`}
    aria-label={t("holidays.badge_label", { count: shift.crossed_holidays.length })}
    title={shift.crossed_holidays.map((h) => h.name).join(", ")}
    className="inline-flex items-center gap-0.5 rounded bg-amber-100 px-1 text-amber-700 dark:bg-amber-950 dark:text-amber-300 flex-shrink-0"
  >
    📅<span className="text-[10px] leading-4">{shift.crossed_holidays.length}</span>
  </span>
)}
```

(This uses a plain inline badge rather than the `HolidayBadge` component from Task 4, because `HolidayBadge`'s click-to-open popover assumes normal document flow for positioning, and FullCalendar event cells clip/reflow in ways that would fight it — a `title` tooltip is consistent with how this file already surfaces detail text on the swap-count pill.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- UnitCalendar`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite for regressions**

Run: `npm test`
Expected: PASS, no new failures.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/UnitCalendar.tsx frontend/src/components/UnitCalendar.test.tsx frontend/src/styles/globals.css
git commit -m "feat: shade holiday day cells and badge holiday-crossing shifts in UnitCalendar"
```

---

## Task 7: Holiday note on constraint submit + approval

**Files:**
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Test: `frontend/src/pages/MyRequestsPage.test.tsx`, `frontend/src/pages/ApprovalsPage.test.tsx` (both already exist per the earlier exploration — add cases, matching their existing mock setup for `../api/constraints`).

**Interfaces:**
- Consumes: `HolidayBadge` (Task 4), `PersonalConstraint.crossed_holidays` (Task 4).

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/pages/MyRequestsPage.test.tsx` (match its existing `vi.mock("../api/constraints", ...)` shape for `submitConstraint`):

```tsx
it("shows a note listing crossed holidays after a successful submit", async () => {
  vi.mocked(submitConstraint).mockResolvedValue({
    /* ...spread this file's existing minimal PersonalConstraint fixture... */
    crossed_holidays: [{ date: "2026-09-12", name: "Rosh Hashanah" }],
  });
  // ...render, open the constraint form, fill start/end/reason, submit
  // (copy the exact interaction steps from this file's existing "submits a
  // personal constraint" test, if one exists)...
  await waitFor(() => {
    expect(screen.getByText(/Rosh Hashanah/)).toBeInTheDocument();
  });
});
```

Add to `frontend/src/pages/ApprovalsPage.test.tsx` (match its existing `listPendingApprovals` mock):

```tsx
it("shows a holiday badge on a constraint approval card that crosses a holiday", async () => {
  vi.mocked(listPendingApprovals).mockResolvedValue([
    { /* ...this file's existing minimal PersonalConstraint fixture... */
      crossed_holidays: [{ date: "2026-09-12", name: "Rosh Hashanah" }] },
  ]);
  // ...render and switch to the constraints tab, as the file's existing tests do...
  await waitFor(() => {
    expect(screen.getByTestId("holiday-badge")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- MyRequestsPage ApprovalsPage`
Expected: FAIL — no holiday note/badge rendered yet.

- [ ] **Step 3: Implement in `MyRequestsPage.tsx`**

Add state to hold the last submit's crossed holidays (near `const [error, setError] = useState<string | null>(null);` at line 193):

```tsx
const [submittedHolidays, setSubmittedHolidays] = useState<{ date: string; name: string }[]>([]);
```

Update `onSubmit` (line 295-321) to capture and clear it:

```tsx
async function onSubmit(e: FormEvent) {
  e.preventDefault();
  setError(null);
  if (isDateInPast(start)) {
    setError(t("errors.start_date_in_past"));
    return;
  }
  if (!isDateRangeValid(start, end)) {
    setError(t("errors.date_range_invalid"));
    return;
  }
  setSubmitting(true);
  try {
    const created = await submitConstraint({
      start_date: start,
      end_date: end,
      reason,
    });
    setStart(""); setEnd(""); setReason("");
    setSubmittedHolidays(created.crossed_holidays);
    await queryClient.invalidateQueries({ queryKey: queryKeys.myConstraints() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.remainingConstraintDays() });
  } catch (err: unknown) {
    setError(translateApiError(err, t));
  } finally {
    setSubmitting(false);
  }
}
```

Render the note in the form (immediately after the `{error && ...}` block at line 414):

```tsx
{error && <div className="text-red-600 text-sm" data-testid="req-error">{error}</div>}
{submittedHolidays.length > 0 && (
  <div className="text-amber-700 dark:text-amber-400 text-sm" data-testid="req-holiday-note">
    {t("holidays.crossed_note", { names: submittedHolidays.map((h) => h.name).join(", ") })}
  </div>
)}
```

- [ ] **Step 4: Implement in `ApprovalsPage.tsx`**

Add the import near the top (with the other component imports, line 50):

```tsx
import HolidayBadge from "../components/HolidayBadge";
```

Render it next to the existing `DaysBadge` on the constraint card (line 571-574):

```tsx
<p className="text-sm flex items-center gap-2" dir="ltr">
  <span>{c.start_date} → {c.end_date ?? "—"}</span>
  <DaysBadge start={c.start_date} end={c.end_date} />
  <HolidayBadge holidays={c.crossed_holidays} />
</p>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- MyRequestsPage ApprovalsPage`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/ApprovalsPage.tsx frontend/src/pages/MyRequestsPage.test.tsx frontend/src/pages/ApprovalsPage.test.tsx
git commit -m "feat: surface crossed holidays on constraint submit and approval"
```

---

## Task 8: Replace `DateInput`'s native popup with a `react-calendar` grid

**Files:**
- Modify: `frontend/src/components/DateInput.tsx`
- Test: `frontend/src/components/DateInput.test.tsx` (all 12 existing tests exercise only the visible text field's typing/commit behavior and never touch the 📅 button or native popup — confirmed during design research — so none of them should need changes; this task only adds new cases)

**Interfaces:**
- Consumes: `Calendar` from the `react-calendar` package (already in `frontend/package.json`, currently unused).
- Produces: no change to `DateInputProps` from this task (the `showHolidays` prop is added in Task 9) — the text-field value/onChange/onBlur contract is unchanged; only what's behind the 📅 button changes.

- [ ] **Step 1: Write the failing tests**

```tsx
// Add to frontend/src/components/DateInput.test.tsx
it("opens an in-app calendar grid when the calendar button is clicked", () => {
  render(<DateInput data-testid="date-input" />);
  fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
  expect(screen.getByRole("grid")).toBeInTheDocument();
});

it("commits the picked date and closes the grid when a day is clicked", () => {
  const onChange = vi.fn();
  render(<DateInput value="2026-08-14" onChange={onChange} data-testid="date-input" />);
  fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
  fireEvent.click(screen.getByRole("button", { name: "15" }));
  expect(onChange).toHaveBeenLastCalledWith("2026-08-15");
  expect(screen.queryByRole("grid")).not.toBeInTheDocument();
});

it("closes the grid when clicking outside it", () => {
  render(
    <div>
      <DateInput data-testid="date-input" />
      <button>outside</button>
    </div>
  );
  fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
  expect(screen.getByRole("grid")).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByText("outside"));
  expect(screen.queryByRole("grid")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- DateInput`
Expected: FAIL — clicking the 📅 button currently calls `showPicker()` on a hidden native input, producing no `role="grid"` element in jsdom.

- [ ] **Step 3: Implement**

Add the import at the top of `frontend/src/components/DateInput.tsx`:

```tsx
import Calendar from "react-calendar";
import "react-calendar/dist/Calendar.css";
```

Add two helpers near the other pure functions at the top of the file (after `expandTwoDigitYear`):

```tsx
function dateToIso(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function isoToJsDate(iso: string | undefined): Date | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  if (!m) return undefined;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}
```

Add picker-open state and positioning refs alongside the existing refs (after `const nativeRef = useRef<HTMLInputElement>(null);` at line 75 — this line and the whole hidden native `<input type="date">` block at lines 246-255 are being removed in favor of the grid, so `nativeRef` itself is also removed):

```tsx
const [pickerOpen, setPickerOpen] = useState(false);
const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({});
const calendarBtnRef = useRef<HTMLButtonElement>(null);
const popoverRef = useRef<HTMLDivElement>(null);
```

(Add `type { CSSProperties }` to the existing `import { useEffect, useRef, useState } from "react";` line — change it to `import { useEffect, useLayoutEffect, useRef, useState } from "react";` and add a second import line `import type { CSSProperties } from "react";`.)

Add the popover positioning/outside-click effects (near the other `useEffect` at line 77-82):

```tsx
useLayoutEffect(() => {
  if (!pickerOpen) return;
  function reposition() {
    const btn = calendarBtnRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const POPOVER_WIDTH = 280;
    const MARGIN = 8;
    const left = Math.min(Math.max(rect.right - POPOVER_WIDTH, MARGIN), window.innerWidth - POPOVER_WIDTH - MARGIN);
    setPopoverStyle({ position: "fixed", top: rect.bottom + 4, left });
  }
  reposition();
  window.addEventListener("resize", reposition);
  window.addEventListener("scroll", reposition, true);
  return () => {
    window.removeEventListener("resize", reposition);
    window.removeEventListener("scroll", reposition, true);
  };
}, [pickerOpen]);

useEffect(() => {
  if (!pickerOpen) return;
  function onDocClick(e: MouseEvent) {
    if (
      calendarBtnRef.current && !calendarBtnRef.current.contains(e.target as Node) &&
      popoverRef.current && !popoverRef.current.contains(e.target as Node)
    ) {
      setPickerOpen(false);
    }
  }
  document.addEventListener("mousedown", onDocClick);
  return () => document.removeEventListener("mousedown", onDocClick);
}, [pickerOpen]);

function handleGridPick(picked: Date) {
  const iso = dateToIso(picked);
  setText(isoToDisplay(iso));
  rawDigitsRef.current = isoToDigits(iso);
  isTypingRef.current = false;
  commit(iso);
  setPickerOpen(false);
}
```

Replace the calendar-button + hidden-native-input block (lines 231-255) with:

```tsx
      <button
        ref={calendarBtnRef}
        type="button"
        tabIndex={-1}
        disabled={disabled}
        aria-label="פתח לוח שנה"
        onClick={() => setPickerOpen((o) => !o)}
        className="shrink-0 text-gray-400 hover:text-gray-600 disabled:opacity-40 text-xs leading-none"
      >
        📅
      </button>
      {pickerOpen && (
        <div ref={popoverRef} style={popoverStyle} className="z-[70] rounded border border-gray-200 bg-white p-1 shadow-lg dark:border-gray-600 dark:bg-gray-800">
          <Calendar
            onChange={(v) => handleGridPick(Array.isArray(v) ? v[0]! : (v as Date))}
            value={isoToJsDate(displayToIso(text) ?? undefined) ?? null}
            minDate={isoToJsDate(min)}
            maxDate={isoToJsDate(max)}
            locale="he-IL"
          />
        </div>
      )}
```

Remove the now-unused `nativeRef` declaration and its `ref={nativeRef}` usage (both already covered by the block replacement above — `nativeRef` no longer appears anywhere in the file after this edit).

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- DateInput`
Expected: PASS — all 12 pre-existing tests plus the 3 new ones (15 total).

- [ ] **Step 5: Run the full frontend suite for regressions**

Run: `npm test`
Expected: PASS. `DateInput` is used in 23 files (registration, profile, settings, shift forms, etc.) — any pre-existing test that clicked the 📅 button or asserted on the native `<input type="date">` (none were found during design research, but re-confirm here) will need updating to match the new grid; if `npm test` surfaces any such failure, fix that specific test's assertion to look for `role="grid"` instead of the removed native input.

Run: `npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DateInput.tsx frontend/src/components/DateInput.test.tsx
git commit -m "feat: replace DateInput's native date-picker popup with an in-app calendar grid"
```

---

## Task 9: Holiday shading in `DateInput`'s grid, wired to constraint/exemption fields

**Files:**
- Modify: `frontend/src/components/DateInput.tsx`
- Modify: `frontend/src/pages/MyRequestsPage.tsx` (lines 427, 431, 479, 483 — add `showHolidays`)
- Modify: `frontend/src/components/ExemptionsPanel.tsx` (lines 329, 331 — add `showHolidays`)
- Test: `frontend/src/components/DateInput.test.tsx`

**Interfaces:**
- Consumes: `listHolidays` from `../api/calendarHolidays`.
- Produces: `DateInputProps.showHolidays?: boolean` (default `false`).

- [ ] **Step 1: Write the failing test**

```tsx
// Add to frontend/src/components/DateInput.test.tsx
import { listHolidays } from "../api/calendarHolidays";

vi.mock("../api/calendarHolidays", () => ({
  listHolidays: vi.fn().mockResolvedValue([{ date: "2026-08-15", name: "חג" }]),
}));

it("shades holiday days in the grid when showHolidays is set", async () => {
  render(<DateInput value="2026-08-01" showHolidays data-testid="date-input" />);
  fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
  await waitFor(() => expect(listHolidays).toHaveBeenCalledWith(2026));
  await waitFor(() => {
    const dayBtn = screen.getByRole("button", { name: "15" });
    expect(dayBtn.className).toMatch(/holiday-date-tile/);
  });
});

it("does not fetch holidays when showHolidays is not set", () => {
  render(<DateInput value="2026-08-01" data-testid="date-input" />);
  fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
  expect(listHolidays).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- DateInput`
Expected: FAIL — `showHolidays` prop doesn't exist yet, no shading applied.

- [ ] **Step 3: Implement**

Add `showHolidays?: boolean;` to `DateInputProps` (after `"data-testid"?: string;`):

```tsx
interface DateInputProps {
  value?: string;
  defaultValue?: string;
  onChange?: (isoValue: string) => void;
  onBlur?: (isoValue: string) => void;
  className?: string;
  disabled?: boolean;
  required?: boolean;
  autoFocus?: boolean;
  min?: string;
  max?: string;
  id?: string;
  showHolidays?: boolean;
  "data-testid"?: string;
}
```

Destructure it in the component signature:

```tsx
export default function DateInput({
  value, defaultValue, onChange, onBlur, className, disabled, required, autoFocus, min, max, id, showHolidays, ...rest
}: DateInputProps) {
```

Add holiday state and a fetch-on-open-and-navigate effect (near the picker state added in Task 8):

```tsx
const [holidayDates, setHolidayDates] = useState<Set<string>>(new Set());
const fetchedHolidayYearsRef = useRef<Set<number>>(new Set());

function ensureHolidaysFetched(year: number) {
  if (!showHolidays || fetchedHolidayYearsRef.current.has(year)) return;
  fetchedHolidayYearsRef.current.add(year);
  listHolidays(year)
    .then((hs) => {
      setHolidayDates((prev) => {
        const next = new Set(prev);
        hs.forEach((h) => next.add(h.date));
        return next;
      });
    })
    .catch(() => fetchedHolidayYearsRef.current.delete(year));
}

useEffect(() => {
  if (pickerOpen && showHolidays) {
    const iso = displayToIso(text);
    ensureHolidaysFetched(iso ? Number(iso.slice(0, 4)) : new Date().getFullYear());
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [pickerOpen, showHolidays]);
```

Add the import: `import { listHolidays } from "../api/calendarHolidays";`

Wire `tileClassName` and `onActiveStartDateChange` into the `<Calendar>` element added in Task 8:

```tsx
<Calendar
  onChange={(v) => handleGridPick(Array.isArray(v) ? v[0]! : (v as Date))}
  value={isoToJsDate(displayToIso(text) ?? undefined) ?? null}
  minDate={isoToJsDate(min)}
  maxDate={isoToJsDate(max)}
  locale="he-IL"
  onActiveStartDateChange={({ activeStartDate }) => {
    if (activeStartDate) ensureHolidaysFetched(activeStartDate.getFullYear());
  }}
  tileClassName={({ date: tileDate, view }) =>
    view === "month" && holidayDates.has(dateToIso(tileDate)) ? "holiday-date-tile" : null
  }
/>
```

Add the CSS rule to `frontend/src/styles/globals.css` (append after the `.holiday-day-cell` rule from Task 6):

```css
.holiday-date-tile {
  background-color: rgb(253 230 138 / 0.5) !important; /* amber-200 @ 50% */
}
```

- [ ] **Step 4: Wire `showHolidays` into the constraint and exemption date fields**

`frontend/src/pages/MyRequestsPage.tsx` — add `showHolidays` to the four `DateInput` calls at lines 427, 431, 479, 483:

```tsx
<DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={start} onChange={(iso) => setStart(iso)} min={todayIso()} max={end || undefined} required showHolidays data-testid="req-start" />
```

```tsx
<DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={end} onChange={(iso) => setEnd(iso)} min={start || undefined} required showHolidays data-testid="req-end" />
```

```tsx
<DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erPermanent ? "" : erStart} onChange={(iso) => setErStart(iso)} max={erEnd || undefined} disabled={erPermanent} required={!erPermanent} showHolidays data-testid="er-start" />
```

```tsx
<DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erPermanent ? "" : erEnd} onChange={(iso) => setErEnd(iso)} min={erStart || undefined} disabled={erPermanent} required={!erPermanent} showHolidays data-testid="er-end" />
```

`frontend/src/components/ExemptionsPanel.tsx` — add `showHolidays` to the two `DateInput` calls at lines 329 and 331 the same way (read those two lines first to preserve every existing prop, then add `showHolidays` alongside them).

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test -- DateInput MyRequestsPage ExemptionsPanel`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite, typecheck, and lint for regressions**

Run: `npm test`
Expected: PASS, no new failures.

Run: `npm run typecheck`
Expected: PASS.

Run: `npm run lint`
Expected: PASS (zero warnings enforced in this repo).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DateInput.tsx frontend/src/components/DateInput.test.tsx frontend/src/pages/MyRequestsPage.tsx frontend/src/components/ExemptionsPanel.tsx frontend/src/styles/globals.css
git commit -m "feat: shade holidays in DateInput's grid for constraint and exemption dates"
```

---

## Final verification

- [ ] Run the full backend suite: `pytest -q` (from `backend/`, venv activated) — expect PASS.
- [ ] Run the full frontend suite: `npm test` (from `frontend/`) — expect PASS.
- [ ] Run `npm run lint` and `npm run typecheck` (from `frontend/`) — expect PASS with zero warnings.
- [ ] Manually smoke-test via `.\dev.ps1`: submit a personal constraint whose range crosses a known 2026 IL holiday, confirm the amber note appears after submit; check the approvals page shows the holiday badge on that constraint; open a duty shift that crosses a holiday in both the admin (`ShiftDetailPanel`) and dashboard (`DutyDetailModal`) views and confirm the badge/list appears; view the unit calendar and confirm the holiday day cell has a distinct background and the shift chip shows the holiday badge; open the constraint-request date picker and confirm holiday days are shaded amber in the grid.
