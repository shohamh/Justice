# Colored Formula Chips + Hakpaza Scoring Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the hakpaza scoring bug (×3.0 instead of ×2.0) and add colored type-labeled chips below the score formula in the Duty History panel.

**Architecture:** Three backend changes (model field, migration, scoring/hakpaza logic) plus one frontend rendering change. Backend tasks are sequential (migration must run before scoring change; scoring change before duty_history change). Frontend is independent.

**Spec:** `docs/superpowers/specs/2026-06-10-colored-formula-chips-design.md`

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic (backend), React/TypeScript/Tailwind CSS (frontend), PostgreSQL

---

## File Map

| File | Change |
|---|---|
| `backend/app/db/models.py` | Add `forced_call_up_multiplier` nullable Decimal field to `DutyAssignment` |
| `backend/alembic/versions/0044_forced_callup_multiplier.py` | New migration: add column, backfill from `forced_callups`, delete old ScoreAdjustments |
| `backend/app/routes/hakpaza.py` | Set `forced_call_up_multiplier` on new assignment; remove `ScoreAdjustment` creation |
| `backend/app/services/scoring.py` | Branch on `forced_call_up_multiplier` before `is_reserve` in `effective_duty_days` |
| `backend/app/services/duty_history.py` | `_score_parts` returns 3-tuple; `_day_mult` tracks `seg_type`; call sites store `score_segments` |
| `backend/tests/integration/test_hakpaza.py` | Add test asserting `forced_call_up_multiplier` is set and no `ScoreAdjustment` created |
| `backend/app/services/tests/test_duty_history.py` | Add/update tests verifying `score_segments` in metadata |
| `frontend/src/components/DutyHistoryPanel.tsx` | Parse `score_segments`; render colored chips row in expanded card |

---

## Task 1: DB Model + Migration

**Files:**
- Modify: `backend/app/db/models.py` — `DutyAssignment` class
- Create: `backend/alembic/versions/0044_forced_callup_multiplier.py`

- [ ] **Step 1: Add field to DutyAssignment model**

In `backend/app/db/models.py`, in the `DutyAssignment` class, add after the `called_up_to` field (line ~263):

```python
forced_call_up_multiplier: Mapped[Decimal | None] = mapped_column(
    Numeric(6, 2), nullable=True, default=None
)
```

- [ ] **Step 2: Create Alembic migration**

Create `backend/alembic/versions/0044_forced_callup_multiplier.py`:

```python
"""Add forced_call_up_multiplier to duty_assignments

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column("forced_call_up_multiplier", sa.Numeric(6, 2), nullable=True),
    )

    # Backfill: copy callup_multiplier from approved forced_callups to their
    # replacement assignments (these were previously represented as ScoreAdjustments)
    op.execute(text("""
        UPDATE duty_assignments da
        SET forced_call_up_multiplier = fc.callup_multiplier
        FROM forced_callups fc
        WHERE fc.replacement_assignment_id = da.id
          AND fc.status = 'approved'
    """))

    # Remove the old ScoreAdjustment rows that the hakpaza approve code created.
    # These are now fully represented by the forced_call_up_multiplier field.
    op.execute(text("""
        DELETE FROM score_adjustments
        WHERE reason LIKE 'הקפצה פיקודית%'
    """))


def downgrade() -> None:
    # Restore ScoreAdjustments for approved forced callups before dropping column
    op.execute(text("""
        INSERT INTO score_adjustments (id, soldier_id, delta, reason, created_by)
        SELECT
            gen_random_uuid(),
            fc.replacement_soldier_id,
            dt.score_per_day
                * ((fc.original_end_date - fc.pull_date + 1))
                * fc.callup_multiplier,
            'הקפצה פיקודית (restored)',
            fc.approver_id
        FROM forced_callups fc
        JOIN duty_assignments orig ON orig.id = fc.original_assignment_id
        JOIN duty_types dt ON dt.id = orig.duty_type_id
        WHERE fc.status = 'approved'
          AND fc.replacement_assignment_id IS NOT NULL
    """))

    op.drop_column("duty_assignments", "forced_call_up_multiplier")
```

