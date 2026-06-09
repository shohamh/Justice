# ניקוד Badge in Duty History — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a ניקוד (score) badge on every duty-related history card, with the full formula visible on expand.

**Architecture:** Backend enriches `TimelineEvent.metadata` with `score_total` and `score_formula` strings computed inside `get_duty_history`. Frontend reads these keys directly from metadata — no new endpoints or API calls.

**Tech Stack:** Python / SQLAlchemy (backend), React / TypeScript / Tailwind (frontend), pytest (backend tests), Vitest / Testing Library (frontend tests).

---

## Files

| Action | Path |
|--------|------|
| Modify | `backend/app/services/duty_history.py` |
| Modify | `backend/app/services/tests/test_duty_history.py` |
| Modify | `frontend/src/components/DutyHistoryPanel.tsx` |

---

## Task 1: Add `_score_parts` helper to `duty_history.py`

**Files:**
- Modify: `backend/app/services/duty_history.py`
- Test: `backend/app/services/tests/test_duty_history.py`

This helper computes `(score_total, score_formula)` for an assignment or a sub-period of one. It is tested directly by inspecting `get_duty_history` metadata in Task 2 — in Task 1 we only add the helper, no wiring yet.

- [ ] **Step 1.1 — Add imports and `_fmt` + `_score_parts` to `duty_history.py`**

Open `backend/app/services/duty_history.py`. Make these changes:

**a) Extend the import line** at the top from:
```python
from datetime import date
```
to:
```python
from datetime import date, timedelta
from decimal import Decimal
```

**b) Add the two helpers** just before the `_isodate` function (after the `@dataclass` block, around line 35):

```python
def _fmt(d: Decimal) -> str:
    """Format a Decimal in fixed notation with at least one decimal place.

    Examples: Decimal("3.000") -> "3.0", Decimal("0.600") -> "0.6",
              Decimal("1.300") -> "1.3", Decimal("0.000") -> "0.0"
    """
    n = d.normalize()
    sign, _, exponent = n.as_tuple()
    if exponent >= 0:
        return str(int(n)) + ".0"
    return format(n, "f")


def _score_parts(
    a: "DutyAssignment",
    dismissal_ranges: list[tuple[date, date]],
    spd: Decimal,
    standby_mult: Decimal,
    called_up_mult: Decimal,
    dismissed_mult: Decimal,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[str, str]:
    """Return (score_total, score_formula) for the given period of an assignment.

    date_from / date_to optionally restrict computation to a sub-period (used
    for call_up and dismissal events).  score_formula is an empty string when
    there are no days in range or spd is zero.

    Formula notation: "N × SPD × mult" per segment, joined by " + ".
    """
    start = max(a.start_date, date_from) if date_from is not None else a.start_date
    end = min(a.end_date, date_to) if date_to is not None else a.end_date

    if start > end or spd == Decimal("0"):
        return "0.0", ""

    def _day_mult(day: date) -> Decimal:
        if a.is_reserve:
            if (
                a.called_up_from is not None
                and a.called_up_to is not None
                and a.called_up_from <= day <= a.called_up_to
            ):
                return called_up_mult
            return standby_mult
        if any(df <= day <= dt for df, dt in dismissal_ranges):
            return dismissed_mult
        return Decimal("1.0")

    # Group consecutive days by multiplier to build formula segments
    segments: list[tuple[int, Decimal]] = []
    cur_mult: Decimal | None = None
    cur_count = 0

    day = start
    while day <= end:
        m = _day_mult(day)
        if m == cur_mult:
            cur_count += 1
        else:
            if cur_mult is not None:
                segments.append((cur_count, cur_mult))
            cur_mult = m
            cur_count = 1
        day += timedelta(days=1)
    if cur_mult is not None:
        segments.append((cur_count, cur_mult))

    if not segments:
        return "0.0", ""

    total: Decimal = sum(Decimal(str(count)) * spd * mult for count, mult in segments)
    formula = " + ".join(
        f"{count} × {_fmt(spd)} × {_fmt(mult)}" for count, mult in segments
    )
    return _fmt(total), formula
```

