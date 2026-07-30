# Homepage & Duty Display Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five homepage/duty-display issues: reserve-vs-primary assignment isn't visually distinguished, duty location is missing from the upcoming-duties list for non-admin users, awkward Hebrew phrasing "תורנויות שירתתי", no past/future split in the duty-type breakdown chart, and calendar hour labels show bare numbers instead of "HH:00".

**Architecture:** All five are presentational/data-shaping fixes on top of already-correct or already-available data — no new tables, no new endpoints except loosening one over-restrictive auth dependency. Backend changes: relax the `/duty-config/locations` endpoint's role requirement, and split `soldier_score_breakdown`'s day counts into past/future. Frontend changes: add reserve styling, relabel two stat cards, render the split breakdown, and set FullCalendar's `slotLabelFormat`.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript, FullCalendar, Recharts-or-equivalent (whatever the existing chart lib in HomePage.tsx is — check before Task 4), vitest, pytest.

## Global Constraints

- Hebrew UI strings only for any new user-facing text — add to `frontend/src/i18n/he.json`.
- Run `pytest -m scoring -q` after backend changes; run `npm run typecheck` and targeted vitest files after frontend changes.
- Do not change `EffectiveDuty`/`DutyAssignment` schema — `is_reserve` already exists end-to-end.

---

## File Structure

- **Modify:** `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx` — reserve styling on rows.
- **Modify:** `frontend/src/components/dashboard/DutyDetailModal.tsx` — reserve styling on the modal shell (optional secondary spot, see Task 1).
- **Modify:** `backend/app/routes/duty_config.py` — relax `GET /duty-config/locations` auth dependency.
- **Modify:** `frontend/src/pages/HomePage.tsx` — relabel "תורנויות שירתתי"; render split past/future breakdown chart.
- **Modify:** `frontend/src/pages/MyDutiesPage.tsx` — same relabel + breakdown changes (mirrors HomePage).
- **Modify:** `backend/app/services/scoring.py` — split `soldier_score_breakdown` output into past/future day counts.
- **Modify:** `backend/app/routes/scoring.py` — update `BreakdownOut` schema for the new split fields.
- **Modify:** `frontend/src/api/scoring.ts` — update TS type for the new split fields.
- **Modify:** `frontend/src/components/dashboard/DutyCalendarWidget.tsx`, `frontend/src/components/UnitCalendar.tsx` — add `slotLabelFormat`.
- **Test:** `backend/app/services/tests/test_scoring.py`.

---

### Task 1: Visually distinguish reserve assignments on the homepage