- [ ] **Step 3: Apply migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 0043 -> 0044`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0044_forced_callup_multiplier.py
git commit -m "feat: add forced_call_up_multiplier column to duty_assignments"
```

---

## Task 2: Scoring Fix + Hakpaza Route Fix

**Files:**
- Modify: `backend/app/services/scoring.py` — `effective_duty_days`
- Modify: `backend/app/routes/hakpaza.py` — `approve` endpoint
- Modify: `backend/tests/integration/test_hakpaza.py` — add approval scoring test

- [ ] **Step 1: Write failing test**

Add to `backend/tests/integration/test_hakpaza.py`:

```python
def test_approve_hakpaza_sets_multiplier_no_score_adjustment(client, admin_session):
    """Approving a hakpaza sets forced_call_up_multiplier on the replacement
    assignment and does NOT create a ScoreAdjustment."""
    from app.db.models import ScoreAdjustment
    from sqlalchemy import select

    dm, commander, pulled, replacement, assignment = _setup(admin_session, "hk005")

    create_resp = client.post(
        "/api/hakpaza",
        json={
            "pulled_assignment_id": str(assignment.id),
            "pull_date": "2030-01-05",
            "replacement_soldier_id": str(replacement.id),
        },
        headers=auth_headers(commander),
    )
    assert create_resp.status_code == 201
    hakpaza_id = create_resp.json()["id"]

    approve_resp = client.post(
        f"/api/hakpaza/{hakpaza_id}/approve",
        headers=auth_headers(dm),
    )
    assert approve_resp.status_code == 200
    data = approve_resp.json()
    assert data["replacement_assignment_id"] is not None

    # replacement assignment must have the multiplier set
    from app.db.models import DutyAssignment
    repl_asgn = admin_session.get(DutyAssignment, data["replacement_assignment_id"])
    assert repl_asgn is not None
    assert repl_asgn.forced_call_up_multiplier == Decimal("2.0")

    # no ScoreAdjustment should have been created for the replacement soldier
    adjs = admin_session.execute(
        select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == replacement.id)
    ).scalars().all()
    assert adjs == []
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd backend && uv run pytest tests/integration/test_hakpaza.py::test_approve_hakpaza_sets_multiplier_no_score_adjustment -v
```

Expected: FAIL (the route still creates a ScoreAdjustment)

- [ ] **Step 3: Fix `scoring.py` — branch on `forced_call_up_multiplier`**

In `backend/app/services/scoring.py`, inside `effective_duty_days`, replace the existing per-day multiplier logic (the `if a.is_reserve:` block, lines ~77-88):

```python
# New code — forced_call_up_multiplier takes priority
if a.forced_call_up_multiplier is not None:
    mult = a.forced_call_up_multiplier
elif a.is_reserve:
    if (a.called_up_from is not None and a.called_up_to is not None
            and a.called_up_from <= day <= a.called_up_to):
        mult = called_up_mult
    else:
        mult = standby_mult
else:
    ranges = dismissal_ranges.get(a.id, [])
    if any(df <= day <= dt for df, dt in ranges):
        mult = dismissed_mult
    else:
        mult = Decimal("1.0")
```

- [ ] **Step 4: Fix `hakpaza.py` approve endpoint**

In `backend/app/routes/hakpaza.py`:

**a) Update import** — remove `ScoreAdjustment` from the import on line 13:

```python
from app.db.models import DutyAssignment, DutyType, ForcedCallup, Soldier
```

**b) In the `approve` endpoint**, replace the `new_assignment` creation and the block that follows it (roughly lines 165-189):