- [ ] **Step 1.2 — Verify file parses**

```bash
cd backend && uv run python -c "from app.services.duty_history import _score_parts; print('ok')"
```

Expected: `ok`

- [ ] **Step 1.3 — Commit**

```bash
git add backend/app/services/duty_history.py
git commit -m "feat: add _score_parts helper to duty_history"
```

---

## Task 2: Wire score metadata into `get_duty_history`

**Files:**
- Modify: `backend/app/services/duty_history.py`
- Modify: `backend/app/services/tests/test_duty_history.py`

- [ ] **Step 2.1 — Write failing tests**

Append to `backend/app/services/tests/test_duty_history.py`:

```python
# ---------------------------------------------------------------------------
# Score metadata tests
# ---------------------------------------------------------------------------


def test_assignment_score_regular(admin_session, soldier, duty_type, location):
    """Regular 3-day assignment: score_total='3.0', formula='3 × 1.0 × 1.0'."""
    # duty_type has score_per_day=Decimal("1.00")
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),  # 3 days inclusive
        status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    ev = next(e for e in events if e.event_type == "assignment")

    assert ev.metadata["score_total"] == "3.0"
    assert ev.metadata["score_formula"] == "3 × 1.0 × 1.0"


def test_assignment_score_reserve_standby_only(admin_session, soldier, duty_type, location):
    """Reserve 3-day standby (no call-up): score=0.6, formula uses standby multiplier 0.2."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="published",
        is_reserve=True,
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    ev = next(e for e in events if e.event_type == "assignment")

    assert ev.metadata["score_total"] == "0.6"
    assert ev.metadata["score_formula"] == "3 × 1.0 × 0.2"


def test_assignment_score_reserve_with_calledup(admin_session, soldier, duty_type, location):
    """Reserve 5-day assignment where days 3-4 are called up.

    Days 1-2 (Jun 10-11): standby ×0.2  → 0.4
    Days 3-4 (Jun 12-13): called-up ×1.3 → 2.6
    Day 5   (Jun 14):     standby ×0.2  → 0.2
    Total: 3.2
    """
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 6, 12),
        called_up_to=date(2026, 6, 13),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    ev = next(e for e in events if e.event_type == "assignment")

    assert ev.metadata["score_total"] == "3.2"
    assert ev.metadata["score_formula"] == "2 × 1.0 × 0.2 + 2 × 1.0 × 1.3 + 1 × 1.0 × 0.2"


def test_call_up_score_within_assignment(admin_session, soldier, duty_type, location):
    """call_up event carries score for the called-up sub-period only."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 6, 12),
        called_up_to=date(2026, 6, 13),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    call_up_ev = next(e for e in events if e.event_type == "call_up")

    assert call_up_ev.metadata["score_total"] == "2.6"
    assert call_up_ev.metadata["score_formula"] == "2 × 1.0 × 1.3"


def test_call_up_score_zero_when_outside_assignment(admin_session, soldier, duty_type, location):
    """call_up event before the main assignment span scores 0 (no overlap)."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 6, 8),   # before start_date — no overlap
        called_up_to=date(2026, 6, 9),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    call_up_ev = next(e for e in events if e.event_type == "call_up")

    assert call_up_ev.metadata["score_total"] == "0.0"
    assert call_up_ev.metadata.get("score_formula", "") == ""


def test_dismissal_score_is_zero(admin_session, soldier, duty_type, location):
    """Dismissal event carries score=0 with formula showing dismissed multiplier."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    d = DutyDismissal(
        duty_assignment_id=a.id,
        dismissed_from=date(2026, 6, 11),
        dismissed_to=date(2026, 6, 12),
        reason="חופש",
    )
    admin_session.add(d)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    dismissal_ev = next(e for e in events if e.event_type == "dismissal")

    assert dismissal_ev.metadata["score_total"] == "0.0"
    assert dismissal_ev.metadata["score_formula"] == "2 × 1.0 × 0.0"


def test_cancellation_score_is_zero(admin_session, soldier, duty_type, location):
    """Cancelled assignment carries score_total='0' and no formula."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        status="cancelled",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    ev = next(e for e in events if e.event_type == "cancellation")

    assert ev.metadata["score_total"] == "0"
    assert "score_formula" not in ev.metadata
```