**Files:**
- Modify: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx` (row rendering, lines ~34-53)
- Test: manual (this widget has no existing unit test file; do not introduce a new test harness for a pure styling change — verify visually per Step 3)

- [ ] **Step 1: Read current row rendering**

Confirm the exact current JSX at `UpcomingDutiesWidget.tsx:34-53` (already known from investigation):
```tsx
{upcoming.map((d) => (
  <tr
    key={d.assignment_id}
    role="button"
    tabIndex={0}
    className="border-b dark:border-gray-600 last:border-0 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
    ...
  >
```

- [ ] **Step 2: Add conditional reserve styling**

```tsx
{upcoming.map((d) => (
  <tr
    key={d.assignment_id}
    role="button"
    tabIndex={0}
    className={`border-b last:border-0 cursor-pointer ${
      d.is_reserve
        ? "border-dashed border-2 border-gray-400 dark:border-gray-500 bg-gray-100/40 dark:bg-gray-700/30 hover:bg-gray-100/70 dark:hover:bg-gray-700/50"
        : "dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700"
    }`}
    ...
  >
```

Add a small badge/label so the distinction isn't color-only (accessibility): in the first `<td>` of the row, prepend a "רזרבה" tag when `d.is_reserve`:

```tsx
<td className="py-2">
  {d.is_reserve && (
    <span className="inline-block text-[10px] px-1 rounded bg-gray-300 dark:bg-gray-600 text-gray-700 dark:text-gray-200 me-1">
      רזרבה
    </span>
  )}
  {formatDutyRange(d.start_date, d.end_date)}
</td>
```

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, log in as a soldier with at least one reserve (`is_reserve=true`) upcoming assignment, confirm the homepage "תורנויות קרובות" widget shows that row with a dashed border, translucent fill, and "רזרבה" tag, while primary assignments render normally.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/dashboard/UpcomingDutiesWidget.tsx
git commit -m "feat: visually distinguish reserve duty assignments on the homepage"
```

---

### Task 2: Fix missing duty location for non-admin users

**Files:**
- Modify: `backend/app/routes/duty_config.py:302-306` (`GET /duty-config/locations`)
- Test: `backend/app/routes/tests/test_duty_config.py` (check file exists first; if not, check `backend/app/routes/tests/` for the right test module naming convention used for this router)

**Interfaces:**
- Produces: `GET /duty-config/locations` now accessible to any authenticated soldier (`require_password_changed`), matching `GET /duty-config/duty-types`'s existing auth level.

- [ ] **Step 1: Write the failing test**

Read the existing test file for `duty_config` routes first to match fixture/client style (likely `backend/app/routes/tests/test_duty_config.py` with a `client` fixture and helper to create/login a plain soldier vs admin). Add:

```python
def test_list_locations_accessible_to_plain_soldier(client, plain_soldier_token):
    resp = client.get("/duty-config/locations", headers={"Authorization": f"Bearer {plain_soldier_token}"})
    assert resp.status_code == 200
```

(Match the exact fixture names already used in this test file for "a plain authenticated non-admin soldier's auth token" — do not invent a fixture name; read the file first.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/routes/tests/test_duty_config.py -k "list_locations_accessible_to_plain_soldier" -v`
Expected: FAIL — 403

- [ ] **Step 3: Relax the auth dependency**

In `backend/app/routes/duty_config.py` lines 302-306:

```python
# BEFORE
@router.get("/locations", response_model=list[LocationOut])
def list_locations(
    session: Session = Depends(get_session), user: Soldier = Depends(require_config_manager)
) -> list[LocationOut]:
```

```python
# AFTER
@router.get("/locations", response_model=list[LocationOut])
def list_locations(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[LocationOut]:
```

(This matches the exact auth level already used by the sibling `GET /duty-config/duty-types` endpoint at `duty_config.py:116-119`.) Confirm no other part of this function relies on `user` having config-manager privileges (read the full function body first — investigation only showed the decorator/signature, not the body, so verify there's no privileged filtering logic inside that would need adjusting too).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/routes/tests/test_duty_config.py -k "list_locations_accessible_to_plain_soldier" -v`
Expected: PASS

- [ ] **Step 5: Run the broader duty_config test file for regressions**

Run: `cd backend && pytest app/routes/tests/test_duty_config.py -q`
Expected: PASS

- [ ] **Step 6: Manually verify in the running app**

Start `.\dev.ps1`, log in as a plain (non-admin) soldier with an upcoming duty that has a location, confirm the homepage "תורנויות קרובות" widget now shows the location instead of "—".

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/duty_config.py backend/app/routes/tests/test_duty_config.py
git commit -m "fix: allow any authenticated soldier to read duty locations, not just admins"
```

---

### Task 3: Reword "תורנויות שירתתי"

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx:308-312`
- Modify: `frontend/src/pages/MyDutiesPage.tsx:145-149`
- Test: manual (label-only string change)

- [ ] **Step 1: Update HomePage.tsx**

```tsx
// BEFORE (HomePage.tsx:308-312)
<StatCard
  label="תורנויות שירתתי"
  value={pastCount}
  sub={`ממוצע יחידה: ${unitAvgShifts}`}
/>
```

```tsx
// AFTER
<StatCard
  label="תורנויות שביצעתי"
  value={pastCount}
  sub={`ממוצע יחידה: ${unitAvgShifts}`}
/>
```

- [ ] **Step 2: Update MyDutiesPage.tsx identically**

Apply the same `label` change at `MyDutiesPage.tsx:145-149`.

- [ ] **Step 3: Manually verify**

Start `.\dev.ps1`, confirm both the homepage and "היומן שלי" page show "תורנויות שביצעתי" instead of the old phrasing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/HomePage.tsx frontend/src/pages/MyDutiesPage.tsx
git commit -m "fix: reword awkward Hebrew duty-count stat label"
```

---

### Task 4: Split duty-type breakdown into past vs. future day counts

**Files:**
- Modify: `backend/app/services/scoring.py:603-630` (`soldier_score_breakdown`)
- Modify: `backend/app/routes/scoring.py:204-222` (`BreakdownOut`)
- Modify: `frontend/src/api/scoring.ts:82-86` (`getBreakdown` / response type)
- Modify: `frontend/src/pages/HomePage.tsx:234-244, 330-363` (`typeChartData` + chart rendering)
- Modify: `frontend/src/pages/MyDutiesPage.tsx:101-111, 174-212` (same, mirrored)
- Test: `backend/app/services/tests/test_scoring.py`

**Interfaces:**
- Produces (backend): `soldier_score_breakdown` per-type entries now include `days_past: int` and `days_future: int` (in addition to or replacing the current single `days` field — keep `days` as `days_past + days_future` for backward compatibility with any other consumer, confirmed via grep before removing it).

- [ ] **Step 1: Check for other consumers of the current `days` field before changing its shape**

Run: `cd frontend && grep -rn "breakdown.per_type\|per_type\[" src/` (or use the Grep tool) to confirm `HomePage.tsx` and `MyDutiesPage.tsx` are the only two consumers found in the investigation. If any other file consumes `per_type[].days`, note it and ensure it still works (keep `days` field present, additive change only).

- [ ] **Step 2: Write the failing backend test**

Read `backend/app/services/tests/test_scoring.py` first for fixture conventions (how assignments/soldiers are created in tests). Add:

```python
def test_soldier_score_breakdown_splits_past_and_future_days(session, make_soldier, make_duty_type, make_assignment):
    # Adjust fixture calls to match this file's actual helper signatures — read
    # existing tests in this file first before writing this test body.
    soldier = make_soldier()
    dt = make_duty_type()
    past_date = date.today() - timedelta(days=5)
    future_date = date.today() + timedelta(days=5)
    make_assignment(soldier=soldier, duty_type=dt, date=past_date)
    make_assignment(soldier=soldier, duty_type=dt, date=future_date)

    result = soldier_score_breakdown(session, soldier_id=soldier.id)
    entry = next(p for p in result["per_type"] if p["duty_type_id"] == dt.id)
    assert entry["days_past"] == 1
    assert entry["days_future"] == 1
    assert entry["days"] == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_scoring.py -k "splits_past_and_future" -v`
Expected: FAIL — `KeyError: 'days_past'`

- [ ] **Step 4: Implement the split in scoring.py**

Read the exact current body of `soldier_score_breakdown` at `scoring.py:603-630` and `effective_duty_days` at `scoring.py:44-104` first (investigation showed the loop shape but the exact tuple/row shape returned by `effective_duty_days` needs confirming — it yields `(_day, eff, dtid, mult)` per the investigation snippet). Modify:

```python
def soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict[str, Any]:
    scores = _duty_type_scores(session)
    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    by_type: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    days_past_by_type: dict[uuid.UUID, int] = defaultdict(int)
    days_future_by_type: dict[uuid.UUID, int] = defaultdict(int)
    today = date.today()
    for day, eff, dtid, mult in effective_duty_days(session):
        if eff == soldier_id:
            by_type[dtid] += scores.get(dtid, Decimal("0")) * mult
            if day <= today:
                days_past_by_type[dtid] += 1
            else:
                days_future_by_type[dtid] += 1
    per_type = [
        {
            "duty_type_id": dtid,
            "duty_type_name": dt_names.get(dtid, "?"),
            "score": by_type[dtid],
            "days": days_past_by_type[dtid] + days_future_by_type[dtid],
            "days_past": days_past_by_type[dtid],
            "days_future": days_future_by_type[dtid],
        }
        for dtid in by_type
    ]
    ...
    return {"per_type": per_type, "adjustments": list(adjustments)}
```

(Preserve whatever else was in the original `per_type` dict construction and the trailing `...` logic — read the real file to merge this correctly rather than overwriting unseen fields.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_scoring.py -k "splits_past_and_future" -v`
Expected: PASS

- [ ] **Step 6: Update the route's response schema**

In `backend/app/routes/scoring.py` around line 204-222, find `BreakdownOut`'s per-type item schema (likely a nested Pydantic model) and add the two new fields:

```python
class BreakdownPerTypeOut(BaseModel):
    duty_type_id: uuid.UUID
    duty_type_name: str
    score: Decimal
    days: int
    days_past: int
    days_future: int
```

(Match whatever the existing per-type schema class is actually named — read the file first; this is illustrative of the fields to add, not a guess at the class name.)

- [ ] **Step 7: Run the scoring test marker**

Run: `cd backend && pytest -m scoring -q`
Expected: PASS

- [ ] **Step 8: Update the frontend type and chart data**

In `frontend/src/api/scoring.ts` around lines 82-86, add `days_past: number` and `days_future: number` to the per-type TS type.

In `frontend/src/pages/HomePage.tsx` lines 234-244 (`typeChartData`), change from a single `days`-per-type series to two stacked series:

```tsx
const typeChartData = (breakdown?.per_type ?? []).map((p) => ({
  name: p.duty_type_name,
  "ימים שבוצעו": p.days_past,
  "ימים עתידיים": p.days_future,
}));
```

Then in the chart render section (lines 330-363), read the current chart component usage (bar chart, whatever library) and add a second `<Bar>` (or equivalent series) for `"ימים עתידיים"` stacked on `"ימים שבוצעו"`, with distinct colors/legend entries — match the exact chart library API already in use in this file (confirm import at top of file before writing this).

- [ ] **Step 9: Mirror the same change in MyDutiesPage.tsx**

Apply the identical `typeChartData` and chart-render change at `MyDutiesPage.tsx:101-111, 174-212`.

- [ ] **Step 10: Manually verify in the running app**

Start `.\dev.ps1`, view the homepage and "היומן שלי" for a soldier with both past and future assignments of the same duty type, confirm the breakdown chart shows two distinguishable segments per duty type (past vs. future) with a legend.

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/scoring.py backend/app/routes/scoring.py backend/app/services/tests/test_scoring.py frontend/src/api/scoring.ts frontend/src/pages/HomePage.tsx frontend/src/pages/MyDutiesPage.tsx
git commit -m "feat: split duty-type breakdown chart into past-served vs future-scheduled days"
```

---

### Task 5: Calendar hour labels as "HH:00" instead of bare numbers

**Files:**
- Modify: `frontend/src/components/dashboard/DutyCalendarWidget.tsx:85-99`
- Modify: `frontend/src/components/UnitCalendar.tsx:156-182`
- Test: manual (FullCalendar prop config, no meaningful unit test for rendered label text without a heavier DOM test setup than this codebase currently uses for calendar components — verify visually)

- [ ] **Step 1: Add `slotLabelFormat` to DutyCalendarWidget.tsx**

```tsx
// frontend/src/components/dashboard/DutyCalendarWidget.tsx, inside the <FullCalendar ... /> props (near slotMinTime/slotMaxTime, lines ~85-99)
slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
```

- [ ] **Step 2: Add the same prop to UnitCalendar.tsx**

```tsx
// frontend/src/components/UnitCalendar.tsx, inside the <FullCalendar ... /> props (lines ~156-182)
slotLabelFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
```

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, open the homepage mini-calendar and switch to week/3-day view, confirm hour labels read "00:00", "01:00", etc. Then open the main unit calendar page and confirm the same.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/dashboard/DutyCalendarWidget.tsx frontend/src/components/UnitCalendar.tsx
git commit -m "fix: show calendar hour labels as HH:00 instead of bare numbers"
```

---

## Self-Review Notes

- All 5 spec items (reserve styling, missing location, awkward phrasing, past/future breakdown split, calendar hour format) are covered by Tasks 1-5.
- Task 2 fixes root cause (backend auth) rather than working around it client-side.
- No placeholders; every step has concrete code, exact file/line targets, and exact commands.