```python
    new_assignment = DutyAssignment(
        soldier_id=h.replacement_soldier_id,
        duty_type_id=original.duty_type_id,
        duty_location_id=original.duty_location_id,
        start_date=h.pull_date,
        end_date=original_end_date,
        status="published",
        is_reserve=False,
        forced_call_up_multiplier=h.callup_multiplier,
        notes=f"הקפצה פיקודית — מחליף {session.get(Soldier, h.pulled_soldier_id).full_name if session.get(Soldier, h.pulled_soldier_id) else ''}",
    )
    session.add(new_assignment)
    session.flush()
```

Remove entirely:
- The `dt = session.get(DutyType, ...)` lookup
- The `days_served = ...` calculation
- The `if dt and days_served > 0:` block that creates `ScoreAdjustment`

Also remove the `DutyType` import if it's no longer used elsewhere in the file (check before removing).

- [ ] **Step 5: Run test — verify it passes**

```bash
cd backend && uv run pytest tests/integration/test_hakpaza.py -v
```

Expected: all tests PASS including the new one

- [ ] **Step 6: Run full test suite**

```bash
cd backend && uv run pytest -q
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scoring.py backend/app/routes/hakpaza.py backend/tests/integration/test_hakpaza.py
git commit -m "fix: hakpaza approval sets forced_call_up_multiplier instead of creating ScoreAdjustment"
```

---

## Task 3: `score_segments` in Duty History

**Files:**
- Modify: `backend/app/services/duty_history.py`
- Modify: `backend/app/services/tests/test_duty_history.py`

**Context:** `_score_parts` currently returns `(score_total: str, formula: str)`. We change it to return `(score_total: str, formula: str, segments_json: str)` where `segments_json` is a JSON array of segment objects. A new `seg_type` is tracked per day. All 3 call sites (assignment, call_up, dismissal) must be updated to unpack and store `score_segments`.

- [ ] **Step 1: Write failing tests**

Add to `backend/app/services/tests/test_duty_history.py`:

```python
import json


def test_assignment_score_segments_regular(admin_session, soldier, duty_type, location):
    """Regular assignment produces score_segments with type='regular'."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
        status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    asgn = next(e for e in events if e.event_type == "assignment")
    assert "score_segments" in asgn.metadata
    segs = json.loads(asgn.metadata["score_segments"])
    assert len(segs) == 1
    assert segs[0]["type"] == "regular"
    assert segs[0]["days"] == 3
    assert segs[0]["mult"] == "1.0"


def test_assignment_score_segments_reserve_mixed(admin_session, soldier, duty_type, location):
    """Reserve assignment with a called-up window produces two segments."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        status="published",
        is_reserve=True,
        called_up_from=date(2026, 8, 3),
        called_up_to=date(2026, 8, 5),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    asgn = next(e for e in events if e.event_type == "assignment")
    segs = json.loads(asgn.metadata["score_segments"])
    types = [s["type"] for s in segs]
    assert "reserve_standby" in types
    assert "reserve_called_up" in types


def test_assignment_score_segments_forced_callup(admin_session, soldier, duty_type, location):
    """Assignment with forced_call_up_multiplier set produces a single 'forced_call_up' segment."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        status="published",
        is_reserve=False,
        forced_call_up_multiplier=Decimal("2.0"),
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    asgn = next(e for e in events if e.event_type == "assignment")
    segs = json.loads(asgn.metadata["score_segments"])
    assert len(segs) == 1
    assert segs[0]["type"] == "forced_call_up"
    assert segs[0]["mult"] == "2.0"


def test_cancellation_has_no_score_segments(admin_session, soldier, duty_type, location):
    """Cancelled assignments do not emit score_segments."""
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 3),
        status="cancelled",
    )
    admin_session.add(a)
    admin_session.flush()

    events = get_duty_history(admin_session, soldier.id)
    canc = next(e for e in events if e.event_type == "cancellation")
    assert "score_segments" not in canc.metadata
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && uv run pytest app/services/tests/test_duty_history.py -k "score_segments" -v
```

Expected: 4 FAILs (KeyError or AssertionError — `score_segments` not yet in metadata)

- [ ] **Step 3: Update `_score_parts` in `duty_history.py`**