- [ ] **Step 2.2 — Run tests to verify they fail**

```bash
cd backend && uv run pytest app/services/tests/test_duty_history.py -v -k "score" 2>&1 | tail -20
```

Expected: all 7 new tests FAIL with `KeyError: 'score_total'`.

- [ ] **Step 2.3 — Modify `get_duty_history` to load multipliers and populate score metadata**

Replace the body of `get_duty_history` in `backend/app/services/duty_history.py`. The full new function is:

```python
def get_duty_history(session: Session, soldier_id: uuid.UUID) -> list[TimelineEvent]:
    from app.services.scoring import _get_multiplier_setting

    standby_mult = _get_multiplier_setting(
        session, "scoring.reserve_standby_multiplier", "0.2"
    )
    called_up_mult = _get_multiplier_setting(
        session, "scoring.reserve_called_up_multiplier", "1.3"
    )
    dismissed_mult = _get_multiplier_setting(
        session, "scoring.dismissed_multiplier", "0.0"
    )

    events: list[TimelineEvent] = []

    # --- DutyAssignment events (assignment & cancellation & call_up) ---
    assignments = list(
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.soldier_id == soldier_id,
                DutyAssignment.status.not_in(["algorithm_draft", "algorithm_rejected"]),
            )
        ).scalars().all()
    )

    duty_type_cache: dict[uuid.UUID, str] = {}
    spd_cache: dict[uuid.UUID, Decimal] = {}
    location_cache: dict[uuid.UUID, str] = {}

    def _duty_type_name(dt_id: uuid.UUID) -> str:
        if dt_id not in duty_type_cache:
            dt = session.get(DutyType, dt_id)
            duty_type_cache[dt_id] = dt.name if dt else str(dt_id)
            spd_cache[dt_id] = dt.score_per_day if dt else Decimal("0")
        return duty_type_cache[dt_id]

    def _location_name(loc_id: uuid.UUID) -> str:
        if loc_id not in location_cache:
            loc = session.get(DutyLocation, loc_id)
            location_cache[loc_id] = loc.name if loc else str(loc_id)
        return location_cache[loc_id]

    for a in assignments:
        dt_name = _duty_type_name(a.duty_type_id)
        spd = spd_cache.get(a.duty_type_id, Decimal("0"))
        loc_name = _location_name(a.duty_location_id)

        # Collect dismissals first — needed for score calculation
        dismissals = list(
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id == a.id)
            ).scalars().all()
        )
        dismissal_ranges = [(d.dismissed_from, d.dismissed_to) for d in dismissals]

        # call_up event — if this assignment has called_up_from set
        if a.called_up_from is not None:
            cu_total, cu_formula = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
                date_from=a.called_up_from,
                date_to=a.called_up_to,
            )
            cu_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "is_reserve": "true",
                "score_total": cu_total,
            }
            if cu_formula:
                cu_metadata["score_formula"] = cu_formula
            events.append(
                TimelineEvent(
                    id=uuid.uuid5(a.id, "call_up"),
                    event_type="call_up",
                    date=a.called_up_from.isoformat(),
                    end_date=_isodate(a.called_up_to),
                    title=f"הוקפץ לרזרבה: {dt_name}",
                    description=a.notes,
                    status=None,
                    metadata=cu_metadata,
                    created_at=a.created_at.isoformat(),
                )
            )

        # cancellation or assignment event
        if a.status == "cancelled":
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="cancellation",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"בוטלה: {dt_name} ב{loc_name}",
                    description=a.notes,
                    status="cancelled",
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                        "is_reserve": "true" if a.is_reserve else "false",
                        "called_up": "true" if a.called_up_from is not None else "false",
                        "score_total": "0",
                    },
                    created_at=a.created_at.isoformat(),
                )
            )
        else:
            asgn_total, asgn_formula = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
            )
            asgn_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "duty_type_id": str(a.duty_type_id),
                "duty_location_id": str(a.duty_location_id),
                "is_reserve": "true" if a.is_reserve else "false",
                "called_up": "true" if a.called_up_from is not None else "false",
                "score_total": asgn_total,
            }
            if asgn_formula:
                asgn_metadata["score_formula"] = asgn_formula
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="assignment",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"{dt_name} ב{loc_name}",
                    description=a.notes,
                    status=a.status,
                    metadata=asgn_metadata,
                    created_at=a.created_at.isoformat(),
                )
            )

        # dismissal events linked to this assignment
        for d in dismissals:
            dis_total, dis_formula = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
                date_from=d.dismissed_from,
                date_to=d.dismissed_to,
            )
            dis_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "score_total": dis_total,
            }
            if dis_formula:
                dis_metadata["score_formula"] = dis_formula
            events.append(
                TimelineEvent(
                    id=d.id,
                    event_type="dismissal",
                    date=d.dismissed_from.isoformat(),
                    end_date=_isodate(d.dismissed_to),
                    title=f"שוחרר מתורנות {dt_name}",
                    description=d.reason,
                    status=None,
                    metadata=dis_metadata,
                    created_at=d.created_at.isoformat(),
                )
            )

    # --- ExemptionRequest events ---
    exemption_type_cache: dict[uuid.UUID, str] = {}

    def _exemption_type_name(et_id: uuid.UUID) -> str:
        if et_id not in exemption_type_cache:
            et = session.get(ExemptionType, et_id)
            exemption_type_cache[et_id] = et.name if et else str(et_id)
        return exemption_type_cache[et_id]

    exemption_requests = list(
        session.execute(
            select(ExemptionRequest).where(ExemptionRequest.soldier_id == soldier_id)
        ).scalars().all()
    )
    for er in exemption_requests:
        et_name = _exemption_type_name(er.exemption_type_id)
        events.append(
            TimelineEvent(
                id=er.id,
                event_type="exemption_request",
                date=er.start_date.isoformat(),
                end_date=_isodate(er.end_date),
                title=f"בקשת פטור: {et_name}",
                description=er.reason,
                status=er.status,
                metadata={
                    "exemption_type_name": et_name,
                    "decision_note": er.decision_note,
                },
                created_at=er.created_at.isoformat(),
            )
        )

    # --- PersonalConstraint events ---
    constraints = list(
        session.execute(
            select(PersonalConstraint).where(PersonalConstraint.soldier_id == soldier_id)
        ).scalars().all()
    )
    for c in constraints:
        events.append(
            TimelineEvent(
                id=c.id,
                event_type="personal_constraint",
                date=c.start_date.isoformat(),
                end_date=_isodate(c.end_date),
                title="אילוצים אישיים",
                description=c.reason,
                status=c.status,
                metadata={
                    "decision_note": c.decision_note,
                },
                created_at=c.created_at.isoformat(),
            )
        )

    # Sort: descending by date, then by created_at descending
    events.sort(key=lambda e: (e.date, e.created_at), reverse=True)
    return events
```