At the top of `backend/app/services/duty_history.py`, add `import json` to the imports.

Change the `_score_parts` function signature and body:

```python
import json


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
) -> tuple[str, str, str]:
    """Return (score_total, score_formula, segments_json) for the given period.

    segments_json is a JSON array of {"days", "spd", "mult", "type"} objects.
    Returns ("0.0", "", "[]") when there are no days in range or spd is zero.
    """
    start = max(a.start_date, date_from) if date_from is not None else a.start_date
    end = min(a.end_date, date_to) if date_to is not None else a.end_date

    if start > end or spd == Decimal("0"):
        return "0.0", "", "[]"

    def _day_mult_and_type(day: date) -> tuple[Decimal, str]:
        # Priority: forced_call_up > dismissed > reserve_called_up > reserve_standby > regular
        if a.forced_call_up_multiplier is not None:
            return a.forced_call_up_multiplier, "forced_call_up"
        if any(df <= day <= dt for df, dt in dismissal_ranges):
            return dismissed_mult, "dismissed"
        if a.is_reserve:
            if (
                a.called_up_from is not None
                and a.called_up_to is not None
                and a.called_up_from <= day <= a.called_up_to
            ):
                return called_up_mult, "reserve_called_up"
            return standby_mult, "reserve_standby"
        return Decimal("1.0"), "regular"

    # Group consecutive days by (mult, seg_type)
    segments: list[tuple[int, Decimal, str]] = []
    cur_key: tuple[Decimal, str] | None = None
    cur_count = 0

    day = start
    while day <= end:
        m, t = _day_mult_and_type(day)
        key = (m, t)
        if key == cur_key:
            cur_count += 1
        else:
            if cur_key is not None:
                segments.append((cur_count, cur_key[0], cur_key[1]))
            cur_key = key
            cur_count = 1
        day += timedelta(days=1)
    if cur_key is not None:
        segments.append((cur_count, cur_key[0], cur_key[1]))

    total: Decimal = sum(Decimal(str(count)) * spd * mult for count, mult, _ in segments)
    formula = " + ".join(
        f"{count} × {_fmt(spd)} × {_fmt(mult)}" for count, mult, _ in segments
    )
    segments_json = json.dumps([
        {"days": count, "spd": _fmt(spd), "mult": _fmt(mult), "type": seg_type}
        for count, mult, seg_type in segments
    ])
    return _fmt(total), formula, segments_json
```

- [ ] **Step 4: Update all call sites in `get_duty_history`**

There are 3 places that call `_score_parts`. Update each to unpack 3 values and store `score_segments`.

**Call site 1 — call_up event** (around line 174):

```python
cu_total, cu_formula, cu_segments = _score_parts(
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
    "score_segments": cu_segments,
}
if cu_formula:
    cu_metadata["score_formula"] = cu_formula
```

**Call site 2 — assignment event** (around line 230):

```python
asgn_total, asgn_formula, asgn_segments = _score_parts(
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
    "score_segments": asgn_segments,
}
if asgn_formula:
    asgn_metadata["score_formula"] = asgn_formula
```

**Call site 3 — dismissal event** (around line 266):

```python
dis_total, dis_formula, dis_segments = _score_parts(
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
    "score_segments": dis_segments,
}
if dis_formula:
    dis_metadata["score_formula"] = dis_formula
```

Cancellation events do **not** call `_score_parts` — leave that block unchanged (no `score_segments` key on cancellations).

- [ ] **Step 5: Run new tests — verify they pass**

```bash
cd backend && uv run pytest app/services/tests/test_duty_history.py -v
```

Expected: all 15+ tests PASS

- [ ] **Step 6: Run full test suite**

```bash
cd backend && uv run pytest -q
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/duty_history.py backend/app/services/tests/test_duty_history.py
git commit -m "feat: add score_segments typed metadata to duty history events"
```

---

## Task 4: Frontend Colored Chips

**Files:**
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`

**Context:** The `EventCard` expanded section currently shows a plain-text formula `<p>`. Add a row of colored chips below it, one per segment from `score_segments`. Each chip shows label + ×mult in a color specific to the segment type.

- [ ] **Step 1: Add type definition and helper constants**

Near the top of `DutyHistoryPanel.tsx`, after the existing constant blocks (`TYPE_COLORS`, `DOT_COLORS`, `STATUS_BADGE`), add:

```tsx
interface ScoreSegment {
  days: number;
  spd: string;
  mult: string;
  type: "regular" | "reserve_standby" | "reserve_called_up" | "forced_call_up" | "dismissed";
}

const SEGMENT_CHIP_COLORS: Record<ScoreSegment["type"], string> = {
  regular: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  reserve_standby: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  reserve_called_up: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  forced_call_up: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  dismissed: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
};

const SEGMENT_LABELS: Record<ScoreSegment["type"], string> = {
  regular: "רגיל",
  reserve_standby: "רזרבה",
  reserve_called_up: "הוקפץ מרזרבה",
  forced_call_up: "הקפצה פיקודית",
  dismissed: "שוחרר",
};
```

- [ ] **Step 2: Parse `score_segments` in `EventCard`**

In the `EventCard` function body, before the `return` statement, add:

```tsx
const scoreSegments: ScoreSegment[] | null = (() => {
  try {
    const raw = e.metadata.score_segments;
    if (!raw) return null;
    return JSON.parse(raw) as ScoreSegment[];
  } catch {
    return null;
  }
})();
```

- [ ] **Step 3: Replace the formula `<p>` with formula + chips**

In the `isExpanded` block, find the existing formula paragraph:

```tsx
{e.metadata.score_total != null && (
  <p className="text-xs text-gray-500 dark:text-gray-400" data-testid={`score-formula-${e.id}`}>
    ניקוד:{" "}
    {e.metadata.score_formula
      ? `${e.metadata.score_formula} = ${e.metadata.score_total}`
      : e.metadata.score_total}
  </p>
)}
```

Replace it with:

```tsx
{e.metadata.score_total != null && (
  <div data-testid={`score-formula-${e.id}`}>
    <p className="text-xs text-gray-500 dark:text-gray-400">
      ניקוד:{" "}
      {e.metadata.score_formula
        ? `${e.metadata.score_formula} = ${e.metadata.score_total}`
        : e.metadata.score_total}
    </p>
    {scoreSegments && scoreSegments.length > 0 && (
      <div className="flex flex-wrap gap-1 mt-1">
        {scoreSegments.map((seg, i) => (
          <span
            key={i}
            className={`text-xs px-1.5 py-0.5 rounded ${SEGMENT_CHIP_COLORS[seg.type]}`}
          >
            {SEGMENT_LABELS[seg.type]} ×{seg.mult}
          </span>
        ))}
      </div>
    )}
  </div>
)}
```

- [ ] **Step 4: Run frontend lint**

```bash
cd frontend && pnpm lint
```

Expected: 0 errors, 0 warnings

- [ ] **Step 5: Run frontend tests**

```bash
cd frontend && pnpm vitest run
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DutyHistoryPanel.tsx
git commit -m "feat: show colored segment type chips in score formula expansion"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Section 1 (scoring fix): Tasks 1 + 2 cover model, migration, scoring, hakpaza, test
- ✅ Section 2 (score_segments format): Task 3 covers `_score_parts` return change, seg_type priority, JSON serialization, all call sites
- ✅ Section 3 (frontend chips): Task 4 covers type def, color map, label map, parsing, rendering

**Type consistency:**
- `_score_parts` returns `tuple[str, str, str]` — used consistently as `total, formula, segments = _score_parts(...)` across all 3 call sites
- `ScoreSegment.type` union values match keys of `SEGMENT_CHIP_COLORS` and `SEGMENT_LABELS`
- `forced_call_up_multiplier: Mapped[Decimal | None]` — referenced correctly in model, scoring, duty_history