- [ ] **Step 2.4 — Run all duty_history tests**

```bash
cd backend && uv run pytest app/services/tests/test_duty_history.py -v 2>&1 | tail -30
```

Expected: all tests PASS (including the 7 new score tests and all 8 pre-existing ones).

- [ ] **Step 2.5 — Commit**

```bash
git add backend/app/services/duty_history.py backend/app/services/tests/test_duty_history.py
git commit -m "feat: add score metadata to duty history events"
```

---

## Task 3: Frontend — ניקוד badge and formula in `EventCard`

**Files:**
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`

- [ ] **Step 3.1 — Update `EventCard` to show score badge and expanded formula**

In `frontend/src/components/DutyHistoryPanel.tsx`, find the `EventCard` function.

**Change 1 — Top-right badges cluster** (around line 112–135).

Replace:
```tsx
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-medium">{e.title}</p>
            <p className="text-xs text-gray-500" dir="ltr">
              {e.date}{e.end_date && e.end_date !== e.date ? ` → ${e.end_date}` : ""}
            </p>
            <div className="flex gap-1 mt-1 flex-wrap">
              {e.metadata.is_reserve === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                  {t("duty_history.reserve")}
                </span>
              )}
              {e.metadata.called_up === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-orange-100 text-orange-800">
                  {t("duty_history.called_up")}
                </span>
              )}
            </div>
          </div>
          {badgeClass && (
            <span className={`text-xs px-1.5 py-0.5 rounded whitespace-nowrap ${badgeClass}`}>
              {t(`my_requests.${e.status}`)}
            </span>
          )}
        </div>
```

With:
```tsx
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-medium">{e.title}</p>
            <p className="text-xs text-gray-500" dir="ltr">
              {e.date}{e.end_date && e.end_date !== e.date ? ` → ${e.end_date}` : ""}
            </p>
            <div className="flex gap-1 mt-1 flex-wrap">
              {e.metadata.is_reserve === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                  {t("duty_history.reserve")}
                </span>
              )}
              {e.metadata.called_up === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-orange-100 text-orange-800">
                  {t("duty_history.called_up")}
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 shrink-0">
            {badgeClass && (
              <span className={`text-xs px-1.5 py-0.5 rounded whitespace-nowrap ${badgeClass}`}>
                {t(`my_requests.${e.status}`)}
              </span>
            )}
            {e.metadata.score_total != null && (
              <span
                className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 whitespace-nowrap"
                data-testid={`score-badge-${e.id}`}
              >
                {e.metadata.score_total} ניקוד
              </span>
            )}
          </div>
        </div>
```

**Change 2 — Expanded formula line** (inside the `{isExpanded && ...}` block, around line 166).

Find:
```tsx
        {isExpanded && (
          <div className="mt-2 space-y-1">
            {e.description && <p className="text-gray-600">{e.description}</p>}
            {e.metadata.decision_note && (
```

Replace with:
```tsx
        {isExpanded && (
          <div className="mt-2 space-y-1">
            {e.description && <p className="text-gray-600">{e.description}</p>}
            {e.metadata.score_total != null && (
              <p className="text-xs text-gray-500" data-testid={`score-formula-${e.id}`}>
                ניקוד:{" "}
                {e.metadata.score_formula
                  ? `${e.metadata.score_formula} = ${e.metadata.score_total}`
                  : e.metadata.score_total}
              </p>
            )}
            {e.metadata.decision_note && (
```

- [ ] **Step 3.2 — Run frontend lint and tests**

```bash
cd frontend && pnpm lint && pnpm test --run 2>&1 | tail -20
```

Expected: zero lint warnings, all tests PASS.

- [ ] **Step 3.3 — Commit**

```bash
git add frontend/src/components/DutyHistoryPanel.tsx
git commit -m "feat: show nikud badge and formula in duty history cards"
```

---

## Done

After all tasks complete, every `assignment`, `call_up`, `dismissal`, and `cancellation` card in the Duty History panel will display a `"X.X ניקוד"` badge in the top-right corner. Expanding a card shows the full calculation formula, e.g.:

> ניקוד: 2 × 4.0 × 0.2 + 3 × 4.0 × 1.3 = 17.2
